"""Integrasi Quen Payment (QuenPay) QRIS Pay-In v1.

Hanya Pay-In (deposit QRIS). Payout API belum aktif di sisi Quen.

Base API  : /api/v1  (host diisi di konfigurasi GatewaySettings, contoh https://api.quenpay.com)
Method    : QRIS, Currency IDR
Auth      : Header X-Quen-Api-Key, X-Quen-Timestamp (unix DETIK), X-Quen-Nonce (16-128 char),
            X-Quen-Signature (HMAC-SHA256), Content-Type application/json
Window    : timestamp toleransi +-300 detik; nonce anti-replay 10 menit

Canonical string (di-join dengan newline):
    METHOD
    PATH
    TIMESTAMP
    NONCE
    SHA256_RAW_BODY
signature = HMAC_SHA256(canonical, API_SECRET)  (lowercase hex)

Body hash harus dihitung dari raw JSON persis seperti yang dikirim (jangan
decode/encode ulang setelah signature dihitung).

Callback payment.success:
    Headers: X-Quen-Event, X-Quen-Timestamp, X-Quen-Signature
    signature = HMAC_SHA256(timestamp + "." + raw_json_body, API_SECRET)
    Payload hanya dikirim setelah transaksi SUCCESS & database commit.
"""
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Tuple

import requests

logger = logging.getLogger(__name__)

# Path prefix yang sama dipakai di canonical string & URL
API_PREFIX = "/api/v1"
DEFAULT_API_URL = ""  # host diisi via admin GatewaySettings

CREATE_PATH = "/api/v1/payment/create"
QUERY_PATH = "/api/v1/payment/query"


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hmac_sha256_hex(secret: str, message: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def build_signature(secret: str, method: str, path: str, timestamp: str, nonce: str, raw_body: str) -> str:
    """Hitung signature request QuenPay.

    canonical = METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(raw_body)
    raw_body kosong untuk GET (tidak dipakai di flow ini, semua POST).
    """
    body_hash = _sha256_hex(raw_body or "")
    canonical = "\n".join([method, path, timestamp, nonce, body_hash])
    return _hmac_sha256_hex(secret, canonical)


def build_headers(api_key: str, secret: str, method: str, path: str, raw_body: str,
                  timestamp: str = None, nonce: str = None) -> dict:
    ts = timestamp or str(int(time.time()))
    nc = nonce or uuid.uuid4().hex  # 32 karakter (rentang 16-128 aman)
    signature = build_signature(secret, method, path, ts, nc, raw_body)
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Quen-Api-Key": api_key,
        "X-Quen-Timestamp": ts,
        "X-Quen-Nonce": nc,
        "X-Quen-Signature": signature,
    }


def post_json(
    api_key: str,
    secret: str,
    path: str,
    payload: dict,
    base_url: str = "",
    timeout: int = 30,
) -> Tuple[dict, int]:
    """Kirim request POST JSON ke QuenPay. Return (response_dict, http_status)."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    headers = build_headers(api_key, secret, "POST", path, body)
    url = f"{base_url.rstrip('/')}{path}"
    resp = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=timeout)
    try:
        data = resp.json()
    except Exception:
        data = {}
    return data, resp.status_code


def verify_callback_signature(secret: str, timestamp: str, raw_body: str, signature: str) -> bool:
    """Verifikasi signature callback payment.success.

    signature = HMAC_SHA256(timestamp + "." + raw_json_body, API_SECRET)
    """
    if not secret or not timestamp or not signature:
        return False
    message = f"{timestamp}.{raw_body or ''}"
    expected = _hmac_sha256_hex(secret, message)
    return hmac.compare_digest(expected, signature.strip().lower())
