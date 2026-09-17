import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from banks.models import Bank, UserBank
from deposits.integrations.reepay import build_signature
from products.models import Transaction
from withdrawal.models import FfpayWithdrawal, Withdrawal, WithdrawalSettings

SECRET = "test-ffpay-payout-secret"


def _signed_headers(path, raw_body, secret=SECRET):
    ts = "1760000000000"
    sig = build_signature(secret, ts, "POST", path, raw_body)
    return {"HTTP_X_TIMESTAMP": ts, "HTTP_X_SIGNATURE": sig}


def _callback_body(merchant_ref, event, amount=50000):
    return json.dumps(
        {
            "event": "disbursement",
            "timestamp": "1760000000000",
            "data": {
                "event": event,
                "ref_id": "WDI260916TEST01",
                "merchant_ref": merchant_ref,
                "disbursement_ref_id": "WD260916TEST01",
                "amount": amount,
                "destination_account": "1234567890",
                "bank_code": "014",
                "status": event.rsplit(".", 1)[-1],
                "pg_error_msg": None,
            },
        },
        separators=(",", ":"),
    )


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class FfpayPayoutCallbackTest(TestCase):
    """Callback disbursement.*: verifikasi signature + update status withdraw."""

    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create(
            username="ffpaywduser",
            phone="08123450121",
            email="ffpaywduser@example.com",
            full_name="FFPay WD",
            balance=Decimal("100000"),
        )
        self.gs = WithdrawalSettings.objects.create(
            ffpay_payout_enabled=True,
            lpay_payout_enabled=True,
            mgm_payout_enabled=True,
            ffpay_payout_api_url="https://api.ffpay.test",
            ffpay_payout_api_key="ak_test",
            ffpay_payout_secret_key=SECRET,
        )
        self.bank = Bank.objects.create(code="014", name="BCA")
        self.user_bank = UserBank.objects.create(
            user=self.user, bank=self.bank, account_name="Budi Santoso", account_number="1234567890"
        )

    def _create_processing(self, trx_id, amount=Decimal("50000")):
        trx = Transaction.objects.create(
            user=self.user,
            type="WITHDRAW",
            amount=amount,
            currency_code="IDR",
            status="PROCESSING",
            wallet_type="BALANCE",
            trx_id=trx_id,
            description="Withdraw test",
        )
        wd = Withdrawal.objects.create(
            user=self.user,
            bank_account=self.user_bank,
            amount=amount,
            net_amount=amount,
            status="PROCESSING",
            transaction=trx,
        )
        return trx, wd

    def test_callback_success_completes_all_wallets(self):
        cases = [
            ("WD-FFPAY-0001", "/api/withdrawals/ffpay/callback/"),
            ("WD-LPAY-0001", "/api/withdrawals/lpay/callback/"),
            ("WD-MGM-0001", "/api/withdrawals/mgm/callback/"),
        ]
        for trx_id, path in cases:
            trx, wd = self._create_processing(trx_id)
            body = _callback_body(trx_id, "disbursement.success")
            resp = self.client.post(
                path, data=body, content_type="application/json", **_signed_headers(path, body)
            )
            self.assertEqual(resp.status_code, 200, path)
            wd.refresh_from_db()
            trx.refresh_from_db()
            self.assertEqual(wd.status, "COMPLETED", path)
            self.assertEqual(trx.status, "COMPLETED", path)

    def test_callback_failed_rejects_and_refunds(self):
        trx, wd = self._create_processing("WD-FFPAY-0002")
        path = "/api/withdrawals/ffpay/callback/"
        body = _callback_body("WD-FFPAY-0002", "disbursement.failed")
        resp = self.client.post(
            path, data=body, content_type="application/json", **_signed_headers(path, body)
        )
        self.assertEqual(resp.status_code, 200)
        wd.refresh_from_db()
        self.assertEqual(wd.status, "REJECTED")
        self.user.refresh_from_db()
        # Saldo dikembalikan otomatis oleh Withdrawal.save() saat REJECTED
        self.assertEqual(self.user.balance, Decimal("150000"))

    def test_callback_via_deposits_path_routes_to_withdraw(self):
        trx, wd = self._create_processing("WD-FFPAY-0003")
        path = "/api/deposits/ffpay/callback/"
        body = _callback_body("WD-FFPAY-0003", "disbursement.success")
        resp = self.client.post(
            path, data=body, content_type="application/json", **_signed_headers(path, body)
        )
        self.assertEqual(resp.status_code, 200)
        wd.refresh_from_db()
        self.assertEqual(wd.status, "COMPLETED")

    def test_callback_invalid_signature_ignored(self):
        trx, wd = self._create_processing("WD-FFPAY-0004")
        FfpayWithdrawal.objects.create(withdrawal=wd, wallet="ffpay")
        path = "/api/withdrawals/ffpay/callback/"
        body = _callback_body("WD-FFPAY-0004", "disbursement.success")
        resp = self.client.post(
            path, data=body, content_type="application/json",
            **_signed_headers(path, body, secret="wrong-secret"),
        )
        self.assertEqual(resp.status_code, 200)
        wd.refresh_from_db()
        self.assertEqual(wd.status, "PROCESSING")
        trace = FfpayWithdrawal.objects.get(withdrawal=wd)
        self.assertFalse(trace.response_payload["callback"]["_sign_valid"])


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class FfpayPayoutInitiateTest(TestCase):
    """Initiate payout: flag aktif, validasi amount, dan kode bank per wallet."""

    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.admin = User.objects.create(
            username="ffpayadmin",
            phone="08123450122",
            email="ffpayadmin@example.com",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_authenticate(user=self.admin)
        self.gs = WithdrawalSettings.objects.create(
            ffpay_payout_enabled=True,
            lpay_payout_enabled=True,
            mgm_payout_enabled=True,
            ffpay_payout_api_url="https://api.ffpay.test",
            ffpay_payout_api_key="ak_test",
            ffpay_payout_secret_key=SECRET,
        )
        self.user = User.objects.create(
            username="ffpayinituser",
            phone="08123450123",
            email="ffpayinituser@example.com",
            balance=Decimal("0"),
        )
        self.bank = Bank.objects.create(code="014", name="BCA")
        self.user_bank = UserBank.objects.create(
            user=self.user, bank=self.bank, account_name="Budi Santoso", account_number="1234567890"
        )
        self.trx = Transaction.objects.create(
            user=self.user,
            type="WITHDRAW",
            amount=Decimal("50000"),
            currency_code="IDR",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="WFP260916TEST01",
            description="Withdraw test",
        )
        self.wd = Withdrawal.objects.create(
            user=self.user,
            bank_account=self.user_bank,
            amount=Decimal("50000"),
            net_amount=Decimal("50000"),
            status="PENDING",
            transaction=self.trx,
        )

    def _url(self, wallet):
        return f"/api/withdrawals/{wallet}/initiate/{self.wd.pk}/"

    def test_initiate_disabled_wallet(self):
        self.gs.lpay_payout_enabled = False
        self.gs.save()
        resp = self.client.post(self._url("lpay"), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_initiate_amount_below_minimum(self):
        resp = self.client.post(self._url("ffpay"), {"amount": 5000}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_initiate_bank_code_per_wallet(self):
        fake = {"success": True, "data": {"ref_id": "WD260916TEST01", "status": "processing", "amount": 50000}}
        cases = [
            ("ffpay", "/gateway/payout/create", "014"),
            ("lpay", "/gateway/lpay/payout", "BCA"),
            ("mgm", "/gateway/mgm/payout", "10014"),
        ]
        for wallet, api_path, expected_code in cases:
            with patch("withdrawal.views.reepay_post_json", return_value=(fake, 200)) as mocked:
                resp = self.client.post(self._url(wallet), {}, format="json")
            self.assertEqual(resp.status_code, 200, wallet)
            self.assertEqual(mocked.call_args.args[2], api_path, wallet)
            payload = mocked.call_args.args[3]
            self.assertEqual(payload["bank_code"], expected_code, wallet)
            self.assertEqual(payload["merchant_ref"], "WFP260916TEST01", wallet)
            self.assertEqual(payload["amount"], 50000, wallet)
        self.wd.refresh_from_db()
        self.assertEqual(self.wd.status, "PROCESSING")
        self.assertIn("ref_id: WD260916TEST01", self.wd.note)
        trace = FfpayWithdrawal.objects.get(withdrawal=self.wd)
        self.assertEqual(trace.wallet, "mgm")

    def test_initiate_unmapped_bank_rejected(self):
        self.bank.code = "020"  # Bank Artha Niaga Kencana — tidak ada di tabel LPAY/MGM
        self.bank.save()
        resp = self.client.post(self._url("mgm"), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class FfpayAdminProcessOverrideTest(TestCase):
    """Admin process form: bank pilihan admin menang atas bank user."""

    def setUp(self):
        self.client = Client()
        User = get_user_model()
        self.admin = User.objects.create(
            username="ffpayadmpick",
            phone="08123450124",
            email="ffpayadmpick@example.com",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.admin)
        WithdrawalSettings.objects.create(
            ffpay_payout_enabled=True,
            lpay_payout_enabled=True,
            mgm_payout_enabled=True,
            ffpay_payout_api_url="https://api.ffpay.test",
            ffpay_payout_api_key="ak_test",
            ffpay_payout_secret_key=SECRET,
        )
        user = User.objects.create(
            username="ffpaypickuser",
            phone="08123450125",
            email="ffpaypickuser@example.com",
            balance=Decimal("0"),
        )
        bank = Bank.objects.create(code="10002", name="DANA")
        user_bank = UserBank.objects.create(
            user=user, bank=bank, account_name="Aqeela Calista", account_number="085641453156"
        )
        trx = Transaction.objects.create(
            user=user,
            type="WITHDRAW",
            amount=Decimal("50000"),
            currency_code="IDR",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="WFP260917PICK01",
            description="Withdraw test",
        )
        self.wd = Withdrawal.objects.create(
            user=user,
            bank_account=user_bank,
            amount=Decimal("50000"),
            net_amount=Decimal("44500"),
            status="PENDING",
            transaction=trx,
        )

    def test_admin_bank_picker_overrides_user_bank(self):
        # Bank user DANA (10002), admin memilih Seabank (535) — kode kirim harus ikut pilihan admin.
        url = reverse("admin:withdrawal_withdrawal_process_ffpay", args=[self.wd.pk])
        fake = {"success": True, "data": {"ref_id": "WD260917PICK01"}}
        cases = [("ffpay", "535"), ("lpay", "SEABANK"), ("mgm", "10535")]
        for wallet, expected in cases:
            with patch("withdrawal.admin.reepay_post_json", return_value=(fake, 200)) as mocked:
                resp = self.client.post(url, {
                    "wallet": wallet,
                    "bank_code": "535",
                    "destination_account": "085641453156",
                    "account_holder_name": "Aqeela Calista",
                    "amount": "44500",
                })
            self.assertEqual(resp.status_code, 302, wallet)
            payload = mocked.call_args.args[3]
            self.assertEqual(payload["bank_code"], expected, wallet)
        self.wd.refresh_from_db()
        self.assertEqual(self.wd.status, "PROCESSING")

    def test_change_form_renders_bank_picker(self):
        url = reverse("admin:withdrawal_withdrawal_change", args=[self.wd.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="id_fp_bank"')
        self.assertContains(resp, 'value="10002" selected')  # bank user DANA jadi default pilihan
        self.assertContains(resp, 'data-mgm="10951"')  # kode MGM DANA tampil di opsi
