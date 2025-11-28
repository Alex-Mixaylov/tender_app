import logging
import random
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone

from .forms import EmailLoginForm, CodeConfirmForm, TenderStep1Form
from .models import LoginCode, TenderJob

logger = logging.getLogger(__name__)
User = get_user_model()


def login_step1(request: HttpRequest) -> HttpResponse:
    """
    Шаг 1: ввод e-mail, генерация кода и запись в LoginCode.
    Пока «отправку письма» имитируем записью кода в лог.
    """
    if request.method == "POST":
        form = EmailLoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"].strip().lower()

            try:
                user = User.objects.get(email__iexact=email, is_active=True)
            except User.DoesNotExist:
                form.add_error("email", "Пользователь с таким e-mail не найден.")
            else:
                code = f"{random.randint(0, 999999):06d}"

                LoginCode.objects.create(
                    user=user,
                    code=code,
                )

                logger.info(f"2FA-код для пользователя {user.username} ({email}): {code}")

                request.session["2fa_user_id"] = user.id
                return redirect("tender:login_step2")
    else:
        form = EmailLoginForm()

    return render(request, "tender/login_step1.html", {"form": form})


def login_step2(request: HttpRequest) -> HttpResponse:
    """
    Шаг 2: ввод кода, проверка и вход пользователя.
    """
    user_id = request.session.get("2fa_user_id")
    if not user_id:
        return redirect("tender:login_step1")

    try:
        user = User.objects.get(id=user_id, is_active=True)
    except User.DoesNotExist:
        return redirect("tender:login_step1")

    if request.method == "POST":
        form = CodeConfirmForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["code"].strip()

            now = timezone.now()
            valid_from = now - timedelta(minutes=15)

            login_code = (
                LoginCode.objects
                .filter(user=user, code=code, is_used=False, created_at__gte=valid_from)
                .order_by("-created_at")
                .first()
            )

            if not login_code:
                form.add_error("code", "Неверный или просроченный код.")
            else:
                login_code.is_used = True
                login_code.save(update_fields=["is_used"])

                login(request, user)
                request.session.pop("2fa_user_id", None)

                return redirect("tender:dashboard")
    else:
        form = CodeConfirmForm()

    # передаём user в шаблон, чтобы показать e-mail/username
    return render(request, "tender/login_step2.html", {"form": form, "user": user})


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """
    Простейший дашборд.
    """
    latest_jobs = TenderJob.objects.select_related("client", "user").order_by("-created_at")[:10]

    context = {
        "latest_jobs": latest_jobs,
    }
    return render(request, "tender/dashboard.html", context)


@login_required
def tender_step1(request: HttpRequest) -> HttpResponse:
    """
    Этап 1: форма загрузки XLSX + список последних задач.
    Пока только создаём TenderJob и сохраняем файл; запуск ABCP-скрипта добавим позже.
    """
    if request.method == "POST":
        form = TenderStep1Form(request.POST, request.FILES)
        if form.is_valid():
            client_profile = form.cleaned_data["client_profile"]
            input_file = form.cleaned_data["input_file"]

            job = TenderJob.objects.create(
                client=client_profile,
                user=request.user,
                input_file=input_file,   # FileField сам сохранит файл в MEDIA_ROOT
                status="new",
                log="Задача создана через веб-интерфейс.",
            )

            messages.success(
                request,
                f"Задача #{job.id} создана. Файл загружен, можно запускать проценку после интеграции с API.",
            )
            return redirect("tender:tender_step1")
    else:
        form = TenderStep1Form()

    jobs = (
        TenderJob.objects
        .select_related("client", "user")
        .order_by("-created_at")[:20]
    )

    context = {
        "form": form,
        "jobs": jobs,
    }
    return render(request, "tender/tender_step1.html", context)
