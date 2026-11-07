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

from .models import User
from .roles import ADMIN_ROLE, ROLE_CHOICES
from reporting.models import AuditLog


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

    def save_model(self, request, obj, form, change):
        old = User.objects.get(pk=obj.pk) if change else None
        request._audit_user_before = {
            "email": old.email, "first_name": old.first_name, "last_name": old.last_name,
            "is_active": old.is_active,
            "role": ADMIN_ROLE if old.is_superuser else old.groups.values_list(
                "name", flat=True).first(),
        } if old else None
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        user = form.instance
        after = {
            "email": user.email, "first_name": user.first_name, "last_name": user.last_name,
            "is_active": user.is_active,
            "role": ADMIN_ROLE if user.is_superuser else user.groups.values_list(
                "name", flat=True).first(),
        }
        before = request._audit_user_before
        changes = ({key: [before.get(key), value] for key, value in after.items()}
                   if before is None else {
                       key: [before[key], value] for key, value in after.items()
                       if before[key] != value
                   })
        if changes:
            AuditLog.objects.create(
                user=request.user, username=request.user.get_username(),
                action="create" if before is None else "update", model="User",
                object_pk=str(user.pk), object_repr=user.email, changes=changes,
                ip_address=request.META.get("REMOTE_ADDR"))

    def delete_model(self, request, obj):
        changes = {
            "email": [obj.email, None], "first_name": [obj.first_name, None],
            "last_name": [obj.last_name, None], "is_active": [obj.is_active, None],
            "role": [ADMIN_ROLE if obj.is_superuser else obj.groups.values_list(
                "name", flat=True).first(), None],
        }
        pk, email = str(obj.pk), obj.email
        super().delete_model(request, obj)
        AuditLog.objects.create(
            user=request.user, username=request.user.get_username(), action="delete",
            model="User", object_pk=pk, object_repr=email, changes=changes,
            ip_address=request.META.get("REMOTE_ADDR"))

    def delete_queryset(self, request, queryset):
        snapshots = [{
            "pk": str(user.pk), "email": user.email,
            "changes": {
                "email": [user.email, None], "first_name": [user.first_name, None],
                "last_name": [user.last_name, None], "is_active": [user.is_active, None],
                "role": [ADMIN_ROLE if user.is_superuser else user.groups.values_list(
                    "name", flat=True).first(), None],
            },
        } for user in queryset]
        super().delete_queryset(request, queryset)
        AuditLog.objects.bulk_create([
            AuditLog(user=request.user, username=request.user.get_username(),
                     action="delete", model="User", object_pk=row["pk"],
                     object_repr=row["email"], changes=row["changes"],
                     ip_address=request.META.get("REMOTE_ADDR"))
            for row in snapshots
        ])

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
