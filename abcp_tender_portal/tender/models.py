from django.db import models
from django.contrib.auth import get_user_model

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


class TenderJob(models.Model):
    """
    Задача проценки: какой пользователь загрузил какой файл, под каким profileId,
    где лежат входной и выходной файлы.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Пользователь"
    )

    client_profile = models.ForeignKey(
        ClientProfile, on_delete=models.PROTECT, verbose_name="Профиль клиента"
    )

    # Входной файл (brand, sku, qty)
    input_file = models.FileField(
        upload_to="tender/input/",
        verbose_name="Входной файл (brand/sku/qty)",
    )

    # Результирующий файл (abcp_tender_search_structured_*.xlsx)
    output_file = models.FileField(
        upload_to="tender/output/",
        verbose_name="Результат проценки",
        null=True,
        blank=True,
    )

    # Статус задачи (на будущее, если решим делать очереди / асинхрон)
    STATUS_CHOICES = [
        ("new", "Новая"),
        ("processing", "В обработке"),
        ("done", "Готово"),
        ("error", "Ошибка"),
    ]
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="new", verbose_name="Статус"
    )

    error_message = models.TextField("Текст ошибки", blank=True)

    def __str__(self):
        return f"TenderJob #{self.id} ({self.client_profile})"


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

