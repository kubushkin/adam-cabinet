"""
Настройки личного кабинета Adam University. Всё, что зависит от сервера, — из переменных окружения
(файл .env рядом с docker-compose.yml, образец — .env.example).
"""
import os
import sys
from pathlib import Path

from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return env(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [x.strip() for x in env(name, default).split(",") if x.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("Не задан DJANGO_SECRET_KEY (см. .env.example)")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "cabinet",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.template.context_processors.i18n",
        "cabinet.views.who_context",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "cabinet"),
        "USER": env("DB_USER", "cabinet"),
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", "db"),
        "PORT": env("DB_PORT", "5432"),
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "ru"
LANGUAGES = [("ru", _("Русский")), ("ky", _("Кыргызча")), ("en", _("English"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Bishkek"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # в образе статика собирается collectstatic с хешами в именах; тестам и runserver манифест не нужен
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage" if TESTING or DEBUG
                    else "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

SESSION_COOKIE_AGE = 8 * 3600
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)  # включить, когда будет HTTPS
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
# HTTPS снимает HAProxy на pfSense и передаёт сюда обычный http с заголовком X-Forwarded-Proto: https.
if env_bool("DJANGO_BEHIND_HTTPS_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Вход через Keycloak (OpenID Connect): студенты и преподаватели — разные realm.
# Адрес realm вида https://auth.adam.edu.kg/realms/student; пустой адрес — этот вход скрыт.
OIDC = {
    "student": {"issuer": env("OIDC_STUDENT_ISSUER", ""), "client_id": env("OIDC_STUDENT_CLIENT_ID", "cabinet"),
                "client_secret": env("OIDC_STUDENT_CLIENT_SECRET", "")},
    "staff": {"issuer": env("OIDC_STAFF_ISSUER", ""), "client_id": env("OIDC_STAFF_CLIENT_ID", "cabinet"),
              "client_secret": env("OIDC_STAFF_CLIENT_SECRET", "")},
}

# Гауди: профиль, карта, транскрипт (ключ API с именем «cabinet»)
GAUDI_API_URL = env("GAUDI_API_URL", "")
GAUDI_API_KEY = env("GAUDI_API_KEY", "")
API_TIMEOUT = float(env("API_TIMEOUT", "5"))
