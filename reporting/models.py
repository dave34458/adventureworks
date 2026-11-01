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
        ]


# ---------------------------------------------------------------------------
# Hand-written (not generated): privacy notice version and audit trail.

PRIVACY_NOTICE_VERSION = "1.0"


class AuditLog(models.Model):
    """One row per edit or deletion made through the table pages: who changed which
    record, when, and the old and new values. Written by the shared edit and delete
    views; visible read-only at /manage/ and retained for twelve months per the
    privacy notice."""

    ACTIONS = [("update", "update"), ("delete", "delete")]

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
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["model", "object_pk"]), models.Index(fields=["created_at"])]
        verbose_name = "audit record"
        verbose_name_plural = "audit records"

    def __str__(self):
        return f"{self.username} {self.action} {self.model} {self.object_pk}"


# ---------------------------------------------------------------------------
# Hand-written (not generated): saved report snapshots.
#
# One table holds one saved report per module/range. All KPI and panel data lives in
# `payload`. The report views read the saved row instead of running the aggregate SQL,
# which keeps saved pages fast. A range with no snapshot falls back to the live query.


class Report(models.Model):
    """One saved report row. `module` selects the panel; all KPI and panel data lives
    in `payload`."""

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
    payload = models.JSONField(default=dict, encoder=DjangoJSONEncoder)

    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="reports")
    generated_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-range_end", "-generated_at"]
        constraints = [
            models.UniqueConstraint(fields=["module", "range_start", "range_end"],
                                    name="uq_report_module_range"),
        ]

    def __str__(self):
        return f"{self.get_module_display()} {self.range_start} \u2013 {self.range_end}"
