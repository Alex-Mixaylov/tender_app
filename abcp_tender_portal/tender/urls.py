from django.urls import path
from . import views

app_name = "tender"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),                 # главная после логина
    path("login/", views.login_step1, name="login_step1"),       # шаг 1 логина
    path("login/confirm/", views.login_step2, name="login_step2"),
    path("tender/step1/", views.tender_step1, name="tender_step1"),
]
