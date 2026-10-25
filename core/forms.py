"""The login form, extended with the privacy acknowledgment required by the
Data Privacy Act of 2012 (Republic Act No. 10173)."""
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils.safestring import mark_safe

from .models import PRIVACY_NOTICE_VERSION, Report


class PrivacyAuthenticationForm(AuthenticationForm):
    """Login form whose privacy acknowledgment checkbox is required and validated
    server-side: without it the credentials never log anyone in."""

    privacy_accepted = forms.BooleanField(
        label=mark_safe(
            f'I have read and understood the <a href="/privacy/" target="_blank" rel="noopener">'
            f"Data Privacy Notice</a> (version {PRIVACY_NOTICE_VERSION}), and I am aware that "
            f"the version and time of my acknowledgment are recorded with my account."
        ),
        error_messages={
            "required": "Acknowledge the Data Privacy Notice to log in.",
        },
    )


class ReportEditForm(forms.ModelForm):
    """Metadata editor for a saved report. Payload values are edited separately."""

    class Meta:
        model = Report
        fields = [
            "title", "range_start", "range_end", "compare_start", "compare_end",
            "source_through", "window_label", "prev_label", "period", "custom",
        ]

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
