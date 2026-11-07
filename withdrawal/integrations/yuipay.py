"""Pemetaan kode bank aplikasi ke kode tujuan payout Yuipay (IDR).

Yuipay memakai kode bank numerik klasik Indonesia (014 = BCA, 002 = BRI) dan
kode 10001-10009 untuk e-wallet — sama dengan kode `Bank.code` di aplikasi ini.
Payout hanya mendukung 14 tujuan di bawah; kode lain ditolak sebelum request.

Sumber: daftar bank/e-wallet pada dokumentasi Yuipay (api.montfara.vip).
"""
from urllib.parse import quote

from deposits.integrations.yuipay import DEFAULT_API_URL, get_json

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
    code = (app_code or "").strip()
    return code if code in YUIPAY_BANK_CODES else ""


def yuipay_withdraw_status(api_key: str, merchant_code: str, secret: str, ref_id: str,
                           base_url: str = DEFAULT_API_URL, timeout: int = 20):
    """Ambil status withdraw terbaru: GET /merchant/withdraw/{ref_id}."""
    return get_json(api_key, merchant_code, secret,
                    f"/merchant/withdraw/{quote(str(ref_id), safe='')}",
                    base_url=base_url, timeout=timeout)
