"""Integrasi BankPay untuk deposit IDR.

Base URL: https://pay.bankpay.cfd
Sign: MD5 uppercase, sorted keys, append &key=
Topup: POST /Pay-payment.aspx (x-www-form-urlencoded)
Callback: POST, return plain OK
"""
import hashlib
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlencode
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


def _now_wib():
    return datetime.now(ZoneInfo("Asia/Jakarta"))


def generate_sign(params: dict, key: str) -> str:
    filtered = []
    for k, v in (params or {}).items():
        # "numberId" tidak ikut signature (guide BankPay section 2).
        if k in ("sign", "pay_md5sign", "return_type", "numberId"):
            continue
        if v is None or v == "":
            continue
        filtered.append((str(k), str(v)))
    filtered.sort(key=lambda item: item[0])
    # BankPay verifies sign from raw (decoded) values, NOT URL-encoded
    raw = "&".join(f"{k}={v}" for k, v in filtered) + f"&key={key}"
    import logging
    _log = logging.getLogger("deposits.bankpay")
    _log.warning("BANKPAY sign raw: %s", raw)
    return hashlib.md5(raw.encode()).hexdigest().upper()


def verify_sign(params: dict, key: str) -> bool:
    params_copy = dict(params or {})
    received_sign = str(params_copy.pop("sign", "")).strip().upper()
    if not received_sign or not key:
        return False
    return generate_sign(params_copy, key).upper() == received_sign


def post_form(url: str, payload: dict, timeout: int = 30) -> dict:
    response = requests.post(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        timeout=timeout,
    )
    try:
        return response.json()
    except Exception:
        return {"returncode": str(response.status_code), "msg": response.text}


def format_apply_date(dt=None) -> str:
    """Format: 2026-08-03 14:30:00 (UTC+8)"""
    if dt is None:
        dt = _now_wib()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def build_payout_order_id(base_order_id: str, is_retry: bool = False) -> str:
    """Orderid payout BankPay (<=32 karakter).

    BankPay menyimpan orderid permanen termasuk percobaan yang gagal
    ("Order id already exists"), jadi percobaan ulang memakai orderid baru.
    """
    base = (base_order_id or "").strip()
    if not is_retry:
        return base
    return f"{base[:18]}-{int(time.time() * 1000)}"


def build_payout_payload(
    *,
    member_id: str,
    order_id: str,
    amount: str,
    bankcode: str = "bank",
    notify_url: str = "",
    mobile: str = "",
    email: str = "",
    bank_name: str = "",
    card_number: str = "",
    account_name: str = "",
    bank_no: str = "",
    vpa: str = "",
):
    # order_id must be 16-32 characters per BankPay spec
    order_id = (order_id or "").strip()[:32]
    if len(order_id) < 16:
        order_id = order_id.ljust(16, "0")  # pad with zeros to meet minimum length
    # BankPay hanya mendukung nominal rupiah bulat ("orderAmount this value is not supported").
    try:
        amount = f"{Decimal(str(amount)).quantize(Decimal('1'), rounding=ROUND_HALF_UP):.2f}"
    except (InvalidOperation, ValueError, TypeError):
        pass
    payload = {
        "memberid": member_id,
        "orderid": order_id,
        "bankcode": bankcode,
        "notifyurl": notify_url,
        "amount": amount,
        "mobile": mobile,
        "email": email,
        "pay_currency": "IDR",
    }
    if bank_name and card_number and account_name:
        payload["bankname"] = bank_name
        payload["cardnumber"] = card_number
        payload["accountname"] = account_name
        if bank_no:
            payload["bankno"] = bank_no
    elif account_name and vpa:
        payload["accountname"] = account_name
        payload["vpa"] = vpa
    return payload


def map_payout_returncode(returncode: str) -> str | None:
    code = str(returncode or "").strip()
    if code == "00":
        return "COMPLETED"
    if code in ("01", "02", "99"):
        return "REJECTED"
    return None


# Daftar bank resmi BankPay (hasil API getBankList). Format: (kode resmi, nama resmi).
# Nama harus persis seperti ini karena dikirim sebagai bankname saat payout.
BANKPAY_BANK_LIST = [
    ("1", "OVO电子钱包"),
    ("2", "DANA电子钱包"),
    ("3", "GOPAY电子钱包"),
    ("4", "SHOPEEPAY电子钱包"),
    ("5", "LINKAJA钱包"),
    ("6", "Bank CTBC (China Trust) Indonesia"),
    ("7", "Bank Maybank Indocorp"),
    ("8", "Bank Merincorp"),
    ("9", "Bank Agris"),
    ("10", "Indosat Dompetku"),
    ("11", "BPR KS"),
    ("12", "Bank Harda"),
    ("13", "Bank Victoria International"),
    ("14", "Bank Mandiri Taspen Pos"),
    ("15", "Bank Fama Internasional"),
    ("16", "Centratama Nasional Bank"),
    ("17", "Bank Index Selindo"),
    ("18", "Bank Mayora Indonesia"),
    ("19", "Bank Multi Arta Sentosa"),
    ("20", "Bank Purba Danarta"),
    ("21", "Bank Artos IND"),
    ("22", "Bank BCA Syariah"),
    ("23", "Bank Kesejahteraan Ekonomi"),
    ("24", "Anglomas Internasional Bank"),
    ("25", "Liman International Bank"),
    ("26", "Bank Akita"),
    ("27", "Bank Dipo International (Bank Sahabat Sampoerna)"),
    ("28", "Bank Persyarikatan Indonesia"),
    ("29", "Prima Master Bank"),
    ("30", "Bank Harfa"),
    ("31", "Bank Ina Perdana"),
    ("32", "Bank Syariah Mega"),
    ("33", "Bank Alfindo (Bank National Nobu)"),
    ("34", "Bank Royal Indonesia"),
    ("35", "ank Indomonex (Bank SBI Indonesia)"),
    ("36", "Bank Yudha Bhakti"),
    ("37", "Bank MNC / Bank Bumiputera"),
    ("38", "Bank Bintang Manunggal"),
    ("39", "Bank Jasa Jakarta"),
    ("40", "Bank Sri Partha"),
    ("41", "Bank Bisnis Internasional"),
    ("42", "Bank Syariah Mandiri(BSI)"),
    ("43", "Bank Bukopin"),
    ("44", "Bank BNI Syariah"),
    ("45", "Bank Mega"),
    ("46", "Bank BJB Syariah"),
    ("47", "Bank Swaguna"),
    ("48", "JENIUS"),
    ("49", "Bank Himpunan Saudara 1906"),
    ("50", "Bank Tabungan Negara (BTN)"),
    ("51", "Bank QNB Kesawan (Bank QNB Indonesia)"),
    ("52", "Bank Harmoni International"),
    ("53", "Bank (Bank ICBC Indonesia)"),
    ("54", "Bank Windu Kentjana"),
    ("55", "Bank Ganesha"),
    ("56", "Bank Hagakita"),
    ("57", "Bank Maspion Indonesia"),
    ("58", "Bank Sinarmas"),
    ("59", "Bank Metro Express (Bank Shinhan Indonesia)"),
    ("60", "Bank Mestika Dharma"),
    ("61", "Bank Muamalat"),
    ("62", "Bank of India Indonesia"),
    ("63", "Bank Nusantara Parahyangan"),
    ("64", "Bank Sultra"),
    ("65", "Bank Sulawesi Tengah"),
    ("66", "Bank Bengkulu"),
    ("67", "Bank Papua"),
    ("68", "Bank Maluku Malut"),
    ("69", "Bank NTT"),
    ("70", "Bali"),
    ("71", "Bank NTB, NTB Syariah"),
    ("72", "Bank Sulut Gorontalo"),
    ("73", "Bank Sulsel dan Barat"),
    ("74", "Bank Kalteng"),
    ("75", "Bank Kalimantan Timur dan Utara"),
    ("76", "Bank Kalimantan Barat"),
    ("77", "Bank Kalsel"),
    ("78", "Bank Lampung"),
    ("79", "Bank Sumsel Babel"),
    ("80", "Bank Riau"),
    ("81", "Bank Nagari"),
    ("82", "Bank Sumut"),
    ("83", "BPD Aceh Syariah"),
    ("84", "BPD Jambi"),
    ("85", "Bank Jatim"),
    ("86", "Bank Jateng"),
    ("87", "BPD DIY"),
    ("88", "Bank DKI"),
    ("89", "Bank Jabar dan Banten (BJB)"),
    ("90", "Bank Mayapada"),
    ("91", "Bank JTRUST"),
    ("92", "Bank IFI"),
    ("93", "Bank Haga"),
    ("94", "Bank Antardaerah"),
    ("95", "Bank Ekonomi"),
    ("96", "Bank Bumi Arta"),
    ("97", "Bank OF China"),
    ("98", "Bank Woori Indonesia"),
    ("99", "Deutsche Bank AG."),
    ("100", "Bank ANZ Indonesia"),
    ("101", "Korea Exchange Bank Danamon"),
    ("102", "Bank BNP Paribas Indonesia"),
    ("103", "Bank Capital Indonesia"),
    ("104", "Bank Keppel Tatlee Buana"),
    ("105", "Bank ABN Amro"),
    ("106", "Standard Chartered Bank"),
    ("107", "Bank Mizuho Indonesia"),
    ("108", "Bank Resona Perdania"),
    ("109", "Bank DBS Indonesia"),
    ("110", "Bank Sumitomo Mitsui Indonesia"),
    ("111", "The Bank of Tokyo Mitsubishi UFJ LTD"),
    ("112", "The Hongkong & Shanghai B.C. (Bank HSBC)"),
    ("113", "The Bangkok Bank Comp. LTD"),
    ("114", "Credit Agricole Indosuez"),
    ("115", "Bank Artha Graha Internasional"),
    ("116", "ING Indonesia Bank"),
    ("117", "Bank of America, N.A"),
    ("118", "JP. Morgan Chase Bank, N.A"),
    ("119", "Citibank"),
    ("120", "Bank OCBC NISP"),
    ("121", "Bank Lippo"),
    ("122", "Bank CIMB Niaga"),
    ("123", "Bank Arta Niaga Kencana"),
    ("124", "Bank Panin"),
    ("125", "Bank BII Maybank"),
    ("126", "Bank BCA"),
    ("127", "Permata Bank"),
    ("128", "Bank Danamon"),
    ("129", "Bank BNI"),
    ("130", "Bank Mandiri"),
    ("131", "Bank Ekspor Indonesia"),
    ("132", "Bank BRI"),
    ("133", "Bank UOB Indonesia"),
    ("134", "Bank BRI Agro"),
    ("135", "SEABANK INDONESIA"),
    ("136", "BANK BSI"),
    ("137", "BANK NEO COMMERCE"),
    ("138", "Bank BNC"),
    ("BTPN", "Bank BTPN"),
]

BANKPAY_BANK_NAME_BY_CODE = {code: name for code, name in BANKPAY_BANK_LIST}

# Pemetaan Bank.code aplikasi -> kode bank resmi BankPay.
# Kode aplikasi memakai nol di depan ("014") atau angka besar ("10002"),
# sedangkan kode BankPay tidak ("126", "2"), sehingga tanpa tabrakan makna.
BANKPAY_BANK_CODE_BY_APP_CODE = {
    "002": "132",   # BRI
    "008": "130",   # Mandiri
    "009": "129",   # BNI
    "011": "128",   # Danamon
    "0110": "128",  # Danamon UUS
    "013": "127",   # Permata
    "014": "126",   # BCA
    "016": "125",   # Maybank / BII
    "019": "124",   # Panin
    "020": "123",   # Artha Niaga Kencana
    "022": "122",   # CIMB Niaga
    "0220": "122",  # CIMB Niaga UUS
    "028": "120",   # OCBC NISP
    "031": "119",   # Citibank
    "032": "118",   # JP Morgan Chase
    "037": "115",   # Artha Graha
    "040": "113",   # Bangkok Bank
    "041": "112",   # HSBC
    "042": "111",   # Bank of Tokyo Mitsubishi UFJ
    "046": "109",   # DBS Indonesia
    "048": "107",   # Mizuho
    "050": "106",   # Standard Chartered
    "054": "103",   # Capital Indonesia
    "061": "100",   # ANZ Indonesia
    "067": "99",    # Deutsche Bank
    "069": "97",    # Bank of China
    "076": "96",    # Bumi Arta
    "095": "91",    # JTrust
    "097": "90",    # Mayapada
    "110": "89",    # Bank Jawa Barat (BJB)
    "111": "88",    # Bank DKI
    "113": "86",    # Bank Jateng
    "114": "85",    # Bank Jatim
    "115": "84",    # Bank Jambi (BPD Jambi)
    "116": "83",    # Bank Aceh (BPD Aceh Syariah)
    "131": "68",    # Bank Maluku
    "132": "67",    # Bank Papua
    "133": "66",    # Bank Bengkulu
    "145": "63",    # Nusantara Parahyangan
    "146": "62",    # Bank of India Indonesia
    "147": "61",    # Muamalat
    "151": "60",    # Mestika Dharma
    "152": "59",    # Shinhan Indonesia
    "153": "58",    # Sinarmas
    "157": "57",    # Maspion
    "161": "55",    # Ganesha
    "164": "53",    # ICBC Indonesia
    "200": "50",    # BTN
    "2000": "50",   # BTN UUS
    "212": "98",    # Woori Saudara
    "213": "BTPN",  # BTPN
    "425": "46",    # BJB Syariah
    "426": "45",    # Bank Mega
    "427": "44",    # BNI Syariah
    "441": "43",    # Wokee / Bukopin
    "4510": "136",  # Bank Syariah Indonesia (BSI)
    "459": "41",    # Bisnis Internasional
    "472": "39",    # Jasa Jakarta
    "484": "101",   # LINE Bank / KEB Hana
    "485": "37",    # MNC / Bumiputera
    "490": "137",   # Neo Commerce
    "498": "35",    # SBI Indonesia
    "503": "33",    # National Nobu
    "506": "32",    # Mega Syariah (Bank Syariah Mega)
    "513": "31",    # Ina Perdana
    "520": "29",    # Prima Master
    "523": "27",    # Sahabat Sampoerna (Bank Dipo)
    "531": "24",    # Anglomas Internasional
    "535": "135",   # Seabank
    "536": "22",    # BCA Syariah
    "542": "21",    # Artos / Jago
    "548": "19",    # Multi Arta Sentosa
    "553": "18",    # Mayora
    "555": "17",    # Index Selindo
    "559": "16",    # Centratama Nasional
    "562": "15",    # Fama Internasional
    "567": "12",    # Allo Bank (eks Bank Harda)
    "778": "88",    # Bank DKI UUS
    "949": "6",     # CTBC Indonesia
    "1450": "102",  # BNP Paribas
    "1670": "51",   # QNB Indonesia
    "2120": "49",   # Himpunan Saudara 1906
    "10001": "1",   # OVO
    "10002": "2",   # DANA
    "10003": "3",   # GOPAY
    "10008": "4",   # SHOPEEPAY
    "10009": "5",   # LINKAJA
    "10010": "91",   # Mutiara (eks Bank Mutiara / JTrust)
}

# Kode aplikasi yang angkanya bertabrakan dengan kode resmi BankPay tetapi artinya
# berbeda (mis. "132" = Bank Papua di aplikasi, "132" = Bank BRI di BankPay).
# Nama bank dipakai pembeda: konversi hanya bila nama yang dikirim cocok dengan
# nama bank aplikasi di bawah ini.
BANKPAY_APP_CODE_BANK_NAMES = {
    "110": "Bank Jawa Barat",
    "111": "Bank DKI",
    "113": "Bank Jateng",
    "114": "Bank Jatim",
    "115": "Bank Jambi",
    "116": "Bank Aceh",
    "131": "Bank Maluku",
    "132": "Bank Papua",
    "133": "Bank Bengkulu",
}


def resolve_bankpay_bank(bank_no: str, bank_name: str = "") -> tuple[str, str]:
    """Terjemahkan kode bank aplikasi (Bank.code) atau kode resmi BankPay menjadi
    pasangan (bankno, bankname) yang valid untuk payout BankPay.

    - Kode aplikasi yang punya padanan resmi dikonversi (mis. "014" BCA -> "126").
    - Kode aplikasi yang bertabrakan dengan kode resmi dibedakan dari nama bank.
    - Kode resmi / tidak dikenal dikembalikan apa adanya; nama diisi dari tabel
      resmi bila kodenya dikenali.
    """
    code = (bank_no or "").strip()
    name = (bank_name or "").strip()
    official_name = BANKPAY_BANK_NAME_BY_CODE.get(code)
    mapped = BANKPAY_BANK_CODE_BY_APP_CODE.get(code)
    if mapped:
        app_name = BANKPAY_APP_CODE_BANK_NAMES.get(code, "").lower()
        if not official_name or (app_name and name.lower() == app_name):
            return mapped, BANKPAY_BANK_NAME_BY_CODE.get(mapped, name)
    if official_name:
        return code, official_name
    return code, name


def fetch_bank_list(api_url: str, member_id: str, key: str, timeout: int = 30) -> tuple[list[dict], str]:
    """Fetch daftar bank dari BankPay.
    Returns: (bank_list, error_string)
    - bank_list: [{"bankCode": "126", "bankName": "Bank BCA"}, ...]
    - error_string: "" jika sukses, atau pesan error
    """
    try:
        payload = {
            "memberid": member_id,
            "handle_type": "getBankList",
            "currency": "IDR",
        }
        payload["sign"] = generate_sign(payload, key)
        resp = post_form(f"{api_url.rstrip('/')}/Pay-payment.aspx", payload, timeout=timeout)
        status_code = str(resp.get("status") or "").strip()
        raw_list = resp.get("bankList")
        if status_code in ("200", "1") and isinstance(raw_list, list):
            normalized = []
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                bc = str(item.get("bankCode") or item.get("code") or "").strip()
                bn = str(item.get("bankName") or item.get("name") or "").strip()
                if bc:
                    normalized.append({"bankCode": bc, "bankName": bn})
            return normalized, ""
        return [], f"BankPay bank list error: {resp.get('msg') or resp}"
    except Exception as e:
        return [], str(e)
