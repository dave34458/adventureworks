"""Shared report-page result and snapshot helpers."""
import copy
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.urls import reverse
from django.utils import timezone

from ..constants import META_KEYS
from ..models import Report
from .validation import PayloadValidationError, validate_report_payload


@dataclass
class ReportResult:
    """A report page, with no HTTP response objects."""

    template: str
    context: dict = field(default_factory=dict)
    redirect_to: str | None = None


def _render_snapshot(request, module, template, snapshot):
    context = copy.deepcopy(snapshot.payload or {})
    if module == "cost":
        for row in context.get("biggest", []):
            value = row.get("date")
            if isinstance(value, str):
                try:
                    row["date"] = date.fromisoformat(value)
                except ValueError:
                    pass
    context.update({
        "tab": module,
        "title": snapshot.title or module,
        "through": snapshot.source_through,
        "window_label": snapshot.window_label,
        "prev_label": snapshot.prev_label,
        "custom": snapshot.custom,
        "period": snapshot.period,
        "w_from": snapshot.range_start.isoformat(),
        "w_to": snapshot.range_end.isoformat(),
        "snapshot": snapshot,
    })
    context["snapshots"] = list(Report.objects.filter(module=module))
    can_manage = request.user.has_perm("core.change_report")
    context["can_manage"] = can_manage
    context["edit_url"] = (reverse("snapshot_edit", args=[module, snapshot.pk])
                           if can_manage else "")
    context["manage_url"] = reverse("snapshot_list", args=[module])
    return ReportResult(template, context)


def _empty_report(request, module, template, title):
    return ReportResult(template, {
        "tab": module,
        "title": title,
        "empty_message": "No data is available for the selected range.",
        "has_data": False,
        "w_from": request.GET.get("from", ""),
        "w_to": request.GET.get("to", ""),
        "snapshots": list(Report.objects.filter(module=module)),
        "can_manage": request.user.has_perm("core.change_report"),
        "manage_url": reverse("snapshot_list", args=[module]),
    })


def _report_response(request, module, template, context, window):
    """Save when this request is a Generate action, otherwise render the live data."""
    if getattr(request, "_capture_snapshot", None) == module:
        user = getattr(request, "user", None)
        generated_by = user if user is not None and getattr(user, "pk", None) else None
        payload = json.loads(json.dumps(
            {key: value for key, value in context.items() if key not in META_KEYS},
            cls=DjangoJSONEncoder))
        try:
            validate_report_payload(module, payload)
        except PayloadValidationError as exc:
            raise RuntimeError(f"{module} report payload is invalid: {exc}") from exc
        try:
            compare_end = (window.trend_start - timedelta(microseconds=1)).date()
        except OverflowError:
            compare_end = window.trend_start.date()
        defaults = {
            "title": context.get("title", ""),
            "compare_start": window.window_start.date(),
            "compare_end": compare_end,
            "source_through": window.last.date(),
            "window_label": context.get("window_label", ""),
            "prev_label": context.get("prev_label", ""),
            "period": context.get("period", ""),
            "custom": bool(context.get("custom")),
            "payload": payload,
            "generated_by": generated_by,
            "generated_at": timezone.now(),
        }
        snapshot, _ = Report.objects.update_or_create(
            module=module,
            range_start=window.trend_start.date(),
            range_end=window.last.date(),
            defaults=defaults,
        )
        request._captured_snapshot = snapshot
        return ReportResult("", redirect_to=f"{reverse(module)}?report={snapshot.pk}")
    context["snapshots"] = list(Report.objects.filter(module=module))
    context["can_manage"] = request.user.has_perm("core.change_report")
    context["manage_url"] = reverse("snapshot_list", args=[module])
    return ReportResult(template, context)


def _saved_report(request, module, template):
    if getattr(request, "_capture_snapshot", None):
        return None
    if "report" in request.GET:
        pk = request.GET.get("report")
        if not pk:
            return None
        try:
            snapshot = Report.objects.get(pk=pk, module=module)
        except (ValueError, Report.DoesNotExist):
            return None
        return _render_snapshot(request, module, template, snapshot)
    if "from" in request.GET or "to" in request.GET:
        return None
    snapshot = Report.objects.filter(module=module).first()
    if snapshot is None:
        return None
    return _render_snapshot(request, module, template, snapshot)
