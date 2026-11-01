"""Email login and self-service account editing."""
from typing import ClassVar

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from .models import User


class EmailAuthenticationForm(AuthenticationForm):
    """Email and password login. There is no privacy acknowledgment step."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )
    error_messages: ClassVar[dict] = {
        **AuthenticationForm.error_messages,
        "invalid_login": (
            "Please enter a correct email and password. "
            "Note that both fields may be case-sensitive."
        ),
    }


class AccountForm(forms.ModelForm):
    """Self-service name and password edit for any signed-in account."""

    new_password1 = forms.CharField(
        label="New password",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Leave blank to keep the current password.",
    )
    new_password2 = forms.CharField(
        label="Confirm new password",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name")

    def clean(self):
        cleaned = super().clean()
        for field in ("first_name", "last_name"):
            if cleaned.get(field):
                cleaned[field] = cleaned[field].strip()

        password1 = cleaned.get("new_password1")
        password2 = cleaned.get("new_password2")
        if password1 or password2:
            if password1 != password2:
                self.add_error("new_password2", "The two password fields do not match.")
            else:
                try:
                    password_validation.validate_password(password1, self.instance)
                except ValidationError as error:
                    self.add_error("new_password1", error)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("new_password1")
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user
