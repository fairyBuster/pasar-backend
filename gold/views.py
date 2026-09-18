from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
import uuid
import hashlib

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config import format_currency
from products.models import Transaction

from .models import GoldOrder, GoldSettings
from .serializers import (
    GoldInfoResponseSerializer,
    GoldOrderSerializer,
    GoldSwapRequestSerializer,
    GoldSwapResponseSerializer,
)
from .services import get_gold_price_per_gram

USER_TAG = 'User API'


def _now_in_zone(tz):
    now = timezone.now()
    if timezone.is_aware(now):
        return timezone.localtime(now, tz)
    return now


@method_decorator(csrf_exempt, name='dispatch')
class GoldSwapView(APIView):
    """Tukar balance_hold menjadi emas fisik.

    - Nilai emas (gram x harga emas real-time per gram) dipotong dari balance_hold.
    - Biaya cetak (gram x tarif per gram) + ongkir flat dipotong dari balance_deposit.
    - Alamat pengiriman diambil dari salah satu alamat tersimpan user (address_id).
    """

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(
        tags=[USER_TAG],
        summary='Tukar balance_hold menjadi emas',
        request=GoldSwapRequestSerializer,
        examples=[
            OpenApiExample(
                'Request contoh',
                request_only=True,
                value={'gram': '0.5', 'address_id': 1},
            ),
        ],
        responses={
            201: OpenApiResponse(
                response=GoldSwapResponseSerializer,
                description='Order tukar emas berhasil dibuat',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={
                            'message': 'Tukar emas berhasil. Order akan segera diproses.',
                            'order': {
                                'id': 1,
                                'status': 'PENDING',
                                'gram': '0.5000',
                                'price_per_gram': '1500000.00',
                                'gold_value': '750000.00',
                                'printing_fee': '10000.00',
                                'shipping_cost': '15000.00',
                                'total_fee': '25000.00',
                                'recipient_name': 'Budi Santoso',
                                'phone_number': '081234567890',
                                'address_details': 'Jl. Merdeka No. 10, RT 01/RW 02, Jakarta Pusat',
                                'house_number': '10',
                                'tracking_number': '',
                                'transaction_id': 'SWP-20260915120000-A1B2C3',
                                'fee_transaction_id': 'SWF-20260915120000-D4E5F6',
                                'refunded_at': None,
                                'created_at': '2026-09-15T12:00:00+07:00',
                                'updated_at': '2026-09-15T12:00:00+07:00',
                            },
                            'price_per_gram': '1500000.00',
                            'price_source': 'live',
                            'balance_hold': '250000.00',
                            'balance_deposit': '75000.00',
                        },
                    )
                ],
            ),
            400: OpenApiResponse(
                description='Validasi gagal / fitur tidak aktif / saldo balance_hold atau balance_deposit tidak cukup',
            ),
            503: OpenApiResponse(description='Harga emas real-time sedang tidak tersedia'),
        },
        description=(
            'Tukar balance_hold menjadi emas fisik.\n\n'
            '**Perhitungan:**\n'
            '- `gold_value` = gram x harga emas real-time per gram (potong dari **balance_hold**)\n'
            '- `printing_fee` = gram x biaya cetak per gram (potong dari **balance_deposit**)\n'
            '- `shipping_cost` = ongkir flat (potong dari **balance_deposit**)\n'
            '- `total_fee` = printing_fee + shipping_cost\n\n'
            '**Alamat:** kirim `address_id` dari daftar alamat user (`GET /api/auth/address/`). '
            'Alamat akan di-snapshot ke order sebagai alamat kirim.'
        ),
    )
    def post(self, request):
        serializer = GoldSwapRequestSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        gram = serializer.validated_data['gram']
        address = serializer.address

        settings_obj = GoldSettings.load()
        if settings_obj is None:
            return Response({
                'error': 'Fitur tukar emas belum dikonfigurasi.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if not settings_obj.is_active:
            return Response({
                'error': 'Fitur tukar emas sedang tidak aktif.'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            settings_obj, price_per_gram, price_source = get_gold_price_per_gram()
        except RuntimeError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response({
                'error': 'Harga emas real-time sedang tidak tersedia. Coba beberapa saat lagi.'
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        printing_fee_per_gram = settings_obj.printing_fee_per_gram or Decimal('0.00')
        shipping_cost = settings_obj.shipping_cost or Decimal('0.00')

        # Nilai emas -> balance_hold; biaya cetak + ongkir -> balance_deposit
        gold_value = (gram * price_per_gram).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        printing_fee = (gram * printing_fee_per_gram).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_fee = printing_fee + shipping_cost

        with transaction.atomic():
            User = get_user_model()
            user = User.objects.select_for_update().get(pk=request.user.pk)

            hold_balance = user.balance_hold or Decimal('0.00')
            deposit_balance = user.balance_deposit or Decimal('0.00')

            if hold_balance < gold_value:
                return Response({
                    'error': (
                        f'Saldo balance_hold tidak cukup. Dibutuhkan {format_currency(gold_value)} '
                        f'(nilai emas {gram} gram x {format_currency(price_per_gram)}/gram), '
                        f'tersedia {format_currency(hold_balance)}.'
                    ),
                    'required': str(gold_value),
                    'available': str(hold_balance),
                }, status=status.HTTP_400_BAD_REQUEST)

            if deposit_balance < total_fee:
                return Response({
                    'error': (
                        f'Saldo balance_deposit tidak cukup untuk biaya. Dibutuhkan {format_currency(total_fee)} '
                        f'(biaya cetak {format_currency(printing_fee)} + ongkir {format_currency(shipping_cost)}), '
                        f'tersedia {format_currency(deposit_balance)}.'
                    ),
                    'required': str(total_fee),
                    'available': str(deposit_balance),
                }, status=status.HTTP_400_BAD_REQUEST)

            user.balance_hold = hold_balance - gold_value
            user.balance_deposit = deposit_balance - total_fee
            user.save(update_fields=['balance_hold', 'balance_deposit'])

            now_wib = _now_in_zone(ZoneInfo('Asia/Jakarta'))
            ts = now_wib.strftime('%Y%m%d%H%M%S')

            main_trx = Transaction.objects.create(
                user=user,
                type='SWAP',
                amount=gold_value,
                description=(
                    f'Tukar {gram} gram emas dari balance_hold '
                    f'(harga {format_currency(price_per_gram)}/gram)'
                ),
                status='PENDING',
                wallet_type='BALANCE_HOLD',
                trx_id=f'SWP-{ts}-{uuid.uuid4().hex[:6].upper()}',
            )
            fee_trx = Transaction.objects.create(
                user=user,
                type='SWAP',
                amount=total_fee,
                description=(
                    f'Biaya cetak ({format_currency(printing_fee)}) + ongkir '
                    f'({format_currency(shipping_cost)}) tukar emas {gram} gram dari balance_deposit'
                ),
                status='PENDING',
                wallet_type='BALANCE_DEPOSIT',
                trx_id=f'SWF-{ts}-{uuid.uuid4().hex[:6].upper()}',
            )

            order = GoldOrder.objects.create(
                user=user,
                status='PENDING',
                gram=gram,
                price_per_gram=price_per_gram,
                gold_value=gold_value,
                printing_fee=printing_fee,
                shipping_cost=shipping_cost,
                total_fee=total_fee,
                address=address,
                recipient_name=address.recipient_name,
                phone_number=address.phone_number,
                address_details=address.address_details,
                house_number=address.house_number,
                transaction=main_trx,
                fee_transaction=fee_trx,
            )

        response_data = {
            'message': 'Tukar emas berhasil. Order akan segera diproses.',
            'order': order,
            'price_per_gram': price_per_gram,
            'price_source': price_source,
            'balance_hold': user.balance_hold,
            'balance_deposit': user.balance_deposit,
        }
        return Response(GoldSwapResponseSerializer(response_data).data, status=status.HTTP_201_CREATED)


GOLD_INFO_CACHE_TTL = 120  # detik; key fingerprint bikin cache "rilis" sendiri saat data berubah
# ponytail: TTL cuma jaring pengaman. Bucket fresh/expired harga ikut masuk key, jadi saat
# window price_cache_minutes habis cache otomatis rilis dan view ambil harga baru. Saat API
# harga sedang mati, respons "stale" ikut ter-cache — sekaligus menahan timeout request keluar.


def _gold_info_cache_key(user):
    """Cache key info emas: saldo user + fingerprint GoldSettings + status kesegaran harga.

    price_source bergantung waktu (cache -> live/stale setelah price_cache_minutes),
    jadi status fresh/expired ikut dihitung di key.
    """
    parts = [str(user.pk), str(user.balance_hold or 0), str(user.balance_deposit or 0)]
    settings_obj = GoldSettings.load()
    if settings_obj is None:
        parts.append('no-settings')
    else:
        now = timezone.now()
        cache_minutes = int(settings_obj.price_cache_minutes or 5)
        is_fresh = (
            settings_obj.last_price_per_gram is not None
            and settings_obj.last_price_updated_at is not None
            and (now - settings_obj.last_price_updated_at) < timezone.timedelta(minutes=cache_minutes)
        )
        parts.extend((
            str(settings_obj.is_active), str(settings_obj.printing_fee_per_gram),
            str(settings_obj.shipping_cost), str(settings_obj.price_cache_minutes),
            str(settings_obj.last_price_per_gram), str(settings_obj.last_price_usd_per_oz),
            str(settings_obj.last_usd_idr_rate), str(settings_obj.last_price_updated_at),
            'fresh' if is_fresh else 'expired',
        ))
    return f'gold_info:{user.pk}:{hashlib.md5("|".join(parts).encode()).hexdigest()}'


@method_decorator(csrf_exempt, name='dispatch')
class GoldInfoView(APIView):
    """Info harga emas real-time + tarif biaya cetak & ongkir (untuk halaman tukar emas).

    Di-cache per user; rilis otomatis saat data berubah.
    """

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(
        tags=[USER_TAG],
        summary='Info harga emas & tarif tukar emas',
        responses={
            200: OpenApiResponse(
                response=GoldInfoResponseSerializer,
                description='Info harga emas real-time dan tarif',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={
                            'is_active': True,
                            'price_available': True,
                            'price_per_gram': '1500000.00',
                            'price_source': 'live',
                            'price_updated_at': '2026-09-15T12:00:00+07:00',
                            'price_usd_per_oz': '2680.50',
                            'usd_idr_rate': '16250.5000',
                            'printing_fee_per_gram': '20000.00',
                            'shipping_cost': '15000.00',
                            'balance_hold': '1000000.00',
                            'balance_deposit': '100000.00',
                        },
                    )
                ],
            )
        },
        description=(
            'Harga emas real-time per gram + tarif biaya cetak per gram dan ongkir, '
            'beserta saldo balance_hold & balance_deposit user.\n\n'
            '`price_source`: `live` (baru dari API), `cache` (masih fresh), `stale` (API gagal, pakai harga terakhir).'
        ),
    )
    def get(self, request):
        cache_key = _gold_info_cache_key(request.user)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        settings_obj = GoldSettings.load()
        if settings_obj is None:
            payload = {
                'is_active': False,
                'price_available': False,
                'price_per_gram': None,
                'price_source': 'unavailable',
                'price_updated_at': None,
                'price_usd_per_oz': None,
                'usd_idr_rate': None,
                'printing_fee_per_gram': '0.00',
                'shipping_cost': '0.00',
                'balance_hold': request.user.balance_hold or Decimal('0.00'),
                'balance_deposit': request.user.balance_deposit or Decimal('0.00'),
            }
            cache.set(cache_key, payload, GOLD_INFO_CACHE_TTL)
            return Response(payload, status=status.HTTP_200_OK)

        data = {
            'is_active': bool(settings_obj.is_active),
            'price_available': False,
            'price_per_gram': None,
            'price_source': 'unavailable',
            'price_updated_at': settings_obj.last_price_updated_at,
            'price_usd_per_oz': settings_obj.last_price_usd_per_oz,
            'usd_idr_rate': settings_obj.last_usd_idr_rate,
            'printing_fee_per_gram': settings_obj.printing_fee_per_gram or Decimal('0.00'),
            'shipping_cost': settings_obj.shipping_cost or Decimal('0.00'),
            'balance_hold': request.user.balance_hold or Decimal('0.00'),
            'balance_deposit': request.user.balance_deposit or Decimal('0.00'),
        }

        try:
            settings_obj, price_per_gram, price_source = get_gold_price_per_gram()
            data['price_available'] = True
            data['price_per_gram'] = price_per_gram
            data['price_source'] = price_source
            data['price_updated_at'] = settings_obj.last_price_updated_at
            data['price_usd_per_oz'] = settings_obj.last_price_usd_per_oz
            data['usd_idr_rate'] = settings_obj.last_usd_idr_rate
        except Exception:
            pass

        payload = GoldInfoResponseSerializer(data).data
        cache.set(cache_key, payload, GOLD_INFO_CACHE_TTL)
        return Response(payload, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class GoldOrderDetailView(APIView):
    """Detail satu order tukar emas milik user (dibuka dari riwayat transaksi)."""

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(
        tags=[USER_TAG],
        summary='Detail order tukar emas',
        responses={
            200: OpenApiResponse(
                response=GoldOrderSerializer,
                description='Detail order tukar emas',
                examples=[
                    OpenApiExample(
                        'Success Response',
                        value={
                            'id': 1,
                            'status': 'SHIPPED',
                            'gram': '0.5000',
                            'price_per_gram': '1500000.00',
                            'gold_value': '750000.00',
                            'printing_fee': '10000.00',
                            'shipping_cost': '15000.00',
                            'total_fee': '25000.00',
                            'recipient_name': 'Budi Santoso',
                            'phone_number': '081234567890',
                            'address_details': 'Jl. Merdeka No. 10, RT 01/RW 02, Jakarta Pusat',
                            'house_number': '10',
                            'tracking_number': 'JX1234567890',
                            'transaction_id': 'SWP-20260915120000-A1B2C3',
                            'fee_transaction_id': 'SWF-20260915120000-D4E5F6',
                            'refunded_at': None,
                            'created_at': '2026-09-15T12:00:00+07:00',
                            'updated_at': '2026-09-16T09:00:00+07:00',
                        },
                    )
                ],
            ),
            404: OpenApiResponse(description='Order tukar emas tidak ditemukan'),
        },
        description='Detail order tukar emas milik user yang sedang login (dipakai layar riwayat).',
    )
    def get(self, request, pk):
        order = GoldOrder.objects.filter(pk=pk, user=request.user).first()
        if order is None:
            return Response({
                'error': 'Order tukar emas tidak ditemukan.'
            }, status=status.HTTP_404_NOT_FOUND)
        return Response(GoldOrderSerializer(order).data, status=status.HTTP_200_OK)
