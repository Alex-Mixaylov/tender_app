from django import forms
from django.core.validators import FileExtensionValidator

from .models import ClientProfile


class EmailLoginForm(forms.Form):
    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "you@example.com"}),
    )


class CodeConfirmForm(forms.Form):
    code = forms.CharField(
        label="Код подтверждения",
        max_length=6,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "123456"}),
    )


class TenderStep1Form(forms.Form):
    """
    Форма для Этапа 1:
    - выбор клиентского профиля (profileId для ABCP)
    - загрузка Excel-файла с колонками brand / sku / qty
    """
    client_profile = forms.ModelChoiceField(
        label="Клиентский профиль (profileId)",
        queryset=ClientProfile.objects.filter(is_active=True).order_by("name"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    input_file = forms.FileField(
        label="Excel-файл (brand / sku / qty)",
        validators=[FileExtensionValidator(allowed_extensions=["xls", "xlsx"])],
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
    )
