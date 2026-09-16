from decimal import Decimal
import uuid

from django.conf import settings
from django.db import models
from django.db import transaction as db_transaction
from django.utils import timezone


class GoldSettings(models.Model):
    """Konfigurasi fitur tukar balance_hold menjadi emas fisik (cukup satu baris)."""

    is_active = models.BooleanField(
        default=False,
        help_text='Jika OFF, user tidak bisa melakukan tukar emas.',
    )
    printing_fee_per_gram = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Biaya cetak emas fisik per gram (rupiah). Total biaya cetak = gram x tarif ini. Dibayar dari balance_deposit.',
    )
    shipping_cost = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Ongkos kirim flat per order (rupiah). Dibayar dari balance_deposit.',
    )
    price_cache_minutes = models.PositiveIntegerField(
        default=5,
        help_text='Harga emas real-time di-cache selama X menit sebelum diambil ulang dari API.',
    )

    # Cache harga terakhir (diisi otomatis oleh sistem)
    last_price_per_gram = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Harga emas terakhir per gram (rupiah) - otomatis.',
    )
    last_price_usd_per_oz = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Harga XAU terakhir (USD per troy ounce) - otomatis.',
    )
    last_usd_idr_rate = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Kurs USD -> IDR terakhir - otomatis.',
    )
    last_price_updated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'gold_settings'
        verbose_name = 'Gold Settings'
        verbose_name_plural = 'Gold Settings'

    def __str__(self):
        return f'GoldSettings(id={self.id}, active={self.is_active})'

    @classmethod
    def load(cls):
        """Ambil baris konfigurasi (dibuat lewat migrasi seed, cukup satu baris)."""
        return cls.objects.order_by('id').first()


class GoldOrder(models.Model):
    """Order tukar balance_hold menjadi emas fisik.

    Alur saldo:
    - Nilai emas (gram x harga per gram) dipotong dari balance_hold.
    - Biaya cetak (gram x tarif per gram) + ongkir flat dipotong dari balance_deposit.
    - Jika order dibatalkan, keduanya dikembalikan ke wallet asalnya.
    """

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('SHIPPED', 'Shipped'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='gold_orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    gram = models.DecimalField(max_digits=15, decimal_places=4, help_text='Berat emas yang ditukar (gram).')
    price_per_gram = models.DecimalField(max_digits=15, decimal_places=2, help_text='Harga emas per gram saat swap (rupiah).')
    gold_value = models.DecimalField(max_digits=15, decimal_places=2, help_text='Nilai emas = gram x harga per gram. Dipotong dari balance_hold.')
    printing_fee = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'), help_text='Biaya cetak = gram x tarif per gram. Dipotong dari balance_deposit.')
    shipping_cost = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'), help_text='Ongkir flat. Dipotong dari balance_deposit.')
    total_fee = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'), help_text='Total biaya = biaya cetak + ongkir. Dipotong dari balance_deposit.')

    # Alamat pengiriman (snapshot dari UserAddress saat swap)
    address = models.ForeignKey(
        'accounts.UserAddress',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gold_orders',
    )
    recipient_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    address_details = models.TextField()
    house_number = models.CharField(max_length=50, blank=True, null=True)

    tracking_number = models.CharField(max_length=100, blank=True, default='', help_text='Nomor resi pengiriman (diisi admin).')
    notes = models.TextField(blank=True, default='', help_text='Catatan internal admin.')

    # Transaksi terkait
    transaction = models.ForeignKey(
        'products.Transaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gold_orders',
        help_text='Transaksi SWAP nilai emas (wallet balance_hold).',
    )
    fee_transaction = models.ForeignKey(
        'products.Transaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gold_fee_orders',
        help_text='Transaksi SWAP biaya cetak + ongkir (wallet balance_deposit).',
    )

    refunded_at = models.DateTimeField(null=True, blank=True, help_text='Waktu saldo dikembalikan karena order dibatalkan.')

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'gold_orders'
        ordering = ['-created_at', '-id']
        verbose_name = 'Gold Order'
        verbose_name_plural = 'Gold Orders'

    def __str__(self):
        return f'GoldOrder #{self.id} user={self.user_id} {self.gram}g ({self.status})'

    @property
    def is_refunded(self):
        return self.refunded_at is not None

    def _status_to_transaction_status(self):
        """Mapping status order -> status Transaction (Transaction tidak punya status SHIPPED)."""
        return {
            'PENDING': 'PENDING',
            'PROCESSING': 'PROCESSING',
            'SHIPPED': 'PROCESSING',
            'COMPLETED': 'COMPLETED',
            'CANCELLED': 'CANCELLED',
        }.get(self.status, 'PENDING')

    def sync_transaction_status(self):
        """Samakan status kedua transaksi SWAP dengan status order."""
        trx_status = self._status_to_transaction_status()
        for trx in (self.transaction, self.fee_transaction):
            if trx is not None and trx.status != trx_status:
                trx.status = trx_status
                trx.save(update_fields=['status'])

    def refund_funds(self):
        """Kembalikan saldo ke wallet asal + catat transaksi refund. Idempotent lewat refunded_at.

        Nilai emas kembali ke balance_hold, biaya cetak + ongkir kembali ke balance_deposit.
        """
        if self.refunded_at is not None:
            return False

        from products.models import Transaction

        user_model = self.user.__class__
        with db_transaction.atomic():
            user = user_model.objects.select_for_update().get(pk=self.user_id)

            gold_value = self.gold_value or Decimal('0.00')
            total_fee = self.total_fee or Decimal('0.00')

            user.balance_hold = (user.balance_hold or Decimal('0.00')) + gold_value
            user.balance_deposit = (user.balance_deposit or Decimal('0.00')) + total_fee
            user.save(update_fields=['balance_hold', 'balance_deposit'])

            ts = timezone.now().strftime('%Y%m%d%H%M%S')
            if gold_value > 0:
                Transaction.objects.create(
                    user=user,
                    type='RETURN',
                    amount=gold_value,
                    description=f'Refund swap emas dibatalkan (Order #{self.id}): nilai emas kembali ke balance_hold',
                    status='COMPLETED',
                    wallet_type='BALANCE_HOLD',
                    trx_id=f'SWR-{ts}-{uuid.uuid4().hex[:6].upper()}',
                )
            if total_fee > 0:
                Transaction.objects.create(
                    user=user,
                    type='RETURN',
                    amount=total_fee,
                    description=f'Refund swap emas dibatalkan (Order #{self.id}): biaya cetak + ongkir kembali ke balance_deposit',
                    status='COMPLETED',
                    wallet_type='BALANCE_DEPOSIT',
                    trx_id=f'SWR-{ts}-{uuid.uuid4().hex[:6].upper()}',
                )

            self.refunded_at = timezone.now()

        return True

    def cancel_and_refund(self):
        """Batalkan order + kembalikan saldo (aman dipanggil berulang)."""
        self.refund_funds()
        self.status = 'CANCELLED'
        self.save(update_fields=['status', 'refunded_at', 'updated_at'])
        self.sync_transaction_status()
        return self

    def set_status(self, new_status):
        """Ubah status order tanpa refund (PENDING/PROCESSING/SHIPPED/COMPLETED)."""
        new_status = (new_status or '').strip().upper()
        if new_status == 'CANCELLED':
            return self.cancel_and_refund()
        if new_status not in ('PENDING', 'PROCESSING', 'SHIPPED', 'COMPLETED'):
            return self
        self.status = new_status
        self.save(update_fields=['status', 'updated_at'])
        self.sync_transaction_status()
        return self
