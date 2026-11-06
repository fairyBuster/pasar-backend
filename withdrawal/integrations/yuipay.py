"""Pemetaan kode bank aplikasi ke kode tujuan payout Yuipay (IDR).

Yuipay memakai kode bank numerik klasik Indonesia (014 = BCA, 002 = BRI) dan
kode 10001-10009 untuk e-wallet — sama dengan kode `Bank.code` di aplikasi ini.
Payout hanya mendukung 14 tujuan di bawah; kode lain ditolak sebelum request.

Sumber: daftar bank/e-wallet pada dokumentasi Yuipay (api.montfara.vip).
"""

# kode tujuan payout yang didukung Yuipay
YUIPAY_BANK_CODES = {
    "014": "BCA",
    "009": "BNI",
    "002": "BRI",
    "008": "Mandiri",
    "022": "CIMB Niaga",
    "013": "Permata",
    "011": "Danamon",
    "4510": "BSI",
    "200": "BTN",
    "10003": "GoPay",
    "10002": "DANA",
    "10001": "OVO",
    "10008": "ShopeePay",
    "10009": "LinkAja",
}


def yuipay_bank_code(app_code: str) -> str:
    """Kembalikan kode payout Yuipay, atau '' bila bank tidak didukung."""
    return YUIPAY_BANK_CODES.get((app_code or "").strip(), "")
