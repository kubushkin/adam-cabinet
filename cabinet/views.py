"""
Вход и выход через Keycloak, главная страница кабинета.

В сессии хранится «кто вошёл»: {"kind": "student"|"staff", "id": ID в Гауди, "name": …},
id_token (нужен Keycloak при выходе) и ответы Гауди (профиль, оценки) на PROFILE_SECONDS — Гауди отвечает около секунды,
и без этого чувствовалась задержка при каждом переключении вкладок.
"""
import copy
import time
from functools import wraps
from urllib.parse import urlencode

from authlib.integrations.base_client import OAuthError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.dates import WEEKDAYS
from django.utils.translation import get_language, gettext as _
from django.views.decorators.http import require_POST

from . import gaudi, oidc, schedule
from .models import LectorLink

PROFILE_SECONDS = 300  # профиль меняется редко; после выхода и нового входа берётся заново


def who_context(request):
    saved = request.session.get("sheets") or {}
    waiting = [s for s in saved.get("data") or [] if s["status"] == "approved" and not s.get("result")]
    return {"who": request.session.get("who"),
            "flash": request.session.pop("flash", None),   # сообщение после отправки формы — один раз
            "sheets_waiting": len(waiting)}                 # счётчик на вкладке преподавателя


def _flash(request, text, ok=True):
    request.session["flash"] = {"text": str(text), "ok": ok}


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
    request.session["who"] = {"kind": kind, "id": int(login), "name": info.get("name") or login,
                              "roles": oidc.realm_roles(token)}
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


DATES = ("requested_at", "issued_at", "valid_until", "graded_at")


def _with_dates(sheets):
    """Даты листов из JSON (строки) — в datetime, чтобы шаблон показал их по-местному."""
    return [dict(x, **{k: parse_datetime(x[k]) for k in DATES if x.get(k)}) for x in sheets]


def _sheets(request, who):
    """Экзаменационные листы человека; при ошибке Гауди — пустой список, страница всё равно открывается."""
    try:
        return _with_dates(_saved(request, "sheets", lambda: gaudi.exam_sheets(who["kind"], who["id"])))
    except gaudi.GaudiError:
        return []


def _forget(request, *names):
    """После отправки формы — свежие данные из Гауди при следующем показе."""
    for name in list(request.session.keys()):
        if name in names or name.split(":")[0] in names:
            del request.session[name]


def _profile_and_lessons(request):
    """Профиль из Гауди и пары группы студента. Ошибки — текстом, страница всё равно открывается."""
    who = request.session["who"]
    context = {"profile": None, "lessons": None, "errors": []}
    try:
        context["profile"] = _profile(request, who)
    except gaudi.GaudiError as exc:
        context["errors"].append(str(exc))
        return context
    holder = context["profile"]["holder"]
    try:
        if who["kind"] == "student" and holder.get("group"):
            context["lessons"] = schedule.group_lessons(holder["group"])
        elif who["kind"] == "staff":
            lector_ids = _lector_ids(who, holder["full_name"])
            context["lessons"] = schedule.lector_lessons(lector_ids) if lector_ids else None
    except schedule.ScheduleError as exc:
        context["errors"].append(str(exc))
    return context


def _lector_ids(who, full_name):
    """Записи расписания этого преподавателя. Нет связи — ищем по ФИО: ровно одно совпадение, ещё ни с кем
    не связанное, — запоминаем; иначе пусто (свяжет ИО)."""
    ids = list(LectorLink.objects.filter(staff_id=who["id"]).values_list("lector_id", flat=True))
    if ids:
        return ids
    found = [x for x in schedule.lectors() if schedule.same_person(x["name"], full_name)]
    if len(found) == 1:
        link, _created = LectorLink.objects.get_or_create(lector_id=found[0]["id"], defaults={
            "lector_name": found[0]["name"], "staff_id": who["id"], "staff_name": full_name, "auto": True})
        if link.staff_id == who["id"]:
            return [link.lector_id]
    return []


@login_required
def home(request):
    """Сегодня: профиль и пары дня (текущая подсвечена, следующая отмечена)."""
    context = _profile_and_lessons(request)
    if context["profile"]:
        context["sheets"] = [x for x in _sheets(request, request.session["who"]) if x["status"] in ("requested", "approved")]
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
        if context["transcript"]:
            context["transcript"] = copy.deepcopy(context["transcript"])  # копия: в сессии — ответ Гауди как есть
            latest = {}
            for sheet in _sheets(request, who):  # свежие сверху — по каждой дисциплине берём последний запрос
                latest.setdefault(sheet["row"], sheet)
            for sem in context["transcript"]["semesters"]:
                for item in sem["items"]:
                    item["sheet"] = latest.get(item.get("row"))
    return render(request, "cabinet/study.html", context)


@login_required
@require_POST
def request_sheet(request):
    """Студент просит экзаменационный лист по долгу; решение — за учебным отделом в Гауди."""
    who = request.session["who"]
    if who["kind"] != "student":
        raise Http404
    try:
        gaudi.request_sheet(who["id"], int(request.POST.get("row", 0)))
        _flash(request, _("Запрос отправлен в учебный отдел. Лист выдадут после оплаты пересдачи."))
    except (ValueError, gaudi.GaudiError) as exc:
        _flash(request, exc if isinstance(exc, gaudi.GaudiError) else _("Не та строка."), ok=False)
    _forget(request, "sheets")
    return redirect("study")


@login_required
def sheets(request):
    """Преподаватель: экзаменационные листы, где он экзаменатор, и ввод баллов."""
    who = request.session["who"]
    if who["kind"] != "staff":
        raise Http404
    context = {"errors": [], "sheets": []}
    try:
        context["sheets"] = _with_dates(_saved(request, "sheets", lambda: gaudi.exam_sheets("staff", who["id"])))
    except gaudi.GaudiError as exc:
        context["errors"].append(str(exc))
    return render(request, "cabinet/sheets.html", context)


@login_required
@require_POST
def grade_sheet(request, sheet_id):
    who = request.session["who"]
    if who["kind"] != "staff":
        raise Http404
    try:
        scores = {name: int(request.POST.get(name, "")) for name in ("first_module", "second_module", "exam")}
    except ValueError:
        _flash(request, _("Баллы — целые числа."), ok=False)
        return redirect("sheets")
    try:
        gaudi.grade_sheet(who["id"], sheet_id, scores)
        _flash(request, _("Баллы по листу №%(n)s записаны в Гауди.") % {"n": sheet_id})
    except gaudi.GaudiError as exc:
        _flash(request, exc, ok=False)
    _forget(request, "sheets")
    return redirect("sheets")


IO_ROLE = "io"  # роль realm сотрудников: сотрудник информационного отдела


def io_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        who = request.session.get("who") or {}
        if who.get("kind") != "staff" or IO_ROLE not in who.get("roles", []):
            raise Http404
        return view(request, *args, **kwargs)
    return login_required(wrapper)


@io_required
def io_lectors(request):
    """ИО: преподаватели расписания ↔ сотрудники Гауди. Кого кабинет не нашёл по ФИО — связать вручную."""
    if request.method == "POST":
        lector_id = int(request.POST.get("lector") or 0)
        lector = next((x for x in schedule.lectors() if x["id"] == lector_id), None)
        if lector is None:
            raise Http404
        staff_id = request.POST.get("staff", "").strip()
        if not staff_id:
            LectorLink.objects.filter(lector_id=lector_id).delete()
            _flash(request, _("Связь для «%(name)s» снята.") % {"name": lector["name"]})
        elif not staff_id.isdigit():
            _flash(request, _("ID сотрудника — только цифры."), ok=False)
        else:
            try:
                holder = gaudi.profile("staff", int(staff_id))["holder"]
            except gaudi.GaudiError:
                _flash(request, _("Сотрудника с ID %(id)s нет в Гауди.") % {"id": staff_id}, ok=False)
            else:
                LectorLink.objects.update_or_create(lector_id=lector_id, defaults={
                    "lector_name": lector["name"], "staff_id": int(staff_id), "staff_name": holder["full_name"],
                    "auto": False, "linked_by": request.session["who"]["name"]})
                _flash(request, _("«%(lector)s» — это %(staff)s.") % {"lector": lector["name"], "staff": holder["full_name"]})
        return redirect("io-lectors")
    context = {"errors": [], "rows": []}
    try:
        links = {x.lector_id: x for x in LectorLink.objects.all()}
        context["rows"] = [{"lector": x, "link": links.get(x["id"])} for x in schedule.lectors()]
        context["rows"].sort(key=lambda r: (r["link"] is not None, r["lector"]["name"]))  # несвязанные сверху
    except schedule.ScheduleError as exc:
        context["errors"].append(str(exc))
    return render(request, "cabinet/io_lectors.html", context)
