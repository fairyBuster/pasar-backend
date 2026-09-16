from rest_framework import serializers
from .models import RoulettePrize


class RoulettePrizeSerializer(serializers.ModelSerializer):
    probability_percent = serializers.SerializerMethodField()
    image = serializers.ImageField(read_only=True)

    class Meta:
        model = RoulettePrize
        fields = ("id", "name", "image", "description", "prize_type", "amount", "points_cost", "probability_percent")

    def get_probability_percent(self, obj):
        total_weight = self.context.get("total_weight") or 0
        if not total_weight:
            return "0"
        try:
            return str(round((obj.weight / total_weight) * 100, 4))
        except Exception:
            return "0"


class RouletteStatusResponseSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
    ticket_cost = serializers.IntegerField()
    tickets = serializers.IntegerField()
    prizes = RoulettePrizeSerializer(many=True)


class RouletteSpinResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    tickets_before = serializers.IntegerField()
    tickets_after = serializers.IntegerField()
    prize_id = serializers.IntegerField(allow_null=True)
    prize_name = serializers.CharField(allow_null=True)
    prize_type = serializers.CharField()
    prize_amount = serializers.CharField()
    transaction_id = serializers.CharField(allow_null=True)


class RouletteEarnMethodsResponseSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
    grant_tickets_from_level1_purchase = serializers.BooleanField()
    tickets_per_level1_purchase = serializers.IntegerField()
    grant_tickets_from_self_deposit = serializers.BooleanField()
    tickets_per_completed_deposit = serializers.IntegerField()
    min_deposit_amount_for_tickets = serializers.CharField()
    deposit_ticket_multiple_amount = serializers.CharField()
    ticket_cost = serializers.IntegerField()


class RoulettePointsEarnedBreakdownSerializer(serializers.Serializer):
    level1_purchase = serializers.IntegerField()
    self_deposit = serializers.IntegerField()
    admin_adjust = serializers.IntegerField()


class RoulettePointsSpentBreakdownSerializer(serializers.Serializer):
    spin = serializers.IntegerField()
    redeem = serializers.IntegerField()
    admin_adjust = serializers.IntegerField()


class RoulettePointsResponseSerializer(serializers.Serializer):
    tickets = serializers.IntegerField()
    total_earned = serializers.IntegerField()
    total_spent = serializers.IntegerField()
    earned_breakdown = RoulettePointsEarnedBreakdownSerializer()
    spent_breakdown = RoulettePointsSpentBreakdownSerializer()
    ticket_cost = serializers.IntegerField()
    spins_available = serializers.IntegerField(allow_null=True)
    total_spins = serializers.IntegerField()
    total_redeems = serializers.IntegerField()


class RouletteRedeemPrizeSerializer(serializers.ModelSerializer):
    """Katalog hadiah redeem - tanpa data peluang spin (weight/probability)."""

    image = serializers.ImageField(read_only=True)

    class Meta:
        model = RoulettePrize
        fields = ("id", "name", "image", "description", "prize_type", "amount", "points_cost")


class RouletteRedeemCatalogResponseSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
    tickets = serializers.IntegerField()
    prizes = RouletteRedeemPrizeSerializer(many=True)


class RouletteRedeemRequestSerializer(serializers.Serializer):
    prize_id = serializers.IntegerField(help_text="ID hadiah yang mau ditukar (dari katalog roulette).")


class RouletteRedeemResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    tickets_before = serializers.IntegerField()
    tickets_after = serializers.IntegerField()
    prize_id = serializers.IntegerField(allow_null=True)
    prize_name = serializers.CharField(allow_null=True)
    prize_type = serializers.CharField()
    prize_amount = serializers.CharField()
    points_spent = serializers.IntegerField()
    transaction_id = serializers.CharField(allow_null=True)
    redemption_id = serializers.IntegerField()
