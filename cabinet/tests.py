from unittest import mock

from authlib.integrations.base_client import OAuthError
from django.http import HttpResponseRedirect
from django.test import TestCase, override_settings

OIDC = {
    "student": {"issuer": "https://auth.test/realms/student", "client_id": "cabinet", "client_secret": "s"},
    "staff": {"issuer": "", "client_id": "cabinet", "client_secret": ""},
}
PROFILE = {"holder": {"type": "student", "id": 20231001, "full_name": "Асанова Айпери Бакытовна", "kind": "Студентка",
                      "group": "ИСТ-5-26", "course": 1, "department": "Информационных технологий", "position": None,
                      "active": True, "state": "Обучение", "photo_url": None, "has_active_card": False},
           "card": None}


class FakeClient:
    """Вместо Keycloak: что вернул бы клиент OpenID Connect."""
    client_id = "cabinet"

    def __init__(self, token=None, error=False):
        self.token, self.error = token, error

    def authorize_redirect(self, request, redirect_uri):
        self.redirect_uri = redirect_uri
        return HttpResponseRedirect("https://auth.test/realms/student/auth?redirect_uri=" + redirect_uri)

    def authorize_access_token(self, request):
        if self.error:
            raise OAuthError("access_denied")
        return self.token

    def load_server_metadata(self):
        return {"end_session_endpoint": "https://auth.test/realms/student/logout"}


def token(login="20231001"):
    return {"id_token": "idt", "userinfo": {"preferred_username": login, "name": "Айпери Асанова"}}


def fake_response(status, data=None):
    resp = mock.Mock(status_code=status)
    resp.json.return_value = data
    return resp


@override_settings(OIDC=OIDC, GAUDI_API_URL="http://gaudi.test", GAUDI_API_KEY="k.k")
class LoginTestCase(TestCase):

    def login(self, client_obj):
        with mock.patch("cabinet.oidc.client", return_value=client_obj):
            return self.client.get("/auth/student/callback/")

    def test_login_page_shows_enabled_realms_only(self):
        page = self.client.get("/login/").content.decode()
        self.assertIn("/login/student/", page)
        self.assertNotIn("/login/staff/", page)  # realm преподавателей не настроен — кнопки нет
        self.assertEqual(self.client.get("/login/staff/").status_code, 404)
        self.assertRedirects(self.client.get("/"), "/login/", fetch_redirect_response=False)

    def test_redirect_to_keycloak_with_callback(self):
        fake = FakeClient()
        with mock.patch("cabinet.oidc.client", return_value=fake):
            response = self.client.get("/login/student/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(fake.redirect_uri, "http://testserver/auth/student/callback/")

    @mock.patch("cabinet.gaudi.requests.get")
    def test_login_and_profile(self, get):
        get.side_effect = lambda url, **kw: fake_response(200, {"sheets": []} if url.endswith("/exam-sheets/") else PROFILE)
        self.assertRedirects(self.login(FakeClient(token())), "/", fetch_redirect_response=False)
        self.assertEqual(self.client.session["who"], {"kind": "student", "id": 20231001, "name": "Айпери Асанова"})
        page = self.client.get("/").content.decode()
        self.assertIn("Асанова Айпери Бакытовна", page)
        self.assertIn("ИСТ-5-26", page)
        self.assertEqual(get.call_args_list[0].args[0], "http://gaudi.test/api/cabinet/student/20231001/")
        self.assertEqual(get.call_args_list[0].kwargs["headers"], {"Authorization": "Api-Key k.k"})

    def test_login_must_be_gaudi_id(self):
        page = self.login(FakeClient(token("aiperi"))).content.decode()
        self.assertIn("не похож на ID в Гауди", page)
        self.assertNotIn("who", self.client.session)

    def test_cancelled_login(self):
        self.assertIn("Вход не завершён", self.login(FakeClient(error=True)).content.decode())

    @mock.patch("cabinet.gaudi.requests.get")
    def test_person_missing_in_gaudi(self, get):
        get.return_value = fake_response(404)
        self.login(FakeClient(token()))
        self.assertIn("Вас нет в Гауди", self.client.get("/").content.decode())

    def test_logout_goes_through_keycloak(self):
        self.login(FakeClient(token()))
        with mock.patch("cabinet.oidc.client", return_value=FakeClient()):
            response = self.client.post("/logout/")
        self.assertTrue(response["Location"].startswith("https://auth.test/realms/student/logout?"))
        self.assertIn("id_token_hint=idt", response["Location"])
        self.assertIn("post_logout_redirect_uri=http%3A%2F%2Ftestserver%2Flogin%2F", response["Location"])
        self.assertNotIn("who", self.client.session)
        self.assertEqual(self.client.get("/logout/").status_code, 405)  # выход — только кнопкой (POST)

    def test_language_switch(self):
        self.client.post("/i18n/setlang/", {"language": "en", "next": "/login/"})
        self.assertIn("Sign in", self.client.get("/login/").content.decode())
        self.client.post("/i18n/setlang/", {"language": "ky", "next": "/login/"})
        self.assertIn('lang="ky"', self.client.get("/login/").content.decode())


LESSONS = {"group": {"id": 1, "title": "ИСТ-5-26"}, "lector": None, "lessons": [
    {"id": 1, "weekday": 3, "weekday_title": "Среда", "time": "08:30", "discipline": "Компьютерные сети",
     "lesson_type": "Лекция", "lector": {"id": 7, "name": "Асанов Б. К.", "regalia": "доцент"},
     "group": {"id": 1, "title": "ИСТ-5-26"}, "classroom": "305", "campus": "1", "link": None, "notes": None},
    {"id": 2, "weekday": 3, "weekday_title": "Среда", "time": "10:00", "discipline": "Python",
     "lesson_type": "Практика", "lector": {"id": 8, "name": "Петрова А. С.", "regalia": None},
     "group": {"id": 1, "title": "ИСТ-5-26"}, "classroom": None, "campus": "zoom", "link": "https://zoom.us/j/1", "notes": None},
    {"id": 3, "weekday": 3, "weekday_title": "Среда", "time": "13:10", "discipline": "Английский",
     "lesson_type": "Практика", "lector": {"id": 9, "name": "Смит Дж.", "regalia": None},
     "group": {"id": 1, "title": "ИСТ-5-26"}, "classroom": "201", "campus": "2", "link": None, "notes": None},
    {"id": 4, "weekday": 5, "weekday_title": "Пятница", "time": "08:30", "discipline": "Математика",
     "lesson_type": "Лекция", "lector": {"id": 7, "name": "Асанов Б. К.", "regalia": "доцент"},
     "group": {"id": 1, "title": "ИСТ-5-26"}, "classroom": "305", "campus": "1", "link": None, "notes": None},
]}


@override_settings(OIDC=OIDC, GAUDI_API_URL="http://gaudi.test", GAUDI_API_KEY="k.k",
                   SCHEDULE_API_URL="https://schedule.test", SCHEDULE_API_KEY="s.k")
class ScheduleTestCase(TestCase):
    """Сегодня и неделя: пары группы студента из API расписания, пара — 80 минут."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        with mock.patch("cabinet.oidc.client", return_value=FakeClient(token())):
            self.client.get("/auth/student/callback/")
        self.schedule_calls, self.gaudi_calls, self.schedule_status = [], 0, 200
        patcher = mock.patch("requests.get", side_effect=self.answers)
        patcher.start()
        self.addCleanup(patcher.stop)

    def answers(self, url, **kwargs):
        """Один requests.get на всех: Гауди и расписание различаем по адресу."""
        if url.endswith("/exam-sheets/"):
            return fake_response(200, {"sheets": []})
        if "/api/cabinet/" in url:
            self.gaudi_calls += 1
            return fake_response(200, PROFILE)
        self.schedule_calls.append(kwargs)
        return fake_response(self.schedule_status, LESSONS)

    def at(self, text):
        """Подменить «сейчас»: среда 28.10.2026 в указанное время (по Бишкеку)."""
        import datetime as dt
        from zoneinfo import ZoneInfo
        moment = dt.datetime.fromisoformat("2026-10-28T" + text).replace(tzinfo=ZoneInfo("Asia/Bishkek"))
        return mock.patch("cabinet.views.timezone.localtime", return_value=moment)

    def test_today_marks_current_and_next(self):
        with self.at("10:30"):
            page = self.client.get("/").content.decode()
        self.assertEqual(self.schedule_calls[0]["params"], {"group": "ИСТ-5-26", "lang": "ru"})
        self.assertEqual(self.schedule_calls[0]["headers"], {"Authorization": "Api-Key s.k"})
        self.assertIn("08:30", page)
        self.assertIn("09:50", page)                     # конец первой пары: 08:30 + 1:20
        self.assertIn('class="lesson past"', page)       # 08:30–09:50 уже прошла
        self.assertIn('class="lesson now"', page)        # 10:00–11:20 идёт
        self.assertIn('class="lesson next"', page)       # 13:10 — следующая
        self.assertIn("https://zoom.us/j/1", page)
        self.assertNotIn("Математика", page)             # пятничная пара — не сегодня

    def test_week_and_cache(self):
        with self.at("07:00"):
            page = self.client.get("/schedule/").content.decode()
            self.client.get("/")
        self.assertIn("Математика", page)
        self.assertEqual(page.count('class="card day'), 6)    # понедельник–суббота
        self.assertEqual(page.count("Пар нет."), 4)
        self.assertEqual(len(self.schedule_calls), 1)         # второй раз — из кэша

    def test_schedule_down_does_not_break_page(self):
        self.schedule_status = 500
        page = self.client.get("/").content.decode()
        self.assertIn("Асанова Айпери Бакытовна", page)      # профиль на месте
        self.assertIn("Расписание ответило ошибкой 500", page)

    def test_profile_kept_in_session(self):
        self.client.get("/")
        self.client.get("/schedule/")
        self.assertEqual(self.gaudi_calls, 1)                 # вкладки переключаются без запроса в Гауди
        later = __import__("time").time() + 301
        with mock.patch("cabinet.views.time.time", return_value=later):
            self.client.get("/")
        self.assertEqual(self.gaudi_calls, 2)                 # через 5 минут — свежий профиль
        with mock.patch("cabinet.oidc.client", return_value=FakeClient(token("20231002"))):
            self.client.get("/auth/student/callback/")        # вошёл другой человек в том же браузере
        self.client.get("/")
        self.assertEqual(self.gaudi_calls, 3)                 # профиль прежнего не показываем


TRANSCRIPT = {"student_id": 20231001, "gpa": 3.5, "semesters": [
    {"semestr": 1, "gpa": 3.5, "items": [
        {"row": 101, "code": 11, "name": "Программирование", "hours": 150.0, "credits": 5.0, "control": "Экзамен",
         "first_module": 28, "second_module": 27, "exam": 35, "additional": 0, "points": 90.0,
         "mark": "Отлично", "letter": "A-", "gpa": 3.67},
        {"row": 102, "code": 12, "name": "История Кыргызстана", "hours": 90.0, "credits": 3.0, "control": "Зачёт",
         "first_module": 20, "second_module": 22, "exam": 30, "additional": 5, "points": 77.0,
         "mark": "Хорошо", "letter": "B", "gpa": 3.33}]},
    {"semestr": 2, "gpa": None, "items": [
        {"row": 103, "code": 13, "name": "Базы данных", "hours": 150.0, "credits": 5.0, "control": "Экзамен",
         "first_module": 25, "second_module": 0, "exam": 0, "additional": 0, "points": 25.0,
         "mark": "Неуд.", "letter": None, "gpa": None, "failed": True}]},
]}


def sheet(**extra):
    """Экзаменационный лист, как его отдаёт Гауди."""
    data = {"id": 5, "row": 103, "code": "13", "discipline": "Базы данных", "semestr": 2, "control": "Экзамен",
            "status": "approved", "requested_at": "2026-10-28T09:00:00Z", "issued_at": "2026-10-28T10:00:00Z",
            "valid_until": "2026-11-07T10:00:00Z", "examiner": "Асанов Бакыт Т.", "reject_reason": None,
            "result": None, "graded_at": None}
    data.update(extra)
    return data


class GaudiStub:
    """Вместо Гауди: ответы по адресу, запросы записываются."""

    def __init__(self, test):
        self.sheets, self.transcript, self.post_answer, self.calls = [], TRANSCRIPT, (201, {}), []
        for method in ("get", "post"):
            patcher = mock.patch("requests." + method, side_effect=getattr(self, method))
            patcher.start()
            test.addCleanup(patcher.stop)

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if url.endswith("/transcript/"):
            return fake_response(200, self.transcript) if self.transcript else fake_response(500)
        if url.endswith("/exam-sheets/"):
            return fake_response(200, {"sheets": self.sheets})
        return fake_response(200, PROFILE)

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return fake_response(*self.post_answer)

    def count(self, method, end):
        return sum(1 for m, url, _ in self.calls if m == method and url.endswith(end))


@override_settings(OIDC=OIDC, GAUDI_API_URL="http://gaudi.test", GAUDI_API_KEY="k.k")
class StudyTestCase(TestCase):
    """Учёба: оценки по семестрам из транскрипта Гауди и запрос экзаменационного листа по долгу."""

    def setUp(self):
        with mock.patch("cabinet.oidc.client", return_value=FakeClient(token())):
            self.client.get("/auth/student/callback/")
        self.gaudi = GaudiStub(self)

    def test_semesters_and_gpa(self):
        page = self.client.get("/study/").content.decode()
        url, kwargs = [(u, k) for m, u, k in self.gaudi.calls if u.endswith("/transcript/")][0]
        self.assertEqual(url, "http://gaudi.test/api/cabinet/student/20231001/transcript/")
        self.assertEqual(kwargs["params"], {"lang": "ru"})
        self.assertIn("GPA 3,5", page)                        # по-русски — с запятой
        self.assertIn("Программирование", page)
        self.assertIn("A- · Отлично", page)
        self.assertIn("доп. 5", page)                          # дополнительные баллы — только если есть
        self.assertLess(page.index("2 семестр"), page.index("1 семестр"))  # свежий семестр сверху
        self.assertEqual(page.count('class="failed"'), 1)     # долг выделен, сданные — нет
        self.assertEqual(page.count("Запросить экзаменационный лист"), 1)  # кнопка — только у долга

    def test_kept_in_session_per_language(self):
        self.client.get("/study/")
        self.client.get("/study/")
        self.assertEqual(self.gaudi.count("get", "/transcript/"), 1)
        self.client.post("/i18n/setlang/", {"language": "en", "next": "/study/"})
        self.client.get("/study/")
        self.assertEqual(self.gaudi.count("get", "/transcript/"), 2)   # другой язык — названия дисциплин заново

    def test_gaudi_error_is_shown(self):
        self.gaudi.transcript = None
        page = self.client.get("/study/").content.decode()
        self.assertIn("Гауди ответил ошибкой 500", page)

    def test_request_sheet(self):
        self.client.get("/study/")
        answer = self.client.post("/study/sheet/", {"row": "103"})
        self.assertRedirects(answer, "/study/", fetch_redirect_response=False)
        post = [k for m, u, k in self.gaudi.calls if m == "post"][0]
        self.assertEqual(post["json"], {"row": 103})
        self.gaudi.sheets = [sheet(status="requested")]
        page = self.client.get("/study/").content.decode()
        self.assertIn("Запрос отправлен в учебный отдел", page)          # сообщение — один раз
        self.assertIn("в учебном отделе", page)
        self.assertNotIn("Запросить экзаменационный лист", page)
        self.assertEqual(self.gaudi.count("get", "/exam-sheets/"), 2)     # после запроса — свежий список
        self.assertNotIn("Запрос отправлен", self.client.get("/study/").content.decode())

    def test_refused_request_shows_reason(self):
        self.gaudi.post_answer = (400, {"detail": "Не больше 3 запросов в сутки. Попробуйте завтра."})
        self.client.post("/study/sheet/", {"row": "103"})
        self.assertIn("Не больше 3 запросов в сутки", self.client.get("/study/").content.decode())

    def test_sheet_statuses(self):
        self.gaudi.sheets = [sheet()]
        page = self.client.get("/study/").content.decode()
        self.assertIn("Лист №5 выдан", page)
        self.assertIn("Действителен до 07.11.2026 16:00 · экзаменатор Асанов Бакыт Т.", page)  # время — по Бишкеку
        home = self.client.get("/").content.decode()
        self.assertIn("лист №5 выдан до 07.11.2026, экзаменатор Асанов Бакыт Т.", home)  # уведомление на «Сегодня»

    def test_rejected_can_ask_again(self):
        self.gaudi.sheets = [sheet(status="rejected", reject_reason="Нет оплаты", examiner=None)]
        page = self.client.get("/study/").content.decode()
        self.assertIn("Отказано: Нет оплаты", page)
        self.assertIn("Запросить экзаменационный лист", page)

    def test_staff_has_no_transcript(self):
        session = self.client.session
        session["who"] = {"kind": "staff", "id": 5, "name": "Преподаватель"}
        session.save()
        page = self.client.get("/study/").content.decode()
        self.assertIn("Этот раздел — для студентов.", page)
        self.assertEqual(self.gaudi.count("get", "/transcript/"), 0)
        self.assertEqual(self.client.post("/study/sheet/", {"row": "103"}).status_code, 404)


@override_settings(OIDC=OIDC, GAUDI_API_URL="http://gaudi.test", GAUDI_API_KEY="k.k")
class TeacherSheetsTestCase(TestCase):
    """Преподаватель видит листы, где он экзаменатор, и выставляет баллы."""

    def setUp(self):
        session = self.client.session
        session["who"] = {"kind": "staff", "id": 777, "name": "Асанов Бакыт"}
        session.save()
        self.gaudi = GaudiStub(self)
        self.gaudi.sheets = [sheet(student={"id": 20231001, "full_name": "Асанова Айпери Бакытовна", "group": "ИСТ-5-26"},
                                   current={"first_module": 25, "second_module": 0, "exam": 0, "points": 25.0,
                                            "mark": "Неуд."})]

    def test_list_and_badge(self):
        self.client.get("/")                                   # «Сегодня» подтягивает листы — счётчик на вкладке
        page = self.client.get("/sheets/").content.decode()
        self.assertIn("Лист №5", page)
        self.assertIn("Асанова Айпери Бакытовна · ID 20231001", page)
        self.assertIn('<span class="badge">1</span>', page)
        self.assertIn('name="first_module" min="0" max="100" required value="25"', page)

    def test_grade(self):
        self.gaudi.post_answer = (200, {})
        answer = self.client.post("/sheets/5/", {"first_module": "25", "second_module": "30", "exam": "60"})
        self.assertRedirects(answer, "/sheets/", fetch_redirect_response=False)
        url, kwargs = [(u, k) for m, u, k in self.gaudi.calls if m == "post"][0]
        self.assertEqual(url, "http://gaudi.test/api/cabinet/staff/777/exam-sheets/5/")
        self.assertEqual(kwargs["json"], {"first_module": 25, "second_module": 30, "exam": 60})
        self.assertIn("Баллы по листу №5 записаны в Гауди.", self.client.get("/sheets/").content.decode())

    def test_grade_refused(self):
        self.gaudi.post_answer = (400, {"detail": "Срок листа истёк. Студенту нужно запросить новый."})
        self.client.post("/sheets/5/", {"first_module": "25", "second_module": "30", "exam": "60"})
        self.assertIn("Срок листа истёк", self.client.get("/sheets/").content.decode())
        self.client.post("/sheets/5/", {"first_module": "a", "second_module": "30", "exam": "60"})
        self.assertIn("Баллы — целые числа.", self.client.get("/sheets/").content.decode())

    def test_students_cannot_open(self):
        session = self.client.session
        session["who"] = {"kind": "student", "id": 20231001, "name": "Айпери"}
        session.save()
        self.assertEqual(self.client.get("/sheets/").status_code, 404)
        self.assertEqual(self.client.post("/sheets/5/", {"exam": "1"}).status_code, 404)
