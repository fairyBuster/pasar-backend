"""Pemetaan kode bank aplikasi ke kode payout FF Pay / LPAY / MGM.

Kode bank aplikasi (Bank.code) memakai kode numerik klasik Indonesia (014 = BCA,
002 = BRI) dan kode 10001/10002/10003/10008/10009 untuk e-wallet.

- FF Pay (wallet main) : kode numerik klasik dipakai apa adanya; e-wallet pakai
  kata huruf kecil (dana/ovo/gopay/linkaja/shopeepay).
- LPAY                 : word code resmi v1.1 (2025-11) — BCA, MANDIRI, DANA, ...
- MGM                  : kode numerik 5 digit table 7.15 — 10014 = BCA, 10951 = DANA.

Sumber: GET /gateway/payout/banks?wallet=lpay|mgm pada dokumentasi FF Pay.
Bank yang tidak ada di tabel LPAY/MGM akan ditolak (kode kosong).
"""

# E-wallet: kode aplikasi -> kata huruf kecil untuk /gateway/payout/create (FF Pay main)
FFPAY_EWALLET_CODES = {
    "10001": "ovo",
    "10002": "dana",
    "10003": "gopay",
    "10008": "shopeepay",
    "10009": "linkaja",
}

# Word code resmi LPAY v1.1 — dipakai /gateway/lpay/payout
LPAY_BANK_CODES = {
    "002": "BRI",
    "008": "MANDIRI",
    "009": "BNI",
    "011": "DANAMON",
    "013": "PERMATA",
    "014": "BCA",
    "016": "MAYBANK",
    "019": "PANIN",
    "022": "CIMB",
    "028": "OCBC",
    "050": "STANDARDCHARTERED",
    "110": "BJB",
    "111": "DKI",
    "114": "JATIM",
    "116": "ACEH",
    "147": "MUAMALAT",
    "153": "SINARMAS",
    "200": "BTN",
    "213": "BTPN",
    "426": "MEGA",
    "490": "NEO_COMMERCE",
    "503": "NOBU",
    "535": "SEABANK",
    "542": "JAGO",
    "950": "COMMONWEALTH",
    "10001": "OVO",
    "10002": "DANA",
    "10003": "GOPAY",
    "10008": "SHOPEEPAY",
    "10009": "LINKAJA",
}

# Kode numerik MGM table 7.15 — dipakai /gateway/mgm/payout
MGM_BANK_CODES = {
    "002": "10002",   # BRI
    "008": "10008",   # Mandiri
    "009": "10009",   # BNI
    "011": "10011",   # Danamon
    "013": "10013",   # Permata
    "014": "10014",   # BCA
    "016": "10016",   # Maybank
    "019": "10019",   # Panin
    "022": "10022",   # CIMB Niaga
    "028": "10028",   # OCBC NISP
    "037": "10037",   # Artha Graha
    "041": "10041",   # HSBC
    "046": "10046",   # DBS
    "050": "10050",   # Standard Chartered
    "097": "10097",   # Mayapada
    "110": "10110",   # BJB
    "113": "10113",   # Bank Jateng
    "114": "10114",   # Bank Jatim
    "116": "10116",   # Bank Aceh
    "147": "10147",   # Muamalat
    "153": "10153",   # Sinarmas
    "213": "10213",   # BTPN
    "426": "10426",   # Bank Mega
    "441": "10441",   # Bukopin/Wokee
    "4510": "10451",  # Bank Syariah Indonesia (BSI)
    "484": "10484",   # Hana Bank
    "490": "10490",   # Neo Commerce
    "535": "10535",   # Seabank
    "542": "10542",   # Jago
    "949": "10949",   # CTBC
    "950": "10950",   # Commonwealth
    "10001": "10954",  # OVO
    "10002": "10951",  # DANA
    "10003": "10952",  # GOPAY
    "10008": "10955",  # SHOPEEPAY
    "10009": "10953",  # LINKAJA
}


# Bank populer untuk picker admin "Process via FF Pay / LPAY / MGM" (kode aplikasi, nama tampilan).
FFPAY_POPULAR_BANKS = [
    ("014", "BCA"),
    ("002", "BRI"),
    ("008", "Mandiri"),
    ("009", "BNI"),
    ("4510", "BSI"),
    ("022", "CIMB Niaga"),
    ("011", "Danamon"),
    ("013", "Permata"),
    ("200", "BTN"),
    ("535", "Seabank"),
    ("542", "Jago"),
    ("490", "Neo Commerce"),
    ("10002", "DANA"),
    ("10001", "OVO"),
    ("10003", "GoPay"),
    ("10008", "ShopeePay"),
    ("10009", "LinkAja"),
]


def ffpay_payout_bank_code(app_code: str, wallet: str) -> str:
    """Konversi Bank.code aplikasi ke kode payout wallet. Return '' jika tidak didukung."""
    code = (app_code or "").strip()
    if not code:
        return ""
    if wallet == "lpay":
        return LPAY_BANK_CODES.get(code, "")
    if wallet == "mgm":
        return MGM_BANK_CODES.get(code, "")
    # FF Pay main: e-wallet pakai kata huruf kecil, bank numerik klasik apa adanya
    return FFPAY_EWALLET_CODES.get(code, code)
