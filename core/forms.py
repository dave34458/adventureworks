"""The login form, extended with the privacy acknowledgment required by the
Data Privacy Act of 2012 (Republic Act No. 10173)."""
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils.safestring import mark_safe

from .models import PRIVACY_NOTICE_VERSION


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
