import logging
import random
from datetime import timedelta

from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone

from .forms import EmailLoginForm, CodeConfirmForm
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
                # Генерируем 6-значный код
                code = f"{random.randint(0, 999999):06d}"

                LoginCode.objects.create(
                    user=user,
                    email=email,
                    code=code,
                )

                # Для отладки — пишем код в лог
                logger.info(f"2FA-код для пользователя {user.username} ({email}): {code}")

                # Запоминаем user.id в сессии для шага 2
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
        # Если по какой-то причине нет user_id в сессии — возвращаем на шаг 1
        return redirect("tender:login_step1")

    try:
        user = User.objects.get(id=user_id, is_active=True)
    except User.DoesNotExist:
        return redirect("tender:login_step1")

    if request.method == "POST":
        form = CodeConfirmForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["code"].strip()

            # Ищем последний неиспользованный код для этого пользователя
            now = timezone.now()
            valid_from = now - timedelta(minutes=15)  # код действует 15 минут

            login_code = (
                LoginCode.objects
                .filter(user=user, code=code, is_used=False, created_at__gte=valid_from)
                .order_by("-created_at")
                .first()
            )

            if not login_code:
                form.add_error("code", "Неверный или просроченный код.")
            else:
                # Помечаем код использованным и логиним пользователя
                login_code.is_used = True
                login_code.save(update_fields=["is_used"])

                login(request, user)
                # После логина можно удалить из сессии user_id
                request.session.pop("2fa_user_id", None)

                return redirect("tender:dashboard")
    else:
        form = CodeConfirmForm()

    return render(request, "tender/login_step2.html", {"form": form, "user": user})


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """
    Простейшая заглушка дашборда.
    Потом сюда добавим аккордеон с этапами.
    """
    # На будущее: здесь можно выводить список последних TenderJob
    latest_jobs = TenderJob.objects.order_by("-created_at")[:10]

    context = {
        "latest_jobs": latest_jobs,
    }
    return render(request, "tender/dashboard.html", context)


@login_required
def tender_step1(request: HttpRequest) -> HttpResponse:
    """
    Заглушка для Этапа 1 (загрузка XLSX и запуск проценки).
    """
    return render(request, "tender/tender_step1.html")
