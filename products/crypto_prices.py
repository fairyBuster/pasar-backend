"""Sumber harga coin untuk grafik produk.

CoinGecko free tier itu rate limited. Setiap fetch sukses disimpan ke
CoinPriceSnapshot, jadi kalau kena 429/timeout grafik tetap disajikan dari
harga harian terakhir yang tersimpan (gratis, tanpa API key).
"""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import requests
from django.utils import timezone

from .models import CoinPriceSnapshot

logger = logging.getLogger(__name__)

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/{}/market_chart"
CHART_DAYS = (7, 14, 30, 90)
MAX_DAYS = CHART_DAYS[-1]  # selalu ambil window terlebar, lalu slice sesuai request
FRESH_SECONDS = 600  # jangan tembak CoinGecko lebih sering dari ini per coin
HTTP_TIMEOUT = 15

# Simbol produk -> id CoinGecko
COIN_IDS = {
    "USDT": "tether",
    "USDC": "usd-coin",
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "ADA": "cardano",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "ATOM": "cosmos",
    "DOGE": "dogecoin",
    "SHIB": "shiba-inu",
    "PEPE": "pepe",
    "FLOKI": "floki",
    "BONK": "bonk",
    "XRP": "ripple",
    "TRX": "tron",
    "LTC": "litecoin",
    "LINK": "chainlink",
    "SUI": "sui",
    "TON": "the-open-network",
    "APT": "aptos",
    "NEAR": "near",
    "INJ": "injective-protocol",
    "SEI": "sei-network",
    "TIA": "celestia",
    "POL": "polygon-ecosystem-token",
    "ARB": "arbitrum",
    "OP": "optimism",
    "UNI": "uniswap",
}


def _daily_close(points):
    """[ts_ms, price] dari CoinGecko -> {tanggal: harga terakhir hari itu}."""
    per_day = {}
    for ts_ms, price in points or []:
        day = datetime.fromtimestamp(ts_ms / 1000, tz=dt_timezone.utc).date()
        per_day[day] = price
    return per_day


def _store(coin, per_day):
    if not per_day:
        return
    CoinPriceSnapshot.objects.bulk_create(
        [
            CoinPriceSnapshot(coin=coin, day=day, price_usd=Decimal(str(price)))
            for day, price in per_day.items()
        ],
        update_conflicts=True,
        update_fields=["price_usd", "updated_at"],
        unique_fields=["coin", "day"],
    )


def _fetch_upstream(coin_id, days):
    resp = requests.get(
        COINGECKO_URL.format(coin_id),
        params={"vs_currency": "usd", "days": days},
        timeout=HTTP_TIMEOUT,
    )
    if resp.status_code != 200:
        logger.warning(
            "CoinGecko %s -> HTTP %s (rate limit?), pakai snapshot tersimpan",
            coin_id,
            resp.status_code,
        )
        return None
    return resp.json().get("prices") or []


def get_chart(coin, days):
    """Return (rows, source). None kalau coin tidak punya mapping CoinGecko.

    rows bisa kosong kalau upstream gagal dan belum ada snapshot sama sekali.
    """
    coin = (coin or "").strip().upper()
    coin_id = COIN_IDS.get(coin)
    if not coin_id:
        return None

    source = "cache"
    last_fetch = (
        CoinPriceSnapshot.objects.filter(coin=coin)
        .order_by("-updated_at")
        .values_list("updated_at", flat=True)
        .first()
    )
    fresh = last_fetch is not None and (timezone.now() - last_fetch).total_seconds() < FRESH_SECONDS
    if not fresh:
        try:
            points = _fetch_upstream(coin_id, MAX_DAYS)
        except requests.RequestException as exc:
            logger.warning("CoinGecko %s gagal: %s - pakai snapshot tersimpan", coin_id, exc)
            points = None
        if points is not None:
            _store(coin, _daily_close(points))
            source = "coingecko"

    # USE_TZ=False di project ini, jadi pakai date() biasa (bukan timezone.localdate)
    since = datetime.now(dt_timezone.utc).date() - timedelta(days=days)
    rows = list(
        CoinPriceSnapshot.objects.filter(coin=coin, day__gte=since)
        .order_by("day")
        .values("day", "price_usd")
    )
    return rows, source
