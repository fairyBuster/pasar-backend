# Cara Withdraw (WD / 代付) BankPay

Panduan praktis untuk **withdraw / 代付 (disbursement)** di platform BankPay.
Sumber resmi: `https://bankpay.cfd/Home-Index-apiDoc.aspx`

---

## 1. Prasyarat

| Item | Keterangan |
| --- | --- |
| `memberid` (商户号) | Diberikan platform saat registrasi merchant |
| `key` (密钥 / 安全码) | Password string yang dipasangkan ke memberid |
| Gateway | `https://pay.bankpay.cfd` (HTTPS) |
| Protokol | `HTTP POST` — `application/x-www-form-urlencoded;charset=utf-8` |
| Encoding | UTF-8 |
| Format balasan | JSON |

> ⚠️ **QPS limit**: interface WD dibatasi **5 request/detik**. Jangan burst.

---

## 2. Aturan Signature (MD5)

1. Ambil semua parameter yang **ikut sign** dan **nilainya tidak kosong**.
2. Urutkan berdasarkan **nama parameter, ASCII ascending (字典序)**.
3. Gabung jadi `key1=value1&key2=value2...`.
4. Tambahkan `&key=<KEY_ANDA>` di paling akhir.
5. MD5 dari string itu, lalu **UPPERCASE**.

> Field `sign` (dan `numberId`) **TIDAK** ikut signature.

**Contoh string asli → MD5:**
```
accountname=IKteBo&amount=500&bankcode=bank&email=test@mail.com&memberid=10002&mobile=8111293332&notifyurl=google.com/demo/page.php&orderid=EE20211008133348340819&pay_currency=INR&vpa=123123123&key=KEY_ANDA
```
(sort ASCII, semua nilai non-kosong, `&key=` di akhir, hasil MD5 uppercase.)

> Catatan: contoh string di dokumen resmi menampilkan `[email protected]` (email di-obfuscate JS) dan ada 1 field yang posisinya tidak persis ASCII-sort. Ikuti **aturan sort ASCII** di atas — itu yang benar, bukan teks contoh literalnya.

---

## 3. Request WD

### Endpoint
```
POST https://pay.bankpay.cfd/Pay-payment-draw.aspx
Content-Type: application/x-www-form-urlencoded;charset=utf-8
```

### Parameter publik (semua ikut sign, kecuali `sign`)

| Field | Wajib | Ikut sign | Keterangan |
| --- | :-: | :-: | --- |
| `memberid` | √ | √ | 商户号 |
| `orderid` | √ | √ | **Unik, 16–32 karakter** |
| `bankcode` | √ | √ | Tipe pembayaran, misal `bank` |
| `notifyurl` | √ | √ | URL notifikasi (kalau ada `?`/`&` → urlencode dulu) |
| `amount` | √ | √ | Nominal, satuan 元, 2 desimal, cth `10.00` |
| `mobile` | √ | √ | HP penerima |
| `email` | √ | √ | Email penerima |
| `pay_currency` | √ | √ | Kode mata uang, cth `INR` / `IDR` |
| `sign` | √ | ✗ | MD5 signature (hasil step 2) |

### WD jalur UPI vs Kartu Bank — pilih salah satu

> **Kalau `vpa` dikirim → otomatis dianggap UPI.** Kalau tidak → kartu bank.

#### 3a. UPI (传 `vpa`)

| Field | Wajib | Ikut sign | Keterangan |
| --- | :-: | :-: | --- |
| `accountname` | √ | √ | Nama penerima |
| `vpa` | √ | √ | UPI ID / UPI账户 |

#### 3b. Kartu bank (bankcard)

| Field | Wajib | Ikut sign | Keterangan |
| --- | :-: | :-: | --- |
| `bankname` | √ | √ | Nama bank, **jangan pakai huruf Cina**; kalau kosong isi `bank` |
| `cardnumber` | √ | √ | Nomor rekening/kartu penerima |
| `accountname` | √ | √ | Nama penerima |
| `bankno` | √ | √ | Kode bank — **India: IFSC**; negara lain: kode bank (lihat tabel di bawah) |
| `numberId` | N | ✗ | Khusus **Kolombia**: nomor identitas (8–11 digit) |

> **Brasil** spesial: `bankname` diisi salah satu dari `CPF` / `CNPJ` / `PHONE` / `EMAIL`,
> dan `cardnumber` diisi nilai sesuai tipe itu. `bankno` = kode bank Brasil (cth `237`).

---

## 4. Kode Bank Indonesia (untuk `bankno`)

Kode internal platform (BUKAN kode standar BI). Contoh yang sering dipakai:

| Kode | Bank |
| --- | --- |
| `126` | Bank BCA |
| `129` | Bank BNI |
| `130` | Bank Mandiri |
| `132` | Bank BRI |
| `128` | Bank Danamon |
| `127` | Permata Bank |
| `122` | Bank CIMB Niaga |
| `120` | Bank OCBC NISP |
| `124` | Bank Panin |
| `136` | Bank BSI |
| `135` | SeaBank Indonesia |
| `137` | Bank Neo Commerce |

Daftar lengkap 139 bank/wallet Indonesia: `bankpay_idr_bank_codes.csv`.
Sumber data live (tanpa login):
```
curl -sS "https://bankpay.cfd/Home-Index-getBankListByCountry?country_id=11" \
  -H "X-Requested-With: XMLHttpRequest" \
  -H "Referer: https://bankpay.cfd/Home-Index-apiDoc.aspx"
```

---

## 5. Respons WD

**Sukses:**
```json
{
  "status": 1,
  "msg": {
    "memberid": "10002",
    "transaction_id": "20210101104300485bf84f7b",
    "accountname": "PSK3QA",
    "mobile": "8111293332",
    "email": "test@mail.com",
    "bankno": "",
    "vpa": "1336321521",
    "orderid": "2021010110430048523a",
    "amount": "500",
    "trade_state": "SUCCESS"
  }
}
```
- `trade_state` = `SUCCESS` → WD diterima; selain itu → ditolak.

**Gagal:**
```json
{ "status": 0, "msg": "Error 99, The withdrawal amount is too small" }
```
> `status` = `0` artinya error. Baca `msg` untuk alasannya.

---

## 6. Callback / Notifikasi WD (server → kamu)

Platform kirim `HTTP POST FORM` ke `notifyurl`. **Kamu wajib membalas string `OK`** (tanpa tanda kutip); kalau tidak, platform mengirim ulang sampai **3×**.

| Field | Ikut sign | Keterangan |
| --- | :-: | --- |
| `memberid` | √ | 商户号 |
| `orderid` | √ | 订单号 |
| `transaction_id` | √ | Platform流水号 |
| `amount` | √ | **Nominal aktual yang dibayarkan** — jadikan dasar pencatatan |
| `datetime` | √ | Format `20170303111111` |
| `returncode` | √ | `00` = sukses; selain itu (cth `fail`) gagal |
| `msg` | ✗ | Alasan gagal (kalau ada) |
| `sign` | ✗ | Verifikasi pakai aturan section 2 |

> Contoh balasan sukses: cukup body `OK`.

---

## 7. Query status WD

```
POST https://pay.bankpay.cfd/Pay-Trade-dfquery.aspx
memberid + orderid + sign
```

**Respons:**
| Field | Keterangan |
| --- | --- |
| `amount` | Nominal WD |
| `fee` | Biaya |
| `cldatetime` | Waktu selesai diproses |
| `returncode` | `00` = respons sukses |
| `trade_state` | `WAIT PAY` (menunggu) / `SUCCESS` (sukses) / `REFUSE` (ditolak) |
| `trade_msg` | Alasan gagal (kosong kalau sukses) |

---

## 8. Cek Saldo

```
POST https://pay.bankpay.cfd/Pay-Trade-getBalance.aspx
memberid (+ currency opsional, misal IDR) + sign
```
Respons: `memberid`, `balance`, `returncode` (`00` sukses), `sign`.

---

## 9. Helper Python (sign + request WD)

```python
import hashlib, urllib.parse, urllib.request

MEMBERID = "10002"
KEY      = "KEY_ANDA_RAHASIA"

def md5_sign(fields: dict) -> str:
    """Sort ASCII ascending, gabung k=v, + &key=, MD5 uppercase."""
    items = sorted((k, v) for k, v in fields.items() if v not in (None, ""))
    raw = "&".join(f"{k}={v}" for k, v in items) + f"&key={KEY}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

def wd_upi(orderid, amount, accountname, vpa, mobile, email,
           notifyurl, pay_currency="INR", bankcode="bank"):
    body = {
        "memberid": MEMBERID, "orderid": orderid, "bankcode": bankcode,
        "notifyurl": notifyurl, "amount": amount, "mobile": mobile,
        "email": email, "pay_currency": pay_currency,
        "accountname": accountname, "vpa": vpa,
    }
    body["sign"] = md5_sign(body)          # sign TIDAK ikut hash
    data = urllib.parse.urlencode(body).encode("utf-8")
    req = urllib.request.Request(
        "https://pay.bankpay.cfd/Pay-payment-draw.aspx",
        data=data, headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")

def wd_bank(orderid, amount, accountname, cardnumber, bankno, bankname,
            mobile, email, notifyurl, pay_currency="IDR", bankcode="bank"):
    body = {
        "memberid": MEMBERID, "orderid": orderid, "bankcode": bankcode,
        "notifyurl": notifyurl, "amount": amount, "mobile": mobile,
        "email": email, "pay_currency": pay_currency,
        "bankname": bankname, "cardnumber": cardnumber,
        "accountname": accountname, "bankno": bankno,
    }
    body["sign"] = md5_sign(body)
    data = urllib.parse.urlencode(body).encode("utf-8")
    req = urllib.request.Request(
        "https://pay.bankpay.cfd/Pay-payment-draw.aspx",
        data=data, headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")

# Contoh pakai — WD kartu bank ke BCA (IDR):
print(wd_bank(
    orderid="WD202610061200000001",
    amount="10.00",
    accountname="Budi Santoso",
    cardnumber="1234567890",
    bankno="126",           # BCA
    bankname="Bank BCA",    # jangan huruf Cina
    mobile="081234567890",
    email="budi@mail.com",
    notifyurl="https://contoh.com/notify",
))
```

---

## 10. Checklist cepat sebelum request

- [ ] `orderid` unik, panjang 16–32 karakter
- [ ] `amount` 2 desimal (`10.00`, bukan `10`)
- [ ] `notifyurl` sudah di-urlencode kalau ada `?`/`&`
- [ ] Semua field wajib terisi (mobile & email wajib)
- [ ] `bankname` tidak memakai huruf Cina
- [ ] Sign dihitung dari field yang ikut sign saja, urut ASCII, MD5 uppercase
- [ ] Callback membalas `OK`
- [ ] Pencatatan pakai `amount` dari callback, bukan dari request
- [ ] Jangan melebihi 5 request/detik

---

## 11. Troubleshooting umum

| Masalah | Kemungkinan penyebab |
| --- | --- |
| `status: 0` + `msg: Error 99, The withdrawal amount is too small` | Nominal WD di bawah minimum |
| `Merchant ID error` saat下单 | Salah `memberid`, atau salah Content-Type (harus form-urlencoded, bukan JSON) |
| Callback tidak sampai | `notifyurl` belum urlencode; atau kamu tidak balas `OK` |
| `trade_state` = `REFUSE` | Cek `trade_msg` untuk alasan penolakan |
| Sign ditolak | Field salah urut / ada field kosong ikut terhash / `&key=` tidak di akhir / tidak uppercase |
