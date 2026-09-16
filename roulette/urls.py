from django.urls import path
from .views import RouletteEarnMethodsView, RouletteStatusView, RoulettePointsView, RouletteSpinView, RouletteRedeemView


urlpatterns = [
    path("earn/", RouletteEarnMethodsView.as_view(), name="roulette-earn"),
    path("status/", RouletteStatusView.as_view(), name="roulette-status"),
    path("points/", RoulettePointsView.as_view(), name="roulette-points"),
    path("spin/", RouletteSpinView.as_view(), name="roulette-spin"),
    path("redeem/", RouletteRedeemView.as_view(), name="roulette-redeem"),
]
