import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from deposits.integrations.quenpay import build_headers, verify_callback_signature
from deposits.models import GatewaySettings, Deposit
from products.models import Transaction

SECRET = "qns_test_secret"
API_KEY = "qnp_test_key"


class QuenpaySignatureTest(TestCase):
    """Signature QuenPay: canonical METHOD\\nPATH\\nTS\\nNONCE\\nSHA256(body)."""

    def test_request_signature_matches_spec(self):
        body = json.dumps({"order_id": "DQP1", "amount": 50000}, separators=(",", ":"))
        headers = build_headers(
            API_KEY, SECRET, "POST", "/api/v1/payment/create", body,
            timestamp="1760000000", nonce="abc123",
        )
        canonical = "\n".join([
            "POST",
            "/api/v1/payment/create",
            "1760000000",
            "abc123",
            hashlib.sha256(body.encode()).hexdigest(),
        ])
        expected = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(headers["X-Quen-Signature"], expected)
        self.assertEqual(headers["X-Quen-Api-Key"], API_KEY)

    def test_callback_signature_verify(self):
        body = '{"event":"payment.success"}'
        ts = "1760000000"
        sig = hmac.new(SECRET.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
        self.assertTrue(verify_callback_signature(SECRET, ts, body, sig))
        self.assertFalse(verify_callback_signature(SECRET, ts, body, "deadbeef"))
        self.assertFalse(verify_callback_signature(SECRET, ts, '{"event":"tampered"}', sig))


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class QuenpayInitiateTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create(
            username="quenpayuser",
            phone="08123450114",
            email="quenpay@example.com",
            full_name="QuenPay User",
            balance=0,
        )
        self.client.force_authenticate(user=self.user)
        GatewaySettings.objects.create(
            default_wallet_type="BALANCE",
            quenpay_enabled=True,
            quenpay_api_url="https://quenpayment.test",
            quenpay_api_key=API_KEY,
            quenpay_secret_key=SECRET,
        )

    def test_initiate_success_returns_qr_string(self):
        fake = {
            "success": True,
            "data": {
                "quen_order_id": "QUEN-1",
                "qr_string": "00020101021226example",
                "status": "PENDING",
                "expired_at": "2026-09-16T23:00:00+07:00",
            },
        }
        with patch("deposits.views.quenpay_post_json", return_value=(fake, 200)) as mocked:
            resp = self.client.post("/api/deposits/quenpay/initiate/", {"amount": 50000}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["qr_string"], "00020101021226example")
        self.assertEqual(resp.data["quen_order_id"], "QUEN-1")
        self.assertEqual(resp.data["amount"], 50000)
        self.assertEqual(mocked.call_args.args[2], "/api/v1/payment/create")
        self.assertEqual(mocked.call_args.args[3]["amount"], 50000)
        dep = Deposit.objects.get(order_num=resp.data["order_num"])
        self.assertEqual(dep.gateway, "QUENPAY")
        self.assertEqual(dep.payment_url, "00020101021226example")

    def test_initiate_failure_marks_deposit_failed(self):
        with patch(
            "deposits.views.quenpay_post_json",
            return_value=({"success": False, "message": "Merchant disabled"}, 403),
        ):
            resp = self.client.post("/api/deposits/quenpay/initiate/", {"amount": 50000}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["detail"], "Merchant disabled")
        dep = Deposit.objects.get(gateway="QUENPAY")
        self.assertEqual(dep.status, "FAILED")


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class QuenpayCallbackTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create(
            username="quenpaycb",
            phone="08123450115",
            email="quenpaycb@example.com",
            full_name="QuenPay CB",
            balance=0,
        )
        GatewaySettings.objects.create(
            default_wallet_type="BALANCE",
            quenpay_enabled=True,
            quenpay_api_url="https://quenpayment.test",
            quenpay_api_key=API_KEY,
            quenpay_secret_key=SECRET,
        )

    def _pending(self, order_num):
        trx = Transaction.objects.create(
            user=self.user,
            type="DEPOSIT",
            amount=Decimal("50000"),
            currency_code="IDR",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id=order_num,
        )
        dep = Deposit.objects.create(
            user=self.user,
            gateway="QUENPAY",
            order_num=order_num,
            amount=Decimal("50000"),
            amount_currency_code="IDR",
            wallet_type="BALANCE",
            status="PENDING",
            transaction=trx,
        )
        return trx, dep

    def _signed_post(self, body, ts="1760000000", secret=SECRET):
        sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
        return self.client.post(
            "/api/deposits/quenpay/callback/",
            data=body,
            content_type="application/json",
            HTTP_X_QUEN_TIMESTAMP=ts,
            HTTP_X_QUEN_SIGNATURE=sig,
            HTTP_X_QUEN_EVENT="payment.success",
        )

    def test_callback_completes_deposit(self):
        trx, dep = self._pending("DQP260916000000TEST01")
        body = json.dumps({
            "event": "payment.success",
            "order_id": "DQP260916000000TEST01",
            "amount": 50000,
            "payment_amount": 50002,
        })
        resp = self._signed_post(body)
        self.assertEqual(resp.status_code, 200)
        trx.refresh_from_db()
        dep.refresh_from_db()
        self.assertEqual(trx.status, "COMPLETED")
        self.assertEqual(dep.status, "COMPLETED")
        self.assertEqual(dep.credited_amount, Decimal("50000"))
        self.assertIsNotNone(dep.callback_at)
        self.assertTrue(dep.callback_payload.get("_sign_valid"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.balance, Decimal("50000"))

    def test_callback_invalid_signature_ignored(self):
        trx, dep = self._pending("DQP260916000000TEST02")
        body = json.dumps({
            "event": "payment.success",
            "order_id": "DQP260916000000TEST02",
            "amount": 50000,
        })
        resp = self._signed_post(body, secret="wrong-secret")
        self.assertEqual(resp.status_code, 200)
        trx.refresh_from_db()
        dep.refresh_from_db()
        self.assertEqual(trx.status, "PENDING")
        self.assertEqual(dep.status, "PENDING")
