"""Запросы к API Гауди для кабинета (/api/cabinet/…, ключ с именем «cabinet»)."""
import requests
from django.conf import settings
from django.utils.translation import gettext as _


class GaudiError(Exception):
    """Понятная человеку причина, почему данных из Гауди нет."""


class NotFound(GaudiError):
    pass


def _get(path, params=None):
    if not settings.GAUDI_API_URL or not settings.GAUDI_API_KEY:
        raise GaudiError(_("Связь с Гауди не настроена."))
    try:
        resp = requests.get(settings.GAUDI_API_URL.rstrip("/") + path, params=params,
                            headers={"Authorization": "Api-Key %s" % settings.GAUDI_API_KEY},
                            timeout=settings.API_TIMEOUT)
    except requests.RequestException:
        raise GaudiError(_("Гауди сейчас не отвечает. Попробуйте позже."))
    if resp.status_code == 404:
        raise NotFound(_("Вас нет в Гауди. Обратитесь в учебный отдел."))
    if resp.status_code != 200:
        raise GaudiError(_("Гауди ответил ошибкой %(code)s.") % {"code": resp.status_code})
    return resp.json()


def profile(kind, person_id):
    """{"holder": {...}, "card": {"url", "issued_at"} | None}"""
    return _get("/api/cabinet/%s/%s/" % (kind, person_id))
