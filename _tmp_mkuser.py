
from django.contrib.auth import get_user_model
from decimal import Decimal
U = get_user_model()
u, created = U.objects.get_or_create(username="zz_smoketest", defaults=dict(
    email="zz_smoketest@example.com", phone="085100009999", full_name="Smoke Test",
    balance=Decimal("1234567.00"), balance_deposit=Decimal("7654321.00"),
    is_enabled=True, is_account_non_expired=True, is_account_non_locked=True,
    is_credentials_non_expired=True, banned_status=False,
))
u.set_password("Smoketest123")
u.save()
print("CREATED" if created else "EXISTED", "|", u.username, u.phone, "| enabled:", u.is_enabled)
