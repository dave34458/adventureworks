"""All views for the app: home, the central dashboard, the four reports, the saved-report
editor, and the generic table browser (list / detail / edit / delete / autocomplete)."""
import copy
import json
import re
from datetime import date, datetime, time, timedelta

from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required, permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.models import ProtectedError, Q, TextField
from django.db.models.functions import Cast
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views import View
from django.views.generic import DeleteView, DetailView, ListView, UpdateView

from .widgets import SearchSelect

from .forms import PrivacyAuthenticationForm, ReportEditForm
from .models import (
    AuditLog,
    PRIVACY_NOTICE_VERSION,
    PrivacyAcknowledgment,
    Report,
    SalesOrderHeader,
)
from .utils import csv_response, delta, money, rank, ring, window_for

META_KEYS = {
    "tab", "title", "through", "window_label", "prev_label", "custom", "period",
    "w_from", "w_to", "snapshot", "snapshots",
    "edit_url", "manage_url", "can_manage",
}

EDITABLE_KEYS = {
    "sales": ["kpis", "products", "low_products"],
    "customer-profile": [
        "kpis", "channels", "countries", "cities", "network", "frequency",
        "biggest", "new_legend", "ret_legend",
    ],
    "revenue-and-loss": [
        "kpis", "mix", "declining", "leaks", "products", "donut_mid",
    ],
    "cost": [
        "kpis", "pipeline", "mix", "vendors", "products", "reasons", "changes",
        "biggest", "performance", "recommendations", "donut_mid",
    ],
}

SECTION_LABELS = {
    "kpis": "KPI cards",
    "products": "Product rows",
    "low_products": "Low-performing product rows",
    "channels": "Buyer channels",
    "countries": "Countries",
    "cities": "Cities",
    "network": "Store network",
    "frequency": "Purchase frequency",
    "biggest": "Largest rows",
    "new_legend": "New-buyer legend",
    "ret_legend": "Returning-buyer legend",
    "mix": "Category mix",
    "declining": "Declining products",
    "leaks": "Below-cost products",
    "pipeline": "Buy / make / waste / sell",
    "vendors": "Vendors",
    "reasons": "Scrap reasons",
    "changes": "Standard-cost changes",
    "performance": "Cost performance",
    "recommendations": "Recommendations",
    "donut_mid": "Donut centre",
}

# ---------------------------------------------------------------------------
# Pages: home, the central dashboard, the four report panels, and the generic table
# browser for the remaining source tables. Each report is one view: it builds its own
# data and template.

def home(request):
    """Open the central dashboard, or explain that the user has no report access."""
    if any(request.user.has_perm(f"core.access_{slug.replace('-', '_')}")
           for slug in ("sales", "customer-profile", "revenue-and-loss", "cost")):
        return redirect("dashboard")
    return render(request, "core/no_access.html")


@login_not_required
def privacy(request):
    """The public data privacy notice (RA 10173), linked from the footer and the login form."""
    return render(request, "core/privacy.html",
                  {"title": "Data privacy notice", "version": PRIVACY_NOTICE_VERSION})


class PrivacyLogin(LoginView):
    """Login that requires acknowledging the privacy notice. Every successful login
    records the acknowledgment (current notice version + time) for the account."""

    template_name = "registration/login.html"
    form_class = PrivacyAuthenticationForm

    def form_valid(self, form):
        response = super().form_valid(form)
        PrivacyAcknowledgment.objects.update_or_create(
            user=self.request.user,
            defaults={"version": PRIVACY_NOTICE_VERSION, "acknowledged_at": timezone.now()},
        )
        return response


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
    if request.GET.get("export") == "csv":
        filename, header, rows = _csv_for(module, context)
        return csv_response(filename, header, rows)
    context["snapshots"] = list(Report.objects.filter(module=module))
    can_manage = request.user.has_perm("core.change_report")
    context["can_manage"] = can_manage
    context["edit_url"] = (reverse("snapshot_edit", args=[module, snapshot.pk])
                           if can_manage else "")
    context["manage_url"] = reverse("snapshot_list", args=[module])
    return render(request, template, context)


def _empty_report(request, module, template, title):
    return render(request, template, {
        "tab": module,
        "title": title,
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
            compare_end = (window.trend_start - timedelta(seconds=1)).date()
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
            "schema_version": 2,
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
        return redirect(f"{reverse(module)}?report={snapshot.pk}")
    context["snapshots"] = list(Report.objects.filter(module=module))
    context["can_manage"] = request.user.has_perm("core.change_report")
    context["manage_url"] = reverse("snapshot_list", args=[module])
    return render(request, template, context)


def _saved_report(request, module, template):
    if getattr(request, "_capture_snapshot", None):
        return None
    pk = request.GET.get("report")
    if not pk:
        return None
    try:
        snapshot = Report.objects.get(pk=pk, module=module)
    except (ValueError, Report.DoesNotExist):
        return None
    return _render_snapshot(request, module, template, snapshot)


def _saved_range(request, module, window):
    if getattr(request, "_capture_snapshot", None):
        return None
    return Report.objects.filter(
        module=module,
        range_start=window.trend_start.date(),
        range_end=window.last.date(),
    ).first()


def _csv_for(module, context):
    """Return (filename, header, rows) for the CSV export of a saved report."""
    label = context.get("window_label", "")
    prev_label = context.get("prev_label", "")
    rows = [["Period", label, "compare", prev_label]]
    rows += [["KPI", k.get("label", ""), k.get("value", ""),
              f"{k.get('delta')} \u00b7 {k.get('cap', '')}" if k.get("delta") else k.get("cap", "")]
             for k in context.get("kpis", [])]

    if module == "sales":
        rows += [["Sales trend", t.get("full", ""), t.get("money", ""),
                  f"{t.get('orders', '')} orders"] for t in context.get("trend", [])]
        rows += [["Sales trend (previous)", t.get("prev_full", ""), t.get("prev_money", ""),
                  f"{t.get('prev_orders', '')} orders"]
                 for t in context.get("trend", []) if t.get("prev_full")]
        rows += [["High-performing product", r.get("name", ""), r.get("value", ""),
                  f"{r.get('pct', '')}% of top product"] for r in context.get("products", [])]
        rows += [["Low-performing product", r.get("name", ""), r.get("value", ""),
                  f"{r.get('pct', '')}% of low list top"] for r in context.get("low_products", [])]
        return "sales.csv", ["Section", "Item", "Value", "Detail"], rows

    if module == "customer-profile":
        rows += [["Country", r.get("name", ""), r.get("value", ""), ""]
                 for r in context.get("countries", [])]
        rows += [["City", r.get("name", ""), r.get("value", ""), ""]
                 for r in context.get("cities", [])]
        rows += [["Store type", r.get("name", ""), r.get("value", ""), r.get("note", "")]
                 for r in context.get("network", [])]
        rows += [["Orders per customer", r.get("name", ""), r.get("value", ""), ""]
                 for r in context.get("frequency", [])]
        rows += [["Top customer", r.get("name", ""), r.get("rev", ""),
                  f"{r.get('orders', '')} orders \u00b7 {'store' if r.get('store') else 'individual'}"]
                 for r in context.get("biggest", [])]
        return "customer-profile.csv", ["Section", "Item", "Value", "Detail"], rows

    if module == "revenue-and-loss":
        rows += [["Revenue trend", t.get("full", ""), t.get("money", ""),
                  f"previous {t.get('prev_full', '')}: {t.get('prev_money', '')}"]
                 for t in context.get("rev_trend", []) if t.get("prev_full")]
        rows += [["Category", r.get("name", ""), r.get("money", ""),
                  f"{r.get('pct', '')}% of revenue \u00b7 {r.get('margin', '')}% margin"]
                 for r in context.get("mix", [])]
        rows += [["Declining product", r.get("name", ""), r.get("value", ""), r.get("note", "")]
                 for r in context.get("declining", [])]
        rows += [["Below-cost product", r.get("name", ""), r.get("value", ""), r.get("note", "")]
                 for r in context.get("leaks", [])]
        rows += [["Product", r.get("name", ""), r.get("rev", ""),
                  f"cost {r.get('cost', '')} \u00b7 profit {r.get('profit', '')} \u00b7 {r.get('margin', '')} margin"]
                 for r in context.get("products", [])]
        return "revenue-and-loss.csv", ["Section", "Item", "Value", "Detail"], rows

    rows += [["Pipeline", p.get("k", ""), p.get("big", ""), p.get("cap", "")]
             for p in context.get("pipeline", [])]
    rows += [["Category", r.get("name", ""), r.get("money", ""),
              f"{r.get('pct', '')}% of cost \u00b7 {r.get('margin', '')}% margin"]
             for r in context.get("mix", [])]
    rows += [["Vendor", r.get("name", ""), r.get("value", ""), r.get("note", "")]
             for r in context.get("vendors", [])]
    rows += [["Product", r.get("name", ""), r.get("value", ""), r.get("note", "")]
             for r in context.get("products", [])]
    rows += [["Scrap reason", r.get("name", ""), r.get("value", ""), r.get("note", "")]
             for r in context.get("reasons", [])]
    rows += [["Cost change", r.get("name", ""), r.get("value", ""), r.get("note", "")]
             for r in context.get("changes", [])]
    performance = context.get("performance")
    if performance:
        rows += [["Performance", "Cost of goods", performance.get("cost", ""), "share of revenue"],
                 ["Performance", "Gross margin", performance.get("margin", ""), "share of revenue"]]
    rows += [["Recommendation", r.get("title", ""), "", r.get("text", "")]
             for r in context.get("recommendations", [])]
    rows += [["Purchase order", f"PO{r.get('id', '')}", r.get("total", ""),
              f"{r.get('date', '')} \u00b7 {r.get('vendor', '')} \u00b7 {r.get('status', '')}"]
             for r in context.get("biggest", [])]
    return "cost.csv", ["Section", "Item", "Value", "Detail"], rows


@login_required
def dashboard(request):
    """Central dashboard: one integrated view of the four reports.

    The figures use the same sales-line base and report window as the Revenue and
    Cost reports; the category filter narrows every figure on the page so the
    comparisons stay like-for-like.
    """
    access = {
        "sales": request.user.has_perm("core.access_sales"),
        "customer_profile": request.user.has_perm("core.access_customer_profile"),
        "revenue_and_loss": request.user.has_perm("core.access_revenue_and_loss"),
        "cost": request.user.has_perm("core.access_cost"),
    }
    if not any(access.values()):
        return render(request, "core/no_access.html")

    with connection.cursor() as c:
        c.execute("SELECT ProductCategoryID, Name FROM Production_ProductCategory ORDER BY Name")
        categories = [{"id": row[0], "name": row[1]} for row in c.fetchall()]

    try:
        category_id = int(request.GET.get("category", ""))
    except (TypeError, ValueError):
        category_id = None
    selected_category = next((c for c in categories if c["id"] == category_id), None)
    if selected_category is None:
        category_id = None
    cat_sql = " AND pc.ProductCategoryID = %s" if category_id is not None else ""
    cat_params = [category_id] if category_id is not None else []

    show_revenue = access["sales"] or access["revenue_and_loss"]
    show_profit = access["revenue_and_loss"]
    show_cost = access["cost"] or access["revenue_and_loss"]
    show_customer = access["customer_profile"]
    metric_name = "Sales" if access["sales"] else "Revenue" if show_revenue else "Cost of goods"
    metric_lower = metric_name.lower()

    report_rows = (
        ("sales", "Sales report", "sales", "Sales, trends and high/low products"),
        ("customer_profile", "Customer profile report", "customer-profile",
         "Segments, frequency, spending and geography"),
        ("revenue_and_loss", "Revenue and loss report", "revenue-and-loss",
         "Revenue, gross profit, margin and below-cost sales"),
        ("cost", "Cost report", "cost", "Cost structure, contributors and recommendations"),
    )
    reports = [{"key": key, "name": name, "url": url, "text": text}
               for key, name, url, text in report_rows if access[key]]

    context = {
        "tab": "dashboard",
        "title": "Business performance dashboard",
        "access": access,
        "reports": reports,
        "categories": categories,
        "category_id": category_id,
        "selected_category": selected_category,
        "show_profit": show_profit,
        "has_data": False,
    }
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return render(request, "core/dashboard.html", context)

    with connection.cursor() as c:
        c.execute(
            f"""
            WITH lines AS (
                SELECT d.LineTotal AS rev,
                       d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) AS cost,
                       h.SalesOrderID AS order_id,
                       h.CustomerID AS customer_id,
                       CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
                       CASE WHEN d.LineTotal
                                 < d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)
                            THEN 1 ELSE 0 END AS below
                FROM Sales_SalesOrderDetail d
                JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
                JOIN Production_Product p ON p.ProductID = d.ProductID
                LEFT JOIN Production_ProductCostHistory ch
                  ON ch.ProductID = d.ProductID
                 AND h.OrderDate >= ch.StartDate
                 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
                LEFT JOIN Production_ProductSubcategory sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
                LEFT JOIN Production_ProductCategory pc ON pc.ProductCategoryID = sc.ProductCategoryID
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s{cat_sql}
            )
            SELECT
              COALESCE(SUM(CASE WHEN side = 'cur' THEN rev END), 0) AS rev,
              COALESCE(SUM(CASE WHEN side = 'prev' THEN rev END), 0) AS rev_prev,
              COALESCE(SUM(CASE WHEN side = 'cur' THEN cost END), 0) AS cogs,
              COALESCE(SUM(CASE WHEN side = 'prev' THEN cost END), 0) AS cogs_prev,
              COUNT(DISTINCT CASE WHEN side = 'cur' THEN order_id END) AS orders,
              COUNT(DISTINCT CASE WHEN side = 'prev' THEN order_id END) AS orders_prev,
              COUNT(DISTINCT CASE WHEN side = 'cur' THEN customer_id END) AS customers,
              COUNT(DISTINCT CASE WHEN side = 'prev' THEN customer_id END) AS customers_prev,
              COALESCE(SUM(CASE WHEN side = 'cur' THEN below ELSE 0 END), 0) AS below_n,
              COALESCE(SUM(CASE WHEN side = 'cur' AND below = 1 THEN cost - rev ELSE 0 END), 0) AS below_short
            FROM lines
            """,
            [w.trend_start, w.window_start, w.last] + cat_params,
        )
        (rev, rev_prev, cogs, cogs_prev, orders, orders_prev,
         customers, customers_prev, below_n, below_short) = c.fetchone()

    rev, rev_prev = float(rev or 0), float(rev_prev or 0)
    cogs, cogs_prev = float(cogs or 0), float(cogs_prev or 0)
    orders, orders_prev = int(orders or 0), int(orders_prev or 0)
    customers, customers_prev = int(customers or 0), int(customers_prev or 0)
    below_n = int(below_n or 0)
    short = float(below_short or 0)
    profit = rev - cogs
    profit_prev = rev_prev - cogs_prev
    margin = round(profit / rev * 100, 1) if rev else 0.0
    prev_margin = round(profit_prev / rev_prev * 100, 1) if rev_prev else 0.0

    kpis = []

    def add_kpi(label, value, change, cap):
        kpis.append({"label": label, "value": value, "delta": change[0],
                     "dir": change[1], "cap": cap})

    if access["sales"]:
        add_kpi("Total sales", money(rev), delta(rev, rev_prev),
                "merchandise, excl. tax & freight")
        add_kpi("Orders", f"{orders:,}", delta(orders, orders_prev), "orders in the period")
    elif access["revenue_and_loss"]:
        add_kpi("Total revenue", money(rev), delta(rev, rev_prev),
                "merchandise, excl. tax & freight")
    if show_profit:
        add_kpi("Gross profit", money(profit), delta(profit, profit_prev),
                f"{margin}% margin \u00b7 was {prev_margin}%")
    if show_cost:
        add_kpi("Cost of goods", money(cogs), delta(cogs, cogs_prev),
                "at standard cost on the sale date")
    if show_customer:
        add_kpi("Active customers", f"{customers:,}", delta(customers, customers_prev),
                "distinct buyers")
    if show_profit:
        add_kpi("Below-cost shortfall", money(short), (None, None),
                f"{below_n:,} sales lines below standard cost")

    trend = []
    margin_chart = None
    cur_series = []
    prev_series = []
    if show_revenue or show_cost:
        metric_key = "rev" if show_revenue else "cogs"
        with connection.cursor() as c:
            c.execute(
                f"""
                SELECT substr(h.OrderDate, 1, 7) AS month,
                       CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
                       SUM(d.LineTotal) AS rev,
                       SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cogs,
                       COUNT(DISTINCT h.SalesOrderID) AS orders
                FROM Sales_SalesOrderDetail d
                JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
                JOIN Production_Product p ON p.ProductID = d.ProductID
                LEFT JOIN Production_ProductCostHistory ch
                  ON ch.ProductID = d.ProductID
                 AND h.OrderDate >= ch.StartDate
                 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
                LEFT JOIN Production_ProductSubcategory sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
                LEFT JOIN Production_ProductCategory pc ON pc.ProductCategoryID = sc.ProductCategoryID
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s{cat_sql}
                GROUP BY month, side
                ORDER BY month
                """,
                [w.trend_start, w.window_start, w.last] + cat_params,
            )
            series = [
                {"month": datetime.strptime(month, "%Y-%m"), "side": side,
                 "rev": float(rev or 0), "cogs": float(cogs or 0), "orders": int(orders or 0)}
                for month, side, rev, cogs, orders in c.fetchall()
            ]
        cur_series = [row for row in series if row["side"] == "cur"]
        prev_series = [row for row in series if row["side"] == "prev"]
        top = max((row[metric_key] for row in cur_series + prev_series), default=0)
        for i, row in enumerate(cur_series):
            prev = prev_series[i] if i < len(prev_series) else None
            value = row[metric_key]
            title = f"{row['month']:%b %Y} \u00b7 {money(value)}"
            if access["sales"]:
                title += f" \u00b7 {row['orders']:,} orders"
            if show_profit and row["rev"]:
                title += f" \u00b7 {round((row['rev'] - row['cogs']) / row['rev'] * 100, 1)}% margin"
            if prev:
                title += f" \u00b7 previous {prev['month']:%b %Y}: {money(prev[metric_key])}"
            trend.append({
                "label": f"{row['month']:%b}",
                "full": f"{row['month']:%b %Y}",
                "money": money(value),
                "height": max(round(value / top * 100), 2) if top else 0,
                "title": title,
                "prev_h": (max(round(prev[metric_key] / top * 100), 2)
                           if prev and prev[metric_key] and top else 0),
            })

        def margin_of(row):
            value = row["rev"]
            return round((value - row["cogs"]) / value * 100, 1) if value else 0.0

        if show_profit and cur_series:
            n = len(cur_series)
            cur_margins = [margin_of(row) for row in cur_series]
            prev_margins = [margin_of(row) for row in prev_series[:n]]
            high = max(cur_margins + prev_margins + [0])
            m_max = 60 if high <= 60 else (int(high / 10) + 1) * 10
            px_w, px_h, pad_l, pad_r, pad_t, pad_b = 960, 260, 52, 16, 12, 28
            plot_w, plot_h = px_w - pad_l - pad_r, px_h - pad_t - pad_b
            xs = [round(pad_l + i * plot_w / max(n - 1, 1), 1) for i in range(n)]

            def y_at(value):
                return round(pad_t + (1 - value / m_max) * plot_h, 1)

            ticks = [{"y": y_at(value), "label": f"{value:.0f}%"}
                     for value in (0, m_max / 2, m_max)]
            step = max(1, (n + 11) // 12)
            xticks = [{"x": xs[i], "label": f"{cur_series[i]['month']:%b}"}
                      for i in range(0, n, step)]
            cur_pts = " ".join(f"{xs[i]},{y_at(cur_margins[i])}" for i in range(n))
            prev_pts = " ".join(f"{xs[i]},{y_at(prev_margins[i])}"
                                for i in range(len(prev_margins)))
            dots = []
            for i, row in enumerate(cur_series):
                gross = row["rev"] - row["cogs"]
                dots.append({"x": xs[i], "y": y_at(cur_margins[i]),
                             "t": f"{row['month']:%b %Y} \u00b7 margin {cur_margins[i]}%"
                                  f" \u00b7 gross profit {money(gross)}"})
            prev_dots = [{"x": xs[i], "y": y_at(prev_margins[i]),
                          "t": f"{prev_series[i]['month']:%b %Y} \u00b7 margin {prev_margins[i]}%"}
                         for i in range(len(prev_margins))]
            margin_chart = {"ticks": ticks, "xticks": xticks, "cur_pts": cur_pts,
                            "prev_pts": prev_pts, "dots": dots, "prev_dots": prev_dots}

        if access["sales"]:
            trend_title = "Sales trend by month"
        elif access["revenue_and_loss"]:
            trend_title = "Revenue trend by month"
        else:
            trend_title = "Cost of goods sold by month"
    else:
        trend_title = ""

    if access["sales"]:
        category_title = "Revenue contribution by category"
    else:
        category_title = "Revenue contribution by category" if show_revenue else "Cost distribution by category"
    category_mid_label = "revenue" if show_revenue else "cost of goods"

    products = []
    products_top = []
    category_rows = []
    if show_revenue or show_cost:
        order_expr = ("SUM(d.LineTotal)" if show_revenue
                      else "SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost))")
        with connection.cursor() as c:
            c.execute(
                f"""
                SELECT p.ProductID, p.Name, pc.Name,
                       SUM(d.OrderQty) AS units,
                       SUM(d.LineTotal) AS rev,
                       SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cost
                FROM Sales_SalesOrderDetail d
                JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
                JOIN Production_Product p ON p.ProductID = d.ProductID
                LEFT JOIN Production_ProductCostHistory ch
                  ON ch.ProductID = d.ProductID
                 AND h.OrderDate >= ch.StartDate
                 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
                LEFT JOIN Production_ProductSubcategory sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
                LEFT JOIN Production_ProductCategory pc ON pc.ProductCategoryID = sc.ProductCategoryID
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s{cat_sql}
                GROUP BY p.ProductID, p.Name, pc.Name
                ORDER BY {order_expr} DESC
                LIMIT 10
                """,
                [w.trend_start, w.last] + cat_params,
            )
            raw_products = c.fetchall()

        metric_total = rev if show_revenue else cogs
        top_product = max((float(rev if show_revenue else cost) for _, _, _, _, rev, cost in raw_products),
                          default=0)
        for product_id, name, category, units, revenue, cost in raw_products:
            value = float(revenue if show_revenue else cost or 0)
            margin_pct = (round((float(revenue) - float(cost)) / float(revenue) * 100, 1)
                          if revenue else 0.0)
            products.append({
                "id": product_id,
                "name": name,
                "category": category or "Uncategorized",
                "units": f"{int(units or 0):,}",
                "value": money(value),
                "profit": money(float(revenue or 0) - float(cost or 0)),
                "margin": f"{margin_pct:.1f}%",
                "pct": max(round(value / top_product * 100), 2) if top_product else 0,
                "share": round(value / metric_total * 100, 1) if metric_total else 0,
            })
        products_top = products[:6]

        if category_id is None:
            with connection.cursor() as c:
                c.execute(
                    f"""
                    SELECT pc.ProductCategoryID, pc.Name,
                           SUM(d.LineTotal) AS rev,
                           SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cost
                    FROM Sales_SalesOrderDetail d
                    JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
                    JOIN Production_Product p ON p.ProductID = d.ProductID
                        LEFT JOIN Production_ProductCostHistory ch
                      ON ch.ProductID = d.ProductID
                     AND h.OrderDate >= ch.StartDate
                     AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
                    LEFT JOIN Production_ProductSubcategory sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
                    LEFT JOIN Production_ProductCategory pc ON pc.ProductCategoryID = sc.ProductCategoryID
                    WHERE h.OrderDate >= %s AND h.OrderDate <= %s
                    GROUP BY pc.ProductCategoryID, pc.Name
                    ORDER BY {order_expr} DESC
                    """,
                    [w.trend_start, w.last],
                )
                raw_categories = c.fetchall()

            palette = ["c1", "c2", "c3", "c4"]
            total_metric = sum(float(rev if show_revenue else cost or 0)
                               for _, _, rev, cost in raw_categories)
            for i, (cat_id, name, revenue, cost) in enumerate(raw_categories):
                value = float(revenue if show_revenue else cost or 0)
                pct = round(value / total_metric * 100) if total_metric else 0
                margin_pct = (round((float(revenue) - float(cost)) / float(revenue) * 100, 1)
                              if revenue else 0.0)
                note = f"{name} \u00b7 {money(value)} \u00b7 {pct}% of {metric_lower}"
                if show_profit:
                    note += f" \u00b7 {margin_pct:.1f}% margin"
                category_rows.append({
                    "id": cat_id,
                    "name": name or "Uncategorized",
                    "value": money(value),
                    "pct": pct,
                    "cls": palette[i % len(palette)],
                    "margin": f"{margin_pct:.1f}",
                    "t": note,
                })
            category_rows = ring(category_rows)

    customer_mix = None
    if show_customer:
        with connection.cursor() as c:
            c.execute(
                f"""
                SELECT CASE WHEN cu.StoreID IS NULL THEN 0 ELSE 1 END AS is_store,
                       SUM(d.LineTotal) AS rev,
                       COUNT(DISTINCT h.SalesOrderID) AS orders,
                       COUNT(DISTINCT h.CustomerID) AS customers
                FROM Sales_SalesOrderDetail d
                JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
                JOIN Sales_Customer cu ON cu.CustomerID = h.CustomerID
                JOIN Production_Product p ON p.ProductID = d.ProductID
                LEFT JOIN Production_ProductSubcategory sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
                LEFT JOIN Production_ProductCategory pc ON pc.ProductCategoryID = sc.ProductCategoryID
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s{cat_sql}
                GROUP BY is_store
                """,
                [w.trend_start, w.last] + cat_params,
            )
            raw_mix = c.fetchall()
        if raw_mix:
            rows = {0: {"rev": 0.0, "orders": 0, "customers": 0},
                    1: {"rev": 0.0, "orders": 0, "customers": 0}}
            for is_store, revenue, order_count, customer_count in raw_mix:
                rows[int(is_store)] = {"rev": float(revenue or 0),
                                       "orders": int(order_count or 0),
                                       "customers": int(customer_count or 0)}
            total_rev = rows[0]["rev"] + rows[1]["rev"]
            total_buyers = rows[0]["customers"] + rows[1]["customers"]
            store_pct = round(rows[1]["rev"] / total_rev * 100) if total_rev else 0
            store_buyers_pct = round(rows[1]["customers"] / total_buyers * 100) if total_buyers else 0
            customer_mix = {"total": money(total_rev), "channels": [
                {"name": "Individuals", "cls": "online", "pct": 100 - store_pct,
                 "buyers_pct": 100 - store_buyers_pct, "money": money(rows[0]["rev"]),
                 "customers": f"{rows[0]['customers']:,}",
                 "aov": money(rows[0]["rev"] / rows[0]["orders"] if rows[0]["orders"] else None)},
                {"name": "Stores", "cls": "store", "pct": store_pct,
                 "buyers_pct": store_buyers_pct, "money": money(rows[1]["rev"]),
                 "customers": f"{rows[1]['customers']:,}",
                 "aov": money(rows[1]["rev"] / rows[1]["orders"] if rows[1]["orders"] else None)},
            ]}

    insights = []
    if show_revenue or show_cost:
        metric_value = rev if show_revenue else cogs
        metric_prev = rev_prev if show_revenue else cogs_prev
        change = delta(metric_value, metric_prev)[0]
        best = max(cur_series, key=lambda row: row[metric_key], default=None) if cur_series else None
        if best:
            lead = (f"{metric_name} is {change} versus {w.prev_label}."
                    if change else f"{metric_name} has no prior-period comparison.")
            insights.append({"title": f"{metric_name} trend",
                             "text": f"{lead} The strongest month was {best['month']:%b %Y} "
                                     f"at {money(best[metric_key])}."})
    if show_profit:
        points = margin - prev_margin
        below = (f"{below_n:,} sales lines sold below standard cost, a {money(short)} shortfall."
                 if below_n else "No sales line sold below standard cost.")
        insights.append({"title": "Profitability",
                         "text": f"Gross margin is {margin}% ({points:+.1f} pts versus {w.prev_label}). {below}"})
    if show_revenue or show_cost:
        if selected_category and products:
            top = products[0]
            insights.append({
                "title": "Category mix",
                "text": f"{top['name']} is the largest product in {selected_category['name']} "
                        f"at {top['value']} ({top['share']}% of the category's {metric_lower}).",
            })
        elif category_rows:
            top = category_rows[0]
            text = f"{top['name']} contributes {top['pct']}% of {metric_lower}."
            if show_profit:
                text += f" Its gross margin is {top['margin']}%."
            insights.append({"title": "Category mix", "text": text})
    if customer_mix:
        stores = customer_mix["channels"][1]
        insights.append({
            "title": "Customer mix",
            "text": f"{customers:,} customers bought in this period; stores account for "
                    f"{stores['pct']}% of revenue and {stores['buyers_pct']}% of buyers.",
        })

    context.update({
        "has_data": True,
        "kpis": kpis,
        "trend": trend,
        "trend_title": trend_title,
        "metric_name": metric_name,
        "metric_lower": metric_lower,
        "margin_chart": margin_chart,
        "products": products,
        "products_top": products_top,
        "category_rows": category_rows,
        "category_title": category_title,
        "category_total": money(rev if show_revenue else cogs),
        "category_mid_label": category_mid_label,
        "customer_mix": customer_mix,
        "insights": insights,
        "period": "the selected range" if w.custom else "the last 12 months",
        "through": w.last,
        "window_label": w.label,
        "prev_label": w.prev_label,
        "custom": w.custom,
        "w_from": w.trend_start.strftime("%Y-%m-%d"),
        "w_to": w.last.strftime("%Y-%m-%d"),
    })
    return render(request, "core/dashboard.html", context)


@permission_required("core.access_sales", raise_exception=True)
def sales(request):
    """Sales report: one aggregate query per panel, all windows anchored to the
    data's own last order date (the sample data is historical, so "today" would be empty)."""
    saved = _saved_report(request, "sales", "core/sales/report.html")
    if saved:
        return saved
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return _empty_report(request, "sales", "core/sales/report.html", "Sales report")
    saved = _saved_range(request, "sales", w)
    if saved:
        return _render_snapshot(request, "sales", "core/sales/report.html", saved)

    cur_lo, cur_hi = w.trend_start, w.last
    prev_lo, prev_hi = w.window_start, w.trend_start

    with connection.cursor() as c:  # chart 1: total sales and summary KPIs
        c.execute(
            """
            WITH lines AS (
                SELECT h.OrderDate, h.SalesOrderID, h.CustomerID,
                       d.LineTotal AS rev
                FROM Sales_SalesOrderDetail d
                JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            )
            SELECT
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate <= %s THEN rev END), 0) AS rev,
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate < %s THEN rev END), 0) AS rev_prev,
              COUNT(DISTINCT CASE WHEN OrderDate >= %s AND OrderDate <= %s THEN SalesOrderID END) AS orders,
              COUNT(DISTINCT CASE WHEN OrderDate >= %s AND OrderDate < %s THEN SalesOrderID END) AS orders_prev,
              COUNT(DISTINCT CASE WHEN OrderDate >= %s AND OrderDate <= %s THEN CustomerID END) AS customers,
              COUNT(DISTINCT CASE WHEN OrderDate >= %s AND OrderDate < %s THEN CustomerID END) AS customers_prev
            FROM lines
            WHERE OrderDate >= %s
            """,
            [cur_lo, cur_hi, prev_lo, prev_hi, cur_lo, cur_hi, prev_lo, prev_hi,
             cur_lo, cur_hi, prev_lo, prev_hi, w.window_start],
        )
        rev, rev_prev, orders, orders_prev, customers, customers_prev = c.fetchone()

    aov = (rev / orders) if orders else None
    aov_prev = (rev_prev / orders_prev) if orders_prev else None

    kpis = []
    for label, value, change, cap in (
        ("Total sales", money(rev), delta(rev, rev_prev), "merchandise, excl. tax & freight"),
        ("Orders", f"{orders:,}", delta(orders, orders_prev), "sales orders placed"),
        ("Avg order value", money(aov), delta(aov, aov_prev), "sales per order"),
        ("Customers", f"{customers or 0:,}", delta(customers, customers_prev), "distinct buyers"),
    ):
        kpis.append({"label": label, "value": value, "delta": change[0], "dir": change[1], "cap": cap})

    with connection.cursor() as c:  # chart 2: sales trend and distribution, current vs previous window
        c.execute(
            """
            SELECT substr(h.OrderDate, 1, 7) AS month,
                   CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
                   SUM(d.LineTotal) AS rev,
                   COUNT(DISTINCT h.SalesOrderID) AS orders
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY month, side
            ORDER BY month
            """,
            [w.trend_start, w.window_start, w.last],
        )
        series = [
            {"month": datetime.strptime(m, "%Y-%m"), "side": side, "rev": rev, "orders": orders}
            for m, side, rev, orders in c.fetchall()
        ]
    months = [m for m in series if m["side"] == "cur"]
    prev_months = [m for m in series if m["side"] == "prev"]
    top = max((float(m["rev"] or 0) for m in months + prev_months), default=0)
    trend = [
        {
            "label": m["month"].strftime("%b"),
            "full": m["month"].strftime("%b %Y"),
            "money": money(m["rev"]),
            "orders": f"{m['orders']:,}",
            "height": max(round(float(m["rev"] or 0) / top * 100), 2) if top else 0,
            "prev_full": prev_months[i]["month"].strftime("%b %Y") if i < len(prev_months) else "",
            "prev_money": money(prev_months[i]["rev"]) if i < len(prev_months) else "\u2014",
            "prev_orders": f"{prev_months[i]['orders']:,}" if i < len(prev_months) else "\u2014",
            "prev_h": (max(round(float(prev_months[i]["rev"] or 0) / top * 100), 2)
                       if i < len(prev_months) and prev_months[i]["rev"] and top else 0),
        }
        for i, m in enumerate(months)
    ]

    with connection.cursor() as c:  # chart 3: sales by product, high performers
        c.execute(
            """
            SELECT pr.Name, SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product pr ON pr.ProductID = d.ProductID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY pr.Name
            ORDER BY rev DESC
            LIMIT 8
            """,
            [cur_lo, cur_hi],
        )
        products = rank([{"name": name, "rev": rev} for name, rev in c.fetchall()],
                        "name", "rev", money)

    with connection.cursor() as c:  # chart 4: sales by product, low performers
        c.execute(
            """
            SELECT pr.Name, SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product pr ON pr.ProductID = d.ProductID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY pr.Name
            ORDER BY rev ASC
            LIMIT 6
            """,
            [cur_lo, cur_hi],
        )
        low_products = rank([{"name": name, "rev": rev} for name, rev in c.fetchall()],
                            "name", "rev", money)

    if request.GET.get("export") == "csv":
        rows = [["Period", w.label, "compare", w.prev_label]]
        rows += [["KPI", k["label"], k["value"], f"{k['delta']} \u00b7 {k['cap']}" if k["delta"] else k["cap"]]
                 for k in kpis]
        rows += [["Sales trend", t["full"], t["money"], f"{t['orders']} orders"]
                 for t in trend]
        rows += [["Sales trend (previous)", t["prev_full"], t["prev_money"], f"{t['prev_orders']} orders"]
                 for t in trend if t["prev_full"]]
        rows += [["High-performing product", r["name"], r["value"], f"{r['pct']}% of top product"]
                 for r in products]
        rows += [["Low-performing product", r["name"], r["value"], f"{r['pct']}% of low list top"]
                 for r in low_products]
        return csv_response("sales.csv", ["Section", "Item", "Value", "Detail"], rows)

    return _report_response(request, "sales", "core/sales/report.html", {
        "tab": "sales",
        "title": "Sales report",
        "kpis": kpis,
        "trend": trend,
        "products": products,
        "low_products": low_products,
        "through": w.last,
        "window_label": w.label,
        "prev_label": w.prev_label,
        "custom": w.custom,
        "period": "the selected range" if w.custom else "the last 12 months",
        "w_from": w.trend_start.strftime("%Y-%m-%d"),
        "w_to": w.last.strftime("%Y-%m-%d"),
    }, w)


@permission_required("core.access_customer_profile", raise_exception=True)
def customer_profile(request):
    """Customer profile report: who buys (individuals vs stores), how often they come
    back, where they are, and which stores make up the B2B side."""
    saved = _saved_report(request, "customer-profile", "core/customer-profile/report.html")
    if saved:
        return saved
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return _empty_report(request, "customer-profile", "core/customer-profile/report.html",
                             "Customer profile report")
    saved = _saved_range(request, "customer-profile", w)
    if saved:
        return _render_snapshot(request, "customer-profile",
                                "core/customer-profile/report.html", saved)

    cur_lo, cur_hi = w.trend_start, w.last
    prev_lo, prev_hi = w.window_start, w.trend_start

    with connection.cursor() as c:  # chart 1: the five KPI cards
        c.execute(
            """
            WITH firsts AS (
                SELECT CustomerID, MIN(OrderDate) AS first_date
                FROM Sales_SalesOrderHeader GROUP BY CustomerID
            ), lines AS (
                SELECT h.CustomerID, h.OrderDate,
                       d.LineTotal AS rev
                FROM Sales_SalesOrderDetail d
                JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            )
            SELECT
              COALESCE(SUM(CASE WHEN l.OrderDate >= %s AND l.OrderDate <= %s
                                THEN l.rev END), 0) AS rev,
              COALESCE(SUM(CASE WHEN l.OrderDate >= %s AND l.OrderDate < %s
                                THEN l.rev END), 0) AS rev_prev,
              COUNT(DISTINCT CASE WHEN l.OrderDate >= %s AND l.OrderDate <= %s
                                  THEN l.CustomerID END) AS actives,
              COUNT(DISTINCT CASE WHEN l.OrderDate >= %s AND l.OrderDate < %s
                                  THEN l.CustomerID END) AS actives_prev,
              COALESCE(SUM(CASE WHEN l.OrderDate >= %s AND l.OrderDate <= %s
                                 AND f.first_date >= %s AND f.first_date <= %s
                                THEN l.rev END), 0) AS new_rev
            FROM lines l
            JOIN firsts f ON f.CustomerID = l.CustomerID
            WHERE l.OrderDate >= %s
            """,
            [cur_lo, cur_hi, prev_lo, prev_hi, cur_lo, cur_hi, prev_lo, prev_hi,
             cur_lo, cur_hi, cur_lo, cur_hi, w.window_start],
        )
        rev, rev_prev, actives, actives_prev, new_rev = c.fetchone()

        c.execute(  # how many customers were first seen in each window
            """
            SELECT
              COALESCE(SUM(CASE WHEN first_date >= %s AND first_date <= %s THEN 1 ELSE 0 END), 0),
              COALESCE(SUM(CASE WHEN first_date >= %s AND first_date < %s THEN 1 ELSE 0 END), 0)
            FROM (
                SELECT CustomerID, MIN(OrderDate) AS first_date
                FROM Sales_SalesOrderHeader GROUP BY CustomerID
            )
            """,
            [cur_lo, cur_hi, prev_lo, prev_hi],
        )
        new_count, prev_new = c.fetchone()

        c.execute(  # customers active now who also bought in the compare window
            """
            SELECT COUNT(DISTINCT h.CustomerID)
            FROM Sales_SalesOrderHeader h
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
              AND h.CustomerID IN (
                  SELECT CustomerID FROM Sales_SalesOrderHeader
                  WHERE OrderDate >= %s AND OrderDate < %s
              )
            """,
            [cur_lo, cur_hi, prev_lo, prev_hi],
        )
        kept = c.fetchone()[0] or 0

    new_count, prev_new = new_count or 0, prev_new or 0
    actives, actives_prev = actives or 0, actives_prev or 0
    rev, rev_prev = rev or 0, rev_prev or 0
    new_rev = new_rev or 0
    repeat = actives - new_count
    repeat_rev = rev - new_rev

    with connection.cursor() as c:  # chart 2: buyers per month, newest first-seen buyers split out
        c.execute(
            """
            SELECT substr(OrderDate, 1, 7) AS month, COUNT(DISTINCT CustomerID) AS act
            FROM Sales_SalesOrderHeader
            WHERE OrderDate >= %s AND OrderDate <= %s
            GROUP BY month
            ORDER BY month
            """,
            [cur_lo, cur_hi],
        )
        months = [{"month": datetime.strptime(m, "%Y-%m"), "act": act}
                  for m, act in c.fetchall()]

        c.execute(
            """
            SELECT substr(first_date, 1, 7) AS month, COUNT(*)
            FROM (
                SELECT CustomerID, MIN(OrderDate) AS first_date
                FROM Sales_SalesOrderHeader GROUP BY CustomerID
            )
            WHERE first_date >= %s AND first_date <= %s
            GROUP BY month
            """,
            [cur_lo, cur_hi],
        )
        new_per_month = {datetime.strptime(m, "%Y-%m"): n for m, n in c.fetchall()}
    top = max((m["act"] for m in months), default=0)
    growth = [
        {
            "label": m["month"].strftime("%b"), "full": m["month"].strftime("%b %Y"),
            "act": f"{m['act']:,}", "nw": f"{new_per_month.get(m['month'], 0):,}",
            "ret": f"{m['act'] - new_per_month.get(m['month'], 0):,}",
            "new_h": round(new_per_month.get(m["month"], 0) / top * 100, 2) if top else 0,
            "ret_h": round((m["act"] - new_per_month.get(m["month"], 0)) / top * 100, 2) if top else 0,
        }
        for m in months
    ]

    with connection.cursor() as c:  # chart 3: individuals vs stores
        c.execute(
            """
            SELECT
              COALESCE(SUM(CASE WHEN cu.StoreID IS NULL
                                THEN d.LineTotal END), 0) AS ind_rev,
              COALESCE(SUM(CASE WHEN cu.StoreID IS NOT NULL
                                THEN d.LineTotal END), 0) AS st_rev,
              COUNT(DISTINCT CASE WHEN cu.StoreID IS NULL THEN h.SalesOrderID END) AS ind_orders,
              COUNT(DISTINCT CASE WHEN cu.StoreID IS NOT NULL THEN h.SalesOrderID END) AS st_orders,
              COUNT(DISTINCT CASE WHEN cu.StoreID IS NULL THEN h.CustomerID END) AS ind_customers,
              COUNT(DISTINCT CASE WHEN cu.StoreID IS NOT NULL THEN h.CustomerID END) AS st_customers
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Sales_Customer cu ON cu.CustomerID = h.CustomerID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            """,
            [cur_lo, cur_hi],
        )
        (ind_rev, st_rev, ind_orders, st_orders, ind_n, st_n) = c.fetchone()

    ind_rev, st_rev = ind_rev or 0, st_rev or 0
    ind_n, st_n = ind_n or 0, st_n or 0
    st_share = round(float(st_rev) / float(rev) * 100) if rev else 0
    buyers = (ind_n + st_n) or 1
    ind_buyers = round(ind_n / buyers * 100)
    channels = [
        {"name": "Individuals", "pct": 100 - st_share, "cust_pct": ind_buyers, "cls": "online",
         "money": money(ind_rev), "customers": f"{ind_n:,}",
         "aov": money((ind_rev / ind_orders) if ind_orders else None)},
        {"name": "Stores", "pct": st_share, "cust_pct": 100 - ind_buyers, "cls": "store",
         "money": money(st_rev), "customers": f"{st_n:,}",
         "aov": money((st_rev / st_orders) if st_orders else None)},
    ]

    with connection.cursor() as c:  # chart 4: revenue by country (feeds the map and the list)
        c.execute(
            """
            SELECT co.Name, SUM(d.LineTotal) AS rev,
                   COUNT(DISTINCT h.SalesOrderID) AS orders
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Person_Address a ON a.AddressID = h.ShipToAddressID
            JOIN Person_StateProvince sp ON sp.StateProvinceID = a.StateProvinceID
            JOIN Person_CountryRegion co ON co.CountryRegionCode = sp.CountryRegionCode
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY co.Name
            ORDER BY rev DESC
            LIMIT 6
            """,
            [cur_lo, cur_hi],
        )
        country_rows = [{"name": name, "rev": rev, "orders": orders}
                        for name, rev, orders in c.fetchall()]
    countries = rank(country_rows, "name", "rev", money)
    geo = {
        "United States": ("US", 39.8, -98.6),
        "Canada": ("CA", 56.1, -106.3),
        "United Kingdom": ("UK", 54.0, -2.0),
        "France": ("FR", 46.6, 2.4),
        "Germany": ("DE", 51.2, 10.4),
        "Australia": ("AU", -25.3, 134.5),
    }
    top_country = max((float(r["rev"] or 0) for r in country_rows), default=0) or 1
    bubbles = []
    for r in country_rows:
        name = r["name"]
        if name not in geo:
            continue
        code, lat, lon = geo[name]
        bubbles.append({
            "code": code, "lat": lat, "lon": lon,
            "r": round(9 + 17 * (float(r["rev"] or 0) / top_country) ** 0.5, 1),
            "title": f"{name} · {money(r['rev'])} · {r['orders']:,} orders",
        })

    with connection.cursor() as c:  # chart 5: top shipping cities
        c.execute(
            """
            SELECT a.City, SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Person_Address a ON a.AddressID = h.ShipToAddressID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY a.City
            ORDER BY rev DESC
            LIMIT 8
            """,
            [cur_lo, cur_hi],
        )
        cities = rank([{"name": city, "rev": rev} for city, rev in c.fetchall()],
                      "name", "rev", money)

    type_stats, store_rev = {}, {}
    with connection.cursor() as c:  # chart 6: the store network (all stores, not windowed)
        c.execute("SELECT Demographics FROM Sales_Store WHERE Demographics IS NOT NULL")
        for (demo,) in c.fetchall():
            m = re.search(r"<BusinessType>([^<]*)</BusinessType>", demo)
            if not m:
                continue
            b = type_stats.setdefault(m.group(1), {"n": 0, "sqft": 0.0, "emp": 0.0})
            b["n"] += 1
            for tag, key in (("SquareFeet", "sqft"), ("NumberEmployees", "emp")):
                v = re.search(rf"<{tag}>(\d+)</{tag}>", demo)
                if v:
                    b[key] += int(v.group(1))

        c.execute(
            """
            SELECT s.Demographics, SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Sales_Customer cu ON cu.CustomerID = h.CustomerID
            JOIN Sales_Store s ON s.BusinessEntityID = cu.StoreID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY s.Demographics
            """,
            [cur_lo, cur_hi],
        )
        for demo, store_total in c.fetchall():
            m = re.search(r"<BusinessType>([^<]*)</BusinessType>", demo or "")
            if m:
                store_rev[m.group(1)] = store_rev.get(m.group(1), 0) + float(store_total or 0)
    names = {"BS": "Bike shops", "BM": "Bike manufacturers", "OS": "Other specialty stores"}
    network_rows = [
        {"name": names.get(t, t), "rev": store_rev.get(t, 0), "n": b["n"],
         "sqft": round(b["sqft"] / b["n"]) if b["n"] else 0}
        for t, b in type_stats.items()
    ]
    network_rows.sort(key=lambda r: -r["rev"])
    network = rank(network_rows, "name", "rev", money)
    for r, s in zip(network, network_rows):
        r["note"] = f"{s['n']} stores · avg {s['sqft']:,} sq ft"

    with connection.cursor() as c:  # chart 7: how many orders each buyer placed
        c.execute(
            """
            SELECT CASE WHEN n = 1 THEN '1 order'
                        WHEN n = 2 THEN '2 orders'
                        WHEN n <= 4 THEN '3–4 orders'
                        WHEN n <= 9 THEN '5–9 orders'
                        ELSE '10+ orders' END AS bucket,
                   COUNT(*)
            FROM (
                SELECT CustomerID, COUNT(*) AS n
                FROM Sales_SalesOrderHeader
                WHERE OrderDate >= %s AND OrderDate <= %s
                GROUP BY CustomerID
            )
            GROUP BY bucket
            """,
            [cur_lo, cur_hi],
        )
        counts = dict(c.fetchall())
    buckets = {k: counts.get(k, 0) for k in
               ("1 order", "2 orders", "3–4 orders", "5–9 orders", "10+ orders")}
    frequency = rank([{"name": k, "n": v} for k, v in buckets.items()], "name", "n", lambda v: f"{int(v):,}")

    biggest = []
    with connection.cursor() as c:  # chart 8: biggest buyers (stores, then individuals)
        c.execute(
            """
            SELECT h.CustomerID, s.Name, p.FirstName, p.LastName, t.Name,
                   COUNT(DISTINCT h.SalesOrderID) AS orders,
                   SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Sales_Customer cu ON cu.CustomerID = h.CustomerID
            LEFT JOIN Sales_Store s ON s.BusinessEntityID = cu.StoreID
            LEFT JOIN Person_Person p ON p.BusinessEntityID = cu.PersonID
            LEFT JOIN Sales_SalesTerritory t ON t.TerritoryID = cu.TerritoryID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s AND cu.StoreID IS NOT NULL
            GROUP BY h.CustomerID, s.Name, p.FirstName, p.LastName, t.Name
            ORDER BY rev DESC
            LIMIT 6
            """,
            [cur_lo, cur_hi],
        )
        store_buyers = c.fetchall()

        c.execute(
            """
            SELECT h.CustomerID, s.Name, p.FirstName, p.LastName, t.Name,
                   COUNT(DISTINCT h.SalesOrderID) AS orders,
                   SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Sales_Customer cu ON cu.CustomerID = h.CustomerID
            LEFT JOIN Sales_Store s ON s.BusinessEntityID = cu.StoreID
            LEFT JOIN Person_Person p ON p.BusinessEntityID = cu.PersonID
            LEFT JOIN Sales_SalesTerritory t ON t.TerritoryID = cu.TerritoryID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s AND cu.StoreID IS NULL
            GROUP BY h.CustomerID, s.Name, p.FirstName, p.LastName, t.Name
            ORDER BY rev DESC
            LIMIT 3
            """,
            [cur_lo, cur_hi],
        )
        individual_buyers = c.fetchall()

    for is_store, rows in ((True, store_buyers), (False, individual_buyers)):
        for customer_id, store_name, first, last, territory, orders, buyer_total in rows:
            name = store_name or " ".join(x for x in (first, last) if x)
            biggest.append({
                "id": customer_id, "name": name or f"Customer {customer_id}", "store": is_store,
                "territory": territory or "—", "orders": orders, "rev": money(buyer_total),
            })

    avg_spend = (rev / actives) if actives else None
    prev_spend = (rev_prev / actives_prev) if actives_prev else None
    ind_avg = (ind_rev / ind_n) if ind_n else None
    st_avg = (st_rev / st_n) if st_n else None
    retention = round(kept / actives_prev * 100) if actives_prev else 0

    kpis = []
    for label, value, change, cap in (
        ("Active customers", f"{actives:,}", delta(actives, actives_prev), "distinct buyers in the window"),
        ("New customers", f"{new_count:,}", delta(new_count, prev_new),
         f"{money(new_rev)} · {round(new_count / actives * 100) if actives else 0}% of buyers"),
        ("Repeat revenue share", f"{round(float(repeat_rev) / float(rev) * 100) if rev else 0}%", (None, None),
         f"{money(repeat_rev)} from {repeat:,} returning buyers"),
        ("Avg spend per customer", money(avg_spend), delta(avg_spend, prev_spend),
         f"individual {money(ind_avg)} · store {money(st_avg)}"),
        ("Retention", f"{retention}%", (None, None),
         f"{kept:,} of {actives_prev:,} last-year buyers returned"),
    ):
        kpis.append({"label": label, "value": value, "delta": change[0], "dir": change[1], "cap": cap})

    if request.GET.get("export") == "csv":
        rows = [["Period", w.label, "compare", w.prev_label]]
        rows += [["KPI", k["label"], k["value"], f"{k['delta']} · {k['cap']}" if k["delta"] else k["cap"]]
                 for k in kpis]
        rows += [["Country", r["name"], r["value"], ""] for r in countries]
        rows += [["City", r["name"], r["value"], ""] for r in cities]
        rows += [["Store type", r["name"], r["value"], r["note"]] for r in network]
        rows += [["Orders per customer", r["name"], r["value"], ""] for r in frequency]
        rows += [["Top customer", r["name"], r["rev"],
                  f"{r['orders']} orders · {'store' if r['store'] else 'individual'}"] for r in biggest]
        return csv_response("customer-profile.csv", ["Section", "Item", "Value", "Detail"], rows)

    return _report_response(request, "customer-profile", "core/customer-profile/report.html", {
        "tab": "customer-profile",
        "title": "Customer profile report",
        "kpis": kpis,
        "growth": growth,
        "channels": channels,
        "countries": countries,
        "bubbles": bubbles,
        "cities": cities,
        "network": network,
        "frequency": frequency,
        "biggest": biggest,
        "new_legend": {"n": f"{new_count:,}", "rev": money(new_rev)},
        "ret_legend": {"n": f"{repeat:,}", "rev": money(repeat_rev)},
        "through": w.last,
        "window_label": w.label,
        "prev_label": w.prev_label,
        "custom": w.custom,
        "period": "the selected range" if w.custom else "the last 12 months",
        "w_from": w.trend_start.strftime("%Y-%m-%d"),
        "w_to": w.last.strftime("%Y-%m-%d"),
    }, w)


@permission_required("core.access_cost", raise_exception=True)
def cost(request):
    """Cost report: what the merchandise cost us (standard cost), what we spent
    buying it (purchase orders), and what manufacturing wasted (work order scrap)."""
    saved = _saved_report(request, "cost", "core/cost/report.html")
    if saved:
        return saved
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return _empty_report(request, "cost", "core/cost/report.html", "Cost report")
    saved = _saved_range(request, "cost", w)
    if saved:
        return _render_snapshot(request, "cost", "core/cost/report.html", saved)

    cur_lo, cur_hi = w.trend_start, w.last
    prev_lo, prev_hi = w.window_start, w.trend_start

    with connection.cursor() as c:  # chart 1: cost KPIs (sales lines at standard cost)
        c.execute(
            """
            SELECT
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                                THEN d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) END), 0) AS cogs,
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate < %s
                                THEN d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) END), 0) AS cogs_prev,
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                                THEN d.LineTotal END), 0) AS rev,
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate < %s
                                THEN d.LineTotal END), 0) AS rev_prev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            LEFT JOIN Production_ProductCostHistory ch
              ON ch.ProductID = d.ProductID
             AND h.OrderDate >= ch.StartDate
             AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
            WHERE h.OrderDate >= %s
            """,
            [cur_lo, cur_hi, prev_lo, prev_hi, cur_lo, cur_hi, prev_lo, prev_hi, w.window_start],
        )
        cogs, cogs_prev, rev, rev_prev = c.fetchone()

        c.execute(  # procurement: orders placed for parts
            """
            SELECT
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate <= %s
                                THEN SubTotal END), 0) AS spend,
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate < %s
                                THEN SubTotal END), 0) AS spend_prev,
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate <= %s
                                THEN 1 ELSE 0 END), 0) AS orders
            FROM Purchasing_PurchaseOrderHeader
            WHERE OrderDate >= %s AND Status <> 3
            """,
            [cur_lo, cur_hi, prev_lo, prev_hi, cur_lo, cur_hi, w.window_start],
        )
        spend, spend_prev, po_count = c.fetchone()

        c.execute(  # receipts against those orders
            """
            SELECT COALESCE(SUM(d.ReceivedQty), 0), COALESCE(SUM(d.RejectedQty), 0)
            FROM Purchasing_PurchaseOrderDetail d
            JOIN Purchasing_PurchaseOrderHeader h ON h.PurchaseOrderID = d.PurchaseOrderID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            """,
            [cur_lo, cur_hi],
        )
        received, rejected = c.fetchone()

        c.execute(  # manufacturing: units started and scrapped
            """
            SELECT
              COALESCE(SUM(CASE WHEN StartDate >= %s THEN OrderQty ELSE 0 END), 0) AS qty,
              COALESCE(SUM(CASE WHEN StartDate >= %s THEN ScrappedQty ELSE 0 END), 0) AS scr,
              COALESCE(SUM(CASE WHEN StartDate < %s THEN OrderQty ELSE 0 END), 0) AS qty_prev,
              COALESCE(SUM(CASE WHEN StartDate < %s THEN ScrappedQty ELSE 0 END), 0) AS scr_prev
            FROM Production_WorkOrder
            WHERE StartDate >= %s AND StartDate <= %s
            """,
            [cur_lo, cur_lo, cur_lo, cur_lo, w.window_start, w.last],
        )
        qty, scr, qty_prev, scr_prev = c.fetchone()

    cogs, cogs_prev = cogs or 0, cogs_prev or 0
    rev, rev_prev = rev or 0, rev_prev or 0
    proc = {"spend": spend, "orders": po_count}
    proc_prev = {"spend": spend_prev}
    rec = {"rec": received, "rej": rejected}
    scrap = {"qty": qty, "scr": scr, "qty_prev": qty_prev, "scr_prev": scr_prev}
    ratio = float(cogs) / float(rev) * 100 if rev else None
    ratio_prev = float(cogs_prev) / float(rev_prev) * 100 if rev_prev else None
    rej_pct = float(rec["rej"] or 0) / float(rec["rec"] or 1) * 100
    rate = (scrap["scr"] or 0) / (scrap["qty"] or 1) * 100
    rate_prev = (scrap["scr_prev"] or 0) / (scrap["qty_prev"] or 1) * 100

    pipeline = [
        {"k": "Buy", "big": money(proc["spend"]),
         "cap": f"{proc['orders']:,} purchase orders · merchandise, excl. rejected", "cls": ""},
        {"k": "Make", "big": f"{scrap['qty']:,}", "cap": "units started on work orders", "cls": ""},
        {"k": "Waste", "big": f"{scrap['scr']:,}", "cap": f"units scrapped · {rate:.2f}%", "cls": "bad"},
        {"k": "Sell", "big": money(cogs), "cap": "cost of goods sold to customers", "cls": ""},
    ]

    kpis = []
    for label, value, change, cap in (
        ("Cost of goods sold", money(cogs), delta(cogs, cogs_prev),
         "standard cost effective on the sale date"),
        ("Cost per $1 revenue", f"{ratio:.0f}¢" if ratio is not None else "—",
         delta(ratio, ratio_prev),
         f"was {ratio_prev:.0f}¢ last year" if ratio_prev is not None else "no revenue last year"),
        ("Procurement spend", money(proc["spend"]), delta(proc["spend"], proc_prev["spend"]),
         f"{proc['orders']:,} non-rejected POs · merchandise, excl. tax & freight"),
        ("Scrap rate", f"{rate:.2f}%", delta(rate, rate_prev),
         f"{scrap['scr']:,} units of {scrap['qty']:,} started"),
        ("Rejected receipts", f"{rej_pct:.1f}%", (None, None),
         f"{rec['rej']:,.0f} units of {rec['rec']:,.0f} received · all POs"),
    ):
        kpis.append({"label": label, "value": value, "delta": change[0], "dir": change[1], "cap": cap})

    with connection.cursor() as c:  # chart 2: monthly cost of goods sold
        c.execute(
            """
            SELECT substr(h.OrderDate, 1, 7) AS month,
                   CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
                   SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cogs,
                   SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            LEFT JOIN Production_ProductCostHistory ch
              ON ch.ProductID = d.ProductID
             AND h.OrderDate >= ch.StartDate
             AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY month, side
            ORDER BY month
            """,
            [w.trend_start, w.window_start, w.last],
        )
        series = [
            {"month": datetime.strptime(m, "%Y-%m"), "side": side, "cogs": cogs, "rev": rev}
            for m, side, cogs, rev in c.fetchall()
        ]
    months = [m for m in series if m["side"] == "cur"]
    prev_months = [m for m in series if m["side"] == "prev"]
    top = max((float(m["cogs"]) for m in months + prev_months), default=0)
    trend = [
        {
            "label": m["month"].strftime("%b"), "full": m["month"].strftime("%b %Y"),
            "money": money(m["cogs"]),
            "margin": round((float(m["rev"]) - float(m["cogs"])) / float(m["rev"]) * 100, 1) if m["rev"] else 0,
            "height": round(float(m["cogs"]) / top * 100, 2) if top else 0,
            "prev_full": prev_months[i]["month"].strftime("%b %Y") if i < len(prev_months) else "",
            "prev_money": money(prev_months[i]["cogs"]) if i < len(prev_months) else "—",
            "prev_h": (max(round(float(prev_months[i]["cogs"]) / top * 100), 2)
                       if i < len(prev_months) and prev_months[i]["cogs"] and top else 0),
        }
        for i, m in enumerate(months)
    ]

    with connection.cursor() as c:  # chart 3: where costs sit (category mix)
        c.execute(
            """
            SELECT cat.Name, SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cogs,
                   SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            LEFT JOIN Production_ProductCostHistory ch
              ON ch.ProductID = d.ProductID
             AND h.OrderDate >= ch.StartDate
             AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
            JOIN Production_ProductSubcategory sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
            JOIN Production_ProductCategory cat ON cat.ProductCategoryID = sc.ProductCategoryID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY cat.Name
            ORDER BY cogs DESC
            """,
            [cur_lo, cur_hi],
        )
        cats = [{"name": name, "cogs": cogs, "rev": rev}
                for name, cogs, rev in c.fetchall()]
    total_cogs = float(cogs) or 1
    mix = [
        {
            "name": r["name"],
            "cls": f"c{i}",
            "pct": round(float(r["cogs"]) / total_cogs * 100, 1),
            "money": money(r["cogs"]),
            "margin": round((float(r["rev"]) - float(r["cogs"])) / float(r["rev"]) * 100, 1) if r["rev"] else 0,
        }
        for i, r in enumerate(cats, 1)
    ]
    donut = ring([{"cls": m["cls"], "pct": m["pct"],
                   "t": f"{m['name']} · {m['money']} · {m['pct']}% of cost · {m['margin']}% margin"}
                  for m in mix])

    with connection.cursor() as c:  # chart 4: top vendors by procurement spend
        c.execute(
            """
            SELECT v.Name, SUM(po.SubTotal) AS spend, COUNT(*) AS orders, v.ActiveFlag
            FROM Purchasing_PurchaseOrderHeader po
            JOIN Purchasing_Vendor v ON v.BusinessEntityID = po.VendorID
            WHERE po.OrderDate >= %s AND po.OrderDate <= %s AND po.Status <> 3
            GROUP BY v.Name, v.ActiveFlag
            ORDER BY spend DESC
            LIMIT 8
            """,
            [cur_lo, cur_hi],
        )
        vendor_rows = [{"name": name, "spend": vendor_spend, "orders": orders,
                        "active": bool(active)}
                       for name, vendor_spend, orders, active in c.fetchall()]
    vendors = rank(vendor_rows, "name", "spend", money)
    for r, s in zip(vendors, vendor_rows):
        r["note"] = f"{s['orders']:,} non-rejected purchase orders"
        if not s["active"]:
            r["note"] += " · inactive vendor"

    with connection.cursor() as c:  # chart 5: products that cost us most
        c.execute(
            """
            SELECT p.Name, SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cogs,
                   SUM(d.OrderQty) AS units
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            LEFT JOIN Production_ProductCostHistory ch
              ON ch.ProductID = d.ProductID
             AND h.OrderDate >= ch.StartDate
             AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY p.Name
            ORDER BY cogs DESC
            LIMIT 8
            """,
            [cur_lo, cur_hi],
        )
        costly = [{"name": name, "cogs": product_cogs, "units": units}
                  for name, product_cogs, units in c.fetchall()]
    products = rank(costly, "name", "cogs", money)
    for r, s in zip(products, costly):
        r["note"] = f"{s['units']:,} units"

    with connection.cursor() as c:  # chart 6: scrap reasons
        c.execute(
            """
            SELECT sr.Name, SUM(w.ScrappedQty) AS scr, COUNT(*) AS orders
            FROM Production_WorkOrder w
            JOIN Production_ScrapReason sr ON sr.ScrapReasonID = w.ScrapReasonID
            WHERE w.StartDate >= %s AND w.StartDate <= %s
            GROUP BY sr.Name
            ORDER BY scr DESC
            LIMIT 8
            """,
            [cur_lo, cur_hi],
        )
        reason_rows = [{"name": name, "scr": scrapped, "orders": orders}
                       for name, scrapped, orders in c.fetchall()]
    reasons = rank(reason_rows, "name", "scr", lambda v: f"{int(v):,} units")
    for r, s in zip(reasons, reason_rows):
        r["note"] = f"{s['orders']:,} work orders"

    with connection.cursor() as c:  # chart 7: standard cost changes
        c.execute("SELECT ProductID, StandardCost FROM Production_ProductCostHistory WHERE EndDate IS NULL")
        open_cost = dict(c.fetchall())

        c.execute(
            """
            SELECT h.ProductID, p.Name, h.StandardCost
            FROM Production_ProductCostHistory h
            JOIN Production_Product p ON p.ProductID = h.ProductID
            WHERE h.EndDate IS NOT NULL
            ORDER BY h.StartDate
            """
        )
        earliest = {}
        for product_id, product_name, standard_cost in c.fetchall():
            earliest.setdefault(product_id, {"product_id": product_id, "product__name": product_name,
                                             "standard_cost": standard_cost})
    hikes, seen = [], set()
    for r in earliest.values():
        now = open_cost.get(r["product_id"])
        if now and now > r["standard_cost"]:
            base = r["product__name"].split(",")[0].strip()
            if base in seen:
                continue
            seen.add(base)
            hikes.append({"name": r["product__name"], "old": r["standard_cost"], "now": now,
                          "pct": round((now - r["standard_cost"]) / r["standard_cost"] * 100, 1)})
    hikes.sort(key=lambda h: -h["pct"])
    hikes = hikes[:6]
    changes = rank(hikes, "name", "pct", lambda v: f"+{v:.1f}%")
    for row, h in zip(changes, hikes):
        row["value"] = f"${h['old']:,.2f} → ${h['now']:,.2f}"
        row["note"] = "standard cost per unit"

    statuses = {1: ("Pending", ""), 2: ("Approved", "online"), 3: ("Rejected", "bad"), 4: ("Complete", "")}
    with connection.cursor() as c:  # chart 8: largest purchase orders
        c.execute(
            """
            SELECT po.PurchaseOrderID, v.Name, po.OrderDate, po.TotalDue, po.Status,
                   (SELECT COUNT(*) FROM Purchasing_PurchaseOrderDetail d
                    WHERE d.PurchaseOrderID = po.PurchaseOrderID) AS lines
            FROM Purchasing_PurchaseOrderHeader po
            JOIN Purchasing_Vendor v ON v.BusinessEntityID = po.VendorID
            WHERE po.OrderDate >= %s AND po.OrderDate <= %s
            ORDER BY po.TotalDue DESC
            LIMIT 8
            """,
            [cur_lo, cur_hi],
        )
        biggest = [
            {
                "id": order_id, "vendor": vendor, "date": order_date,
                "lines": lines, "total": money(total),
                "status": statuses.get(status, ("—", ""))[0], "cls": statuses.get(status, ("", ""))[1],
            }
            for order_id, vendor, order_date, total, status, lines in c.fetchall()
        ]

    performance = None
    if ratio is not None:
        margin_ratio = round(100 - ratio, 1)
        if ratio > 100:
            note = (f"Cost of goods exceeds revenue: every revenue dollar carries {ratio:.0f}\u00a2 of cost, "
                    "so gross margin is negative.")
        else:
            note = (f"Cost of goods absorbs {ratio:.0f}\u00a2 of each revenue dollar; "
                    f"gross margin keeps the other {margin_ratio:.0f}\u00a2.")
        if ratio_prev is not None:
            note += f" Last year cost was {ratio_prev:.0f}\u00a2 per revenue dollar."
        performance = {
            "cost": f"{ratio:.1f}%", "margin": f"{margin_ratio:.1f}%",
            "cost_w": min(max(round(ratio, 1), 0), 100),
            "margin_w": max(margin_ratio, 0),
            "note": note,
        }

    recommendations = []
    if vendor_rows and spend:
        share = round(float(vendor_rows[0]["spend"]) / float(spend) * 100)
        recommendations.append({
            "title": "Keep the largest vendor competitive",
            "text": (f"{vendor_rows[0]['name']} is the largest vendor at {share}% of procurement spend; "
                     "keep a second qualified source for its main parts."),
        })
    if mix:
        recommendations.append({
            "title": "Target the largest cost category",
            "text": (f"{mix[0]['name']} is {mix[0]['pct']}% of cost of goods; "
                     "a small reduction in its unit costs has the largest effect on total cost."),
        })
    if reason_rows and scr:
        share = round(float(reason_rows[0]["scr"]) / float(scr) * 100)
        recommendations.append({
            "title": "Attack the top scrap reason",
            "text": (f"{reason_rows[0]['name']} explains {share}% of scrapped units "
                     f"({int(reason_rows[0]['scr']):,}); review that process step."),
        })
    if hikes:
        recommendations.append({
            "title": "Check pricing after cost increases",
            "text": (f"{hikes[0]['name']} rose {hikes[0]['pct']}% in standard cost; "
                     "confirm the selling price still protects margin."),
        })

    if request.GET.get("export") == "csv":
        rows = [["Period", w.label, "compare", w.prev_label]]
        rows += [["KPI", k["label"], k["value"], f"{k['delta']} · {k['cap']}" if k["delta"] else k["cap"]]
                 for k in kpis]
        rows += [["Pipeline", p["k"], p["big"], p["cap"]] for p in pipeline]
        rows += [["Category", m["name"], m["money"], f"{m['pct']}% of cost · {m['margin']}% margin"]
                 for m in mix]
        rows += [["Vendor", r["name"], r["value"], r["note"]] for r in vendors]
        rows += [["Product", r["name"], r["value"], r["note"]] for r in products]
        rows += [["Scrap reason", r["name"], r["value"], r["note"]] for r in reasons]
        rows += [["Cost change", r["name"], r["value"], r["note"]] for r in changes]
        if performance:
            rows += [["Performance", "Cost of goods", performance["cost"], "share of revenue"],
                     ["Performance", "Gross margin", performance["margin"], "share of revenue"]]
        rows += [["Recommendation", r["title"], "", r["text"]] for r in recommendations]
        rows += [["Purchase order", f"PO{r['id']}", r["total"],
                  f"{r['date']:%Y-%m-%d} · {r['vendor']} · {r['status']}"] for r in biggest]
        return csv_response("cost.csv", ["Section", "Item", "Value", "Detail"], rows)

    return _report_response(request, "cost", "core/cost/report.html", {
        "tab": "cost",
        "title": "Cost report",
        "kpis": kpis,
        "pipeline": pipeline,
        "trend": trend,
        "mix": mix,
        "donut": donut,
        "donut_mid": {"big": money(cogs), "small": "cost of goods"},
        "vendors": vendors,
        "products": products,
        "reasons": reasons,
        "changes": changes,
        "biggest": biggest,
        "performance": performance,
        "recommendations": recommendations,
        "through": w.last,
        "window_label": w.label,
        "prev_label": w.prev_label,
        "custom": w.custom,
        "period": "the selected range" if w.custom else "the last 12 months",
        "w_from": w.trend_start.strftime("%Y-%m-%d"),
        "w_to": w.last.strftime("%Y-%m-%d"),
    }, w)


@permission_required("core.access_revenue_and_loss", raise_exception=True)
def revenue_and_loss(request):
    """Revenue and loss report: revenue, cost, gross profit and where the money leaks
    (below-cost wholesale lines); the page also states how each figure is calculated."""
    saved = _saved_report(request, "revenue-and-loss", "core/revenue-and-loss/report.html")
    if saved:
        return saved
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return _empty_report(request, "revenue-and-loss",
                             "core/revenue-and-loss/report.html", "Revenue and loss report")
    saved = _saved_range(request, "revenue-and-loss", w)
    if saved:
        return _render_snapshot(request, "revenue-and-loss",
                                "core/revenue-and-loss/report.html", saved)

    cur_lo, cur_hi = w.trend_start, w.last
    prev_lo, prev_hi = w.window_start, w.trend_start

    with connection.cursor() as c:  # chart 1: the five KPI cards
        c.execute(
            """
            WITH lines AS (
                SELECT d.LineTotal AS rev,
                       d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) AS cost,
                       CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side
                FROM Sales_SalesOrderDetail d
                JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
                JOIN Production_Product p ON p.ProductID = d.ProductID
                LEFT JOIN Production_ProductCostHistory ch
                  ON ch.ProductID = d.ProductID
                 AND h.OrderDate >= ch.StartDate
                 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            )
            SELECT
              COALESCE(SUM(CASE WHEN side = 'cur' THEN rev END), 0) AS rev,
              COALESCE(SUM(CASE WHEN side = 'prev' THEN rev END), 0) AS rev_prev,
              COALESCE(SUM(CASE WHEN side = 'cur' THEN cost END), 0) AS cogs,
              COALESCE(SUM(CASE WHEN side = 'prev' THEN cost END), 0) AS cogs_prev
            FROM lines
            """,
            [w.trend_start, w.window_start, w.last],
        )
        rev, rev_prev, cogs, cogs_prev = c.fetchone()

        c.execute(  # invoiced totals from the order headers
            """
            SELECT
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                                THEN h.TaxAmt END), 0) AS tax,
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                                THEN h.Freight END), 0) AS freight,
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                                THEN h.TotalDue END), 0) AS due,
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate < %s
                                THEN h.TotalDue END), 0) AS due_prev
            FROM Sales_SalesOrderHeader h
            WHERE h.OrderDate >= %s
            """,
            [cur_lo, cur_hi, cur_lo, cur_hi, cur_lo, cur_hi, prev_lo, prev_hi, w.window_start],
        )
        tax, freight, due, due_prev = c.fetchone()

        c.execute(  # lines sold below their standard cost
            """
            SELECT COUNT(*),
                   COALESCE(SUM(d.LineTotal), 0),
                   COALESCE(SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)), 0)
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            LEFT JOIN Production_ProductCostHistory ch
              ON ch.ProductID = d.ProductID
             AND h.OrderDate >= ch.StartDate
             AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
              AND d.LineTotal
                  < d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)
            """,
            [cur_lo, cur_hi],
        )
        loss_n, loss_rev, loss_cost = c.fetchone()

    rev, cogs = rev or 0, cogs or 0
    profit = rev - cogs
    profit_prev = (rev_prev or 0) - (cogs_prev or 0)
    margin = round(float(profit) / float(rev) * 100, 1) if rev else 0
    prev_margin = round(float(profit_prev) / float(rev_prev) * 100, 1) if rev_prev else 0
    short = (loss_cost or 0) - (loss_rev or 0)

    kpis = []
    for label, value, change, cap in (
        ("Total revenue", money(rev), delta(rev, rev_prev), "merchandise, excl. tax & freight"),
        ("Cost of goods", money(cogs), delta(cogs, cogs_prev),
         "at standard cost on the sale date"),
        ("Gross profit", money(profit), delta(profit, profit_prev),
         f"{margin}% margin \u00b7 was {prev_margin}%"),
        ("Invoiced total", money(due), delta(due, due_prev),
         f"incl. {money(tax)} tax · {money(freight)} freight"),
        ("Below-cost sales", money(short), (None, None), f"{loss_n:,} sales lines below standard cost"),
    ):
        kpis.append({"label": label, "value": value, "delta": change[0], "dir": change[1], "cap": cap})

    with connection.cursor() as c:  # chart 2: revenue trend, current vs previous window
        c.execute(
            """
            SELECT substr(h.OrderDate, 1, 7) AS month,
                   CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
                   SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY month, side
            ORDER BY month
            """,
            [w.trend_start, w.window_start, w.last],
        )
        rev_series = [{"month": datetime.strptime(m, "%Y-%m"), "side": side, "rev": rev}
                      for m, side, rev in c.fetchall()]
    rev_months = [m for m in rev_series if m["side"] == "cur"]
    prev_rev_months = [m for m in rev_series if m["side"] == "prev"]
    rev_top = max((float(m["rev"] or 0) for m in rev_series), default=0)
    rev_trend = [
        {
            "label": m["month"].strftime("%b"),
            "full": m["month"].strftime("%b %Y"),
            "money": money(m["rev"]),
            "height": max(round(float(m["rev"] or 0) / rev_top * 100), 2) if rev_top else 0,
            "prev_full": prev_rev_months[i]["month"].strftime("%b %Y") if i < len(prev_rev_months) else "",
            "prev_money": money(prev_rev_months[i]["rev"]) if i < len(prev_rev_months) else "\u2014",
            "prev_h": (max(round(float(prev_rev_months[i]["rev"] or 0) / rev_top * 100), 2)
                       if i < len(prev_rev_months) and prev_rev_months[i]["rev"] and rev_top else 0),
        }
        for i, m in enumerate(rev_months)
    ]

    with connection.cursor() as c:  # chart 3: profit and margin by month (24 months)
        c.execute(
            """
            SELECT substr(h.OrderDate, 1, 7) AS month,
                   SUM(d.LineTotal) AS rev,
                   SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cogs
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            LEFT JOIN Production_ProductCostHistory ch
              ON ch.ProductID = d.ProductID
             AND h.OrderDate >= ch.StartDate
             AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY month
            ORDER BY month
            """,
            [w.window_start, w.last],
        )
        months24 = [{"month": datetime.strptime(m, "%Y-%m"), "rev": rev, "cogs": cogs}
                    for m, rev, cogs in c.fetchall()]

    def margin_of(row):
        return round((float(row["rev"]) - float(row["cogs"])) / float(row["rev"]) * 100, 1) if row["rev"] else 0.0

    cur_rows = [r for r in months24 if r["month"] >= w.trend_start]
    prev_rows = [r for r in months24 if r["month"] < w.trend_start]
    cur_dates = [r["month"] for r in cur_rows]
    prev_dates = [r["month"] for r in prev_rows[:len(cur_dates)]]
    cur_vals = [margin_of(r) for r in cur_rows]
    prev_vals = [margin_of(r) for r in prev_rows[:len(cur_dates)]]

    profits = [float(r["rev"]) - float(r["cogs"]) for r in cur_rows]
    pmax = max(round(max(profits + [0.0]) / 200000) * 200000, 200000)
    m_max = 60  # right axis: margin percent
    px_w, px_h, pad_l, pad_r, pad_t, pad_b = 960, 260, 72, 40, 10, 24
    plot_w, plot_h = px_w - pad_l - pad_r, px_h - pad_t - pad_b
    barw = round(min(44, plot_w / max(len(cur_dates) - 1, 1) * 0.65), 1)  # bars shrink when a range has many months

    def x_at(i):
        return round(pad_l + i * plot_w / max(len(cur_dates) - 1, 1), 1)

    def y_money(v):
        return round(pad_t + (1 - v / pmax) * plot_h, 1)

    def y_pct(v):
        return round(pad_t + (1 - v / m_max) * plot_h, 1)

    def axis_money(v):
        if v >= 1e6:
            return f"${v / 1e6:,.1f}M"
        return f"${v / 1e3:,.0f}K" if v else "$0"

    bars = []
    for i, (m, p) in enumerate(zip(cur_dates, profits)):
        h = round(p / pmax * plot_h, 1)
        bars.append({"x": round(x_at(i) - barw / 2, 1), "y": round(pad_t + plot_h - h, 1), "h": h, "w": barw,
                     "t": f"{m:%b %Y} · {money(p)} gross profit"})
    dots = []
    for cls, dates, vals in (("dotp", prev_dates, prev_vals), ("dotc", cur_dates, cur_vals)):
        for i, (m, v) in enumerate(zip(dates, vals)):
            dots.append({"cls": cls, "x": x_at(i), "y": y_pct(v), "t": f"{m:%b %Y} · {v}% margin"})
    combo = {
        "bars": bars,
        "cur_pts": " ".join(f"{x_at(i)},{y_pct(v)}" for i, v in enumerate(cur_vals)),
        "prev_pts": " ".join(f"{x_at(i)},{y_pct(v)}" for i, v in enumerate(prev_vals)),
        "dots": dots,
        "xticks": [{"x": x_at(i), "lab": m.strftime("%b")} for i, m in enumerate(cur_dates)],
        "lticks": [{"y": y_money(v), "lab": axis_money(v)} for v in (0, pmax / 2, pmax)],
        "rticks": [{"y": y_pct(v), "lab": f"{v}%"} for v in (0, 20, 40, 60)],
    }

    with connection.cursor() as c:  # chart 4: revenue by category
        c.execute(
            """
            SELECT cat.Name, SUM(d.LineTotal) AS rev,
                   SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cogs
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            LEFT JOIN Production_ProductCostHistory ch
              ON ch.ProductID = d.ProductID
             AND h.OrderDate >= ch.StartDate
             AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
            JOIN Production_ProductSubcategory sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
            JOIN Production_ProductCategory cat ON cat.ProductCategoryID = sc.ProductCategoryID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY cat.Name
            ORDER BY rev DESC
            """,
            [cur_lo, cur_hi],
        )
        cats = [{"name": name, "rev": rev, "cogs": cogs} for name, rev, cogs in c.fetchall()]
    total_rev = float(rev) or 1
    mix = [
        {
            "name": r["name"],
            "cls": f"c{i}",
            "pct": round(float(r["rev"]) / total_rev * 100, 1),
            "money": money(r["rev"]),
            "margin": round((float(r["rev"]) - float(r["cogs"])) / float(r["rev"]) * 100, 1) if r["rev"] else 0,
        }
        for i, r in enumerate(cats, 1)
    ]

    donut = ring([{"cls": m["cls"], "pct": m["pct"],
                   "t": f"{m['name']} · {m['money']} · {m['pct']}% of revenue · {m['margin']}% margin"}
                  for m in mix])

    with connection.cursor() as c:  # chart 5: products with declining revenue vs previous window
        c.execute(
            """
            SELECT p.Name,
                   SUM(CASE WHEN h.OrderDate >= %s
                            THEN d.LineTotal ELSE 0 END) AS cur_rev,
                   SUM(CASE WHEN h.OrderDate < %s
                            THEN d.LineTotal ELSE 0 END) AS prev_rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY p.ProductID, p.Name
            HAVING prev_rev > 0 AND cur_rev < prev_rev
            ORDER BY (prev_rev - cur_rev) DESC
            LIMIT 8
            """,
            [cur_lo, cur_lo, w.window_start, w.last],
        )
        decline_rows = [{"name": name, "cur": cur_rev, "prev": prev_rev,
                         "drop": float(prev_rev) - float(cur_rev)}
                        for name, cur_rev, prev_rev in c.fetchall()]
    declining = rank(decline_rows, "name", "drop", lambda v: f"-{money(v)}")
    for r, s_row in zip(declining, decline_rows):
        pct = round(s_row["drop"] / float(s_row["prev"]) * 100, 1)
        r["note"] = f"{money(s_row['cur'])} vs {money(s_row['prev'])} \u00b7 -{pct}%"

    with connection.cursor() as c:  # chart 6: below-cost products
        c.execute(
            """
            SELECT p.Name,
                   SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost))
                   - SUM(d.LineTotal) AS gap,
                   COUNT(*) AS n
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            LEFT JOIN Production_ProductCostHistory ch
              ON ch.ProductID = d.ProductID
             AND h.OrderDate >= ch.StartDate
             AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
              AND d.LineTotal
                  < d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)
            GROUP BY p.Name
            ORDER BY gap DESC
            LIMIT 6
            """,
            [cur_lo, cur_hi],
        )
        leak_rows = [{"name": name, "gap": gap, "n": n} for name, gap, n in c.fetchall()]
    leaks = rank(leak_rows, "name", "gap", lambda v: f"-{money(v)}")
    for r, s in zip(leaks, leak_rows):
        r["note"] = f"{s['n']:,} lines"

    with connection.cursor() as c:  # chart 7: product profitability table
        c.execute(
            """
            SELECT p.ProductID, p.Name,
                   SUM(d.LineTotal) AS rev,
                   SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cogs
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            LEFT JOIN Production_ProductCostHistory ch
              ON ch.ProductID = d.ProductID
             AND h.OrderDate >= ch.StartDate
             AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY p.ProductID, p.Name
            ORDER BY rev DESC
            LIMIT 12
            """,
            [cur_lo, cur_hi],
        )
        prods = [{"product_id": product_id, "name": name, "rev": rev, "cogs": cogs}
                 for product_id, name, rev, cogs in c.fetchall()]
    products = [
        {
            "id": r["product_id"], "name": r["name"],
            "rev": money(r["rev"]), "cost": money(r["cogs"]),
            "profit": money(float(r["rev"]) - float(r["cogs"])),
            "margin": f"{round((float(r['rev']) - float(r['cogs'])) / float(r['rev']) * 100, 1)}%",
        }
        for r in prods[:8]
    ]

    if request.GET.get("export") == "csv":
        rows = [["Period", w.label, "compare", w.prev_label]]
        rows += [["KPI", k["label"], k["value"], f"{k['delta']} \u00b7 {k['cap']}" if k["delta"] else k["cap"]]
                 for k in kpis]
        rows += [["Revenue trend", t["full"], t["money"], f"previous {t['prev_full']}: {t['prev_money']}"]
                 for t in rev_trend if t["prev_full"]]
        rows += [["Category", m["name"], m["money"], f"{m['pct']}% of revenue \u00b7 {m['margin']}% margin"]
                 for m in mix]
        rows += [["Declining product", r["name"], r["value"], r["note"]] for r in declining]
        rows += [["Below-cost product", r["name"], r["value"], r["note"]] for r in leaks]
        rows += [["Product", r["name"], r["rev"], f"cost {r['cost']} \u00b7 profit {r['profit']} \u00b7 {r['margin']} margin"]
                 for r in products]
        return csv_response("revenue-and-loss.csv", ["Section", "Item", "Value", "Detail"], rows)

    return _report_response(request, "revenue-and-loss",
                            "core/revenue-and-loss/report.html", {
        "tab": "revenue-and-loss",
        "title": "Revenue and loss report",
        "kpis": kpis,
        "combo": combo,
        "donut": donut,
        "donut_mid": {"big": money(rev), "small": "revenue"},
        "mix": mix,
        "rev_trend": rev_trend,
        "declining": declining,
        "leaks": leaks,
        "products": products,
        "through": w.last,
        "window_label": w.label,
        "prev_label": w.prev_label,
        "custom": w.custom,
        "period": "the selected range" if w.custom else "the last 12 months",
        "w_from": w.trend_start.strftime("%Y-%m-%d"),
        "w_to": w.last.strftime("%Y-%m-%d"),
    }, w)


REPORT_VIEWS = {
    "sales": sales,
    "customer-profile": customer_profile,
    "revenue-and-loss": revenue_and_loss,
    "cost": cost,
}


@require_POST
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
    finally:
        request._range_params = old_params
        request._capture_snapshot = old_capture
    snapshot = getattr(request, "_captured_snapshot", None)
    request._captured_snapshot = old_captured
    return snapshot


# ---------------------------------------------------------------------------
# Saved-report editor: list, edit and delete one module's snapshots. The report
# itself is still generated by the report view, so there is no blank create form.

class SnapshotMixin(PermissionRequiredMixin):
    perm = None
    page_title = "Saved reports"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.tab = kwargs["tab"]
        if self.tab not in REPORT_VIEWS:
            raise Http404
        self.model = Report

    def get_permission_required(self):
        required = [f"core.access_{self.tab.replace('-', '_')}"]
        if self.perm:
            required.append(f"core.{self.perm}_report")
        return required

    def get_success_url(self):
        return reverse("snapshot_list", args=[self.tab])

    def get_context_data(self, **kw):
        user = self.request.user
        return super().get_context_data(
            tab=self.tab, title=self.page_title,
            can_change=user.has_perm("core.change_report"),
            can_delete=user.has_perm("core.delete_report"), **kw)


class SnapshotList(SnapshotMixin, ListView):
    page_title = "Saved reports"
    template_name = "core/snapshot_list.html"
    context_object_name = "snapshots"
    paginate_by = 50

    def get_queryset(self):
        return self.model._default_manager.filter(module=self.tab)

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        rows, headers = [], []
        for snapshot in ctx["object_list"]:
            kpis = (snapshot.payload or {}).get("kpis", [])
            if not headers:
                headers = [kpi.get("label", "") for kpi in kpis]
            rows.append({
                "snapshot": snapshot,
                "cells": [kpi.get("value", "") for kpi in kpis],
            })
        ctx["rows"] = rows
        ctx["kpi_headers"] = headers
        return ctx


class SnapshotEdit(SnapshotMixin, UpdateView):
    perm = "change"
    page_title = "Edit saved report"
    template_name = "core/snapshot_form.html"
    context_object_name = "snapshot"

    def get_form_class(self):
        return ReportEditForm

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        sections = []
        for key in EDITABLE_KEYS.get(self.tab, []):
            value = (self.object.payload or {}).get(key)
            label = SECTION_LABELS.get(key, key.replace("_", " ").title())
            if isinstance(value, list) and all(isinstance(row, dict) for row in value):
                columns = []
                for row in value:
                    for field, field_value in row.items():
                        if not isinstance(field_value, (dict, list)) and field not in columns:
                            columns.append(field)
                sections.append({
                    "key": key,
                    "label": label,
                    "kind": "table",
                    "columns": [{"name": c, "label": c.replace("_", " ").title()}
                                for c in columns],
                    "rows": [
                        {
                            "index": index,
                            "fields": [
                                {
                                    "name": c,
                                    "label": c.replace("_", " ").title(),
                                    "value": "" if row.get(c) is None else row.get(c),
                                }
                                for c in columns
                            ],
                        }
                        for index, row in enumerate(value)
                    ],
                })
            elif isinstance(value, dict):
                sections.append({
                    "key": key,
                    "label": label,
                    "kind": "dict",
                    "items": [
                        {
                            "name": field,
                            "label": field.replace("_", " ").title(),
                            "value": "" if field_value is None else field_value,
                        }
                        for field, field_value in value.items()
                        if not isinstance(field_value, (dict, list))
                    ],
                })
            else:
                sections.append({
                    "key": key,
                    "label": label,
                    "kind": "scalar",
                    "value": "" if value is None else value,
                })
        ctx["editor_sections"] = sections
        return ctx

    def form_valid(self, form):
        old = self.model._default_manager.filter(pk=self.object.pk).first()
        payload = copy.deepcopy(self.object.payload or {})
        edits = []
        for key in EDITABLE_KEYS.get(self.tab, []):
            original = payload.get(key)
            if isinstance(original, list) and all(isinstance(row, dict) for row in original):
                for index, row in enumerate(original):
                    for field, field_value in list(row.items()):
                        if isinstance(field_value, (dict, list)):
                            continue
                        edits.append((row, field, field_value,
                                      f"editor-{key}-{index}-{field}"))
            elif isinstance(original, dict):
                for field, field_value in list(original.items()):
                    if isinstance(field_value, (dict, list)):
                        continue
                    edits.append((original, field, field_value, f"editor-{key}-{field}"))
            else:
                edits.append((payload, key, original, f"editor-{key}"))
        errors = []
        for container, field, original_value, name in edits:
            if name not in self.request.POST:
                continue
            value = self.request.POST[name]
            if isinstance(original_value, bool):
                new_value = str(value).lower() in {"1", "true", "on", "yes"}
            elif isinstance(original_value, int):
                try:
                    new_value = int(value)
                except (TypeError, ValueError):
                    errors.append(f"{field.replace('_', ' ').capitalize()} must be a whole number.")
                    continue
            elif isinstance(original_value, float):
                try:
                    new_value = float(value)
                except (TypeError, ValueError):
                    errors.append(f"{field.replace('_', ' ').capitalize()} must be a number.")
                    continue
            elif original_value is None:
                new_value = value or None
            else:
                new_value = value
            container[field] = new_value

        if errors:
            for message in dict.fromkeys(errors):
                form.add_error(None, message)
            return self.form_invalid(form)

        changes = {}
        if old is not None:
            for field in form.changed_data:
                before = getattr(old, field)
                after = form.cleaned_data.get(field)
                changes[field] = [
                    str(before) if before is not None else None,
                    str(after) if after is not None else None,
                ]
            if payload != old.payload:
                changes["payload"] = ["edited", "edited"]

        form.instance.payload = payload
        messages.success(self.request, f"Saved {form.instance}.")
        response = super().form_valid(form)
        if changes:
            AuditLog.objects.create(
                user=self.request.user, username=self.request.user.get_username(),
                action="update", model=self.model.__name__,
                object_pk=str(form.instance.pk), object_repr=str(form.instance)[:255],
                changes=changes, ip_address=self.request.META.get("REMOTE_ADDR"))
        return response


class SnapshotDelete(SnapshotMixin, DeleteView):
    perm = "delete"
    page_title = "Delete saved report"
    template_name = "core/snapshot_confirm_delete.html"
    context_object_name = "snapshot"

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        audit = {
            f.name: str(getattr(obj, f.name)) if getattr(obj, f.name) is not None else None
            for f in obj._meta.fields
            if f.name != "payload" and f.get_internal_type() != "BinaryField"
        }
        pk, repr_ = str(obj.pk), str(obj)[:255]
        response = super().post(request, *args, **kwargs)
        AuditLog.objects.create(
            user=request.user, username=request.user.get_username(), action="delete",
            model=self.model.__name__, object_pk=pk, object_repr=repr_, changes=audit,
            ip_address=request.META.get("REMOTE_ADDR"))
        return response


def shown(model):
    """Fields worth showing in tables: skip blobs (all other columns are kept)."""
    return [f for f in model._meta.fields
            if f.get_internal_type() != "BinaryField"]


# the biggest dropdowns only load the columns their names are built from
LABEL_COLUMNS = {
    "SalesOrderHeader": ["sales_order_number"],
    "Person": ["first_name", "last_name"],
    "PersonAddress": ["address_line1", "city"],
}
_JOINS = {}


def name_needs_joins(model):
    """True if str(record) runs extra queries, so dropdowns must join the related tables."""
    if model not in _JOINS:
        obj, hits = model._default_manager.first(), []
        if obj is not None:
            with connection.execute_wrapper(lambda ex, sql, p, many, ctx: (hits.append(1), ex(sql, p, many, ctx))[1]):
                str(obj)
        _JOINS[model] = bool(hits)
    return _JOINS[model]


class TableMixin(PermissionRequiredMixin):
    perm = None  # "view", "change" or "delete"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.tab, name = kwargs["tab"], kwargs["model"]
        try:
            self.model = apps.get_model("core", name)
        except LookupError:
            raise Http404

    def get_permission_required(self):
        return [f"core.access_{self.tab.replace('-', '_')}", f"core.{self.perm}_{self.model._meta.model_name}"]

    def get_success_url(self):
        return reverse("table_list", args=[self.tab, self.model.__name__])

    def get_context_data(self, **kw):
        user, label = self.request.user, self.model._meta.model_name
        return super().get_context_data(
            tab=self.tab, name=self.model.__name__, title=self.model._meta.verbose_name.capitalize(),
            can_change=user.has_perm(f"core.change_{label}"), can_delete=user.has_perm(f"core.delete_{label}"), **kw)


def cell(obj, f, tab):
    """One table cell: its text, plus a link to the related record when it is a foreign key."""
    value = getattr(obj, f.name)
    if isinstance(value, (date, datetime, time)):
        value = value.isoformat().replace("T", " ")
    if f.is_relation and value is not None:
        name = type(value).__name__
        return {"text": str(value), "url": reverse("table_detail", args=[tab, name, value.pk])}
    return {"text": "" if value is None else value, "url": None}


class TableList(TableMixin, ListView):
    perm, paginate_by, template_name = "view", 50, "core/list.html"

    def get(self, request, *args, **kwargs):
        export = request.GET.get("export")
        if export in ("page", "all"):
            qs = self.get_queryset()
            fields = shown(self.model)
            header = [f.verbose_name for f in fields]
            if export == "page":
                try:
                    number = max(int(request.GET.get("page", 1)), 1)
                except ValueError:
                    number = 1
                qs = qs[(number - 1) * self.paginate_by:number * self.paginate_by]
                filename = f"{self.model.__name__}-page{number}.csv"
            else:
                filename = f"{self.model.__name__}.csv"
            rows = ([cell(o, f, self.tab)["text"] for f in fields] for o in qs.iterator())
            return csv_response(filename, header, rows)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        fks = [f.name for f in self.model._meta.fields if f.is_relation]
        qs = self.model._default_manager.select_related(*fks).order_by("pk")
        q, col = self.request.GET.get("q", "").strip(), self.request.GET.get("col", "")
        if q:
            castable = ("AutoField", "BigAutoField", "IntegerField", "BigIntegerField",
                        "SmallIntegerField", "PositiveIntegerField", "FloatField",
                        "DecimalField", "DateField", "DateTimeField", "TimeField", "UUIDField")
            fields = {f.name: f for f in self.model._meta.fields}
            targets = [fields[col]] if col in fields else list(fields.values())
            conds, ann = [], {}
            for f in targets:
                t = f.get_internal_type()
                if t in ("BinaryField", "BooleanField"):
                    continue
                if f.is_relation:
                    # also search the related record's label (first 2 CharFields)
                    rel = f.related_model
                    subs = [s for s in rel._meta.fields
                            if s.get_internal_type() == "CharField"][:2]
                    conds += [Q(**{f"{f.name}__{s.name}__icontains": q}) for s in subs]
                    # names often live one hop away, via a FK to Person (customer, employee, ...)
                    pf = next((r.name for r in rel._meta.fields
                               if r.is_relation and r.related_model.__name__ == "Person"), None)
                    if pf:
                        conds += [Q(**{f"{f.name}__{pf}__{n}__icontains": q})
                                  for n in ("first_name", "last_name")]
                elif t in castable:
                    # numbers, dates and uuids: cast to text first, LIKE does not match them raw
                    key = f"txt_{f.name}"
                    ann[key] = Cast(f.name, output_field=TextField())
                    # SQLite stores uuids as hex without dashes, so drop them from the needle
                    conds.append(Q(**{f"{key}__icontains": q.replace("-", "") if t == "UUIDField" else q}))
                    if t not in ("DateField", "DateTimeField", "TimeField", "UUIDField"):
                        # exact value too, so "201.0400" matches a stored 201.04
                        try:
                            conds.append(Q(**{f.name: float(q)}))
                        except ValueError:
                            pass
                else:
                    conds.append(Q(**{f"{f.name}__icontains": q}))
            qs = qs.annotate(**ann).filter(Q(*conds, _connector=Q.OR)) if conds else qs.none()
        sort = self.request.GET.get("sort", "")
        name = sort[1:] if sort.startswith("-") else sort
        try:
            sf = self.model._meta.get_field(name) if name else None
        except FieldDoesNotExist:
            sf = None
        if sf is not None:
            prefix = "-" if sort.startswith("-") else ""
            if sf.is_relation:
                # fk columns sort by the label you see (the related person, or first CharFields)
                rel = sf.related_model
                pf = next((r.name for r in rel._meta.fields
                           if r.is_relation and r.related_model.__name__ == "Person"), None)
                if pf:
                    subs = [f"{pf}__first_name", f"{pf}__last_name"]
                else:
                    subs = [s.name for s in rel._meta.fields
                            if s.get_internal_type() == "CharField"][:2]
                if subs:
                    qs = qs.order_by(*[f"{prefix}{sf.name}__{s}" for s in subs], "pk")
            else:
                qs = qs.order_by(f"{prefix}{sf.name}", "pk")
        return qs

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        fields = shown(self.model)
        sort = self.request.GET.get("sort", "")
        ctx["headers"] = [(f.verbose_name, f.name) for f in fields]
        ctx["rows"] = [{"obj": o, "cells": [cell(o, f, self.tab) for f in fields]} for o in ctx["object_list"]]
        ctx["columns"] = [(f.verbose_name, f.name) for f in self.model._meta.fields
                          if f.get_internal_type() not in ("BinaryField", "BooleanField")]
        ctx["col"] = self.request.GET.get("col", "")
        ctx["sort"], ctx["sort_desc"] = sort.lstrip("-"), sort.startswith("-")
        return ctx


class TableDetail(TableMixin, DetailView):
    perm, template_name = "view", "core/detail.html"

    def get_context_data(self, **kw):
        fields = [f for f in self.model._meta.fields if f.get_internal_type() != "BinaryField"]
        return super().get_context_data(
            fields=[(f.verbose_name, cell(self.object, f, self.tab)) for f in fields], **kw)


class TableEdit(TableMixin, UpdateView):
    perm, template_name = "change", "core/form.html"

    def get_form_class(self):
        names = [f.name for f in self.model._meta.fields
                 if f.editable and not f.primary_key and f.name != "modified_date"]
        return forms.modelform_factory(self.model, fields=names)

    def get_form(self, *a, **kw):
        form = super().get_form(*a, **kw)
        for name, field in form.fields.items():
            if isinstance(field, forms.ModelChoiceField):
                # dropdowns show each record's name; join what its name is built from in one query
                rel = field.queryset.model
                fks = [f.name for f in rel._meta.fields if f.is_relation] if name_needs_joins(rel) else []
                qs = field.queryset.select_related(*fks)
                if rel.__name__ in LABEL_COLUMNS:
                    qs = qs.only(*LABEL_COLUMNS[rel.__name__])
                widget = SearchSelect(attrs=field.widget.attrs)
                widget.queryset = qs
                widget.url = reverse("table_autocomplete", args=[self.tab, self.model.__name__, name])
                field.widget = widget
                field.queryset = qs
        return form

    def form_valid(self, form):
        old = self.model._default_manager.filter(pk=form.instance.pk).first()  # the row as stored
        changes = {}
        for f in (self.model._meta.fields if old is not None else []):
            if not f.editable or f.primary_key or f.name == "modified_date":
                continue
            before, after = getattr(old, f.name), form.cleaned_data[f.name]
            if getattr(before, "pk", before) != getattr(after, "pk", after):
                changes[f.name] = [str(before) if before is not None else None,
                                   str(after) if after is not None else None]
        if hasattr(form.instance, "modified_date"):
            form.instance.modified_date = timezone.now()
        messages.success(self.request, f"Saved {form.instance}.")
        response = super().form_valid(form)
        if changes:  # audit trail: only a save that really changed something is recorded
            AuditLog.objects.create(
                user=self.request.user, username=self.request.user.get_username(),
                action="update", model=self.model.__name__, object_pk=str(form.instance.pk),
                object_repr=str(form.instance)[:255], changes=changes,
                ip_address=self.request.META.get("REMOTE_ADDR"))
        return response


class TableAutocomplete(TableMixin, View):
    """JSON search for one foreign-key field: the name fields of the target record (plus the
    person behind it, and the pk for labels like "PersonBusinessEntity 42"), 20 rows at most.
    Works for every table because it is driven by the model metadata."""
    perm = "view"

    def get(self, request, *args, **kwargs):
        try:
            f = self.model._meta.get_field(kwargs["field"])
        except FieldDoesNotExist:
            raise Http404
        if not f.is_relation or not f.editable:
            raise Http404
        rel, q = f.related_model, request.GET.get("q", "").strip()
        qs = rel._default_manager.all()
        if q:
            conds = [Q(**{c.name + "__icontains": q}) for c in rel._meta.fields
                     if c.get_internal_type() == "CharField"]
            if rel._meta.pk.get_internal_type() in ("AutoField", "BigAutoField", "SmallAutoField", "CharField"):
                # labels like "PersonBusinessEntity 42" only hold the pk (skipped when the pk is a relation)
                conds.append(Q(pk__icontains=q))
            pf = next((r.name for r in rel._meta.fields
                       if r.is_relation and r.related_model.__name__ == "Person"), None)
            if pf:
                conds += [Q(**{f"{pf}__{n}__icontains": q}) for n in ("first_name", "last_name")]
            qs = qs.filter(Q(*conds, _connector=Q.OR))
        if name_needs_joins(rel):
            qs = qs.select_related(*[fk.name for fk in rel._meta.fields if fk.is_relation])
        if rel.__name__ in LABEL_COLUMNS:
            qs = qs.only(*LABEL_COLUMNS[rel.__name__])
        return JsonResponse({"results": [{"id": o.pk, "text": str(o)} for o in qs.order_by("pk")[:20]]})


class TableDelete(TableMixin, DeleteView):
    perm, template_name = "delete", "core/confirm_delete.html"

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        snapshot = {f.name: str(getattr(obj, f.name)) if getattr(obj, f.name) is not None else None
                    for f in obj._meta.fields if f.get_internal_type() != "BinaryField"}
        pk, repr_ = str(obj.pk), str(obj)[:255]
        try:
            response = super().post(request, *args, **kwargs)
        except ProtectedError as e:
            kinds = ", ".join(sorted({type(o).__name__ for o in e.protected_objects}))
            messages.error(request, f"Cannot delete: {len(e.protected_objects)} record(s) in {kinds} still point to it.")
            return redirect(request.path)
        AuditLog.objects.create(  # audit trail: the row is gone, so the snapshot is the evidence
            user=request.user, username=request.user.get_username(), action="delete",
            model=self.model.__name__, object_pk=pk, object_repr=repr_, changes=snapshot,
            ip_address=request.META.get("REMOTE_ADDR"))
        return response
