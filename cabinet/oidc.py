"""
Вход через Keycloak (OpenID Connect, authorization code). Логин в Keycloak — ID человека в Гауди.

Два realm: студенты и преподаватели (ID студентов и сотрудников в Гауди пересекаются,
поэтому в одном realm их логины столкнулись бы). Подпись токена и nonce проверяет authlib.
"""
from authlib.integrations.django_client import OAuth
from django.conf import settings

KINDS = ("student", "staff")
_oauth = OAuth()


def enabled(kind):
    return bool(settings.OIDC.get(kind, {}).get("issuer"))


def client(kind):
    """Клиент OpenID Connect для realm студентов или преподавателей."""
    found = _oauth.create_client(kind)
    if found is None:
        conf = settings.OIDC[kind]
        found = _oauth.register(
            name=kind,
            server_metadata_url=conf["issuer"].rstrip("/") + "/.well-known/openid-configuration",
            client_id=conf["client_id"],
            client_secret=conf["client_secret"],
            client_kwargs={"scope": "openid profile"},
        )
    return found
