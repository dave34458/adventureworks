"""Email login and self-service account editing."""
from typing import ClassVar

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from .models import User
from .roles import ADMIN_ROLE


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


class DepartmentUserForm(forms.ModelForm):
    """Create or update a user through the in-app manage-users page."""

    role = forms.ChoiceField(label="Role")
    password = forms.CharField(
        label="Password", required=False, strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Required for a new user; leave blank when editing to keep the password.",
    )
    password_confirm = forms.CharField(
        label="Confirm password", required=False, strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "is_active")

    def __init__(self, *args, department=None, roles=None, **kwargs):
        self.department = department
        super().__init__(*args, **kwargs)
        self.fields["password_confirm"].required = not bool(self.instance.pk)
        self.fields["role"].choices = roles or [
            (f"{department} {kind}", kind)
            for kind in ("Manager", "Supervisor", "Employee")
        ]
        if self.instance and self.instance.pk:
            self.initial["role"] = (
                ADMIN_ROLE if self.instance.is_superuser
                else self.instance.groups.values_list("name", flat=True).first() or ""
            )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        duplicates = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if not self.instance.pk and not password:
            raise forms.ValidationError("A password is required for a new user.")
        if password:
            password_validation.validate_password(password, self.instance)
        return password

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("password_confirm"):
            self.add_error("password_confirm", "The passwords do not match.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data["password"]
        if password:
            user.set_password(password)
        if commit:
            role = self.cleaned_data["role"]
            user.save()
            user.user_permissions.clear()
            if role == ADMIN_ROLE:
                user.groups.clear()
                user.is_superuser = True
                user.is_staff = True
            else:
                user.groups.set([Group.objects.get(name=role)])
                user.is_superuser = False
                user.is_staff = False
            user.save(update_fields=["is_superuser", "is_staff"])
        return user
