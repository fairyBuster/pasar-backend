from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework import serializers
from rest_framework.test import APIClient

from accounts.balance_serializers import BalanceStatisticsSerializer
from accounts.models import GeneralSetting, RankLevel
from accounts.serializers import DownlineListSerializer, DownlineStatsResponseSerializer, ProfilePhotoSerializer
from deposits.models import Deposit
from products.models import Transaction


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class AccountInfoRankSyncTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="rank-user",
            phone="8111222333",
            email="rank@example.com",
            password="pass123",
        )
        User.objects.create_user(
            username="child-user",
            phone="8111222444",
            email="child@example.com",
            password="pass123",
            referral_by=self.user,
        )
        GeneralSetting.objects.create(
            rank_use_missions=False,
            rank_use_downlines_total=True,
            rank_use_downlines_active=False,
            rank_use_deposit_self_total=False,
            rank_use_team_deposit_level_1_total=False,
            rank_count_levels_upto=1,
        )
        RankLevel.objects.create(
            rank=1,
            title="intern",
            missions_required_total=0,
            downlines_total_required=1,
            downlines_active_required=0,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="0.00",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_account_info_updates_rank_before_responding(self):
        self.assertIsNone(self.user.rank)

        response = self.client.get("/api/auth/account-info/")

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.rank, 1)
        self.assertEqual(response.data["rank"], 1)


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class RankOrLogicTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="rank-or-user",
            phone="8111222555",
            email="rankor@example.com",
            password="pass123",
            rank=1,
        )
        self.child = User.objects.create_user(
            username="rank-or-child",
            phone="8111222666",
            email="rankorchild@example.com",
            password="pass123",
            referral_by=self.user,
        )
        GeneralSetting.objects.create(
            rank_use_missions=False,
            rank_use_downlines_total=False,
            rank_use_downlines_active=True,
            rank_use_deposit_self_total=False,
            rank_use_team_deposit_level_1_total=True,
            rank_count_levels_upto=1,
        )
        RankLevel.objects.create(
            rank=1,
            title="intern",
            missions_required_total=0,
            downlines_total_required=0,
            downlines_active_required=0,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="0.00",
        )
        RankLevel.objects.create(
            rank=2,
            title="EV1",
            missions_required_total=0,
            downlines_total_required=0,
            downlines_active_required=10,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="2500000.00",
        )
        Deposit.objects.create(
            user=self.child,
            gateway="JAYAPAY",
            order_num="DEP-RANK-OR-001",
            amount="6400000.00",
            credited_amount="6400000.00",
            wallet_type="BALANCE",
            status="COMPLETED",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_account_info_uses_or_logic_for_rank_update(self):
        response = self.client.get("/api/auth/account-info/")

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.rank, 2)
        self.assertEqual(response.data["rank"], 2)

    def test_rank_status_uses_or_logic_for_expected_rank(self):
        response = self.client.get("/api/auth/rank-status/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["current_rank"], 2)
        self.assertEqual(response.data["current_title"], "EV1")


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class RankAndLogicTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="rank-and-user",
            phone="8111222777",
            email="rankand@example.com",
            password="pass123",
            rank=1,
        )
        self.child = User.objects.create_user(
            username="rank-and-child",
            phone="8111222888",
            email="rankandchild@example.com",
            password="pass123",
            referral_by=self.user,
        )
        GeneralSetting.objects.create(
            rank_logic="AND",
            rank_use_missions=False,
            rank_use_downlines_total=False,
            rank_use_downlines_active=True,
            rank_use_deposit_self_total=False,
            rank_use_team_deposit_level_1_total=True,
            rank_count_levels_upto=1,
        )
        RankLevel.objects.create(
            rank=1,
            title="intern",
            missions_required_total=0,
            downlines_total_required=0,
            downlines_active_required=0,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="0.00",
        )
        RankLevel.objects.create(
            rank=2,
            title="EV1",
            missions_required_total=0,
            downlines_total_required=0,
            downlines_active_required=10,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="2500000.00",
        )
        Deposit.objects.create(
            user=self.child,
            gateway="JAYAPAY",
            order_num="DEP-RANK-AND-001",
            amount="6400000.00",
            credited_amount="6400000.00",
            wallet_type="BALANCE",
            status="COMPLETED",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_rank_status_keeps_lower_rank_when_and_requirements_not_all_met(self):
        response = self.client.get("/api/auth/rank-status/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["current_rank"], 1)
        self.assertEqual(response.data["current_title"], "intern")


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class ActiveMemberDefinitionTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="active-def-user",
            phone="8111999000",
            email="actdef@example.com",
            password="pass123",
        )
        self.child = User.objects.create_user(
            username="active-def-child",
            phone="8111999001",
            email="actdefchild@example.com",
            password="pass123",
            referral_by=self.user,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_active_downlines_uses_deposit_completed_when_configured(self):
        GeneralSetting.objects.create(
            active_member_logic="OR",
            active_member_use_deposit_completed=True,
            active_member_use_active_investment=False,
            rank_use_missions=False,
            rank_use_downlines_total=False,
            rank_use_downlines_active=True,
            rank_use_deposit_self_total=False,
            rank_use_team_deposit_level_1_total=False,
            rank_count_levels_upto=1,
        )
        RankLevel.objects.create(
            rank=1,
            title="intern",
            missions_required_total=0,
            downlines_total_required=0,
            downlines_active_required=0,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="0.00",
        )
        RankLevel.objects.create(
            rank=2,
            title="EV1",
            missions_required_total=0,
            downlines_total_required=0,
            downlines_active_required=1,
            deposit_self_total_required="0.00",
            team_deposit_level_1_total_required="0.00",
        )
        Deposit.objects.create(
            user=self.child,
            gateway="JAYAPAY",
            order_num="DEP-ACTDEF-001",
            amount="100000.00",
            credited_amount="100000.00",
            wallet_type="BALANCE",
            status="COMPLETED",
        )
        resp = self.client.get("/api/auth/account-info/")
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.rank, 2)


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class PublicSettingsOtpFlagTest(TestCase):
    def setUp(self):
        GeneralSetting.objects.create(
            otp_enabled=False,
            whatsapp_check_enabled=True,
            otp_provider="AUTO",
        )
        self.client = APIClient()

    def test_public_settings_exposes_otp_enabled_flag(self):
        resp = self.client.get("/api/auth/settings/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("otp_enabled", resp.data)
        self.assertEqual(resp.data["otp_enabled"], False)


class ProfilePhotoValidationTest(TestCase):
    """Validasi upload foto profil: decompression-bomb ditolak, PNG normal lolos."""

    def _png(self, size):
        buf = BytesIO()
        Image.new("RGB", size, color=(120, 10, 10)).save(buf, format="PNG")
        buf.seek(0)
        return SimpleUploadedFile("foto.png", buf.read(), content_type="image/png")

    def test_rejects_decompression_bomb(self):
        with self.assertRaises(serializers.ValidationError):
            ProfilePhotoSerializer().validate_avatar(self._png((5001, 5001)))

    def test_accepts_normal_png(self):
        ProfilePhotoSerializer().validate_avatar(self._png((64, 64)))


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class AccountInfoCacheTest(TestCase):
    """account-info di-cache per user; cache rilis otomatis begitu data berubah."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="cache-info-user",
            phone="8111888777",
            email="cacheinfo@example.com",
            password="pass123",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_cache_hit_dan_rilis_saat_data_berubah(self):
        with patch("accounts.views.update_user_rank") as mocked_rank:
            first = self.client.get("/api/auth/account-info/")
            self.assertEqual(first.status_code, 200)
            self.assertEqual(mocked_rank.call_count, 1)

            # Request kedua tanpa perubahan data: disajikan dari cache (rank tidak dihitung lagi)
            second = self.client.get("/api/auth/account-info/")
            self.assertEqual(second.data, first.data)
            self.assertEqual(mocked_rank.call_count, 1)

            # Data berubah -> cache rilis, respons baru
            self.user.balance = Decimal("12345.00")
            self.user.save(update_fields=["balance"])
            third = self.client.get("/api/auth/account-info/")
            self.assertEqual(third.data["balance"], "12345.00")
            self.assertEqual(mocked_rank.call_count, 2)


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class BalanceStatisticsCacheTest(TestCase):
    """Statistik balance di-cache per user+period; cache rilis otomatis saat data berubah."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="balstat-user",
            phone="8111777666",
            email="balstat@example.com",
            password="pass123",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_all_time_cache_hit_dan_rilis_saat_data_berubah(self):
        url = "/api/auth/balance-statistics/all-time/"
        with patch("accounts.views.BalanceStatisticsSerializer", wraps=BalanceStatisticsSerializer) as mocked_ser:
            first = self.client.get(url)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(mocked_ser.call_count, 1)

            # Request kedua tanpa perubahan: disajikan dari cache (tidak hitung ulang)
            second = self.client.get(url)
            self.assertEqual(second.data, first.data)
            self.assertEqual(mocked_ser.call_count, 1)

            # Balance berubah -> cache rilis
            self.user.balance = Decimal("500.00")
            self.user.save(update_fields=["balance"])
            third = self.client.get(url)
            self.assertEqual(third.data["balance"], "500.00")
            self.assertEqual(mocked_ser.call_count, 2)

            # Deposit COMPLETED baru -> cache rilis juga, total deposit naik
            Deposit.objects.create(
                user=self.user,
                gateway="JAYAPAY",
                order_num="DEP-BALSTAT-001",
                amount=Decimal("150.00"),
                credited_amount=Decimal("150.00"),
                wallet_type="BALANCE",
                status="COMPLETED",
            )
            fourth = self.client.get(url)
            self.assertEqual(fourth.data["total_deposit_completed"], "150.00")
            self.assertEqual(mocked_ser.call_count, 3)

    def test_ganti_hari_otomatis_rilis_cache_period_today(self):
        url = "/api/auth/balance-statistics/today/"
        day1 = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
        day2 = day1 + timedelta(days=1)
        with patch("accounts.views.timezone.now", return_value=day1), \
                patch("accounts.views.BalanceStatisticsSerializer", wraps=BalanceStatisticsSerializer) as mocked_ser:
            self.client.get(url)
            self.client.get(url)
            self.assertEqual(mocked_ser.call_count, 1)  # request kedua kena cache

            with patch("accounts.views.timezone.now", return_value=day2):
                self.client.get(url)
            self.assertEqual(mocked_ser.call_count, 2)  # hari berganti -> hitung ulang


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class DownlineListCacheTest(TestCase):
    """Daftar downline di-cache per user+filter; cache rilis otomatis saat data berubah."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="dl-user",
            phone="8111888999",
            email="dl@example.com",
            password="pass123",
        )
        self.child = User.objects.create_user(
            username="dl-child",
            phone="8111889000",
            email="dlchild@example.com",
            password="pass123",
            referral_by=self.user,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_cache_hit_dan_rilis_saat_data_berubah(self):
        User = get_user_model()
        url = "/api/auth/downline-list/"
        with patch("accounts.views.DownlineListSerializer", wraps=DownlineListSerializer) as mocked_ser:
            first = self.client.get(url)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.data["total_members"], 1)
            self.assertEqual(mocked_ser.call_count, 1)

            # Request kedua tanpa perubahan: disajikan dari cache
            second = self.client.get(url)
            self.assertEqual(second.data, first.data)
            self.assertEqual(mocked_ser.call_count, 1)

            # Filter lain punya key sendiri; balik ke URL awal tetap kena cache
            self.client.get(url + "?level=2")
            self.assertEqual(mocked_ser.call_count, 2)
            self.client.get(url)
            self.assertEqual(mocked_ser.call_count, 2)

            # Anggota baru masuk subtree (level 2) -> cache rilis
            User.objects.create_user(
                username="dl-child2",
                phone="8111889001",
                email="dlchild2@example.com",
                password="pass123",
                referral_by=self.child,
            )
            third = self.client.get(url)
            self.assertEqual(third.data["total_members"], 2)
            self.assertEqual(mocked_ser.call_count, 3)

            # Rank anggota berubah via save(update_fields) (updated_at tidak ikut bump) -> rilis
            self.child.rank = 1
            self.child.save(update_fields=["rank"])
            fourth = self.client.get(url)
            self.assertEqual(fourth.data["members"][0]["rank"], 1)
            self.assertEqual(mocked_ser.call_count, 4)

            # Deposit COMPLETED milik anggota -> is_active anggota berubah -> rilis
            Deposit.objects.create(
                user=self.child,
                gateway="JAYAPAY",
                order_num="DEP-DL-001",
                amount=Decimal("100.00"),
                credited_amount=Decimal("100.00"),
                wallet_type="BALANCE",
                status="COMPLETED",
            )
            fifth = self.client.get(url)
            self.assertEqual(fifth.data["members"][0]["is_active"], True)
            self.assertEqual(mocked_ser.call_count, 5)


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class DownlineStatsCacheTest(TestCase):
    """Statistik downline di-cache per user; cache rilis otomatis saat data berubah."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="dlstat-user",
            phone="8111999000",
            email="dlstat@example.com",
            password="pass123",
        )
        self.child = User.objects.create_user(
            username="dlstat-child",
            phone="8111999001",
            email="dlstatchild@example.com",
            password="pass123",
            referral_by=self.user,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_cache_hit_dan_rilis_saat_data_berubah(self):
        User = get_user_model()
        url = "/api/auth/downline-stats/"
        with patch("accounts.views.DownlineStatsResponseSerializer", wraps=DownlineStatsResponseSerializer) as mocked_ser:
            first = self.client.get(url)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(len(first.data["levels"]), 5)
            self.assertEqual(first.data["levels"][0]["members_total"], 1)
            self.assertEqual(mocked_ser.call_count, 1)

            # Request kedua tanpa perubahan: disajikan dari cache
            second = self.client.get(url)
            self.assertEqual(second.data, first.data)
            self.assertEqual(mocked_ser.call_count, 1)

            # Anggota baru di level 1 -> cache rilis
            User.objects.create_user(
                username="dlstat-child2",
                phone="8111999002",
                email="dlstatchild2@example.com",
                password="pass123",
                referral_by=self.user,
            )
            third = self.client.get(url)
            self.assertEqual(third.data["levels"][0]["members_total"], 2)
            self.assertEqual(mocked_ser.call_count, 2)

            # Deposit COMPLETED milik anggota -> level 1 jadi aktif -> rilis
            Deposit.objects.create(
                user=self.child,
                gateway="JAYAPAY",
                order_num="DEP-DLS-001",
                amount=Decimal("100.00"),
                credited_amount=Decimal("100.00"),
                wallet_type="BALANCE",
                status="COMPLETED",
            )
            fourth = self.client.get(url)
            self.assertEqual(fourth.data["levels"][0]["members_active"], 1)
            self.assertEqual(fourth.data["levels"][0]["deposits_total_count"], 1)
            self.assertEqual(fourth.data["levels"][0]["deposits_total_amount"], "100.00")
            self.assertEqual(mocked_ser.call_count, 3)

            # Komisi baru (PROFIT_COMMISSION level 1) -> rilis
            Transaction.objects.create(
                user=self.user,
                trx_id="TRX-DLS-001",
                type="PROFIT_COMMISSION",
                commission_level=1,
                amount=Decimal("10.00"),
                description="Komisi test",
                status="COMPLETED",
                wallet_type="BALANCE",
            )
            fifth = self.client.get(url)
            self.assertEqual(fifth.data["levels"][0]["profit_commission_amount"], "10.00")
            self.assertEqual(mocked_ser.call_count, 4)
