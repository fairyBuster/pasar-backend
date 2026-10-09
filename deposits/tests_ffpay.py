import base64
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from banks.models import Bank, UserBank
from deposits.integrations.reepay import build_signature
from deposits.models import GatewaySettings, Deposit
from deposits.views import _scrape_mgm_payment_page, _scrape_lpay_payment_page
from products.models import Transaction
from withdrawal.models import Withdrawal, WithdrawalSettings

SECRET = "test-ffpay-secret"


def _signed_headers(path, raw_body, secret=SECRET):
    ts = "1760000000000"
    sig = build_signature(secret, ts, "POST", path, raw_body)
    return {"HTTP_X_TIMESTAMP": ts, "HTTP_X_SIGNATURE": sig}


def _callback_body(merchant_ref, amount=50000, event="payment.paid"):
    return json.dumps(
        {
            "event": "payment",
            "timestamp": "1760000000000",
            "data": {
                "event": event,
                "ref_id": "TXN260915TEST01",
                "merchant_ref": merchant_ref,
                "amount": amount,
                "status": "paid",
            },
        },
        separators=(",", ":"),
    )


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class FfpayCallbackTest(TestCase):
    """Callback FF Pay/LPAY/MGM: verifikasi signature + kredit saldo."""

    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create(
            username="ffpayuser",
            phone="08123450111",
            email="ffpayuser@example.com",
            full_name="FFPay User",
            balance=0,
        )
        self.gs = GatewaySettings.objects.create(
            default_wallet_type="BALANCE",
            ffpay_enabled=True,
            ffpay_api_key="ak_test",
            ffpay_secret_key=SECRET,
        )

    def _create_pending(self, order_num, gateway, amount=Decimal("50000")):
        trx = Transaction.objects.create(
            user=self.user,
            type="DEPOSIT",
            amount=amount,
            currency_code="IDR",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id=order_num,
        )
        dep = Deposit.objects.create(
            user=self.user,
            gateway=gateway,
            order_num=order_num,
            amount=amount,
            amount_currency_code="IDR",
            wallet_type="BALANCE",
            status="PENDING",
            transaction=trx,
        )
        return trx, dep

    def test_callback_completes_deposit_all_gateways(self):
        cases = [
            ("DFF260915TEST0001", "FFPAY", "/api/deposits/ffpay/callback/"),
            ("DLP260915TEST0002", "LPAY", "/api/deposits/lpay/callback/"),
            ("DMG260915TEST0003", "MGM", "/api/deposits/mgm/callback/"),
        ]
        for order_num, gateway, path in cases:
            trx, dep = self._create_pending(order_num, gateway)
            body = _callback_body(order_num)
            resp = self.client.post(
                path, data=body, content_type="application/json",
                **_signed_headers(path, body),
            )
            self.assertEqual(resp.status_code, 200, gateway)
            trx.refresh_from_db()
            dep.refresh_from_db()
            self.assertEqual(trx.status, "COMPLETED", gateway)
            self.assertEqual(dep.status, "COMPLETED", gateway)
            self.assertEqual(dep.credited_amount, Decimal("50000"), gateway)
            self.assertIsNotNone(dep.callback_at, gateway)

        self.user.refresh_from_db()
        self.assertEqual(self.user.balance, Decimal("150000"))

    def test_callback_invalid_signature_ignored(self):
        trx, dep = self._create_pending("DFF260915TEST0004", "FFPAY")
        body = _callback_body("DFF260915TEST0004")
        resp = self.client.post(
            "/api/deposits/ffpay/callback/", data=body, content_type="application/json",
            **_signed_headers("/api/deposits/ffpay/callback/", body, secret="wrong-secret"),
        )
        self.assertEqual(resp.status_code, 200)
        trx.refresh_from_db()
        dep.refresh_from_db()
        self.assertEqual(trx.status, "PENDING")
        self.assertEqual(dep.status, "PENDING")
        self.assertFalse(dep.callback_payload["_sign_valid"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.balance, 0)

    def test_callback_amount_mismatch_fails(self):
        trx, dep = self._create_pending("DFF260915TEST0005", "FFPAY")
        body = _callback_body("DFF260915TEST0005", amount=1000)
        resp = self.client.post(
            "/api/deposits/ffpay/callback/", data=body, content_type="application/json",
            **_signed_headers("/api/deposits/ffpay/callback/", body),
        )
        self.assertEqual(resp.status_code, 200)
        trx.refresh_from_db()
        dep.refresh_from_db()
        self.assertEqual(trx.status, "FAILED")
        self.assertEqual(dep.status, "FAILED")
        self.user.refresh_from_db()
        self.assertEqual(self.user.balance, 0)

    def test_disbursement_on_collections_url_updates_withdrawal(self):
        # Provider: satu Webhook URL untuk semua kanal; Payout Webhook URL boleh
        # dikosongkan → event disbursement.* masuk ke URL collections (ffpay/callback)
        # dan harus dirutekan ke handler withdrawal.
        payout_secret = "test-ffpay-payout-secret"
        WithdrawalSettings.objects.create(
            is_active=True,
            ffpay_payout_enabled=True,
            ffpay_payout_secret_key=payout_secret,
        )
        bank = Bank.objects.create(
            code="BCA",
            name="BCA",
            min_withdrawal=Decimal("0"),
            max_withdrawal=Decimal("0"),
            withdrawal_fee=Decimal("0"),
            withdrawal_fee_fixed=Decimal("0"),
        )
        user_bank = UserBank.objects.create(
            user=self.user,
            bank=bank,
            account_name="FFPay User",
            account_number="1234567890",
            is_default=True,
        )
        wd_trx = Transaction.objects.create(
            user=self.user,
            type="WITHDRAW",
            amount=Decimal("50000"),
            currency_code="IDR",
            status="PENDING",
            wallet_type="BALANCE",
            trx_id="DWD260917TEST0001",
        )
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            bank_account=user_bank,
            amount=Decimal("50000"),
            fee=Decimal("0"),
            net_amount=Decimal("50000"),
            status="PENDING",
            transaction=wd_trx,
        )

        path = "/api/deposits/ffpay/callback/"
        body = json.dumps(
            {
                "event": "disbursement",
                "timestamp": "1760000000000",
                "data": {
                    "event": "disbursement.success",
                    "ref_id": "TXN260917PAYOUT01",
                    "merchant_ref": wd_trx.trx_id,
                    "amount": 50000,
                    "wallet_type": "mgm",
                    "provider": "mgm",
                },
            },
            separators=(",", ":"),
        )
        resp = self.client.post(
            path, data=body, content_type="application/json",
            **_signed_headers(path, body, secret=payout_secret),
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content.decode().strip(), "OK")
        withdrawal.refresh_from_db()
        wd_trx.refresh_from_db()
        self.assertEqual(withdrawal.status, "COMPLETED")


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class FfpayInitiateTest(TestCase):
    """Initiate: validasi flag aktif + payload khusus tiap provider."""

    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create(
            username="ffpayinit",
            phone="08123450112",
            email="ffpayinit@example.com",
            full_name="FFPay Init",
            balance=0,
        )
        self.client.force_authenticate(user=self.user)
        self.gs = GatewaySettings.objects.create(
            default_wallet_type="BALANCE",
            ffpay_enabled=True,
            lpay_enabled=True,
            mgm_enabled=True,
            ffpay_api_url="https://api.ffpay.test",
            ffpay_api_key="ak_test",
            ffpay_secret_key=SECRET,
        )

    def test_initiate_disabled_gateway(self):
        self.gs.lpay_enabled = False
        self.gs.save()
        resp = self.client.post("/api/deposits/lpay/initiate/", {"amount": 50000}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_initiate_builds_provider_payload(self):
        fake = {"success": True, "data": {"ref_id": "TXN1", "pay_url": "https://pay.test/1", "expires_at": None}}
        cases = [
            ("/api/deposits/vega/initiate/", "FFPAY", "/gateway/charge/create", "method", ""),
            ("/api/deposits/lpay/initiate/", "LPAY", "/gateway/lpay/payin", "code", "3560"),
            ("/api/deposits/lyra/initiate/", "MGM", "/gateway/mgm/qris", "method", "QRCODE"),
        ]
        for url, gateway, api_path, key, expected in cases:
            with patch("deposits.views.ffpay_post_json", return_value=(fake, 200)) as mocked:
                resp = self.client.post(url, {"amount": 50000}, format="json")
            self.assertEqual(resp.status_code, 200, gateway)
            self.assertEqual(resp.data["pay_url"], "https://pay.test/1", gateway)
            self.assertEqual(mocked.call_args.args[2], api_path, gateway)
            dep = Deposit.objects.get(order_num=resp.data["order_num"])
            self.assertEqual(dep.gateway, gateway)
            self.assertEqual(dep.request_params[key], expected, gateway)
            self.assertEqual(dep.payment_url, "https://pay.test/1")

    def test_mgm_wallet_uses_payin_path(self):
        self.gs.mgm_method = "WALLET"
        self.gs.save()
        fake = {"success": True, "data": {"ref_id": "TXN2", "pay_url": "https://pay.test/2"}}
        with patch("deposits.views.ffpay_post_json", return_value=(fake, 200)) as mocked, patch(
            "deposits.views._scrape_mgm_payment_page"
        ) as scrape_mock:
            resp = self.client.post("/api/deposits/lyra/initiate/", {"amount": 50000}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mocked.call_args.args[2], "/gateway/mgm/payin")
        self.assertEqual(mocked.call_args.args[3]["method"], "WALLET")
        scrape_mock.assert_not_called()  # WALLET bukan QRIS

    def test_mgm_qris_returns_qr_url(self):
        fake = {
            "success": True,
            "data": {
                "ref_id": "TXN3",
                "pay_url": "https://cashier.mgm.test/x",
                "pay_data": "https://platform.test/pay/qr-img/TXN3/abc",
                "pay_data_type": "QR_URL",
                "qr_url": "https://provider.test/qris/abc",
                "extracted": True,
            },
        }
        with patch("deposits.views.ffpay_post_json", return_value=(fake, 200)) as mocked, patch(
            "deposits.views._scrape_mgm_payment_page"
        ) as scrape_mock:
            resp = self.client.post("/api/deposits/lyra/initiate/", {"amount": 50000}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mocked.call_args.args[2], "/gateway/mgm/qris")
        self.assertEqual(resp.data["pay_data"], "https://platform.test/pay/qr-img/TXN3/abc")
        self.assertEqual(resp.data["pay_data_type"], "QR_URL")
        self.assertEqual(resp.data["qr_url"], "https://provider.test/qris/abc")
        self.assertEqual(resp.data["pay_url"], "https://cashier.mgm.test/x")
        # pay_data sudah diisi platform — tidak perlu scrape
        scrape_mock.assert_not_called()
        self.assertEqual(resp.data["qr_image"], "")

    def test_mgm_qris_scrapes_cashier_when_pay_data_missing(self):
        # kasus nyata di produksi: extraction platform gagal → pay_data null, pay_data_type PG_URL
        fake = {
            "success": True,
            "data": {
                "ref_id": "TXN4",
                "pay_url": "https://paycash.mgm.test/cashier/payment/PIDN1",
                "pay_data": None,
                "pay_data_type": "PG_URL",
            },
        }
        with patch("deposits.views.ffpay_post_json", return_value=(fake, 200)), patch(
            "deposits.views._scrape_mgm_payment_page",
            return_value={"qr_image": "data:image/png;base64,QUJD"},
        ) as scrape_mock:
            resp = self.client.post("/api/deposits/lyra/initiate/", {"amount": 50000}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data["pay_data"])
        self.assertEqual(resp.data["qr_image"], "data:image/png;base64,QUJD")
        self.assertEqual(scrape_mock.call_args.args[0], "https://paycash.mgm.test/cashier/payment/PIDN1")

    def test_lpay_scrapes_session_api_when_pay_data_missing(self):
        # kasus nyata di produksi: LPAY pay_data selalu null (pay_data_type PG_URL)
        fake = {
            "success": True,
            "data": {
                "ref_id": "TXN5",
                "pay_url": "https://payment.xuqelo.test/pay?sessionId=abc-123",
                "pay_data": None,
                "pay_data_type": "PG_URL",
            },
        }
        with patch("deposits.views.ffpay_post_json", return_value=(fake, 200)), patch(
            "deposits.views._scrape_lpay_payment_page",
            return_value={"qr_string": "00020101021226670016COM.NOBUBANK", "qr_image": "data:image/png;base64,QUJD"},
        ) as scrape_mock:
            resp = self.client.post("/api/deposits/lpay/initiate/", {"amount": 50000}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data["pay_data"])
        self.assertEqual(resp.data["qr_string"], "00020101021226670016COM.NOBUBANK")
        self.assertEqual(resp.data["qr_image"], "data:image/png;base64,QUJD")
        self.assertEqual(scrape_mock.call_args.args[0], "https://payment.xuqelo.test/pay?sessionId=abc-123")

    def test_ffpay_does_not_scrape(self):
        # FFPAY bukan QRIS — pay_data null tidak memicu scrape
        fake = {"success": True, "data": {"ref_id": "TXN6", "pay_url": "https://pay.ffpay.test/x", "pay_data": None}}
        with patch("deposits.views.ffpay_post_json", return_value=(fake, 200)), patch(
            "deposits.views._scrape_lpay_payment_page"
        ) as scrape_mock:
            resp = self.client.post("/api/deposits/vega/initiate/", {"amount": 50000}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data["qr_string"])
        scrape_mock.assert_not_called()


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class MgmCashierScrapeTest(TestCase):
    """Scrape QRIS halaman cashier MGM: pilih gambar QR (bukan logo) lalu encode data URI."""

    def _fake_page(self, html):
        page = MagicMock()
        page.url = "https://cashier.heypay.org/index.php/cash/detail?token=T1"
        page.text = html
        return page

    def test_picks_qr_image_and_skips_logos(self):
        html = (
            '<img src="https://cashout.heypay.org/logo/QS/QRIS.png">'
            '<img src="https://bad.test/logo/black.png">'
            '<img src="https://qr.cdn.test/qris/v2/abc123">'
        )
        img = MagicMock()
        img.headers = {"Content-Type": "image/png"}
        img.content = b"\x89PNG\r\n\x1a\nfake-qr"
        with patch("deposits.views.requests.Session") as session_mock:
            session_mock.return_value.get.side_effect = [self._fake_page(html), img]
            out = _scrape_mgm_payment_page("https://paycash.mgm.test/cashier/payment/PIDN1")
        expected = "data:image/png;base64," + base64.b64encode(img.content).decode()
        self.assertEqual(out["qr_image"], expected)
        # yang diunduh harus kandidat QR, bukan logo (walau logo mengandung 'qris')
        self.assertEqual(
            session_mock.return_value.get.call_args_list[1].args[0],
            "https://qr.cdn.test/qris/v2/abc123",
        )

    def test_returns_empty_when_no_qr_candidate(self):
        html = '<img src="https://cashout.heypay.org/logo/QS/QRIS.png">'
        with patch("deposits.views.requests.Session") as session_mock:
            session_mock.return_value.get.return_value = self._fake_page(html)
            out = _scrape_mgm_payment_page("https://paycash.mgm.test/cashier/payment/PIDN1")
        self.assertEqual(out["qr_image"], "")


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class LpayCashierScrapeTest(TestCase):
    """Scrape QRIS cashier LPAY: sessionId dari pay_url → API session → qr_string + qr_image."""

    def _fake_resp(self, payload):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = payload
        return resp

    def test_fetches_session_api_and_builds_qr(self):
        payload = {"qrPayload": "00020101021226670016COM.NOBUBANK.WWW6304ABCD", "mode": "qris", "amount": 100000.0}
        with patch("deposits.views.requests.get", return_value=self._fake_resp(payload)) as get_mock:
            out = _scrape_lpay_payment_page("https://payment.xuqelo.test/pay?sessionId=a5efcbce-1111-2222")
        self.assertEqual(out["qr_string"], payload["qrPayload"])
        self.assertTrue(out["qr_image"].startswith("data:image/png;base64,"))
        self.assertEqual(
            get_mock.call_args.args[0],
            "https://payment.xuqelo.test/api/checkout/sessions/a5efcbce-1111-2222",
        )

    def test_returns_empty_without_session_id(self):
        out = _scrape_lpay_payment_page("https://payment.xuqelo.test/pay")
        self.assertEqual(out, {"qr_string": "", "qr_image": ""})

    def test_returns_empty_on_bad_payload(self):
        url = "https://payment.xuqelo.test/pay?sessionId=a5efcbce-1111-2222"
        with patch("deposits.views.requests.get", return_value=self._fake_resp(["not-a-dict"])):
            out = _scrape_lpay_payment_page(url)
        self.assertEqual(out, {"qr_string": "", "qr_image": ""})
        with patch("deposits.views.requests.get", return_value=self._fake_resp({"qrPayload": ""})):
            out = _scrape_lpay_payment_page(url)
        self.assertEqual(out, {"qr_string": "", "qr_image": ""})
