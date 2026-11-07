from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Hand-written (not generated): one permission per nav tab.

class TabAccess(models.Model):
    """Holds one permission per nav tab. It has no database table (managed = False):
    it exists only so Django creates the permissions below."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("access_sales", "Can open the Sales tab"),
            ("access_customer_profile", "Can open the Customer profile tab"),
            ("access_revenue_and_loss", "Can open the Revenue and loss tab"),
            ("access_cost", "Can open the Cost tab"),
            ("manage_department_users", "Can manage users in the department"),
        ]


# ---------------------------------------------------------------------------
# Hand-written (not generated): privacy notice version and audit trail.

PRIVACY_NOTICE_VERSION = "1.0"


class AuditLog(models.Model):
    """One row per report, table, or account change."""

    ACTIONS = [("create", "create"), ("update", "update"), ("delete", "delete")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="audit_log")
    username = models.CharField(max_length=150)  # snapshot: the record survives user deletion
    action = models.CharField(max_length=8, choices=ACTIONS)
    model = models.CharField(max_length=100)
    object_pk = models.CharField(max_length=64)
    object_repr = models.CharField(max_length=255)
    changes = models.JSONField(default=dict, blank=True)  # {field: [old, new]}, or the row on delete
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_log"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["model", "object_pk"]), models.Index(fields=["created_at"])]
        verbose_name = "audit record"
        verbose_name_plural = "audit records"

    def __str__(self):
        return f"{self.username} {self.action} {self.model} {self.object_pk}"


# ---------------------------------------------------------------------------
# Hand-written (not generated): saved report snapshots.
#
# One table holds saved report snapshots; multiple snapshots can share a module and range.
# KPI and panel data lives in `payload`;
# selected report-level filters live in `filters`. Saved pages read the row instead of
# running aggregate SQL, which keeps them fast. A range with no snapshot uses live data.


class Report(models.Model):
    """One saved report row. `module` selects the panel; all KPI and panel data lives
    in `payload`, with the applied report-level filters in `filters`."""

    MODULES = [
        ("sales", "Sales"),
        ("customer-profile", "Customer profile"),
        ("revenue-and-loss", "Revenue and loss"),
        ("cost", "Cost"),
    ]

    module = models.CharField(max_length=32, choices=MODULES)
    title = models.CharField(max_length=120, default="")
    range_start = models.DateField()
    range_end = models.DateField()
    compare_start = models.DateField(null=True, blank=True)
    compare_end = models.DateField(null=True, blank=True)
    source_through = models.DateField()
    window_label = models.CharField(max_length=120)
    prev_label = models.CharField(max_length=120)
    period = models.CharField(max_length=120)
    custom = models.BooleanField(default=False)
    filters = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, encoder=DjangoJSONEncoder)

    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="reports")
    generated_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reports"
        ordering = ["-range_end", "-generated_at"]

    def __str__(self):
        return f"{self.get_module_display()} {self.range_start} \u2013 {self.range_end}"

    @property
    def display_title(self):
        """Return the editable report name, removing filter text from legacy titles."""
        title = self.title or self.module
        if not self.filters:
            for marker in (" | Categories: ", " | Countries: "):
                title = title.split(marker, 1)[0]
        return title.strip()
