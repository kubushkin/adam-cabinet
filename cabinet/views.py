"""
Вход и выход через Keycloak, главная страница кабинета.

В сессии хранится только «кто вошёл»: {"kind": "student"|"staff", "id": ID в Гауди, "name": …}
и id_token (нужен Keycloak при выходе). Всё остальное кабинет каждый раз берёт из Гауди.
"""
from functools import wraps
from urllib.parse import urlencode

from authlib.integrations.base_client import OAuthError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import gaudi, oidc


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
    request.session.cycle_key()  # новая сессия после входа
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


@login_required
def home(request):
    who = request.session["who"]
    context = {"profile": None, "error": None}
    try:
        context["profile"] = gaudi.profile(who["kind"], who["id"])
    except gaudi.GaudiError as exc:
        context["error"] = str(exc)
    return render(request, "cabinet/home.html", context)
