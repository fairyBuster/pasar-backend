# Dokumentasi Integrasi FF Pay / LPAY / MGM

> Satu akun merchant, tiga wallet. **FF Pay (main)**, **LPAY**, dan **MGM** berbagi satu merchant
> di `https://api.nextcdn.online` — API key & secret key **sama** untuk deposit dan payout.
> Autentikasi: **HMAC-SHA256** via header `X-API-Key`, `X-Timestamp`, `X-Signature`.

---

## 1. Kredensial Aktif (production)

Diambil dari DB production (25 Sep 2026). Disimpan di `GatewaySettings` (deposit) dan
`WithdrawalSettings` (payout).

| Item | Nilai |
|---|---|
| Base URL | `https://api.nextcdn.online` |
| X-API-Key (deposit & payout) | `ak_s40u2k8h4Dd4DHWNMFaqX7PclHPVJU20` |
| Secret Key (deposit & payout) | lihat blok di bawah (347 karakter) |

**Secret key (HMAC-SHA256):**

```
sk_9GLfvGt2MOyFukgb9OmD9u4AR2nTD5yS2w0AYB09aPzdwrRJDL7SX5xEmNTFZ1aDbHSKTYe0i1FYQhmQIPhsgTeqpJLOcC9x0ursTTUPFYAhdJagsNavNoJt5lByO3jJEevFoRRNl7oaSjWRbMRXaWmSDCVV1nC7vKi8x376qryaainqlTVSMmZBJ3ERrrY0tesEbpFFc3MctmS7irw6hhhwBSBXZRwh9dXcIyQxnFD49aVHhhq0NK5BUpXAI86MUdK5wcq1uCjkcuHEqcOENhEJ6u6OcH31uHo53VsypMaG05mWwICqbfncge7FX8AHYRn3U0qwumBHUmL48t6s0DD4
```

> **PENTING:** secret key 347 karakter — jangan dipotong. Field di model bertipe `TextField`
> justru karena panjangnya melebihi 255 (`ffpay_secret_key` / `ffpay_payout_secret_key`).

### Status gateway saat ini

| Setting | Nilai aktif |
|---|---|
| `ffpay_enabled` (deposit FF Pay) | `True` |
| `lpay_enabled` | `True` |
| `mgm_enabled` | `True` |
| `mgm_method` | `QRCODE` |
| `lpay_code` | `3560` |
| `ffpay_return_url` | `https://jelajahemas.com/#/index/transactions/isi-ulang` |
| `min_deposit_amount` | `40000.00` |
| `max_deposit_amount` | `100000000.00` |
| `default_wallet_type` | `BALANCE_DEPOSIT` |
| `ffpay_payout_enabled` (payout FF Pay) | `True` |
| `lpay_payout_enabled` | `True` |
| `mgm_payout_enabled` | `True` |

---

## 2. Skema Signature

### 2.1 Request merchant → provider

```
X-Signature = HMAC_SHA256(secret, timestamp + method + path + body)   (lowercase hex)
```

| Komponen | Aturan |
|---|---|
| `timestamp` | Unix milidetik sebagai string (`str(int(time.time() * 1000))`) |
| `method` | `POST` / `GET` (huruf kapital) |
| `path` | URL path saja, tanpa query string (mis. `/gateway/charge/create`) |
| `body` | Raw JSON string, `separators=(",", ":")`, `ensure_ascii=False`; kosong (`""`) untuk GET |

Header request: `Content-Type: application/json`, `X-API-Key`, `X-Timestamp`, `X-Signature`.

### 2.2 Verifikasi callback (provider → merchant)

```
X-Signature = HMAC_SHA256(secret, X-Timestamp + "POST" + webhookPath + rawBody)
```

Bandingkan `hmac.compare_digest` dengan nilai header `X-Signature` (lowercase). Callback tanpa
`X-Timestamp`/`X-Signature` valid → dianggap tidak valid dan **tidak** mengubah status transaksi
(payload tetap disimpan ke `callback_payload` untuk audit).

Implementasi bersama (juga dipakai Reepay): `deposits/integrations/reepay.py`
(`build_signature`, `verify_callback_signature`, `post_json`).

---

## 3. Deposit (Pay-In)

### 3.1 Endpoint provider

| Wallet | Method | HTTP |
|---|---|---|
| FF Pay (main) | cashier (metode dipilih di halaman FF Pay) | `POST /gateway/charge/create` |
| FF Pay (main) | pilih metode langsung tanpa cashier | `POST /gateway/charge/{ref_id}/method` |
| LPAY | — | `POST /gateway/lpay/payin` |
| MGM | `WALLET` | `POST /gateway/mgm/payin` |
| MGM | `QRCODE` | `POST /gateway/mgm/qris` |

### 3.2 Payload initiate

| Field | Keterangan |
|---|---|
| `amount` | Nominal **integer IDR** (dibulatkan) |
| `merchant_ref` | Order ID dari kita (= `trx_id`/`order_num`) |
| `customer_name`, `customer_email`, `customer_phone` | Data user, dipotong 100/100/32 char |
| `description` | Deskripsi, maks 100 char |
| `method` | FF Pay: `""` (cashier); MGM: `WALLET`/`QRCODE` |
| `code` | LPAY saja, dari `GatewaySettings.lpay_code` (aktif: `3560`) |
| `expiry_period` | FF Pay saja, opsional (menit) |
| `return_url` | Opsional, dari `GatewaySettings.ffpay_return_url` |

### 3.3 Response initiate (field yang kita pakai)

| Field | Keterangan |
|---|---|
| `success` | `true` = sukses |
| `data.pay_url` | Halaman pembayaran/cashier |
| `data.ref_id` | ID transaksi di provider |
| `data.pay_data` + `data.pay_data_type` | Konten QR (`QR_URL`/`QR_CODE`) bila metode QRIS |
| `data.qr_url` | URL gambar QR mentah (referensi/debug) |
| `data.expires_at` | Waktu kedaluwarsa |

Catatan fallback: platform provider kadang tidak mengekstrak QR (`pay_data` null,
`pay_data_type: PG_URL`). Saat itu terjadi:
- **MGM QRCODE** → scrape halaman cashier `pay_url` untuk ambil gambar QR (`qr_image` data URI).
- **LPAY** → scrape QRIS string dari API session cashier + generate `qr_image` lokal.

### 3.4 Endpoint aplikasi kita

| Endpoint | Keterangan |
|---|---|
| `POST /api/deposits/vega/initiate/` | Initiate FF Pay (prefix order `DFF`) |
| `POST /api/deposits/lpay/initiate/` | Initiate LPAY (prefix `DLP`) |
| `POST /api/deposits/lyra/initiate/` | Initiate MGM (prefix `DMG`) |
| `POST /api/deposits/vega/select-method/` | FF Pay: pilih metode langsung (`QRIS`/`BRI`/`PERMATA`/`MANDIRI`) |

Request body initiate: `amount` (wajib), `wallet_type` (`BALANCE`/`BALANCE_DEPOSIT`),
`expiry_period` (opsional, FF Pay). `amount` integer IDR; deposit dikreditkan setelah callback
`payment.paid` dengan signature valid.

### 3.5 Callback deposit

- **Webhook URL (satu untuk ketiga wallet):** `https://richnetworkers.online/api/deposits/ffpay/callback/`
- Event asli ada di `data.event`: `payment.paid`, `payment.failed`, `payment.expired`.
  (Top-level `event` hanya kategori `payment`/`disbursement`.)
- Deposit dicocokkan via `merchant_ref`; balas body `OK` (teks) agar provider tidak retry.
- Transaksi yang sudah `COMPLETED` di-skip (idempotent terhadap retry).
- Event `disbursement.*` yang masuk ke URL ini otomatis dirutekan ke handler payout
  (dipakai bila *Withdraw Webhook URL* dikosongkan di dashboard provider).

---

## 4. Withdrawal (Payout)

### 4.1 Endpoint provider

| Wallet | HTTP |
|---|---|
| FF Pay (main) | `POST /gateway/payout/create` |
| LPAY | `POST /gateway/lpay/payout` |
| MGM | `POST /gateway/mgm/payout` |

### 4.2 Payload payout

| Field | Keterangan |
|---|---|
| `amount` | Integer IDR; batas aplikasi **10.000 – 50.000.000** |
| `destination_account` | Nomor rekening / akun e-wallet tujuan |
| `bank_code` | Kode bank per wallet (lihat §5) |
| `account_holder_name` | Nama pemilik rekening (wajib untuk LPAY & MGM) |
| `merchant_ref` | `trx_id` withdrawal |
| `code` | LPAY saja, opsional |
| `description` | LPAY/MGM saja, opsional (maks 100 char) |

### 4.3 Response & status provider

`success: true` + `data.ref_id` + `data.status` (`processing`). Nominal **> 5.000.000**
dikembalikan `awaiting_approval` (menunggu approve manual platform); di aplikasi status
withdrawal tetap diset `PROCESSING`.

### 4.4 Endpoint aplikasi kita (admin)

| Endpoint | Keterangan |
|---|---|
| `POST /api/withdrawals/ffpay/initiate/<pk>/` | Initiate payout FF Pay (admin) |
| `POST /api/withdrawals/lpay/initiate/<pk>/` | Initiate payout LPAY (admin) |
| `POST /api/withdrawals/mgm/initiate/<pk>/` | Initiate payout MGM (admin) |

### 4.5 Callback payout

- **Webhook URL:** `https://richnetworkers.online/api/withdrawals/ffpay/callback/`
- Event (di `data.event`):
  - `disbursement.success` → withdrawal `COMPLETED`
  - `disbursement.failed` → withdrawal `REJECTED` (memicu auto-refund saldo)
  - `disbursement.processing` → withdrawal `PROCESSING`
- Model trace: satu `FfpayWithdrawal` dengan kolom `wallet` (`ffpay`/`lpay`/`mgm`).

---

## 5. Pemetaan Kode Bank

Referensi: `withdrawal/integrations/ffpay.py`. Tabel resmi bisa di-fetch dari
`GET /gateway/payout/banks?wallet=lpay|mgm`.

| Wallet | Format kode | Contoh |
|---|---|---|
| FF Pay (main) | Kode numerik klasik apa adanya; e-wallet pakai kata huruf kecil | `014` (BCA), `dana`, `ovo`, `gopay` |
| LPAY | Word code resmi (v1.1, 2025-11) | `BCA`, `MANDIRI`, `DANA` |
| MGM | Kode 5 digit (tabel 7.15) | `10014` (BCA), `10951` (DANA) |

Di form admin, wallet di-map lewat bank picker dengan 17 bank populer
(BCA, BRI, Mandiri, BNI, BSI, CIMB, Danamon, Permata, BTN, Seabank, Jago, Neo Commerce,
DANA, OVO, GoPay, ShopeePay, LinkAja). Bank di luar daftar otomatis ditambahkan; bank yang
tidak ada di tabel LPAY/MGM akan ditolak (kode kosong).

---

## 6. Catatan Operasional

1. **Satu merchant** — key `ak_...` yang sama dipakai semua endpoint payin/payout ketiga wallet;
   deposit key dan payout key identik (sudah diverifikasi di production).
2. **Callback wajib dibalas `OK`** (HTTP 200) — retry provider otomatis di-skip (idempotent).
3. **Secret jangan bocor** — siapa pun yang memegang secret bisa memalsukan callback
   `payment.paid` / `disbursement.success` (server memang memvalidasi signature sebelum
   mengubah status, tapi tetap: rahasiakan).
4. **Nominal FF Pay hanya integer IDR** — jangan kirim desimal di payload provider.
5. Jika *Withdraw Webhook URL* dikosongkan di dashboard provider, event `disbursement.*`
   otomatis masuk ke collections URL (`/api/deposits/ffpay/callback/`) dan dirutekan
   ke handler payout.
