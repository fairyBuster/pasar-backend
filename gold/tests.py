from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from accounts.models import UserAddress
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from gold.models import GoldOrder, GoldSettings
from gold.serializers import GoldInfoResponseSerializer
from gold.services import get_gold_price_per_gram


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class GoldInfoCacheTest(TestCase):
    """Info emas di-cache per user; cache rilis otomatis saat data berubah."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="gold-user",
            phone="8111000111",
            email="gold@example.com",
            password="pass123",
            balance_hold=Decimal("500.00"),
            balance_deposit=Decimal("100.00"),
        )
        # Migrasi 0002 seed satu baris GoldSettings; load() ambil baris paling awal,
        # jadi konfigurasi row itu (bukan bikin row baru).
        self.settings_obj = GoldSettings.load()
        self.settings_obj.is_active = True
        self.settings_obj.printing_fee_per_gram = Decimal("20000.00")
        self.settings_obj.shipping_cost = Decimal("15000.00")
        self.settings_obj.price_cache_minutes = 5
        self.settings_obj.last_price_per_gram = Decimal("1500000.00")
        self.settings_obj.last_price_usd_per_oz = Decimal("2680.50")
        self.settings_obj.last_usd_idr_rate = Decimal("16250.5000")
        self.settings_obj.last_price_updated_at = timezone.now()
        self.settings_obj.save()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_cache_hit_dan_rilis_saat_data_berubah(self):
        url = "/api/gold/info/"
        with patch("gold.views.GoldInfoResponseSerializer", wraps=GoldInfoResponseSerializer) as mocked_ser:
            first = self.client.get(url)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.data["price_source"], "cache")  # harga masih fresh, tanpa API call
            self.assertEqual(first.data["price_per_gram"], "1500000.00")
            self.assertEqual(first.data["balance_hold"], "500.00")
            self.assertEqual(mocked_ser.call_count, 1)

            # Request kedua tanpa perubahan: disajikan dari cache
            second = self.client.get(url)
            self.assertEqual(second.data, first.data)
            self.assertEqual(mocked_ser.call_count, 1)

            # Saldo user berubah -> cache rilis
            self.user.balance_hold = Decimal("450.00")
            self.user.save(update_fields=["balance_hold"])
            third = self.client.get(url)
            self.assertEqual(third.data["balance_hold"], "450.00")
            self.assertEqual(mocked_ser.call_count, 2)

            # Tarif di GoldSettings berubah -> cache rilis
            self.settings_obj.printing_fee_per_gram = Decimal("25000.00")
            self.settings_obj.save(update_fields=["printing_fee_per_gram"])
            fourth = self.client.get(url)
            self.assertEqual(fourth.data["printing_fee_per_gram"], "25000.00")
            self.assertEqual(mocked_ser.call_count, 3)

            # Window harga lewat (price_cache_minutes) -> cache rilis, harga diambil ulang
            future = timezone.now() + timedelta(minutes=10)
            with patch("gold.views.timezone.now", return_value=future), \
                    patch("gold.views.get_gold_price_per_gram",
                          return_value=(self.settings_obj, Decimal("1600000.00"), "live")):
                fifth = self.client.get(url)
            self.assertEqual(fifth.data["price_per_gram"], "1600000.00")
            self.assertEqual(fifth.data["price_source"], "live")
            self.assertEqual(mocked_ser.call_count, 4)


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class GoldStaleFallbackTest(TestCase):
    """API harga emas gagal dipanggil -> pakai harga terakhir yang tersimpan, bukan error."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="gold-stale",
            phone="8111000222",
            email="gold-stale@example.com",
            password="pass123",
            balance_hold=Decimal("5000000.00"),
            balance_deposit=Decimal("100000.00"),
        )
        self.address = UserAddress.objects.create(
            user=self.user,
            recipient_name="Budi Santoso",
            phone_number="081234567890",
            address_details="Jl. Merdeka No. 10",
            house_number="10",
        )
        # Migrasi 0002 seed satu baris GoldSettings; load() ambil baris paling awal.
        self.settings_obj = GoldSettings.load()
        self.settings_obj.is_active = True
        self.settings_obj.printing_fee_per_gram = Decimal("20000.00")
        self.settings_obj.shipping_cost = Decimal("15000.00")
        self.settings_obj.price_cache_minutes = 5
        self.settings_obj.last_price_per_gram = Decimal("1500000.00")
        self.settings_obj.last_price_usd_per_oz = Decimal("2680.50")
        self.settings_obj.last_usd_idr_rate = Decimal("16250.5000")
        # Window cache sudah lewat -> service mencoba fetch (di-patch gagal di test).
        self.settings_obj.last_price_updated_at = timezone.now() - timedelta(hours=1)
        self.settings_obj.save()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_service_dan_info_pakai_harga_terakhir_saat_api_gagal(self):
        with patch("gold.services.requests.get", side_effect=ConnectionError("simulasi API down")):
            settings_obj, price, source = get_gold_price_per_gram()
            self.assertEqual(source, "stale")
            self.assertEqual(price, Decimal("1500000.00"))

            response = self.client.get("/api/gold/info/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["price_available"])
        self.assertEqual(response.data["price_source"], "stale")
        self.assertEqual(response.data["price_per_gram"], "1500000.00")

        # Harga tersimpan tidak berubah / tidak ter-overwrite saat gagal
        self.settings_obj.refresh_from_db()
        self.assertEqual(self.settings_obj.last_price_per_gram, Decimal("1500000.00"))

    def test_swap_tetap_jalan_pakai_harga_terakhir_saat_api_gagal(self):
        with patch("gold.services.requests.get", side_effect=ConnectionError("simulasi API down")):
            response = self.client.post(
                "/api/gold/swap/",
                {"gram": "0.5", "address_id": self.address.id},
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["price_source"], "stale")
        self.assertEqual(response.data["price_per_gram"], "1500000.00")
        self.assertEqual(response.data["order"]["price_per_gram"], "1500000.00")
        # Nilai emas = 0.5 gram x harga terakhir ter-simpan (1.500.000/gram)
        self.assertEqual(response.data["order"]["gold_value"], "750000.00")

        self.user.refresh_from_db()
        self.assertEqual(self.user.balance_hold, Decimal("4250000.00"))   # 5.000.000 - 750.000
        self.assertEqual(self.user.balance_deposit, Decimal("75000.00"))  # 100.000 - (10.000 + 15.000)
        self.assertEqual(GoldOrder.objects.count(), 1)
