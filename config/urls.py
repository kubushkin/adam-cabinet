from django.urls import include, path

from cabinet import views

urlpatterns = [
    path("", views.home, name="home"),
    path("schedule/", views.week, name="week"),
    path("study/", views.study, name="study"),
    path("login/", views.login_page, name="login"),
    path("login/<str:kind>/", views.login_start, name="login-start"),
    path("auth/<str:kind>/callback/", views.login_callback, name="login-callback"),
    path("logout/", views.logout, name="logout"),
    path("i18n/", include("django.conf.urls.i18n")),  # переключатель языка (set_language)
]
