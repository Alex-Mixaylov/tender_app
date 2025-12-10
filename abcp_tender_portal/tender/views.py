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
from .services.abcp_step1 import run_abcp_pricing

from django.contrib.auth import logout
from django.views.decorators.http import require_http_methods

from django.core.mail import send_mail
from django.conf import settings



logger = logging.getLogger(__name__)
User = get_user_model()


def login_step1(request: HttpRequest) -> HttpResponse:
    """
    Шаг 1: ввод e-mail, генерация кода и запись в LoginCode.
    Теперь код отправляется на e-mail пользователя через SMTP.
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
                # 6-значный код
                code = f"{random.randint(0, 999999):06d}"

                LoginCode.objects.create(
                    user=user,
                    code=code,
                )

                logger.info(
                    f"2FA-код для пользователя {user.username} ({email}): {code}"
                )

                # Пытаемся отправить письмо
                subject = "Код входа в ABCP Tender Portal"
                message = (
                    "Здравствуйте!\n\n"
                    f"Ваш одноразовый код для входа: {code}\n\n"
                    "Срок действия кода — 15 минут.\n\n"
                    "Если вы не запрашивали вход, просто проигнорируйте это письмо."
                )
                from_email = settings.DEFAULT_FROM_EMAIL
                recipient_list = [email]

                try:
                    send_mail(
                        subject,
                        message,
                        from_email,
                        recipient_list,
                        fail_silently=False,
                    )
                except Exception as e:
                    logger.error(
                        "Ошибка отправки 2FA-кода пользователю %s (%s): %s",
                        user.username,
                        email,
                        e,
                        exc_info=True,
                    )
                    form.add_error(
                        None,
                        "Не удалось отправить письмо с кодом. "
                        "Проверьте корректность e-mail или попробуйте позже.",
                    )
                else:
                    # Сохраняем id пользователя в сессии только если письмо ушло
                    request.session["2fa_user_id"] = user.id
                    messages.success(
                        request,
                        f"Код подтверждения отправлен на {email}. "
                        "Проверьте почту.",
                    )
                    return redirect("tender:login_step2")
        # если дошли сюда — либо не POST, либо были ошибки в форме/отправке
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
            valid_from = now - timedelta(minutes=15)  # код живёт 15 минут

            login_code = (
                LoginCode.objects
                .filter(
                    user=user,
                    code=code,
                    is_used=False,
                    created_at__gte=valid_from,
                )
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
    return render(
        request,
        "tender/login_step2.html",
        {"form": form, "user": user},
    )


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """
    Простейший дашборд.
    """
    # здесь важно использовать реальные имена полей ForeignKey:
    latest_jobs = (
        TenderJob.objects
        .select_related("client_profile", "created_by")
        .order_by("-created_at")[:10]
    )

    context = {
        "latest_jobs": latest_jobs,
    }
    return render(request, "tender/dashboard.html", context)


@login_required
def tender_step1(request: HttpRequest) -> HttpResponse:
    """
    Этап 1: форма загрузки XLSX и запуск проценки по API ABCP.
    Пока проценка реализована заглушкой в run_abcp_pricing().
    """
    if request.method == "POST":
        form = TenderStep1Form(request.POST, request.FILES)
        if form.is_valid():
            client_profile = form.cleaned_data["client_profile"]
            upload = form.cleaned_data["input_file"]

            job = TenderJob.objects.create(
                created_by=request.user,
                client_profile=client_profile,
                input_file=upload,
                status=TenderJob.STATUS_NEW,
                log="",
            )

            # Ставим статус "в обработке"
            job.status = TenderJob.STATUS_PROCESSING
            job.save(update_fields=["status"])

            # Синхронно запускаем проценку
            run_abcp_pricing(job)

            # Перечитываем задачу из базы (мог измениться статус/лог/файл результата)
            job.refresh_from_db()

            if job.status == TenderJob.STATUS_DONE:
                msg = (
                    f"Задача #{job.id} выполнена. "
                    f"Результат можно скачать в таблице справа."
                )
            else:
                msg = (
                    f"Задача #{job.id} создана, но возникла ошибка. "
                    f"Смотрите лог в админке."
                )

            messages.success(request, msg)
            return redirect("tender:tender_step1")
    else:
        form = TenderStep1Form()

    # Последние задачи для правого блока
    last_jobs = (
        TenderJob.objects
        .select_related("client_profile", "created_by")
        .order_by("-created_at")[:10]
    )

    context = {
        "form": form,
        "last_jobs": last_jobs,
    }
    return render(request, "tender/tender_step1.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def logout_view(request: HttpRequest) -> HttpResponse:
    """
    Выход пользователя из портала.

    GET  -> показываем страницу подтверждения выхода (logout.html)
    POST -> выходим и кидаем на шаг 1 авторизации.
    """
    if request.method == "POST":
        logout(request)
        messages.success(request, "Вы вышли из системы.")
        return redirect("tender:login_step1")

    return render(request, "tender/logout.html")
