import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from banks.models import Bank, UserBank
from deposits.integrations.reepay import build_signature
from deposits.integrations.yuipay import post_json as yuipay_post_json
from deposits.models import GatewaySettings, Deposit
from products.models import Transaction
from withdrawal.models import Withdrawal, WithdrawalSettings

SECRET = "test-yuipay-secret"
PAYOUT_SECRET = "test-yuipay-payout-secret"


def _signed_headers(path, raw_body, secret=SECRET):
    ts = "1760000000000"
    return {"HTTP_X_TIMESTAMP": ts, "HTTP_X_SIGNATURE": build_signature(secret, ts, "POST", path, raw_body)}


class YuipayHeaderTest(TestCase):
    """Header X-Merchant-Code wajib ikut terkirim (beda Yuipay vs Reepay)."""

    def test_post_json_sends_merchant_code(self):
        resp = type("R", (), {"json": lambda self: {"success": True}, "status_code": 200})()
        with patch("deposits.integrations.reepay.requests.post", return_value=resp) as mocked:
            yuipay_post_json("ak_test", "MCH-0001", SECRET, "/merchant/payment/create", {"amount": 10000})
        headers = mocked.call_args.kwargs["headers"]
        self.assertEqual(headers["X-Merchant-Code"], "MCH-0001")
        self.assertEqual(headers["X-API-Key"], "ak_test")


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class YuipayDepositTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create(
            username="yuipayuser", phone="08123450211", email="yuipay@example.com",
            full_name="Yuipay User", balance=0,
        )
        self.client.force_authenticate(user=self.user)
        self.gs = GatewaySettings.objects.create(
            default_wallet_type="BALANCE",
            app_domain="app.test",
            yuipay_enabled=True,
            yuipay_api_key="ak_test",
            yuipay_merchant_code="MCH-0001",
            yuipay_secret_key=SECRET,
        )

    def test_initiate_builds_payload_and_records_deposit(self):
        fake = {"success": True, "data": {
            "ref_id": "YP1", "pay_url": "https://pay.test/1", "method": "QRIS",
            "pay_data": "000201...", "pay_data_type": "QR_CODE",
        }}
        with patch("deposits.views.yuipay_post_json", return_value=(fake, 200)) as mocked:
            resp = self.client.post("/api/deposits/yuipay/initiate/", {"amount": 50000, "method": "qris"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        args = mocked.call_args.args
        self.assertEqual(args[1], "MCH-0001")  # merchant_code
        self.assertEqual(args[3], "/merchant/payment/create")
        self.assertEqual(args[4]["callback_url"], "https://app.test/api/deposits/yuipay/callback/")
        self.assertEqual(args[4]["method"], "QRIS")
        dep = Deposit.objects.get(order_num=resp.data["order_num"])
        self.assertEqual(dep.gateway, "YUIPAY")
        self.assertEqual(dep.payment_url, "https://pay.test/1")
        self.assertEqual(resp.data["pay_data"], "000201...")

    def test_initiate_requires_merchant_code(self):
        self.gs.yuipay_merchant_code = ""
        self.gs.save()
        resp = self.client.post("/api/deposits/yuipay/initiate/", {"amount": 50000}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_callback_credits_balance_only_with_valid_signature(self):
        trx = Transaction.objects.create(
            user=self.user, type="DEPOSIT", amount=Decimal("50000"), currency_code="IDR",
            status="PENDING", wallet_type="BALANCE", trx_id="DYP260915TEST0001",
        )
        dep = Deposit.objects.create(
            user=self.user, gateway="YUIPAY", order_num="DYP260915TEST0001",
            amount=Decimal("50000"), amount_currency_code="IDR", wallet_type="BALANCE",
            status="PENDING", transaction=trx,
        )
        path = "/api/deposits/yuipay/callback/"
        body = json.dumps({"event": "payment", "timestamp": "1760000000000", "data": {
            "event": "payment.paid", "ref_id": "YP1", "merchant_ref": dep.order_num, "amount": 50000,
        }}, separators=(",", ":"))

        resp = self.client.post(path, data=body, content_type="application/json",
                                **_signed_headers(path, body, secret="wrong"))
        self.assertEqual(resp.status_code, 200)
        dep.refresh_from_db()
        self.assertEqual(dep.status, "PENDING")
        self.assertFalse(dep.callback_payload["_sign_valid"])

        resp = self.client.post(path, data=body, content_type="application/json",
                                **_signed_headers(path, body))
        self.assertEqual(resp.status_code, 200)
        trx.refresh_from_db()
        dep.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(trx.status, "COMPLETED")
        self.assertEqual(dep.status, "COMPLETED")
        self.assertEqual(self.user.balance, Decimal("50000"))


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class YuipayPayoutTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create(username="yuipayout", phone="08123450212", email="yuipayout@example.com", balance=0)
        self.admin = User.objects.create(username="yuipadmin", phone="08123450213", email="yuipadmin@example.com", is_staff=True)
        self.client.force_authenticate(user=self.admin)
        WithdrawalSettings.objects.create(
            is_active=True, app_domain="app.test",
            yuipay_payout_enabled=True,
            yuipay_payout_api_key="ak_test",
            yuipay_payout_merchant_code="MCH-0001",
            yuipay_payout_secret_key=PAYOUT_SECRET,
        )

    def _withdrawal(self, bank_code):
        bank = Bank.objects.create(
            code=bank_code, name=bank_code, min_withdrawal=0, max_withdrawal=0,
            withdrawal_fee=0, withdrawal_fee_fixed=0,
        )
        user_bank = UserBank.objects.create(
            user=self.user, bank=bank, account_name="Yuipay User",
            account_number="1234567890", is_default=True,
        )
        trx = Transaction.objects.create(
            user=self.user, type="WITHDRAW", amount=Decimal("50000"), currency_code="IDR",
            status="PENDING", wallet_type="BALANCE", trx_id=f"WD-{bank_code}",
        )
        return Withdrawal.objects.create(
            user=self.user, bank_account=user_bank, amount=Decimal("50000"),
            fee=0, net_amount=Decimal("50000"), status="PENDING", transaction=trx,
        )

    def test_unsupported_bank_rejected(self):
        wd = self._withdrawal("999")
        resp = self.client.post(f"/api/withdrawals/yuipay/initiate/{wd.pk}/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("belum didukung", resp.data["detail"])

    def test_callback_marks_withdrawal_completed(self):
        wd = self._withdrawal("014")
        path = "/api/withdrawals/yuipay/callback/"
        body = json.dumps({"event": "disbursement", "timestamp": "1760000000000", "data": {
            "event": "disbursement.success", "ref_id": "WDI1",
            "merchant_ref": wd.transaction.trx_id, "amount": 50000, "status": "success",
        }}, separators=(",", ":"))
        resp = self.client.post(path, data=body, content_type="application/json",
                                **_signed_headers(path, body, secret=PAYOUT_SECRET))
        self.assertEqual(resp.status_code, 200)
        wd.refresh_from_db()
        self.assertEqual(wd.status, "COMPLETED")
