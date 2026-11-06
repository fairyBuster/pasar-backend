from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from deposits.models import GatewaySettings


@override_settings(BYPASS_DOMAIN_IP_SECURITY=True)
class DepositMethodsViewTest(TestCase):
    """GET /api/deposits/methods/ — status aktif tiap metode deposit untuk frontend."""

    def setUp(self):
        self.client = APIClient()
        GatewaySettings.objects.create(
            jayapay_enabled=True,
            atpay_enabled=True,
            qris_enabled=True,
            bankpay_enabled=False,
            ffpay_enabled=False,
        )

    def test_lists_all_methods_with_enabled_flag(self):
        resp = self.client.get("/api/deposits/methods/")
        self.assertEqual(resp.status_code, 200)
        data = {m["code"]: m for m in resp.data}
        self.assertEqual(len(data), 16)
        self.assertTrue(data["nova"]["enabled"])
        self.assertTrue(data["jayapay"]["enabled"])
        self.assertTrue(data["qris"]["enabled"])
        self.assertFalse(data["orion"]["enabled"])
        self.assertFalse(data["vega"]["enabled"])
        self.assertEqual(data["vega"]["initiate_path"], "/api/deposits/vega/initiate/")
        self.assertEqual(data["orion"]["initiate_path"], "/api/deposits/orion/initiate/")

    def test_enabled_filter_returns_only_active_methods(self):
        resp = self.client.get("/api/deposits/methods/?enabled=true")
        self.assertEqual(resp.status_code, 200)
        codes = {m["code"] for m in resp.data}
        self.assertEqual(codes, {"jayapay", "nova", "qris"})

    def test_all_disabled_when_no_settings_row(self):
        GatewaySettings.objects.all().delete()
        resp = self.client.get("/api/deposits/methods/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 16)
        self.assertFalse(any(m["enabled"] for m in resp.data))
