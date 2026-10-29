"""Запросы к API Гауди для кабинета (/api/cabinet/…, ключ с именем «cabinet»)."""
import requests
from django.conf import settings
from django.utils.translation import gettext as _


class GaudiError(Exception):
    """Понятная человеку причина, почему данных из Гауди нет."""


class NotFound(GaudiError):
    pass


def _call(method, path, **kwargs):
    if not settings.GAUDI_API_URL or not settings.GAUDI_API_KEY:
        raise GaudiError(_("Связь с Гауди не настроена."))
    try:
        resp = getattr(requests, method)(settings.GAUDI_API_URL.rstrip("/") + path,
                                         headers={"Authorization": "Api-Key %s" % settings.GAUDI_API_KEY},
                                         timeout=settings.API_TIMEOUT, **kwargs)
    except requests.RequestException:
        raise GaudiError(_("Гауди сейчас не отвечает. Попробуйте позже."))
    if resp.status_code == 404:
        raise NotFound(_("Вас нет в Гауди. Обратитесь в учебный отдел."))
    if resp.status_code == 400 and method == "post":
        try:
            detail = resp.json().get("detail")  # причина — текстом из Гауди
        except ValueError:
            detail = None
        raise GaudiError(detail or _("Гауди не принял запрос."))
    if resp.status_code not in (200, 201):
        raise GaudiError(_("Гауди ответил ошибкой %(code)s.") % {"code": resp.status_code})
    return resp.json()


def _get(path, params=None):
    return _call("get", path, params=params)


def profile(kind, person_id):
    """{"holder": {...}, "card": {"url", "issued_at"} | None}"""
    return _get("/api/cabinet/%s/%s/" % (kind, person_id))


def transcript(student_id, lang):
    """{"gpa", "semesters": [{"semestr", "gpa", "items": [{name, credits, control, first_module, …, points, mark, letter}]}]}"""
    return _get("/api/cabinet/student/%s/transcript/" % student_id, {"lang": lang})


def exam_sheets(kind, person_id, lang):
    """Экзаменационные листы: у студента — его запросы, у преподавателя — где он экзаменатор."""
    return _get("/api/cabinet/%s/%s/exam-sheets/" % (kind, person_id), {"lang": lang})["sheets"]


def request_sheet(student_id, row):
    """Запросить экзаменационный лист по строке учебного плана (долг)."""
    return _call("post", "/api/cabinet/student/%s/exam-sheets/" % student_id, json={"row": row})


def grade_sheet(staff_id, sheet_id, scores):
    """Баллы экзаменатора по листу: {"first_module", "second_module", "exam"}."""
    return _call("post", "/api/cabinet/staff/%s/exam-sheets/%s/" % (staff_id, sheet_id), json=scores)
