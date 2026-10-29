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
