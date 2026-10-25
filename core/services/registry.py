"""Report registry and snapshot generation entry points."""
from django.core.exceptions import PermissionDenied
from django.http import Http404

from .cost import cost
from .customer_profile import customer_profile
from .revenue_and_loss import revenue_and_loss
from .sales import sales

REPORT_VIEWS = {
    "sales": sales,
    "customer-profile": customer_profile,
    "revenue-and-loss": revenue_and_loss,
    "cost": cost,
}


def report_generate(request, tab):
    """Save or replace the snapshot for this report range."""
    if tab not in REPORT_VIEWS:
        raise Http404
    if not (request.user.has_perm(f"core.access_{tab.replace('-', '_')}")
            and request.user.has_perm("core.change_report")):
        raise PermissionDenied
    request._range_params = request.POST
    request._capture_snapshot = tab
    return REPORT_VIEWS[tab](request)


def capture_snapshot(request, module, start, end, default=False):
    """Rebuild one snapshot in place; used by the seed command."""
    if module not in REPORT_VIEWS:
        return None
    old_params = getattr(request, "_range_params", None)
    old_capture = getattr(request, "_capture_snapshot", None)
    old_captured = getattr(request, "_captured_snapshot", None)
    request._range_params = {} if default else {
        "from": start.isoformat(), "to": end.isoformat(),
    }
    request._capture_snapshot = module
    request._captured_snapshot = None
    try:
        REPORT_VIEWS[module](request)
        return getattr(request, "_captured_snapshot", None)
    finally:
        request._range_params = old_params
        request._capture_snapshot = old_capture
        request._captured_snapshot = old_captured
