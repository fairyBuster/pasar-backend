
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
U = get_user_model()
u = U.objects.get(username="abdul")
tok = str(RefreshToken.for_user(u).access_token)
open(r"D:\\webbarubackend\\web-day-backend\\_tmp_token.txt","w").write(tok)
print("TOKEN_LEN", len(tok))
print("USER", u.username, u.full_name, u.balance, u.balance_deposit)
