"""Admin registrations for read-only audit records."""
from django.contrib import admin

from .models import AuditLog


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
