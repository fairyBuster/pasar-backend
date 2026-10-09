import base64
import hashlib
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from deposits.models import GatewaySettings, Deposit
from deposits.views import _bankpay_fetch_va_detail, _scrape_bankpay_payment_page

VA_PAGE_URL = "https://svpw.test/cash/html/BRI.html?type=BRI&orderNum=PRE72100243422387507200"
VA_PAYLOAD = {
    "code": 0,
    "msg": "Success",
    "data": {
        "vaNumber": "479401000081562",
        "methodStr": "BRI Virtual Account",
        "name": "IRWATI YUNITA",
        "payMoney": "50,861",
    },
}
VA_DETAIL = {
    "va_number": "479401000081562",
    "va_name": "IRWATI YUNITA",
    "va_bank": "BRI Virtual Account",
    "display_amount": "50,861",
}


def _xor_page(inner_url, key="1234567890abcdef"):
    raw = bytes(ord(inner_url[i]) ^ ord(key[i % len(key)]) for i in range(len(inner_url)))
    return (
        "<script>var encryptedPayUrl = '%s'; var payUrlKey = '%s';</script>"
        % (base64.b64encode(raw).decode(), key)
    )


def _fake_page(text, url="https://recall.bkpay.top/pay"):
    page = MagicMock()
    page.url = url
    page.text = text
    page.headers = {"Content-Type": "text/html"}
    return page


class BankPayVaDetailTest(TestCase):
    """_bankpay_fetch_va_detail: replikasi signing ts/ss dari bankdetail.js."""

    def test_posts_signed_request_and_parses_va(self):
        resp = MagicMock()
        resp.json.return_value = VA_PAYLOAD
        with patch("deposits.views.requests.post", return_value=resp) as mocked:
            detail = _bankpay_fetch_va_detail(VA_PAGE_URL)
        self.assertEqual(detail, VA_DETAIL)
        self.assertEqual(mocked.call_args.args[0], "https://svpw.test/gateway/order/detail/v2")
        self.assertEqual(
            json.loads(mocked.call_args.kwargs["data"].decode()),
            {"method": "BRI", "orderNum": "PRE72100243422387507200"},
        )
        headers = mocked.call_args.kwargs["headers"]
        expected_ss = hashlib.md5(
            "&".join(
                sorted(
                    [
                        "method=BRI",
                        "orderNum=PRE72100243422387507200",
                        f"ts={headers['ts']}",
                    ]
                )
            ).encode()
        ).hexdigest()
        self.assertEqual(headers["ss"], expected_ss)

    def test_returns_empty_on_rejected_code(self):
        resp = MagicMock()
        resp.json.return_value = {"code": 401, "msg": "Invalid sign"}
        with patch("deposits.views.requests.post", return_value=resp):
            self.assertEqual(_bankpay_fetch_va_detail(VA_PAGE_URL), {})

    def test_returns_empty_without_order_params(self):
        with patch("deposits.views.requests.post") as mocked:
            self.assertEqual(_bankpay_fetch_va_detail("https://svpw.test/cash/html/BRI.html"), {})
        mocked.assert_not_called()


class BankPayScrapeVaBranchTest(TestCase):
    """Scraper: halaman VA (bankdetail.js) → delegasi ke _bankpay_fetch_va_detail."""

    def test_va_branch_uses_decrypted_url(self):
        inner = '<script src="./../js/bankdetail.js"></script>'
        with patch("deposits.views.requests.Session") as session_mock, patch(
            "deposits.views._bankpay_fetch_va_detail", return_value=dict(VA_DETAIL)
        ) as va_mock:
            session_mock.return_value.get.side_effect = [
                _fake_page(_xor_page(VA_PAGE_URL)),
                _fake_page(inner, url=VA_PAGE_URL),
            ]
            out = _scrape_bankpay_payment_page("https://recall.bkpay.top/Pay-pay-bankpay.aspx?token=x")
        self.assertEqual(va_mock.call_args.args[0], VA_PAGE_URL)
        self.assertEqual(out["va_number"], "479401000081562")
        self.assertEqual(out["display_amount"], "50,861")


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class BankPayInitiateVaTest(TestCase):
    """Initiate BankPay: response menyertakan VA hasil scrape pay_url."""

    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create(
            username="bankpayva",
            phone="08123450113",
            email="bankpayva@example.com",
            full_name="BankPay VA",
            balance=0,
        )
        self.client.force_authenticate(user=self.user)
        self.gs = GatewaySettings.objects.create(
            default_wallet_type="BALANCE_DEPOSIT",
            bankpay_enabled=True,
            bankpay_api_url="https://pay.bankpay.test",
            bankpay_member_id="M1001",
            bankpay_key="test-bankpay-key",
            app_domain="richnetworkers.test",
        )
        self.pay_url = "https://recall.bkpay.top/Pay-pay-bankpay.aspx?token=x"

    def _post(self, path, scraped):
        fake = {"returncode": "200", "payurl": self.pay_url}
        with patch("deposits.views.bankpay_post_form", return_value=fake), patch(
            "deposits.views._scrape_bankpay_payment_page", return_value=scraped
        ) as scrape_mock:
            resp = self.client.post(
                path,
                {"amount": 50000, "wallet_type": "BALANCE_DEPOSIT", "bankcode": "bank"},
                format="json",
            )
        return resp, scrape_mock

    def test_initiate_returns_va_fields(self):
        resp, scrape_mock = self._post("/api/deposits/orion/initiate/", dict(VA_DETAIL))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["va_number"], "479401000081562")
        self.assertEqual(resp.data["va_bank"], "BRI Virtual Account")
        self.assertEqual(resp.data["va_name"], "IRWATI YUNITA")
        self.assertEqual(resp.data["display_amount"], "50,861")
        self.assertEqual(scrape_mock.call_args.args[0], self.pay_url)
        dep = Deposit.objects.get(order_num=resp.data["order_num"])
        self.assertEqual(dep.gateway, "BANKPAY")
        self.assertEqual(dep.payment_url, self.pay_url)

    def test_initiate_qr_returns_qr_image_without_va(self):
        scraped = {
            "qr_image": "data:image/png;base64,QUJD",
            "display_amount": "50861",
            "va_number": "",
            "va_bank": "",
            "va_name": "",
        }
        resp, _ = self._post("/api/deposits/orion/initiate-qr/", scraped)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["qr_image"], "data:image/png;base64,QUJD")
        self.assertEqual(resp.data["display_amount"], "50861")
        self.assertEqual(resp.data["va_number"], "")
