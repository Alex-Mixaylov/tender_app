from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import models

User = get_user_model()


class ClientProfile(models.Model):
    """
    Профиль клиента ABCP (profileId + имя для людей).
    Можно будет выбирать, под каким профилем считать тендер.
    """
    name = models.CharField("Название профиля", max_length=255)
    profile_id = models.CharField("ABCP profileId", max_length=50, unique=True)

    def __str__(self):
        return f"{self.name} (profileId={self.profile_id})"

from django.conf import settings
from django.db import models


class TenderJob(models.Model):
    # ✅ 1. Статусы задачи
    # Было у тебя: STATUS_NEW, STATUS_IN_PROGRESS, STATUS_DONE, STATUS_ERROR
    # Сделал:
    #   - STATUS_PROCESSING, потому что он используется во views.py
    #   - STATUS_IN_PROGRESS оставил как алиас для обратной совместимости
    STATUS_NEW = "new"
    STATUS_PROCESSING = "in_progress"   # строковое значение оставили тем же
    STATUS_DONE = "done"
    STATUS_ERROR = "error"

    # Алиас — если где-то в коде ещё остался STATUS_IN_PROGRESS, он не сломается
    STATUS_IN_PROGRESS = STATUS_PROCESSING

    STATUS_CHOICES = [
        (STATUS_NEW, "Новая"),
        (STATUS_PROCESSING, "В обработке"),
        (STATUS_DONE, "Готово"),
        (STATUS_ERROR, "Ошибка"),
    ]

    # ✅ 2. КТО и КОГДА создал задачу
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tender_jobs",
        verbose_name="Пользователь",
    )

    # ✅ 3. Профиль клиента (profileId)
    client_profile = models.ForeignKey(
        "ClientProfile",
        on_delete=models.CASCADE,
        related_name="tender_jobs",
        verbose_name="Профиль клиента",
    )

    # ✅ 4. Текущий статус
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NEW,
        verbose_name="Статус",
    )

    # ✅ 5. Входной файл (исходный XLSX менеджера)
    input_file = models.FileField(
        upload_to="tenders/input/",
        verbose_name="Входной XLSX-файл",
    )

    # ✅ 6. Результирующий файл (abcp_tender_search_structured_*.xlsx)
    result_file = models.FileField(
        upload_to="tenders/output/",
        blank=True,
        null=True,
        verbose_name="Результирующий XLSX-файл",
    )

    # ✅ 7. Лог выполнения задачи (сюда пишет run_abcp_pricing)
    log = models.TextField(
        blank=True,
        default="",
        verbose_name="Лог выполнения",
    )

    class Meta:
        verbose_name = "Задача проценки"
        verbose_name_plural = "Задачи проценки"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Задача #{self.pk} ({self.get_status_display()})"

class LoginCode(models.Model):
    """
    Таблица одноразовых кодов для 2FA (логин по email + код).
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="login_codes")
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def __str__(self):
        return f"Code {self.code} for {self.user}"

