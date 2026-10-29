"""
Вход и выход через Keycloak, главная страница кабинета.

В сессии хранится «кто вошёл»: {"kind": "student"|"staff", "id": ID в Гауди, "name": …},
id_token (нужен Keycloak при выходе) и ответы Гауди (профиль, оценки) на PROFILE_SECONDS — Гауди отвечает около секунды,
и без этого чувствовалась задержка при каждом переключении вкладок.
"""
import time
from functools import wraps
from urllib.parse import urlencode

from authlib.integrations.base_client import OAuthError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dates import WEEKDAYS
from django.utils.translation import get_language, gettext as _
from django.views.decorators.http import require_POST

from . import gaudi, oidc, schedule

PROFILE_SECONDS = 300  # профиль меняется редко; после выхода и нового входа берётся заново


def who_context(request):
    return {"who": request.session.get("who")}


def login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.session.get("who"):
            return redirect("login")
        return view(request, *args, **kwargs)
    return wrapper


def login_page(request, error=None):
    if request.session.get("who"):
        return redirect("home")
    kinds = [kind for kind in oidc.KINDS if oidc.enabled(kind)]
    return render(request, "cabinet/login.html", {"kinds": kinds, "error": error})


def login_start(request, kind):
    if kind not in oidc.KINDS or not oidc.enabled(kind):
        raise Http404
    callback = request.build_absolute_uri(reverse("login-callback", args=[kind]))
    return oidc.client(kind).authorize_redirect(request, callback)


def login_callback(request, kind):
    if kind not in oidc.KINDS or not oidc.enabled(kind):
        raise Http404
    try:
        token = oidc.client(kind).authorize_access_token(request)
    except OAuthError:
        return login_page(request, _("Вход не завершён. Попробуйте ещё раз."))
    info = token.get("userinfo") or {}
    login = str(info.get("preferred_username", "")).strip()
    if not login.isdigit():
        # логин в Keycloak должен быть ID в Гауди — иначе непонятно, чьи данные показывать
        return login_page(request, _("Логин %(login)s не похож на ID в Гауди. Обратитесь в ИО.") % {"login": login})
    request.session.flush()  # новая пустая сессия после входа: ничего от прежнего пользователя
    request.session["who"] = {"kind": kind, "id": int(login), "name": info.get("name") or login}
    request.session["id_token"] = token.get("id_token", "")
    return redirect("home")


@require_POST
def logout(request):
    who = request.session.get("who") or {}
    id_token = request.session.get("id_token", "")
    request.session.flush()
    kind = who.get("kind")
    if kind not in oidc.KINDS or not oidc.enabled(kind):
        return redirect("login")
    try:
        end = oidc.client(kind).load_server_metadata().get("end_session_endpoint")
    except Exception:  # noqa: BLE001 — Keycloak недоступен: из кабинета всё равно вышли
        end = None
    if not end:
        return redirect("login")
    params = {"post_logout_redirect_uri": request.build_absolute_uri(reverse("login")),
              "client_id": oidc.client(kind).client_id}
    if id_token:
        params["id_token_hint"] = id_token
    return redirect(end + "?" + urlencode(params))


def _saved(request, name, fetch):
    """Ответ Гауди из сессии, если ему меньше PROFILE_SECONDS; иначе — свежий (fetch) и запомнить."""
    saved = request.session.get(name)
    if saved and time.time() - saved["at"] < PROFILE_SECONDS:
        return saved["data"]
    data = fetch()
    request.session[name] = {"at": time.time(), "data": data}
    return data


def _profile(request, who):
    return _saved(request, "profile", lambda: gaudi.profile(who["kind"], who["id"]))


def _profile_and_lessons(request):
    """Профиль из Гауди и пары группы студента. Ошибки — текстом, страница всё равно открывается."""
    who = request.session["who"]
    context = {"profile": None, "lessons": None, "errors": []}
    try:
        context["profile"] = _profile(request, who)
    except gaudi.GaudiError as exc:
        context["errors"].append(str(exc))
        return context
    group = context["profile"]["holder"].get("group")
    if who["kind"] == "student" and group:
        try:
            context["lessons"] = schedule.group_lessons(group)
        except schedule.ScheduleError as exc:
            context["errors"].append(str(exc))
    return context


@login_required
def home(request):
    """Сегодня: профиль и пары дня (текущая подсвечена, следующая отмечена)."""
    context = _profile_and_lessons(request)
    now = timezone.localtime()
    day = now.isoweekday()
    context.update(today=now.date(), weekday=WEEKDAYS[day - 1])
    if context["lessons"] is not None:
        context["today_lessons"] = schedule.mark_today([x for x in context["lessons"] if x["weekday"] == day], now)
    return render(request, "cabinet/home.html", context)


@login_required
def week(request):
    """Расписание на неделю: понедельник–суббота, сегодняшний день отмечен."""
    context = _profile_and_lessons(request)
    now = timezone.localtime()
    if context["lessons"] is not None:
        context["days"] = []
        for n in range(1, 7):
            lessons = sorted((x for x in context["lessons"] if x["weekday"] == n), key=lambda x: x["start"])
            if n == now.isoweekday():
                lessons = schedule.mark_today(lessons, now)  # «идёт» и «следующая» — только сегодня
            context["days"].append({"title": WEEKDAYS[n - 1], "today": n == now.isoweekday(), "lessons": lessons})
    return render(request, "cabinet/week.html", context)


@login_required
def study(request):
    """Учёба: оценки по семестрам из Гауди (баллы модулей, итог, буква и GPA — как в транскрипте)."""
    who = request.session["who"]
    context = {"transcript": None, "errors": []}
    if who["kind"] == "student":
        try:
            lang = get_language()
            context["transcript"] = _saved(request, "transcript:" + lang, lambda: gaudi.transcript(who["id"], lang))
        except gaudi.GaudiError as exc:
            context["errors"].append(str(exc))
    return render(request, "cabinet/study.html", context)
