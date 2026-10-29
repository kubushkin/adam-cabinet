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


def _api(path, params, key):
    """GET к API расписания с кэшем на CACHE_SECONDS. 404 → None."""
    if not settings.SCHEDULE_API_URL or not settings.SCHEDULE_API_KEY:
        raise ScheduleError(_("Связь с расписанием не настроена."))
    found = cache.get(key)
    if found is None:
        try:
            resp = requests.get(settings.SCHEDULE_API_URL.rstrip("/") + path, params=params,
                                headers={"Authorization": "Api-Key %s" % settings.SCHEDULE_API_KEY},
                                timeout=settings.API_TIMEOUT)
        except requests.RequestException:
            raise ScheduleError(_("Расписание сейчас не отвечает. Попробуйте позже."))
        if resp.status_code == 404:
            found = {}
        elif resp.status_code != 200:
            raise ScheduleError(_("Расписание ответило ошибкой %(code)s.") % {"code": resp.status_code})
        else:
            found = resp.json()
        cache.set(key, found, CACHE_SECONDS)
    return found or None


def _lessons(data):
    return [dict(x, start=x["time"], end=_end(x["time"])) for x in data["lessons"]] if data else []


def group_lessons(group):
    """Пары группы на неделю: [{weekday 1–6, start, end, discipline, lesson_type, lector, classroom, campus, link, notes}].
    Группы нет в расписании — пустой список («пар нет»), а не ошибка."""
    lang = translation.get_language() or settings.LANGUAGE_CODE
    return _lessons(_api("/api/v1/lessons/", {"group": group, "lang": lang}, "schedule:%s:%s" % (lang, group.casefold())))


def lector_lessons(lector_ids):
    """Пары преподавателя на неделю (у одного человека в расписании может быть несколько записей)."""
    lang = translation.get_language() or settings.LANGUAGE_CODE
    out = []
    for lector_id in lector_ids:
        out += _lessons(_api("/api/v1/lessons/", {"lector": lector_id, "lang": lang},
                             "schedule:%s:lector:%s" % (lang, lector_id)))
    return sorted(out, key=lambda x: (x["weekday"] or 99, x["start"]))


def lectors():
    """Преподаватели из расписания: [{id, name, regalia}] (имена — по-русски)."""
    data = _api("/api/v1/lectors/", {"lang": "ru"}, "schedule:lectors")
    return data["lectors"] if data else []


def _words(name):
    return [w.strip(".") for w in name.casefold().replace("ё", "е").replace(".", ". ").split() if w.strip(".")]


def same_person(lector_name, full_name):
    """«Асанов Б. К.» или «Асанов Бакыт» в расписании ↔ «Асанов Бакыт Кубатович» в Гауди:
    фамилия совпадает, остальные слова расписания — начало имени и отчества."""
    short, full = _words(lector_name), _words(full_name)
    if len(short) < 2 or len(short) > len(full) or short[0] != full[0]:
        return False
    return all(f.startswith(w) for w, f in zip(short[1:], full[1:]))


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
