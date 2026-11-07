"""Shared report-page result and snapshot helpers."""
import copy
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.http import Http404
from django.urls import reverse
from django.utils import timezone

from core.models import ProductionProductCategory
from ..constants import CHART_FILTERS, META_KEYS, REPORT_COUNTRIES
from ..models import AuditLog, Report

SHOW_OPTIONS = (3, 6, 8, 10, 25, 50, 100)
SHOW_DEFAULTS = {
    "sales": {"products": 8, "low_products": 6},
    "customer-profile": {"countries": 6, "cities": 8, "biggest": 8},
    "revenue-and-loss": {"declining": 8, "leaks": 6, "products": 8},
    "cost": {"vendors": 8, "products": 8, "reasons": 8, "changes": 6, "biggest": 8},
}


def show_amount(params, key, default):
    try:
        amount = int(params.get(f"show_{key}", default))
    except (TypeError, ValueError):
        amount = default
    return amount if amount in SHOW_OPTIONS else default


def show_values(params, module):
    return {key: show_amount(params, key, default)
            for key, default in SHOW_DEFAULTS[module].items()}


def _display_rows(context, module, values):
    if module == "customer-profile":
        for key in ("countries", "cities"):
            context[key] = context.get(key, [])[:values[key]]
        biggest = sorted(context.get("biggest", []),
                         key=lambda row: float(row.get("rev") or 0), reverse=True)
        context["biggest"] = biggest[:values["biggest"]]
    else:
        for key, amount in values.items():
            context[key] = context.get(key, [])[:amount]
        if module == "sales":
            rows = context["low_products"]
            top = max((row["value"] for row in rows), default=0)
            for row in rows:
                row["pct"] = max(round(row["value"] / top * 100), 2) if top else 0


@dataclass
class ReportResult:
    """A report page, with no HTTP response objects."""

    template: str
    context: dict = field(default_factory=dict)
    redirect_to: str | None = None


def _chart_filter(request, module, context, saved_filters=None):
    """Apply a report chart filter and expose its selected value."""
    chart_filter = CHART_FILTERS.get(module)
    if chart_filter is None:
        return
    name, label, default, options = chart_filter
    allowed = {value for value, _ in options}
    params = request.POST if getattr(request, "_capture_snapshot", None) else request.GET
    selected = params.get(name)
    if selected is None and saved_filters:
        selected = saved_filters.get(name)
    if selected not in allowed:
        selected = default
    context.update({
        name: selected,
        "chart_filter_name": name,
        "chart_filter_label": label,
        "chart_filter_value": selected,
        "chart_filter_options": options,
        "has_range_filter": "from" in request.GET or "to" in request.GET,
        "filter_from": request.GET.get("from", ""),
        "filter_to": request.GET.get("to", ""),
    })

    if module == "sales":
        rows = context.get("trend", [])
        metric = "money" if selected == "revenue" else "orders"
        prev_metric = "prev_money" if selected == "revenue" else "prev_orders"
        top = max((abs(float(row.get(key) or 0)) for row in rows
                   for key in (metric, prev_metric)), default=0)
        for row in rows:
            value, previous = row.get(metric) or 0, row.get(prev_metric)
            row["chart_value"], row["prev_chart_value"] = value, previous
            row["chart_h"] = round(abs(float(value)) / top * 100, 2) if top else 0
            row["prev_chart_h"] = (round(abs(float(previous)) / top * 100, 2)
                                   if previous is not None and top else 0)
    elif module == "cost":
        rows = context.get("trend", [])
        metric = "money" if selected == "cost" else "margin"
        prev_metric = "prev_money" if selected == "cost" else "prev_margin"
        top = max((abs(float(row.get(key) or 0)) for row in rows
                   for key in (metric, prev_metric)), default=0)
        for row in rows:
            value, previous = row.get(metric) or 0, row.get(prev_metric)
            row["chart_value"], row["prev_chart_value"] = value, previous
            row["chart_h"] = round(abs(float(value)) / top * 100, 2) if top else 0
            row["prev_chart_h"] = (round(abs(float(previous)) / top * 100, 2)
                                   if previous is not None and top else 0)
        context["chart_has_previous"] = any(row.get("prev_chart_value") is not None
                                             for row in rows)


def report_dimension_filters(request, module, include_country=True):
    """Resolve report dimensions and panel row counts."""
    params = request.POST if getattr(request, "_capture_snapshot", None) else request.GET
    categories = list(ProductionProductCategory.objects.order_by("name").values_list(
        "product_category_id", "name"))
    valid_categories = {row[0] for row in categories}
    category_ids = set()
    for value in params.getlist("category"):
        try:
            category_id = int(value)
        except (TypeError, ValueError):
            continue
        if category_id in valid_categories:
            category_ids.add(category_id)
    countries = REPORT_COUNTRIES if include_country else ()
    valid_countries = {code for code, _ in countries}
    country_codes = {
        value.strip().upper() for value in params.getlist("country")
        if value.strip().upper() in valid_countries
    }

    filters = {
        "category_ids": sorted(category_ids),
        "country_codes": sorted(country_codes),
        "include_country": include_country,
        "show_values": show_values(params, module),
        "show_options": SHOW_OPTIONS,
        "category_options": [{"id": key, "name": name} for key, name in categories],
        "country_options": [{"code": key, "name": name} for key, name in countries],
        "has_range_filter": "from" in params or "to" in params,
        "filter_from": params.get("from", ""),
        "filter_to": params.get("to", ""),
    }
    request._report_dimension_filters = filters
    return filters


def dimension_sql(filters, product_ref="d.ProductID", header_ref="h", order_ref=None):
    """Build product-category and ship-to-country predicates."""
    clauses, params = [], []
    category_ids = filters.get("category_ids", [])
    if category_ids:
        placeholders = ", ".join(["%s"] * len(category_ids))
        if product_ref:
            clauses.append(
                "EXISTS (SELECT 1 FROM Production_Product filter_product "
                "JOIN Production_ProductSubcategory filter_subcategory "
                "ON filter_subcategory.ProductSubcategoryID = filter_product.ProductSubcategoryID "
                f"WHERE filter_product.ProductID = {product_ref} "
                f"AND filter_subcategory.ProductCategoryID IN ({placeholders}))"
            )
        elif order_ref:
            clauses.append(
                "EXISTS (SELECT 1 FROM Sales_SalesOrderDetail filter_detail "
                "JOIN Production_Product filter_product "
                "ON filter_product.ProductID = filter_detail.ProductID "
                "JOIN Production_ProductSubcategory filter_subcategory "
                "ON filter_subcategory.ProductSubcategoryID = filter_product.ProductSubcategoryID "
                f"WHERE filter_detail.SalesOrderID = {order_ref} "
                f"AND filter_subcategory.ProductCategoryID IN ({placeholders}))"
            )
        if clauses:
            params.extend(category_ids)
    country_codes = filters.get("country_codes", [])
    if country_codes and header_ref:
        placeholders = ", ".join(["%s"] * len(country_codes))
        clauses.append(
            "EXISTS (SELECT 1 FROM Person_Address filter_address "
            "JOIN Person_StateProvince filter_state "
            "ON filter_state.StateProvinceID = filter_address.StateProvinceID "
            f"WHERE filter_address.AddressID = {header_ref}.ShipToAddressID "
            f"AND filter_state.CountryRegionCode IN ({placeholders}))"
        )
        params.extend(country_codes)
    return (" AND " + " AND ".join(clauses) if clauses else ""), params


def purchase_category_sql(filters, product_ref="pod.ProductID"):
    category_ids = filters.get("category_ids", [])
    if not category_ids:
        return "", []
    placeholders = ", ".join(["%s"] * len(category_ids))
    return (
        " AND EXISTS (SELECT 1 FROM Production_Product filter_product "
        "JOIN Production_ProductSubcategory filter_subcategory "
        "ON filter_subcategory.ProductSubcategoryID = filter_product.ProductSubcategoryID "
        f"WHERE filter_product.ProductID = {product_ref} "
        f"AND filter_subcategory.ProductCategoryID IN ({placeholders}))",
        category_ids,
    )


def _add_dimension_context(request, context, module):
    filters = getattr(request, "_report_dimension_filters", None)
    if filters:
        context.update(filters)
        _display_rows(context, module, filters["show_values"])


def snapshot_name(snapshot):
    """Return the editable report name, removing legacy filter text from old titles."""
    return snapshot.display_title


def _render_snapshot(request, module, template, snapshot):
    context = copy.deepcopy(snapshot.payload or {})
    context.pop("pipeline", None)
    title = snapshot_name(snapshot)
    filters = snapshot.filters if isinstance(snapshot.filters, dict) else {}
    if not filters:
        title_text = snapshot.title or ""
        names = (title_text.split(" | Categories: ", 1)[1].split(" | ", 1)[0].split(", ")
                 if " | Categories: " in title_text else [])
        ids = dict(ProductionProductCategory.objects.values_list("name", "product_category_id"))
        countries = (title_text.split(" | Countries: ", 1)[1].split(" | ", 1)[0].split(", ")
                     if " | Countries: " in title_text else [])
        filters = {"category_ids": [ids[name] for name in names if name in ids],
                   "country_codes": countries}
    filters.setdefault("category_ids", [])
    filters.setdefault("country_codes", [])
    if module == "cost":
        for row in context.get("biggest", []):
            value = row.get("date")
            if isinstance(value, str):
                try:
                    row["date"] = date.fromisoformat(value)
                except ValueError:
                    pass
    dimensions = report_dimension_filters(request, module, include_country=module != "cost")
    values = show_values(filters, module)
    _display_rows(context, module, values)
    context.update({
        "tab": module,
        "title": title,
        "through": snapshot.source_through,
        "window_label": snapshot.window_label,
        "prev_label": snapshot.prev_label,
        "custom": snapshot.custom,
        "period": snapshot.period,
        "w_from": snapshot.range_start.isoformat(),
        "w_to": snapshot.range_end.isoformat(),
        "snapshot": snapshot,
        "category_ids": filters["category_ids"],
        "country_codes": filters["country_codes"],
        "include_country": module != "cost",
        "category_options": dimensions["category_options"],
        "country_options": dimensions["country_options"],
        "show_values": values,
        "show_options": SHOW_OPTIONS,
        "filter_preview": False,
    })
    context["snapshots"] = list(Report.objects.filter(module=module))
    can_manage = request.user.has_perm("reporting.change_report")
    context["can_manage"] = can_manage
    context["manage_url"] = reverse("snapshot_list", args=[module])
    _chart_filter(request, module, context, saved_filters=filters)
    return ReportResult(template, context)


def _empty_report(request, module, template, title):
    context = {
        "tab": module,
        "title": title,
        "empty_message": "No data is available for the selected range.",
        "has_data": False,
        "w_from": request.GET.get("from", ""),
        "w_to": request.GET.get("to", ""),
        "snapshots": list(Report.objects.filter(module=module)),
        "can_manage": request.user.has_perm("reporting.change_report"),
        "manage_url": reverse("snapshot_list", args=[module]),
    }
    preview_snapshot = getattr(request, "_report_preview_snapshot", None)
    if preview_snapshot is not None:
        context.update({
            "snapshot": preview_snapshot,
            "title": request.GET.get("report_name") or snapshot_name(preview_snapshot),
            "filter_preview": True,
        })
    saved_filters = (preview_snapshot.filters
                     if preview_snapshot is not None
                     and isinstance(preview_snapshot.filters, dict) else None)
    _chart_filter(request, module, context, saved_filters=saved_filters)
    _add_dimension_context(request, context, context["tab"])
    return ReportResult(template, context)


def _report_response(request, module, template, context, window):
    """Save when this request is a Generate action, otherwise render the live data."""
    if getattr(request, "_capture_snapshot", None) == module:
        user = getattr(request, "user", None)
        generated_by = user if user is not None and getattr(user, "pk", None) else None
        payload = json.loads(json.dumps(
            {key: value for key, value in context.items() if key not in META_KEYS},
            cls=DjangoJSONEncoder))
        _chart_filter(request, module, context)
        try:
            compare_end = (window.trend_start - timedelta(microseconds=1)).date()
        except OverflowError:
            compare_end = window.trend_start.date()
        dimensions = request._report_dimension_filters
        generated_filters = {
            "category_ids": dimensions.get("category_ids", []),
            "country_codes": dimensions.get("country_codes", []),
        }
        generated_filters.update({f"show_{key}": value
                                  for key, value in dimensions["show_values"].items()})
        if module in CHART_FILTERS:
            generated_filters[CHART_FILTERS[module][0]] = context["chart_filter_value"]
        overwrite_id = request.POST.get(
            "overwrite_report", getattr(request, "_overwrite_report", ""))
        snapshot = None
        if overwrite_id:
            snapshot = Report.objects.filter(pk=overwrite_id, module=module).first()
            if snapshot is None:
                raise Http404
        saved_filters = dict(snapshot.filters or {}) if snapshot else {}
        saved_filters.pop("subcategory_ids", None)
        saved_filters.update(generated_filters)
        requested_name = request.POST.get("report_name", "").strip()
        title = requested_name or (
            snapshot_name(snapshot) if snapshot else context.get("title", ""))
        defaults = {
            "title": title,
            "filters": saved_filters,
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
        audit_changes = {}
        if snapshot is not None:
            new_start, new_end = window.trend_start.date(), window.last.date()
            if snapshot.title != title:
                audit_changes["title"] = [snapshot.title, title]
            if snapshot.range_start != new_start:
                audit_changes["range_start"] = [str(snapshot.range_start), str(new_start)]
            if snapshot.range_end != new_end:
                audit_changes["range_end"] = [str(snapshot.range_end), str(new_end)]
            if dict(snapshot.filters or {}) != saved_filters:
                audit_changes["filters"] = ["edited", "edited"]
            if snapshot.payload != payload:
                audit_changes["payload"] = ["edited", "edited"]
        if snapshot is None:
            snapshot = Report(module=module)
        snapshot.range_start = window.trend_start.date()
        snapshot.range_end = window.last.date()
        for key, value in defaults.items():
            setattr(snapshot, key, value)
        snapshot.save()
        if audit_changes and getattr(request, "method", "") == "POST":
            user = getattr(request, "user", None)
            username = (user.get_username()
                        if getattr(user, "pk", None) else "system")
            AuditLog.objects.create(
                user=user if getattr(user, "pk", None) else None,
                username=username, action="update", model="Report",
                object_pk=str(snapshot.pk), object_repr=str(snapshot)[:255],
                changes=audit_changes,
                ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"))
        request._captured_snapshot = snapshot
        return ReportResult("", redirect_to=f"{reverse(module)}?report={snapshot.pk}")
    preview_snapshot = getattr(request, "_report_preview_snapshot", None)
    if preview_snapshot is not None:
        context.update({
            "snapshot": preview_snapshot,
            "title": request.GET.get("report_name") or snapshot_name(preview_snapshot),
            "filter_preview": True,
        })
    context["snapshots"] = list(Report.objects.filter(module=module))
    context["can_manage"] = request.user.has_perm("reporting.change_report")
    context["manage_url"] = reverse("snapshot_list", args=[module])
    _chart_filter(request, module, context)
    _add_dimension_context(request, context, module)
    return ReportResult(template, context)


def _saved_report(request, module, template):
    if getattr(request, "_capture_snapshot", None):
        return None
    if request.GET.get("filter_preview") == "1":
        pk = request.GET.get("report")
        try:
            snapshot = Report.objects.get(pk=pk, module=module)
        except (TypeError, ValueError, Report.DoesNotExist):
            raise Http404
        request._report_preview_snapshot = snapshot
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
