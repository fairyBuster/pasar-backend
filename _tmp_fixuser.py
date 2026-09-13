
from django.contrib.auth import get_user_model
from accounts.utils import normalize_phone
U = get_user_model()
p = normalize_phone("085100009999")
print("NORM:", p, "| USERNAME_FIELD:", U.USERNAME_FIELD)
u = U.objects.get(username="zz_smoketest")
u.phone = p
u.save(update_fields=["phone"])
print("OK phone now:", u.phone)
