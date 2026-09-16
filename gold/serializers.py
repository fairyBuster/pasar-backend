from rest_framework import serializers

from .models import GoldOrder


class GoldSwapRequestSerializer(serializers.Serializer):
    """Request tukar balance_hold menjadi emas."""

    gram = serializers.DecimalField(
        max_digits=12,
        decimal_places=4,
        error_messages={
            'required': 'Berat emas (gram) wajib diisi.',
            'invalid': 'Berat emas harus berupa angka (contoh: 0.5).',
            'max_digits': 'Berat emas terlalu besar.',
            'max_decimal_places': 'Berat emas maksimal 4 angka desimal (contoh: 0.5).',
        },
    )
    address_id = serializers.IntegerField(
        error_messages={
            'required': 'address_id wajib diisi (ambil dari daftar alamat akun).',
            'invalid': 'address_id harus berupa angka.',
        },
    )

    def validate_gram(self, value):
        if value <= 0:
            raise serializers.ValidationError('Berat emas harus lebih dari 0 gram.')
        return value

    def validate_address_id(self, value):
        from accounts.models import UserAddress

        request = self.context.get('request')
        address = None
        if request is not None and getattr(request, 'user', None) is not None and request.user.is_authenticated:
            address = UserAddress.objects.filter(id=value, user=request.user).first()
        if address is None:
            raise serializers.ValidationError('Alamat tidak ditemukan. Gunakan address_id dari daftar alamat akun Anda.')
        self._address = address
        return value

    @property
    def address(self):
        return getattr(self, '_address', None)


class GoldOrderSerializer(serializers.ModelSerializer):
    """Detail order tukar emas."""

    transaction_id = serializers.SerializerMethodField()
    fee_transaction_id = serializers.SerializerMethodField()

    class Meta:
        model = GoldOrder
        fields = [
            'id',
            'status',
            'gram',
            'price_per_gram',
            'gold_value',
            'printing_fee',
            'shipping_cost',
            'total_fee',
            'recipient_name',
            'phone_number',
            'address_details',
            'house_number',
            'tracking_number',
            'transaction_id',
            'fee_transaction_id',
            'refunded_at',
            'created_at',
            'updated_at',
        ]

    def get_transaction_id(self, obj):
        return obj.transaction.trx_id if obj.transaction else None

    def get_fee_transaction_id(self, obj):
        return obj.fee_transaction.trx_id if obj.fee_transaction else None


class GoldSwapResponseSerializer(serializers.Serializer):
    """Response tukar emas berhasil."""

    message = serializers.CharField()
    order = GoldOrderSerializer()
    price_per_gram = serializers.DecimalField(max_digits=15, decimal_places=2)
    price_source = serializers.CharField()
    balance_hold = serializers.DecimalField(max_digits=15, decimal_places=2)
    balance_deposit = serializers.DecimalField(max_digits=15, decimal_places=2)


class GoldInfoResponseSerializer(serializers.Serializer):
    """Info tarif & harga emas saat ini (untuk ditampilkan di frontend)."""

    is_active = serializers.BooleanField()
    price_available = serializers.BooleanField()
    price_per_gram = serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True)
    price_source = serializers.CharField()
    price_updated_at = serializers.DateTimeField(allow_null=True)
    price_usd_per_oz = serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True)
    usd_idr_rate = serializers.DecimalField(max_digits=15, decimal_places=4, allow_null=True)
    printing_fee_per_gram = serializers.DecimalField(max_digits=15, decimal_places=2)
    shipping_cost = serializers.DecimalField(max_digits=15, decimal_places=2)
    balance_hold = serializers.DecimalField(max_digits=15, decimal_places=2)
    balance_deposit = serializers.DecimalField(max_digits=15, decimal_places=2)
