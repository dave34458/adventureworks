"""Email login and self-service account editing."""
from typing import ClassVar

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from .models import Report, User


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


class ReportEditForm(forms.ModelForm):
    """Metadata editor for a saved report. Payload values are edited separately."""

    class Meta:
        model = Report
        fields = (
            "title", "range_start", "range_end", "compare_start", "compare_end",
            "source_through", "window_label", "prev_label", "period", "custom",
        )

    def clean(self):
        cleaned = super().clean()
        for field in ("title", "window_label", "prev_label", "period"):
            value = cleaned.get(field)
            if value is not None:
                value = value.strip()
                cleaned[field] = value
                if not value:
                    self.add_error(field, "This field is required.")

        start = cleaned.get("range_start")
        end = cleaned.get("range_end")
        if start and end and start > end:
            self.add_error("range_end", "End date must be on or after the start date.")

        compare_start = cleaned.get("compare_start")
        compare_end = cleaned.get("compare_end")
        if bool(compare_start) != bool(compare_end):
            self.add_error("compare_end", "Set both comparison dates or neither.")
        elif compare_start and compare_end and compare_start > compare_end:
            self.add_error("compare_end", "Comparison end must be on or after its start.")
        if compare_end and start and compare_end >= start:
            self.add_error("compare_end", "Comparison end must be before the report start.")

        through = cleaned.get("source_through")
        if through and end and through < end:
            self.add_error("source_through", "Data-through date must be on or after the end date.")

        if start and end and self.instance.module:
            duplicate = Report.objects.filter(
                module=self.instance.module, range_start=start, range_end=end,
            ).exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error("range_end", "A saved report already exists for this range.")
        return cleaned
