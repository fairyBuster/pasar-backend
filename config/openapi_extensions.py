"""Security schemes for the custom authentication classes.

``drf-spectacular`` ships security scheme extensions only for the stock DRF
authentication classes (and for simplejwt's ``JWTAuthentication``). The
matching is done on the *exact* class, so subclasses such as
``BannedAwareJWTAuthentication`` were left unmatched: the generated schema had
no ``securitySchemes`` at all and Swagger's "Authorize" button never showed up.
Registering the two extensions below fixes that.
"""
from django.conf import settings

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.plumbing import build_bearer_security_scheme_object


class BannedAwareJWTScheme(OpenApiAuthenticationExtension):
    """Bearer access token issued by ``/api/auth/jwt/login/``."""

    target_class = 'accounts.auth.BannedAwareJWTAuthentication'
    name = 'jwtAuth'

    def get_security_definition(self, auto_schema):
        from rest_framework_simplejwt.settings import api_settings

        return build_bearer_security_scheme_object(
            header_name=getattr(api_settings, 'AUTH_HEADER_NAME', 'HTTP_AUTHORIZATION'),
            token_prefix=api_settings.AUTH_HEADER_TYPES[0],
            bearer_format='JWT',
        )


class BannedAwareSessionScheme(OpenApiAuthenticationExtension):
    """Django session cookie, used by the dashboard/admin views."""

    target_class = 'accounts.auth.BannedAwareSessionAuthentication'
    name = 'cookieAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'cookie',
            'name': settings.SESSION_COOKIE_NAME,
        }
