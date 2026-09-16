from django.contrib import admin

from .models import RedeemPrize, RedeemHistory


@admin.register(RedeemPrize)
class RedeemPrizeAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "prize_type", "amount", "points_cost", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active", "prize_type")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Hadiah (Tukar Poin Langsung)",
            {
                "fields": ("name", "image", "description", "prize_type", "amount"),
                "description": "Hadiah untuk fitur REDEEM: ditukar pakai poin langsung tanpa spin. "
                "BALANCE/BALANCE_DEPOSIT dikreditkan otomatis; NONE = hadiah fisik, diproses manual dari menu Redeem history.",
            },
        ),
        (
            "Harga Poin",
            {
                "fields": ("points_cost", "is_active", "sort_order"),
                "description": "points_cost = harga poin/tiket untuk menukar hadiah ini. "
                "Isi lebih dari 0 supaya hadiah muncul di katalog redeem user.",
            },
        ),
        ("Waktu", {"fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).filter(points_cost__gt=0)


@admin.register(RedeemHistory)
class RedeemHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "prize", "prize_type", "prize_amount", "points_spent", "transaction", "created_at")
    list_filter = ("prize_type", "created_at")
    search_fields = ("user__phone", "transaction__trx_id")
    readonly_fields = ("user", "prize", "prize_type", "prize_amount", "points_spent", "transaction", "created_at")
    autocomplete_fields = ("user", "prize", "transaction")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
