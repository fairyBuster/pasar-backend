from django.urls import path

from .views import GoldInfoView, GoldOrderDetailView, GoldSwapView


urlpatterns = [
    path('swap/', GoldSwapView.as_view(), name='gold-swap'),
    path('info/', GoldInfoView.as_view(), name='gold-info'),
    path('orders/<int:pk>/', GoldOrderDetailView.as_view(), name='gold-order-detail'),
]
