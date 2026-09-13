from django.core.management.base import BaseCommand

from support.models import SupportFaq


# Isi awal Pusat Bantuan — silakan ubah/tambah lewat Django admin.
DEFAULTS = [
    {
        'category': 'Akun',
        'order': 1,
        'question': 'Bagaimana cara verifikasi akun?',
        'answer': 'Buka menu Edit Profil, lalu unggah KTP dan foto selfie. Verifikasi biasanya selesai dalam 1x24 jam kerja.',
    },
    {
        'category': 'Akun',
        'order': 2,
        'question': 'Bisakah ganti nomor telepon terdaftar?',
        'answer': 'Bisa. Hubungi CS lewat menu Hubungi CS dengan menyertakan nomor lama dan nomor baru untuk proses penggantian.',
    },
    {
        'category': 'Saldo & Transaksi',
        'order': 1,
        'question': 'Bagaimana cara isi ulang saldo?',
        'answer': 'Masuk ke menu Isi Ulang, pilih nominal, lalu bayar lewat QRIS atau Virtual Account. Saldo masuk otomatis setelah pembayaran terkonfirmasi.',
    },
    {
        'category': 'Saldo & Transaksi',
        'order': 2,
        'question': 'Berapa lama proses tarik dana?',
        'answer': 'Penarikan diproses 1-24 jam kerja pada jam operasional 08:00-20:00 WIB. Statusnya bisa dipantau di Riwayat Penarikan.',
    },
    {
        'category': 'Saldo & Transaksi',
        'order': 3,
        'question': 'Kenapa transaksi saya gagal?',
        'answer': 'Penyebab umum: saldo tidak cukup, rekening tujuan tidak valid, atau batas transaksi harian tercapai. Cek detailnya di Riwayat Transaksi.',
    },
    {
        'category': 'Emas Digital',
        'order': 1,
        'question': 'Apakah emas digital aman?',
        'answer': 'Emas digital disimpan di fasilitas penyimpanan berizin dan diasuransikan penuh.',
    },
    {
        'category': 'Emas Digital',
        'order': 2,
        'question': 'Bagaimana cara cetak emas fisik?',
        'answer': 'Buka menu Emas Digital, pilih Cetak Emas, tentukan pecahan dan alamat pengiriman. Emas fisik dikirim ke alamat kamu.',
    },
]


class Command(BaseCommand):
    help = 'Seed default FAQ untuk halaman Pusat Bantuan'

    def add_arguments(self, parser):
        parser.add_argument('--overwrite', action='store_true', help='Timpa FAQ yang sudah ada dengan isi default')

    def handle(self, *args, **options):
        overwrite = options.get('overwrite', False)
        created, updated, skipped = 0, 0, 0

        for item in DEFAULTS:
            try:
                faq = SupportFaq.objects.filter(question=item['question']).first()
                if not faq:
                    SupportFaq.objects.create(**item)
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"Created: {item['question']}"))
                elif overwrite:
                    for key, value in item.items():
                        setattr(faq, key, value)
                    faq.save()
                    updated += 1
                    self.stdout.write(self.style.WARNING(f"Updated: {item['question']}"))
                else:
                    skipped += 1
                    self.stdout.write(f"Skipped (exists): {item['question']}")
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"Error processing {item['question']}: {exc}"))

        total = SupportFaq.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"Seeding FAQ done. created={created}, updated={updated}, skipped={skipped}, total={total}"
        ))
