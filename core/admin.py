"""Admin registrations. The Users and Groups pages come from Django's defaults;
privacy acknowledgment records and audit records are added read-only so the DPO
can inspect them without being able to alter the evidence."""
from django.contrib import admin

from .models import AuditLog, PrivacyAcknowledgment


@admin.register(PrivacyAcknowledgment)
class PrivacyAcknowledgmentAdmin(admin.ModelAdmin):
    list_display = ("user", "version", "acknowledged_at")
    ordering = ("-acknowledged_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "username", "action", "model", "object_pk", "object_repr")
    list_filter = ("action", "model")
    search_fields = ("username", "object_repr", "model")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
