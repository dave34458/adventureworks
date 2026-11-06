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
from ..constants import META_KEYS
from ..models import Report
from .validation import PayloadValidationError, validate_report_payload


REPORT_COUNTRIES = (
    ("AU", "Australia"), ("CA", "Canada"), ("FR", "France"),
    ("DE", "Germany"), ("GB", "United Kingdom"), ("US", "United States"),
)


@dataclass
class ReportResult:
    """A report page, with no HTTP response objects."""

    template: str
    context: dict = field(default_factory=dict)
    redirect_to: str | None = None


def _chart_filter(request, module, context):
    """Apply a presentation filter without changing the stored report payload."""
    filters = {
        "sales": ("sales_metric", "Sales trend", "revenue", [
            ("revenue", "Sales dollars"), ("orders", "Order count"),
        ]),
        "customer-profile": ("customer_segment", "Customer segment", "all", [
            ("all", "All customers"), ("store", "Stores"), ("individual", "Individuals"),
        ]),
        "cost": ("cost_metric", "Trend metric", "cost", [
            ("cost", "Cost of goods"), ("margin", "Gross margin"),
        ]),
    }
    if module not in filters:
        return
    name, label, default, options = filters[module]
    allowed = {value for value, _ in options}
    selected = request.GET.get(name, default)
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
    elif module == "customer-profile" and selected != "all":
        context["channels"] = [
            row for row in context.get("channels", [])
            if row.get("cls") == ("store" if selected == "store" else "online")
        ]
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


def report_dimension_filters(request, include_country=True):
    """Resolve live-report dimensions and their safe, parameterized SQL clauses."""
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
        "category_options": [{"id": key, "name": name} for key, name in categories],
        "country_options": [{"code": key, "name": name} for key, name in countries],
        "has_range_filter": "from" in params or "to" in params,
        "filter_from": params.get("from", ""),
        "filter_to": params.get("to", ""),
    }
    request._report_dimension_filters = filters
    return filters


def dimension_sql(filters, product_ref="d.ProductID", header_ref="h", order_ref=None):
    """Build line-category and sales ship-to-country predicates for report SQL."""
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


def _add_dimension_context(request, context):
    filters = getattr(request, "_report_dimension_filters", None)
    if filters:
        context.update(filters)


def _snapshot_title(title, filters):
    categories = {row["id"]: row["name"] for row in filters["category_options"]}
    countries = {row["code"]: row["name"] for row in filters["country_options"]}
    parts = []
    selected_categories = [categories[value] for value in filters["category_ids"]
                           if value in categories]
    if selected_categories:
        parts.append("Categories: " + ", ".join(selected_categories))
    selected_countries = [value for value in (code for code, _ in REPORT_COUNTRIES)
                          if value in filters["country_codes"] and value in countries]
    if selected_countries:
        parts.append("Countries: " + ", ".join(selected_countries))
    return f"{title} | " + " | ".join(parts) if parts else title


def _render_snapshot(request, module, template, snapshot):
    context = copy.deepcopy(snapshot.payload or {})
    title = snapshot.title or module
    category_ids = []
    country_codes = []
    if " | Categories: " in title:
        category_names = title.split(" | Categories: ", 1)[1].split(" | ", 1)[0]
        ids_by_name = dict(ProductionProductCategory.objects.values_list(
            "name", "product_category_id"))
        category_ids = [ids_by_name[name] for name in category_names.split(", ")
                        if name in ids_by_name]
    if " | Countries: " in title:
        selected = title.split(" | Countries: ", 1)[1].split(" | ", 1)[0].split(", ")
        country_codes = [code for code, _ in REPORT_COUNTRIES if code in selected]
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
        "title": title,
        "through": snapshot.source_through,
        "window_label": snapshot.window_label,
        "prev_label": snapshot.prev_label,
        "custom": snapshot.custom,
        "period": snapshot.period,
        "w_from": snapshot.range_start.isoformat(),
        "w_to": snapshot.range_end.isoformat(),
        "snapshot": snapshot,
        "category_ids": category_ids,
        "country_codes": country_codes,
        "include_country": module != "cost",
    })
    context["snapshots"] = list(Report.objects.filter(module=module))
    can_manage = request.user.has_perm("reporting.change_report")
    context["can_manage"] = can_manage
    context["edit_url"] = (reverse("snapshot_edit", args=[module, snapshot.pk])
                           if can_manage else "")
    context["manage_url"] = reverse("snapshot_list", args=[module])
    _chart_filter(request, module, context)
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
    _chart_filter(request, module, context)
    _add_dimension_context(request, context)
    return ReportResult(template, context)


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
            "title": _snapshot_title(
                context.get("title", ""),
                getattr(request, "_report_dimension_filters", {
                    "category_ids": [], "country_codes": [],
                    "category_options": [], "country_options": [],
                })),
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
        overwrite_id = request.POST.get(
            "overwrite_report", getattr(request, "_overwrite_report", ""))
        if overwrite_id:
            snapshot = Report.objects.filter(pk=overwrite_id, module=module).first()
            if snapshot is None:
                raise Http404
        else:
            snapshot = Report(module=module)
        snapshot.range_start = window.trend_start.date()
        snapshot.range_end = window.last.date()
        for key, value in defaults.items():
            setattr(snapshot, key, value)
        snapshot.save()
        request._captured_snapshot = snapshot
        return ReportResult("", redirect_to=f"{reverse(module)}?report={snapshot.pk}")
    context["snapshots"] = list(Report.objects.filter(module=module))
    context["can_manage"] = request.user.has_perm("reporting.change_report")
    context["manage_url"] = reverse("snapshot_list", args=[module])
    _chart_filter(request, module, context)
    _add_dimension_context(request, context)
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
