"""
Вход через Keycloak (OpenID Connect, authorization code). Логин в Keycloak — ID человека в Гауди.

Два realm: студенты и преподаватели (ID студентов и сотрудников в Гауди пересекаются,
поэтому в одном realm их логины столкнулись бы). Подпись токена и nonce проверяет authlib.
"""
import base64
import json

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


def realm_roles(token):
    """Роли realm (ППС, ИО, куратор…) из access token Keycloak: realm_access.roles.

    Токен кабинет получил сам, напрямую от Keycloak по HTTPS (обмен кода), поэтому подпись здесь
    не перепроверяем — только читаем содержимое. Не похоже на JWT — ролей нет.
    """
    try:
        payload = str(token.get("access_token", "")).split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return sorted(str(r) for r in data.get("realm_access", {}).get("roles", []))
    except (IndexError, ValueError, AttributeError):
        return []
