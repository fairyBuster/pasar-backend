"""Layanan harga emas real-time untuk fitur tukar emas.

Sumber harga (keduanya API publik gratis, tanpa API key):
- Harga emas dunia XAU (USD per troy ounce): api.gold-api.com
- Kurs USD -> IDR: open.er-api.com (fallback: api.frankfurter.app)

Harga disimpan (cached) di GoldSettings.last_price_per_gram selama
`price_cache_minutes`. Jika API gagal, harga terakhir yang tersimpan
tetap dipakai (fallback) agar fitur tidak mati total.
"""

import logging
from decimal import Decimal, ROUND_HALF_UP

import requests
from django.utils import timezone

from .models import GoldSettings

logger = logging.getLogger(__name__)

GOLD_PRICE_URL = 'https://api.gold-api.com/price/XAU'
FX_PRIMARY_URL = 'https://open.er-api.com/v6/latest/USD'
FX_FALLBACK_URL = 'https://api.frankfurter.app/latest'
TROY_OUNCE_GRAMS = Decimal('31.1034768')
REQUEST_TIMEOUT = 10


def _fetch_gold_usd_per_ounce():
    """Harga emas dunia dalam USD per troy ounce."""
    resp = requests.get(GOLD_PRICE_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    price = data.get('price')
    if price is None:
        raise ValueError('Harga XAU tidak ditemukan di response API.')
    return Decimal(str(price))


def _fetch_usd_idr_rate():
    """Kurs USD -> IDR (API utama, fallback API kedua)."""
    try:
        resp = requests.get(FX_PRIMARY_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        rate = (data.get('rates') or {}).get('IDR')
        if rate:
            return Decimal(str(rate))
    except Exception as exc:
        logger.warning('API kurs utama gagal: %s', exc)

    resp = requests.get(FX_FALLBACK_URL, params={'from': 'USD', 'to': 'IDR'}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    rate = (data.get('rates') or {}).get('IDR')
    if not rate:
        raise ValueError('Kurs USD -> IDR tidak ditemukan di response API.')
    return Decimal(str(rate))


def get_gold_price_per_gram(force_refresh=False):
    """Harga emas per gram dalam rupiah.

    Returns:
        (settings_obj, price_per_gram: Decimal, source: 'cache' | 'live' | 'stale')

    Raises:
        RuntimeError: jika pengaturan fitur emas belum ada.
        Exception: jika harga belum pernah tersimpan dan API gagal diakses.
    """
    settings_obj = GoldSettings.load()
    if settings_obj is None:
        raise RuntimeError('Pengaturan fitur tukar emas belum dikonfigurasi.')

    now = timezone.now()
    cache_minutes = int(getattr(settings_obj, 'price_cache_minutes', None) or 5)
    cached_price = settings_obj.last_price_per_gram
    last_updated = settings_obj.last_price_updated_at

    is_fresh = (
        cached_price is not None
        and last_updated is not None
        and (now - last_updated) < timezone.timedelta(minutes=cache_minutes)
    )
    if is_fresh and not force_refresh:
        return settings_obj, Decimal(cached_price), 'cache'

    try:
        usd_per_oz = _fetch_gold_usd_per_ounce()
        usd_idr = _fetch_usd_idr_rate()
        price_per_gram = (usd_per_oz / TROY_OUNCE_GRAMS * usd_idr).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        settings_obj.last_price_per_gram = price_per_gram
        settings_obj.last_price_usd_per_oz = usd_per_oz.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        settings_obj.last_usd_idr_rate = usd_idr.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        settings_obj.last_price_updated_at = now
        settings_obj.save(update_fields=[
            'last_price_per_gram',
            'last_price_usd_per_oz',
            'last_usd_idr_rate',
            'last_price_updated_at',
            'updated_at',
        ])
        return settings_obj, price_per_gram, 'live'
    except Exception as exc:
        logger.error('Gagal mengambil harga emas real-time: %s', exc)
        if cached_price is not None:
            # Pakai harga terakhir yang tersimpan sebagai fallback
            return settings_obj, Decimal(cached_price), 'stale'
        raise
