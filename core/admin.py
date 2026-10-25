"""Admin registrations. Users get a compact form with one required role; audit
records are read-only so the DPO can inspect them without altering the evidence."""
from typing import ClassVar

from django import forms
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.admin.utils import flatten_fieldsets
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils.html import format_html

from .models import AuditLog, User
from .roles import ADMIN_ROLE, ROLE_CHOICES


class EmailAdminAuthenticationForm(AdminAuthenticationForm):
    username = forms.CharField(
        label="Email",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )
    error_messages: ClassVar[dict] = {
        **AdminAuthenticationForm.error_messages,
        "invalid_login": (
            "Please enter the correct email and password for a staff account. "
            "Note that both fields may be case-sensitive."
        ),
    }


admin.site.login_form = EmailAdminAuthenticationForm


class EmailNormalizationMixin:
    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        duplicates = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email


class RoleFormMixin(EmailNormalizationMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"] = forms.ChoiceField(
            choices=ROLE_CHOICES,
            required=True,
            label="Role",
            help_text="Required. Each user has exactly one role.",
        )
        if self.instance and self.instance.pk:
            if self.instance.is_superuser:
                self.initial["role"] = ADMIN_ROLE
            else:
                self.initial["role"] = self.instance.groups.values_list(
                    "name", flat=True).first() or ""

    def _save_m2m(self):
        super()._save_m2m()
        self._save_role(self.instance)

    def _save_role(self, user):
        role = self.cleaned_data.get("role")
        if not role:
            return
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


class RoleUserCreationForm(RoleFormMixin, AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ("email", "first_name", "last_name")


class RoleUserChangeForm(RoleFormMixin, UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = ("email", "first_name", "last_name", "is_active")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = RoleUserChangeForm
    add_form = RoleUserCreationForm
    list_display = ("email", "role", "is_active")
    list_filter = ("is_active", "groups")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
    filter_horizontal = ()
    readonly_fields = ("password_link",)
    fieldsets = (
        (None, {"fields": ("email", "first_name", "last_name", "role", "password_link")}),
        ("Access", {"fields": ("is_active",)}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "email", "first_name", "last_name", "role",
                "usable_password", "password1", "password2",
            ),
        }),
    )

    def get_form(self, request, obj=None, change=False, **kwargs):
        fields = kwargs.pop("fields", None)
        if fields is None:
            fields = flatten_fieldsets(self.get_fieldsets(request, obj))
        fields = [field for field in fields if field != "role"]
        return super().get_form(
            request, obj, change=change, fields=fields, **kwargs)

    @admin.display(description="Role")
    def role(self, obj):
        if obj.is_superuser:
            return ADMIN_ROLE
        return ", ".join(obj.groups.values_list("name", flat=True)) or "—"

    @admin.display(description="Password")
    def password_link(self, obj):
        if not obj:
            return ""
        url = reverse("admin:auth_user_password_change", args=[obj.pk])
        return format_html('<a href="{}">Reset password</a>', url)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "username", "action", "model", "object_pk", "object_repr")
    list_filter = ("action", "model")
    search_fields = ("username", "object_repr", "model")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
