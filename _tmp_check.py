
from django.contrib.auth import get_user_model
from accounts.models import GeneralSetting
U = get_user_model()
print("jumlah user:", U.objects.count())
print("superuser:", list(U.objects.filter(is_superuser=True).values_list("username", flat=True))[:5])
print("sample:", list(U.objects.values_list("username","phone","is_staff","balance","balance_deposit")[:5]))
gs = GeneralSetting.objects.first()
if gs:
    for f in ("otp_enabled","require_withdraw_pin_on_register","auto_login_on_register","whatsapp_check","require_referral_code_on_register","bypass_otp_on_register","active_member_policy"):
        print(f"GS.{f} =", getattr(gs, f, "N/A"))
