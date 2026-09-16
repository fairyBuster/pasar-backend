from roulette.models import RoulettePrize, RouletteRedemption


class RedeemPrize(RoulettePrize):
    """Proxy katalog hadiah untuk fitur REDEEM (tukar poin langsung, tanpa spin)."""

    class Meta:
        proxy = True
        ordering = ["points_cost", "sort_order", "id"]
        verbose_name = "Redeem Prize"
        verbose_name_plural = "Redeem Prize Catalog"


class RedeemHistory(RouletteRedemption):
    """Proxy riwayat penukaran poin menjadi hadiah (fitur REDEEM)."""

    class Meta:
        proxy = True
        verbose_name = "Redeem History"
        verbose_name_plural = "Redeem History"
