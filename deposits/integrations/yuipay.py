"""Integrasi Yuipay (api.montfara.vip) untuk deposit & withdrawal.

Platform dan skema signature identik dengan Reepay (HMAC-SHA256), hanya
menambah header wajib X-Merchant-Code (USN) di setiap request.

Signature request : HMAC_SHA256(secret, timestamp + method + path + body)
Signature callback: HMAC_SHA256(secret, timestamp + "POST" + callbackPath + rawBody)
"""
from .reepay import (  # noqa: F401  (re-export helper yang identik)
    build_signature,
    extract_callback_field,
    verify_callback_signature,
)
from .reepay import get_json as _get_json, post_json as _post_json

DEFAULT_API_URL = "https://api.montfara.vip"


def post_json(api_key: str, merchant_code: str, secret: str, path: str, payload: dict,
              base_url: str = DEFAULT_API_URL, timeout: int = 30):
    """Kirim request POST JSON ke Yuipay. Return (response_dict, http_status)."""
    return _post_json(api_key, secret, path, payload, base_url=base_url,
                      timeout=timeout, merchant_code=merchant_code)


def get_json(api_key: str, merchant_code: str, secret: str, path: str,
             base_url: str = DEFAULT_API_URL, timeout: int = 30):
    """Kirim request GET ke Yuipay. Return (response_dict, http_status)."""
    return _get_json(api_key, secret, path, base_url=base_url,
                     timeout=timeout, merchant_code=merchant_code)
