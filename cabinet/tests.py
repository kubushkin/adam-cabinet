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
        get.return_value = fake_response(200, PROFILE)
        self.assertRedirects(self.login(FakeClient(token())), "/", fetch_redirect_response=False)
        self.assertEqual(self.client.session["who"], {"kind": "student", "id": 20231001, "name": "Айпери Асанова"})
        page = self.client.get("/").content.decode()
        self.assertIn("Асанова Айпери Бакытовна", page)
        self.assertIn("ИСТ-5-26", page)
        self.assertEqual(get.call_args.args[0], "http://gaudi.test/api/cabinet/student/20231001/")
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Api-Key k.k"})

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
        {"code": 11, "name": "Программирование", "hours": 150.0, "credits": 5.0, "control": "Экзамен",
         "first_module": 28, "second_module": 27, "exam": 35, "additional": 0, "points": 90.0,
         "mark": "Отлично", "letter": "A-", "gpa": 3.67},
        {"code": 12, "name": "История Кыргызстана", "hours": 90.0, "credits": 3.0, "control": "Зачёт",
         "first_module": 20, "second_module": 22, "exam": 30, "additional": 5, "points": 77.0,
         "mark": "Хорошо", "letter": "B", "gpa": 3.33}]},
    {"semestr": 2, "gpa": None, "items": [
        {"code": 13, "name": "Базы данных", "hours": 150.0, "credits": 5.0, "control": "Экзамен",
         "first_module": 25, "second_module": 0, "exam": 0, "additional": 0, "points": 25.0,
         "mark": "Неуд.", "letter": None, "gpa": None, "failed": True}]},
]}


@override_settings(OIDC=OIDC, GAUDI_API_URL="http://gaudi.test", GAUDI_API_KEY="k.k")
class StudyTestCase(TestCase):
    """Учёба: оценки по семестрам из транскрипта Гауди."""

    def setUp(self):
        with mock.patch("cabinet.oidc.client", return_value=FakeClient(token())):
            self.client.get("/auth/student/callback/")

    @mock.patch("requests.get", return_value=fake_response(200, TRANSCRIPT))
    def test_semesters_and_gpa(self, get):
        page = self.client.get("/study/").content.decode()
        self.assertEqual(get.call_args.args[0], "http://gaudi.test/api/cabinet/student/20231001/transcript/")
        self.assertEqual(get.call_args.kwargs["params"], {"lang": "ru"})
        self.assertIn("GPA 3,5", page)                        # по-русски — с запятой
        self.assertIn("Программирование", page)
        self.assertIn("A- · Отлично", page)
        self.assertIn("доп. 5", page)                          # дополнительные баллы — только если есть
        self.assertLess(page.index("2 семестр"), page.index("1 семестр"))  # свежий семестр сверху
        self.assertEqual(page.count('class="failed"'), 1)     # долг выделен, сданные — нет

    @mock.patch("requests.get", return_value=fake_response(200, TRANSCRIPT))
    def test_kept_in_session_per_language(self, get):
        self.client.get("/study/")
        self.client.get("/study/")
        self.assertEqual(get.call_count, 1)
        self.client.post("/i18n/setlang/", {"language": "en", "next": "/study/"})
        self.client.get("/study/")
        self.assertEqual(get.call_count, 2)                   # другой язык — названия дисциплин заново
        self.assertEqual(get.call_args.kwargs["params"], {"lang": "en"})

    @mock.patch("requests.get", return_value=fake_response(500))
    def test_gaudi_error_is_shown(self, get):
        page = self.client.get("/study/").content.decode()
        self.assertIn("Гауди ответил ошибкой 500", page)

    @mock.patch("requests.get")
    def test_staff_has_no_transcript(self, get):
        session = self.client.session
        session["who"] = {"kind": "staff", "id": 5, "name": "Преподаватель"}
        session.save()
        page = self.client.get("/study/").content.decode()
        self.assertIn("Этот раздел — для студентов.", page)
        get.assert_not_called()
