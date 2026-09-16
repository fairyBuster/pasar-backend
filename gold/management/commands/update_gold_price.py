from django.core.management.base import BaseCommand

from gold.services import get_gold_price_per_gram


class Command(BaseCommand):
    help = 'Ambil harga emas real-time terbaru dan simpan ke GoldSettings (untuk cron/scheduler).'

    def handle(self, *args, **options):
        try:
            settings_obj, price, source = get_gold_price_per_gram(force_refresh=True)
            self.stdout.write(self.style.SUCCESS(
                f'Harga emas diperbarui: {price} /gram (sumber: {source})'
            ))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f'Gagal ambil harga emas: {exc}'))
