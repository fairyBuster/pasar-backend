from django.contrib import admin, messages
from django.db import transaction as db_transaction
from django.utils.html import format_html

from .models import GoldOrder, GoldSettings


@admin.register(GoldSettings)
class GoldSettingsAdmin(admin.ModelAdmin):
    """Menu pengaturan tukar emas: ongkir, biaya cetak per gram, on/off fitur."""

    list_display = (
        'id', 'is_active', 'printing_fee_per_gram', 'shipping_cost',
        'price_cache_minutes', 'last_price_per_gram', 'last_price_updated_at', 'updated_at',
    )
    list_filter = ('is_active',)
    readonly_fields = (
        'last_price_per_gram', 'last_price_usd_per_oz', 'last_usd_idr_rate',
        'last_price_updated_at', 'created_at', 'updated_at',
    )
    fieldsets = (
        ('Status Fitur', {
            'fields': ('is_active', 'price_cache_minutes'),
            'description': 'Jika ON, user bisa tukar balance_hold menjadi emas lewat POST /api/gold/swap/.',
        }),
        ('Tarif', {
            'fields': ('printing_fee_per_gram', 'shipping_cost'),
            'description': (
                'Nilai emas (gram x harga emas real-time) dipotong dari balance_hold. '
                'Biaya cetak (gram x tarif per gram) + ongkir flat dipotong dari balance_deposit.'
            ),
        }),
        ('Harga Emas Terakhir (otomatis)', {
            'fields': ('last_price_per_gram', 'last_price_usd_per_oz', 'last_usd_idr_rate', 'last_price_updated_at'),
            'description': 'Diisi otomatis oleh sistem dari API harga emas. Gunakan action "Ambil ulang harga emas" untuk refresh manual.',
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    actions = ('refresh_gold_price',)

    def has_add_permission(self, request):
        # Cukup satu konfigurasi, kalau sudah ada maka tidak bisa tambah baru
        return not GoldSettings.objects.exists()

    @admin.action(description='Ambil ulang harga emas real-time sekarang')
    def refresh_gold_price(self, request, queryset):
        from .services import get_gold_price_per_gram

        try:
            settings_obj, price, source = get_gold_price_per_gram(force_refresh=True)
            self.message_user(
                request,
                f'Harga emas diperbarui: Rp {price} /gram (sumber: {source}).',
                messages.SUCCESS,
            )
        except Exception as exc:
            self.message_user(request, f'Gagal ambil harga emas: {exc}', messages.ERROR)


@admin.register(GoldOrder)
class GoldOrderAdmin(admin.ModelAdmin):
    """Kelola order tukar emas + ubah status (SHIPPED isi resi, CANCELLED otomatis refund)."""

    list_display = (
        'id', 'user_display', 'gram', 'gold_value_display', 'fee_display',
        'status_display', 'tracking_number', 'refunded_display', 'created_at',
    )
    list_filter = ('status', 'created_at')
    search_fields = ('id', 'user__username', 'user__phone', 'tracking_number', 'recipient_name', 'phone_number')
    readonly_fields = (
        'user', 'gram', 'price_per_gram', 'gold_value', 'printing_fee', 'shipping_cost',
        'total_fee', 'address', 'recipient_name', 'phone_number', 'address_details',
        'house_number', 'transaction', 'fee_transaction', 'refunded_at', 'created_at', 'updated_at',
    )
    fieldsets = (
        ('Order', {
            'fields': ('user', 'status', 'gram', 'price_per_gram', 'gold_value', 'created_at', 'updated_at'),
        }),
        ('Biaya (dari balance_deposit)', {
            'fields': ('printing_fee', 'shipping_cost', 'total_fee'),
        }),
        ('Pengiriman', {
            'fields': ('recipient_name', 'phone_number', 'address_details', 'house_number', 'tracking_number', 'notes'),
            'description': 'Isi nomor resi saat status diubah ke SHIPPED.',
        }),
        ('Transaksi Terkait', {
            'fields': ('transaction', 'fee_transaction', 'refunded_at'),
        }),
    )
    actions = ('mark_processing', 'mark_shipped', 'mark_completed', 'cancel_and_refund_orders')

    def user_display(self, obj):
        return obj.user.phone or obj.user.username
    user_display.short_description = 'User'

    def gold_value_display(self, obj):
        return format_html(
            '<b>{}</b><div style="color:#6c757d;">hold -{}</div>',
            obj.gold_value, '',
        )
    gold_value_display.short_description = 'Nilai Emas'

    def fee_display(self, obj):
        return format_html(
            '<b>{}</b><div style="color:#6c757d;">cetak {} + ongkir {}</div>',
            obj.total_fee, obj.printing_fee, obj.shipping_cost,
        )
    fee_display.short_description = 'Total Biaya'

    def status_display(self, obj):
        colors = {
            'PENDING': '#ff9800',
            'PROCESSING': '#2196f3',
            'SHIPPED': '#9c27b0',
            'COMPLETED': '#28a745',
            'CANCELLED': '#dc3545',
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, '#6c757d'), obj.status,
        )
    status_display.short_description = 'Status'

    def refunded_display(self, obj):
        if obj.refunded_at:
            return format_html('<span style="color: #dc3545;">REFUNDED</span>')
        return '-'
    refunded_display.short_description = 'Refund'

    def save_model(self, request, obj, form, change):
        new_status = (obj.status or '').strip().upper()
        with db_transaction.atomic():
            if new_status == 'CANCELLED' and obj.refunded_at is None:
                obj.refund_funds()
                self.message_user(
                    request,
                    f'Order #{obj.pk or "baru"}: saldo dikembalikan ke balance_hold & balance_deposit user.',
                    messages.WARNING,
                )
            super().save_model(request, obj, form, change)
            if change:
                obj.sync_transaction_status()

    def _bulk_set_status(self, request, queryset, new_status):
        updated = 0
        for order in queryset:
            if order.status == new_status:
                continue
            order.set_status(new_status)
            updated += 1
        self.message_user(request, f'{updated} order diubah ke status {new_status}.', messages.SUCCESS)

    @admin.action(description='Tandai PROCESSING (sedang diproses)')
    def mark_processing(self, request, queryset):
        self._bulk_set_status(request, queryset, 'PROCESSING')

    @admin.action(description='Tandai SHIPPED (isi resi dulu di form order)')
    def mark_shipped(self, request, queryset):
        self._bulk_set_status(request, queryset, 'SHIPPED')

    @admin.action(description='Tandai COMPLETED (selesai)')
    def mark_completed(self, request, queryset):
        self._bulk_set_status(request, queryset, 'COMPLETED')

    @admin.action(description='CANCELLED + kembalikan saldo ke user')
    def cancel_and_refund_orders(self, request, queryset):
        refunded = 0
        for order in queryset:
            if order.refunded_at is not None:
                continue
            order.cancel_and_refund()
            refunded += 1
        self.message_user(
            request,
            f'{refunded} order dibatalkan & saldo dikembalikan (nilai emas -> balance_hold, biaya -> balance_deposit).',
            messages.WARNING,
        )
