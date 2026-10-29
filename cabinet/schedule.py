"""Пары из расписания (schedule.gaudi.adam.edu.kg, /api/v1/lessons/?group=…, ключ в SCHEDULE_API_KEY)."""
import datetime as dt

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import translation
from django.utils.translation import gettext as _

LESSON = dt.timedelta(minutes=80)  # пара — 1 час 20 минут
CACHE_SECONDS = 300  # расписание меняется редко, а смотрят его часто


class ScheduleError(Exception):
    """Понятная человеку причина, почему расписания нет."""


def _end(start):
    return (dt.datetime.strptime(start, "%H:%M") + LESSON).strftime("%H:%M")


def group_lessons(group):
    """Пары группы на неделю: [{weekday 1–6, start, end, discipline, lesson_type, lector, classroom, campus, link, notes}]."""
    if not settings.SCHEDULE_API_URL or not settings.SCHEDULE_API_KEY:
        raise ScheduleError(_("Связь с расписанием не настроена."))
    lang = translation.get_language() or settings.LANGUAGE_CODE
    key = "schedule:%s:%s" % (lang, group.casefold())
    lessons = cache.get(key)
    if lessons is None:
        try:
            resp = requests.get(settings.SCHEDULE_API_URL.rstrip("/") + "/api/v1/lessons/",
                                params={"group": group, "lang": lang},
                                headers={"Authorization": "Api-Key %s" % settings.SCHEDULE_API_KEY},
                                timeout=settings.API_TIMEOUT)
        except requests.RequestException:
            raise ScheduleError(_("Расписание сейчас не отвечает. Попробуйте позже."))
        if resp.status_code == 404:
            lessons = []  # группы нет в расписании — показываем «пар нет», а не ошибку
        elif resp.status_code != 200:
            raise ScheduleError(_("Расписание ответило ошибкой %(code)s.") % {"code": resp.status_code})
        else:
            lessons = [dict(x, start=x["time"], end=_end(x["time"])) for x in resp.json()["lessons"]]
        cache.set(key, lessons, CACHE_SECONDS)
    return lessons


def mark_today(lessons, now):
    """Пары одного дня с пометкой: past — прошла, now — идёт, next — следующая."""
    clock = now.strftime("%H:%M")
    out, next_marked = [], False
    for lesson in sorted(lessons, key=lambda x: x["start"]):
        if lesson["end"] <= clock:
            state = "past"
        elif lesson["start"] <= clock:
            state = "now"
        elif not next_marked:
            state, next_marked = "next", True
        else:
            state = ""
        out.append(dict(lesson, state=state))
    return out
