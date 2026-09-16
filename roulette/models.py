from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class RouletteSettings(models.Model):
    is_active = models.BooleanField(default=True, help_text="Jika OFF, fitur roulette tidak bisa dipakai user.")
    grant_tickets_from_level1_purchase = models.BooleanField(
        default=True,
        help_text="Jika ON, upline mendapat tiket saat downline level-1 membeli produk.",
    )
    tickets_per_level1_purchase = models.PositiveIntegerField(
        default=1,
        help_text="Jumlah tiket yang didapat upline saat downline level-1 membeli produk.",
    )
    grant_tickets_from_self_deposit = models.BooleanField(
        default=False,
        help_text="Jika ON, user mendapat tiket saat depositnya berstatus COMPLETED.",
    )
    tickets_per_completed_deposit = models.PositiveIntegerField(
        default=0,
        help_text="Jumlah tiket yang didapat user untuk setiap deposit COMPLETED (jika fitur deposit diaktifkan). "
        "Jika 'Nominal kelipatan tiket deposit' diisi, ini berarti tiket per kelipatan (contoh: kelipatan 10rb & 1 = tiap 10rb dapat 1 tiket).",
    )
    min_deposit_amount_for_tickets = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text="Minimum amount deposit agar dapat tiket (0 = tanpa minimum).",
    )
    deposit_ticket_multiple_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text="Nominal kelipatan untuk tiket deposit (contoh: 10000). Tiket = floor(deposit / kelipatan) x tiket per deposit. "
        "Contoh: kelipatan 10rb & 1 tiket → deposit 20rb = 2 tiket, 18rb/15rb = 1 tiket. Isi 0 = tanpa kelipatan (flat per deposit).",
    )
    ticket_cost = models.PositiveIntegerField(
        default=1,
        help_text="Biaya tiket untuk 1x spin.",
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "roulette_settings"
        verbose_name = "Roulette Settings"
        verbose_name_plural = "Roulette Settings"

    def __str__(self):
        return f"RouletteSettings(active={self.is_active})"


class RoulettePrize(models.Model):
    PRIZE_TYPE_CHOICES = [
        ("BALANCE", "Balance"),
        ("BALANCE_DEPOSIT", "Balance Deposit"),
        ("NONE", "None"),
    ]

    name = models.CharField(max_length=120)
    image = models.ImageField(upload_to='roulette/', blank=True, null=True, help_text='Gambar hadiah roulette')
    description = models.TextField(blank=True)
    prize_type = models.CharField(
        max_length=20,
        choices=PRIZE_TYPE_CHOICES,
        default="BALANCE",
        help_text="BALANCE/BALANCE_DEPOSIT akan mengkredit saldo user. NONE berarti zonk (tanpa hadiah).",
    )
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text="Jumlah hadiah. Jika prize_type=NONE, nilai ini diabaikan.",
    )
    weight = models.PositiveIntegerField(
        default=0,
        help_text="Bobot peluang menang. Peluang = weight / total_weight. Contoh: zonk=90, Rp1000=10.",
    )
    is_active = models.BooleanField(default=True, help_text="Jika OFF, hadiah tidak ikut undian.")
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Urutan tampilan hadiah di aplikasi (lebih kecil tampil lebih dulu).",
    )
    points_cost = models.PositiveIntegerField(
        default=0,
        help_text="Harga poin/tiket untuk tukar langsung hadiah ini (0 = tidak bisa ditukar langsung).",
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "roulette_prizes"
        ordering = ["sort_order", "id"]
        verbose_name = "Roulette Prize"
        verbose_name_plural = "Roulette Prizes"

    def __str__(self):
        return f"{self.name} ({self.prize_type})"

    def clean(self):
        super().clean()
        if self.prize_type == "NONE":
            return
        if (self.amount is None) or (Decimal(str(self.amount)) <= Decimal("0.00")):
            raise ValidationError({"amount": "amount harus > 0 jika prize_type bukan NONE."})


class RouletteTicketWallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="roulette_wallet")
    balance = models.PositiveIntegerField(default=0, help_text="Jumlah tiket roulette milik user.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "roulette_ticket_wallets"
        verbose_name = "Roulette Ticket Wallet"
        verbose_name_plural = "Roulette Ticket Wallets"

    def __str__(self):
        return f"{self.user_id} ({self.balance})"


class RouletteTicketLedger(models.Model):
    REASON_CHOICES = [
        ("LEVEL1_PURCHASE", "Level 1 Purchase"),
        ("SELF_DEPOSIT", "Self Deposit"),
        ("SPIN_COST", "Spin Cost"),
        ("REDEEM", "Redeem Prize"),
        ("ADMIN_ADJUST", "Admin Adjust"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="roulette_ticket_ledgers")
    delta = models.IntegerField(help_text="Perubahan tiket (+ masuk, - keluar).")
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    source_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roulette_ticket_sources",
    )
    source_transaction = models.ForeignKey(
        "products.Transaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roulette_ticket_ledgers",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "roulette_ticket_ledgers"
        ordering = ["-created_at", "-id"]
        verbose_name = "Roulette Ticket Ledger"
        verbose_name_plural = "Roulette Ticket Ledgers"
        constraints = [
            models.UniqueConstraint(
                fields=["source_transaction"],
                condition=Q(reason="LEVEL1_PURCHASE"),
                name="uniq_roulette_ticket_source_tx_level1",
            ),
            models.UniqueConstraint(
                fields=["source_transaction"],
                condition=Q(reason="SELF_DEPOSIT"),
                name="uniq_roulette_ticket_source_tx_self_deposit",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} {self.delta} ({self.reason})"


class RouletteSpin(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="roulette_spins")
    prize = models.ForeignKey(RoulettePrize, on_delete=models.SET_NULL, null=True, blank=True, related_name="spins")
    prize_type = models.CharField(max_length=20, default="NONE")
    prize_amount = models.DecimalField(max_digits=15, decimal_places=2, default="0.00")
    transaction = models.ForeignKey(
        "products.Transaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roulette_spins",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "roulette_spins"
        ordering = ["-created_at", "-id"]
        verbose_name = "Roulette Spin"
        verbose_name_plural = "Roulette Spins"

    def __str__(self):
        return f"{self.user_id} {self.prize_type} {self.prize_amount}"


class RouletteRedemption(models.Model):
    """Catatan penukaran poin/tiket roulette langsung ke hadiah (tanpa spin)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="roulette_redemptions")
    prize = models.ForeignKey(RoulettePrize, on_delete=models.SET_NULL, null=True, blank=True, related_name="redemptions")
    prize_type = models.CharField(max_length=20, default="NONE")
    prize_amount = models.DecimalField(max_digits=15, decimal_places=2, default="0.00")
    points_spent = models.PositiveIntegerField(default=0, help_text="Jumlah poin/tiket yang dipakai.")
    transaction = models.ForeignKey(
        "products.Transaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roulette_redemptions",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "roulette_redemptions"
        ordering = ["-created_at", "-id"]
        verbose_name = "Redeem Roulette"
        verbose_name_plural = "Redeem Roulette"

    def __str__(self):
        return f"{self.user_id} {self.prize_id} (-{self.points_spent})"
