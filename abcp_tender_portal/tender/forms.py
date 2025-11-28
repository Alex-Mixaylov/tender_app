from django import forms

from .models import ClientProfile


class EmailLoginForm(forms.Form):
    email = forms.EmailField(
        label="E-mail",
        help_text="Укажите e-mail, зарегистрированный в портале.",
    )


class CodeConfirmForm(forms.Form):
    code = forms.CharField(
        label="Код подтверждения",
        max_length=6,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code"}),
        help_text="6-значный код из письма / лога.",
    )


class TenderStep1Form(forms.Form):
    """
    Форма для Этапа 1: выбор client_profile (profileId) + загрузка XLSX.
    """

    client_profile = forms.ModelChoiceField(
        label="Клиентский профиль (profileId)",
        queryset=ClientProfile.objects.all().order_by("name"),
        help_text="Выберите, под каким клиентским профилем выполнять проценку.",
    )

    input_file = forms.FileField(
        label="Входной XLSX-файл",
        help_text="Файл с колонками brand / sku / qty.",
        widget=forms.ClearableFileInput(
            attrs={"accept": ".xlsx,.xls"}
        ),
    )
