from django import forms


class EmailLoginForm(forms.Form):
    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "Введите ваш e-mail",
        })
    )


class CodeConfirmForm(forms.Form):
    code = forms.CharField(
        label="Код подтверждения",
        max_length=6,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Укажите код из письма",
        })
    )
