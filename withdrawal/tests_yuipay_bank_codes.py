from django.test import SimpleTestCase

from .integrations.yuipay import YUIPAY_BANK_CODES, yuipay_bank_code


class YuipayBankCodeTests(SimpleTestCase):
    def test_code_dikirim_sebagai_kode_numerik(self):
        # Yuipay menerima kode numerik (10002), bukan nama (DANA).
        for code in YUIPAY_BANK_CODES:
            self.assertEqual(yuipay_bank_code(code), code)

    def test_kode_tidak_dikenal_ditolak(self):
        self.assertEqual(yuipay_bank_code("999"), "")
        self.assertEqual(yuipay_bank_code(""), "")
