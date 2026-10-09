from django.test import SimpleTestCase

from deposits.integrations.bankpay import (
    BANKPAY_BANK_LIST,
    build_payout_order_id,
    build_payout_payload,
    generate_sign,
    resolve_bankpay_bank,
)


class ResolveBankPayBankTest(SimpleTestCase):
    """resolve_bankpay_bank: kode aplikasi (Bank.code) -> kode bank resmi BankPay."""

    def test_bank_list_is_complete_and_unique(self):
        codes = [code for code, _ in BANKPAY_BANK_LIST]
        self.assertEqual(len(codes), 139)
        self.assertEqual(len(set(codes)), 139)

    def test_app_codes_are_converted_to_official_codes(self):
        self.assertEqual(resolve_bankpay_bank("014", "BCA"), ("126", "Bank BCA"))
        self.assertEqual(resolve_bankpay_bank("002", "BRI"), ("132", "Bank BRI"))
        self.assertEqual(resolve_bankpay_bank("10002", "DANA"), ("2", "DANA电子钱包"))
        self.assertEqual(resolve_bankpay_bank("213", "Bank BTPN"), ("BTPN", "Bank BTPN"))

    def test_colliding_code_uses_bank_name_as_disambiguator(self):
        # "132" = Bank Papua di aplikasi, tapi = Bank BRI di tabel BankPay.
        self.assertEqual(resolve_bankpay_bank("132", "Bank Papua"), ("67", "Bank Papua"))
        self.assertEqual(resolve_bankpay_bank("132", "Bank BRI"), ("132", "Bank BRI"))

    def test_official_codes_pass_through(self):
        self.assertEqual(resolve_bankpay_bank("126", ""), ("126", "Bank BCA"))
        self.assertEqual(resolve_bankpay_bank("2", "DANA电子钱包"), ("2", "DANA电子钱包"))

    def test_unknown_code_passes_through_unchanged(self):
        self.assertEqual(resolve_bankpay_bank("777", "Weird Bank"), ("777", "Weird Bank"))

    def test_payout_amount_is_rounded_to_whole_rupiah(self):
        # BankPay menolak nominal berdesimal: "orderAmount this value is not supported 49777.25".
        base = dict(member_id="13310", order_id="WD-TEST000000000001", bankcode="bank")
        self.assertEqual(build_payout_payload(amount="49777.25", **base)["amount"], "49777.00")
        self.assertEqual(build_payout_payload(amount="49777.75", **base)["amount"], "49778.00")
        self.assertEqual(build_payout_payload(amount="500000", **base)["amount"], "500000.00")

    def test_retry_payout_order_id_is_new_and_within_limit(self):
        # BankPay menyimpan orderid gagal selamanya ("Order id already exists").
        base = "WD-6C96E01F08"
        self.assertEqual(build_payout_order_id(base), base)
        retry = build_payout_order_id(base, is_retry=True)
        self.assertTrue(retry.startswith(base + "-"))
        self.assertLessEqual(len(retry), 32)
        self.assertLessEqual(len(build_payout_order_id("A" * 32, is_retry=True)), 32)

    def test_number_id_field_excluded_from_sign(self):
        # Guide BankPay section 2: "numberId" tidak ikut signature.
        base = dict(memberid="13310", orderid="WD-TEST000000000001", amount="50000.00")
        self.assertEqual(
            generate_sign({**base, "numberId": "12345678901"}, "secret"),
            generate_sign(base, "secret"),
        )
