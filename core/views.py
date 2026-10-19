"""All views for the app: home, the four dashboards, and the generic table browser
(list / detail / edit / delete / autocomplete) used by every table."""
import re
from datetime import date, datetime, time

from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import FieldDoesNotExist
from django.db import connection
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Min, ProtectedError, Q, Sum, TextField
from django.db.models.functions import Cast, TruncMonth
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DeleteView, DetailView, ListView, UpdateView

from .models import (
    ProductionProductCostHistory,
    ProductionWorkOrder,
    PurchasingPurchaseOrderDetail,
    PurchasingPurchaseOrderHeader,
    SalesCustomer,
    SalesOrderDetail,
    SalesOrderHeader,
    SalesStore,
    SalesTaxRate,
)
from .utils import csv_response, delta, line_cost, money, rank, ring, shift_months, window_for, MONTHS
from .widgets import SearchSelect


# ---------------------------------------------------------------------------
# Pages: home, the four dashboards (below), and the generic table browser further down.
# Each dashboard is one view: it builds its own data and renders its own template.

def home(request):
    """Send the user to the first tab they may open, or explain that they have none."""
    for slug in ("sales", "customer-profile", "revenue-and-loss", "cost"):
        if request.user.has_perm(f"core.access_{slug.replace('-', '_')}"):
            return redirect(slug)
    return render(request, "core/no_access.html")


@permission_required("core.access_sales", raise_exception=True)
def sales(request):
    """Sales dashboard: one aggregate query per panel, all windows anchored to the
    data's own last order date (the sample data is historical, so "today" would be empty)."""
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return render(request, "core/sales/dashboard.html",
                      {"tab": "sales", "title": "Sales"})

    cur, prev, trend_start = w.cur, w.prev, w.trend_start

    totals = SalesOrderHeader.objects.filter(order_date__gte=w.window_start).aggregate(
        rev=Sum("sub_total", filter=cur),
        rev_prev=Sum("sub_total", filter=prev),
        orders=Count("sales_order_id", filter=cur),
        orders_prev=Count("sales_order_id", filter=prev),
        customers=Count("customer", filter=cur, distinct=True),
        customers_prev=Count("customer", filter=prev, distinct=True),
        online_rev=Sum("sub_total", filter=cur & Q(online_order_flag=True)),
        online_orders=Count("sales_order_id", filter=cur & Q(online_order_flag=True)),
    )

    rev = totals["rev"] or 0
    orders = totals["orders"] or 0
    online_rev = totals["online_rev"] or 0
    online_orders = totals["online_orders"] or 0
    aov = (rev / orders) if orders else None
    aov_prev = (totals["rev_prev"] / totals["orders_prev"]) if totals["orders_prev"] else None
    share = round(float(online_rev) / float(rev) * 100) if rev else 0

    kpis = []
    for label, value, change, cap in (
        ("Revenue", money(rev), delta(rev, totals["rev_prev"]), "merchandise, excl. tax & freight"),
        ("Orders", f"{orders:,}", delta(orders, totals["orders_prev"]), "sales orders placed"),
        ("Avg order value", money(aov), delta(aov, aov_prev), "revenue per order"),
        ("Customers", f"{totals['customers'] or 0:,}", delta(totals["customers"], totals["customers_prev"]), "distinct buyers"),
        ("Online share", f"{share}%", (None, None), f"{money(online_rev)} · {online_orders:,} orders"),
    ):
        kpis.append({"label": label, "value": value, "delta": change[0], "dir": change[1], "cap": cap})

    months = list(
        SalesOrderHeader.objects.filter(cur)
        .annotate(month=TruncMonth("order_date"))
        .values("month")
        .annotate(rev=Sum("sub_total"), orders=Count("sales_order_id"))
        .order_by("month")
    )
    top = max((float(m["rev"] or 0) for m in months), default=0)
    trend = [
        {
            "label": m["month"].strftime("%b"),
            "full": m["month"].strftime("%b %Y"),
            "money": money(m["rev"]),
            "orders": f"{m['orders']:,}",
            "height": max(round(float(m["rev"] or 0) / top * 100), 2) if top else 0,
        }
        for m in months
    ]

    channels = [
        {"name": "Online", "pct": share, "money": money(online_rev), "orders": f"{online_orders:,}",
         "aov": money((online_rev / online_orders) if online_orders else None), "cls": "online"},
        {"name": "Assisted", "pct": 100 - share, "money": money(rev - online_rev), "orders": f"{orders - online_orders:,}",
         "aov": money(((rev - online_rev) / (orders - online_orders)) if orders - online_orders else None), "cls": "store"},
    ]

    territories = rank(
        SalesOrderHeader.objects.filter(cur)
        .values("territory__name").annotate(rev=Sum("sub_total")).order_by("-rev")[:8],
        "territory__name", "rev", money,
    )
    salespeople = rank(
        [
            {
                "name": " ".join(x for x in (
                    s["sales_person__business_entity__business_entity__first_name"],
                    s["sales_person__business_entity__business_entity__last_name"],
                ) if x),
                "rev": s["rev"],
            }
            for s in SalesOrderHeader.objects.filter(cur, sales_person__isnull=False)
            .values(
                "sales_person__business_entity__business_entity__first_name",
                "sales_person__business_entity__business_entity__last_name",
            )
            .annotate(rev=Sum("sub_total")).order_by("-rev")[:8]
        ],
        "name", "rev", money,
    )
    products = rank(
        SalesOrderDetail.objects.filter(sales_order__order_date__gte=trend_start,
                                       sales_order__order_date__lte=w.last)
        .values("product__name").annotate(rev=Sum("line_total")).order_by("-rev")[:8],
        "product__name", "rev", money,
    )
    offers = rank(
        SalesOrderDetail.objects.filter(sales_order__order_date__gte=trend_start,
                                        sales_order__order_date__lte=w.last)
        .exclude(special_offer__description="No Discount")
        .values("special_offer__description").annotate(rev=Sum("line_total")).order_by("-rev")[:6],
        "special_offer__description", "rev", money,
    )

    biggest = [
        {
            "id": r["sales_order_id"],
            "number": r["sales_order_number"],
            "date": r["order_date"],
            "territory": r["territory__name"] or "—",
            "who": " ".join(x for x in (
                r["sales_person__business_entity__business_entity__first_name"],
                r["sales_person__business_entity__business_entity__last_name"],
            ) if x) or "—",
            "total": money(r["sub_total"]),
            "online": r["online_order_flag"],
        }
        for r in SalesOrderHeader.objects.filter(cur).order_by("-sub_total")
        .values(
            "sales_order_id", "sales_order_number", "order_date", "territory__name", "sub_total",
            "online_order_flag",
            "sales_person__business_entity__business_entity__first_name",
            "sales_person__business_entity__business_entity__last_name",
        )[:8]
    ]

    if request.GET.get("export") == "csv":
        rows = [["Period", w.label, "compare", w.prev_label]]
        rows += [["KPI", k["label"], k["value"], f"{k['delta']} · {k['cap']}" if k["delta"] else k["cap"]]
                 for k in kpis]
        rows += [["Channel", c["name"], c["money"], f"{c['pct']}% · {c['orders']} orders · {c['aov']} avg"]
                 for c in channels]
        rows += [["Territory", r["name"], r["value"], ""] for r in territories]
        rows += [["Salesperson", r["name"], r["value"], ""] for r in salespeople]
        rows += [["Product", r["name"], r["value"], ""] for r in products]
        rows += [["Offer", r["name"], r["value"], ""] for r in offers]
        rows += [["Top order", r["number"], r["total"], f"{r['date']:%Y-%m-%d} · {r['territory']} · {r['who']}"]
                 for r in biggest]
        return csv_response("sales.csv", ["Section", "Item", "Value", "Detail"], rows)

    return render(request, "core/sales/dashboard.html", {
        "tab": "sales",
        "title": "Sales",
        "kpis": kpis,
        "trend": trend,
        "channels": channels,
        "territories": territories,
        "salespeople": salespeople,
        "products": products,
        "offers": offers,
        "biggest": biggest,
        "through": w.last,
        "window_label": w.label,
        "prev_label": w.prev_label,
        "w_from": w.trend_start.strftime("%Y-%m-%d"),
        "w_to": w.last.strftime("%Y-%m-%d"),
    })


@permission_required("core.access_customer_profile", raise_exception=True)
def customer_profile(request):
    """Customer profile dashboard: who buys (individuals vs stores), how often they come
    back, where they are, and which stores make up the B2B side."""
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return render(request, "core/customer-profile/dashboard.html",
                      {"tab": "customer-profile", "title": "Customer profile"})

    cur, prev, trend_start = w.cur, w.prev, w.trend_start
    firsts = SalesCustomer.objects.annotate(first=Min("salesorderheader__order_date"))
    newl = firsts.filter(first__gte=trend_start, first__lte=w.last)
    new_ids = newl.values("customer_id")
    prev_ids = (SalesOrderHeader.objects.filter(order_date__gte=w.window_start, order_date__lt=trend_start)
                .values("customer"))

    totals = SalesOrderHeader.objects.filter(order_date__gte=w.window_start).aggregate(
        actives=Count("customer", filter=cur, distinct=True),
        actives_prev=Count("customer", filter=prev, distinct=True),
        rev=Sum("sub_total", filter=cur),
        rev_prev=Sum("sub_total", filter=prev),
        new_rev=Sum("sub_total", filter=cur & Q(customer__in=new_ids)),
        kept=Count("customer", filter=cur & Q(customer__in=prev_ids), distinct=True),
    )
    new_count = newl.count()
    prev_new = firsts.filter(first__gte=w.window_start, first__lt=trend_start).count()

    actives, actives_prev = totals["actives"] or 0, totals["actives_prev"] or 0
    rev, rev_prev = totals["rev"] or 0, totals["rev_prev"] or 0
    new_rev = totals["new_rev"] or 0
    repeat = actives - new_count
    repeat_rev = rev - new_rev
    kept = totals["kept"] or 0

    months = list(
        SalesOrderHeader.objects.filter(cur)
        .annotate(month=TruncMonth("order_date")).values("month")
        .annotate(act=Count("customer", distinct=True)).order_by("month")
    )
    new_per_month = {}
    for d in newl.values_list("first", flat=True):
        key = d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        new_per_month[key] = new_per_month.get(key, 0) + 1
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

    split = SalesOrderHeader.objects.filter(cur).aggregate(
        ind_rev=Sum("sub_total", filter=Q(customer__store__isnull=True)),
        ind_orders=Count("sales_order_id", filter=Q(customer__store__isnull=True)),
        ind_customers=Count("customer", filter=Q(customer__store__isnull=True), distinct=True),
        st_rev=Sum("sub_total", filter=Q(customer__store__isnull=False)),
        st_orders=Count("sales_order_id", filter=Q(customer__store__isnull=False)),
        st_customers=Count("customer", filter=Q(customer__store__isnull=False), distinct=True),
    )
    ind_rev, st_rev = split["ind_rev"] or 0, split["st_rev"] or 0
    ind_n, st_n = split["ind_customers"] or 0, split["st_customers"] or 0
    st_share = round(float(st_rev) / float(rev) * 100) if rev else 0
    channels = [
        {"name": "Individuals", "pct": 100 - st_share, "cls": "online",
         "money": money(ind_rev), "customers": f"{ind_n:,}",
         "aov": money((ind_rev / split["ind_orders"]) if split["ind_orders"] else None)},
        {"name": "Stores", "pct": st_share, "cls": "store",
         "money": money(st_rev), "customers": f"{st_n:,}",
         "aov": money((st_rev / split["st_orders"]) if split["st_orders"] else None)},
    ]
    donut = ring([{"cls": c["cls"], "pct": c["pct"],
                   "t": f"{c['name']} · {c['money']} · {c['pct']}% of revenue · {c['customers']} customers"}
                  for c in channels])

    country_rows = list(
        SalesOrderHeader.objects.filter(cur)
        .values("ship_to_address__state_province__country_region__name")
        .annotate(rev=Sum("sub_total"), orders=Count("sales_order_id")).order_by("-rev")[:6]
    )
    countries = rank(country_rows, "ship_to_address__state_province__country_region__name", "rev", money)
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
        name = r["ship_to_address__state_province__country_region__name"]
        if name not in geo:
            continue
        code, lat, lon = geo[name]
        bubbles.append({
            "code": code, "lat": lat, "lon": lon,
            "r": round(9 + 17 * (float(r["rev"] or 0) / top_country) ** 0.5, 1),
            "title": f"{name} · {money(r['rev'])} · {r['orders']:,} orders",
        })
    cities = rank(
        SalesOrderHeader.objects.filter(cur).values("ship_to_address__city")
        .annotate(rev=Sum("sub_total")).order_by("-rev")[:8],
        "ship_to_address__city", "rev", money,
    )

    type_stats, store_rev = {}, {}
    for demo in SalesStore.objects.exclude(demographics__isnull=True).values_list("demographics", flat=True):
        m = re.search(r"<BusinessType>([^<]*)</BusinessType>", demo)
        if not m:
            continue
        b = type_stats.setdefault(m.group(1), {"n": 0, "sqft": 0.0, "emp": 0.0})
        b["n"] += 1
        for tag, key in (("SquareFeet", "sqft"), ("NumberEmployees", "emp")):
            v = re.search(rf"<{tag}>(\d+)</{tag}>", demo)
            if v:
                b[key] += int(v.group(1))
    for r in (SalesOrderHeader.objects.filter(cur, customer__store__isnull=False)
              .values("customer__store__demographics").annotate(rev=Sum("sub_total"))):
        m = re.search(r"<BusinessType>([^<]*)</BusinessType>", r["customer__store__demographics"] or "")
        if m:
            store_rev[m.group(1)] = store_rev.get(m.group(1), 0) + float(r["rev"] or 0)
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

    buckets = {"1 order": 0, "2 orders": 0, "3–4 orders": 0, "5–9 orders": 0, "10+ orders": 0}
    for r in SalesOrderHeader.objects.filter(cur).values("customer").annotate(n=Count("sales_order_id")):
        n = r["n"]
        key = "1 order" if n == 1 else "2 orders" if n == 2 else "3–4 orders" if n <= 4 else "5–9 orders" if n <= 9 else "10+ orders"
        buckets[key] += 1
    frequency = rank([{"name": k, "n": v} for k, v in buckets.items()], "name", "n", lambda v: f"{int(v):,}")

    def top_buyers(store, count):
        rows = (SalesOrderHeader.objects.filter(cur, customer__store__isnull=not store)
                .values("customer", "customer__store__name", "customer__person__first_name",
                        "customer__person__last_name", "customer__territory__name")
                .annotate(orders=Count("sales_order_id"), rev=Sum("sub_total")).order_by("-rev")[:count])
        out = []
        for r in rows:
            name = r["customer__store__name"] or " ".join(
                x for x in (r["customer__person__first_name"], r["customer__person__last_name"]) if x)
            out.append({"id": r["customer"], "name": name or f"Customer {r['customer']}", "store": store,
                        "territory": r["customer__territory__name"] or "—",
                        "orders": r["orders"], "rev": money(r["rev"])})
        return out

    biggest = top_buyers(True, 6) + top_buyers(False, 3)

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

    return render(request, "core/customer-profile/dashboard.html", {
        "tab": "customer-profile",
        "title": "Customer profile",
        "kpis": kpis,
        "growth": growth,
        "channels": channels,
        "donut": donut,
        "donut_mid": {"big": money(rev), "small": "revenue"},
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
        "w_from": w.trend_start.strftime("%Y-%m-%d"),
        "w_to": w.last.strftime("%Y-%m-%d"),
    })


@permission_required("core.access_cost", raise_exception=True)
def cost(request):
    """Cost dashboard: what the merchandise cost us (standard cost), what we spent
    buying it (purchase orders), and what manufacturing wasted (work order scrap)."""
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return render(request, "core/cost/dashboard.html",
                      {"tab": "cost", "title": "Cost"})

    cur, prev, trend_start = w.cur, w.prev, w.trend_start
    detail = SalesOrderDetail.objects.filter(sales_order__order_date__gte=w.window_start)
    cur_f = Q(sales_order__order_date__gte=trend_start, sales_order__order_date__lte=w.last)
    prev_f = Q(sales_order__order_date__gte=w.window_start, sales_order__order_date__lt=trend_start)

    sold = detail.aggregate(
        cogs=Sum(line_cost(), filter=cur_f),
        cogs_prev=Sum(line_cost(), filter=prev_f),
        rev=Sum("line_total", filter=cur_f),
        rev_prev=Sum("line_total", filter=prev_f),
    )
    cogs, cogs_prev = sold["cogs"] or 0, sold["cogs_prev"] or 0
    rev, rev_prev = sold["rev"] or 0, sold["rev_prev"] or 0
    ratio = float(cogs) / float(rev) * 100 if rev else None
    ratio_prev = float(cogs_prev) / float(rev_prev) * 100 if rev_prev else None

    po_window = PurchasingPurchaseOrderHeader.objects.filter(order_date__gte=trend_start, order_date__lte=w.last)
    proc = po_window.aggregate(spend=Sum("sub_total"), orders=Count("purchase_order_id"))
    proc_prev = PurchasingPurchaseOrderHeader.objects.filter(
        order_date__gte=w.window_start, order_date__lt=trend_start).aggregate(spend=Sum("sub_total"))
    po_lines = PurchasingPurchaseOrderDetail.objects.filter(
        purchase_order__order_date__gte=trend_start, purchase_order__order_date__lte=w.last)
    rec = po_lines.aggregate(rec=Sum("received_qty"), rej=Sum("rejected_qty"))
    rej_pct = float(rec["rej"] or 0) / float(rec["rec"] or 1) * 100

    wos = ProductionWorkOrder.objects.filter(start_date__gte=w.window_start, start_date__lte=w.last)
    scrap = wos.aggregate(
        qty=Sum("order_qty", filter=Q(start_date__gte=trend_start)),
        scr=Sum("scrapped_qty", filter=Q(start_date__gte=trend_start)),
        qty_prev=Sum("order_qty", filter=Q(start_date__lt=trend_start)),
        scr_prev=Sum("scrapped_qty", filter=Q(start_date__lt=trend_start)),
    )
    rate = (scrap["scr"] or 0) / (scrap["qty"] or 1) * 100
    rate_prev = (scrap["scr_prev"] or 0) / (scrap["qty_prev"] or 1) * 100

    pipeline = [
        {"k": "Buy", "big": money(proc["spend"]), "cap": f"{proc['orders']:,} purchase orders", "cls": ""},
        {"k": "Make", "big": f"{scrap['qty']:,}", "cap": "units started on work orders", "cls": ""},
        {"k": "Waste", "big": f"{scrap['scr']:,}", "cap": f"units scrapped · {rate:.2f}%", "cls": "bad"},
        {"k": "Sell", "big": money(cogs), "cap": "cost of goods sold to customers", "cls": ""},
    ]

    kpis = []
    for label, value, change, cap in (
        ("Cost of goods sold", money(cogs), delta(cogs, cogs_prev), "standard cost of merchandise sold"),
        ("Cost per $1 revenue", f"{ratio:.0f}¢", delta(ratio, ratio_prev), f"was {ratio_prev:.0f}¢ last year"),
        ("Procurement spend", money(proc["spend"]), delta(proc["spend"], proc_prev["spend"]),
         f"{proc['orders']:,} purchase orders"),
        ("Scrap rate", f"{rate:.2f}%", delta(rate, rate_prev),
         f"{scrap['scr']:,} units of {scrap['qty']:,} started"),
        ("Rejected receipts", f"{rej_pct:.1f}%", (None, None),
         f"{rec['rej']:,.0f} units of {rec['rec']:,.0f} received"),
    ):
        kpis.append({"label": label, "value": value, "delta": change[0], "dir": change[1], "cap": cap})

    months = list(
        detail.filter(cur_f)
        .annotate(month=TruncMonth("sales_order__order_date")).values("month")
        .annotate(cogs=Sum(line_cost()), rev=Sum("line_total")).order_by("month")
    )
    top = max((float(m["cogs"]) for m in months), default=0)
    trend = [
        {
            "label": m["month"].strftime("%b"), "full": m["month"].strftime("%b %Y"),
            "money": money(m["cogs"]),
            "margin": round((float(m["rev"]) - float(m["cogs"])) / float(m["rev"]) * 100, 1) if m["rev"] else 0,
            "height": round(float(m["cogs"]) / top * 100, 2) if top else 0,
        }
        for m in months
    ]

    cats = list(
        detail.filter(cur_f)
        .values("product__product_subcategory__product_category__name")
        .annotate(cogs=Sum(line_cost()), rev=Sum("line_total")).order_by("-cogs")
    )
    total_cogs = float(cogs) or 1
    mix = [
        {
            "name": r["product__product_subcategory__product_category__name"],
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

    vendor_rows = list(po_window.values("vendor__name")
                       .annotate(spend=Sum("sub_total"), orders=Count("purchase_order_id")).order_by("-spend")[:8])
    vendors = rank(vendor_rows, "vendor__name", "spend", money)
    for r, s in zip(vendors, vendor_rows):
        r["note"] = f"{s['orders']:,} purchase orders"

    costly = list(detail.filter(cur_f).values("product__name")
                  .annotate(cogs=Sum(line_cost()), units=Sum("order_qty")).order_by("-cogs")[:8])
    products = rank(costly, "product__name", "cogs", money)
    for r, s in zip(products, costly):
        r["note"] = f"{s['units']:,} units"

    reason_rows = list(
        ProductionWorkOrder.objects.filter(start_date__gte=trend_start, start_date__lte=w.last,
                                           scrap_reason__isnull=False)
        .values("scrap_reason__name")
        .annotate(scr=Sum("scrapped_qty"), orders=Count("work_order_id")).order_by("-scr")[:8]
    )
    reasons = rank(reason_rows, "scrap_reason__name", "scr", lambda v: f"{int(v):,} units")
    for r, s in zip(reasons, reason_rows):
        r["note"] = f"{s['orders']:,} work orders"

    open_cost = {r["product_id"]: r["standard_cost"]
                 for r in ProductionProductCostHistory.objects.filter(end_date__isnull=True)
                 .values("product_id", "standard_cost")}
    earliest = {}
    for r in (ProductionProductCostHistory.objects.filter(end_date__isnull=False).order_by("start_date")
              .values("product_id", "product__name", "standard_cost")):
        earliest.setdefault(r["product_id"], r)
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
        row["value"] = f"{h['old']:,.2f} → {h['now']:,.2f}"
        row["note"] = "standard cost per unit"

    statuses = {1: ("Pending", ""), 2: ("Approved", "online"), 3: ("Rejected", "bad"), 4: ("Complete", "")}
    biggest = [
        {
            "id": r["purchase_order_id"], "vendor": r["vendor__name"], "date": r["order_date"],
            "lines": r["lines"], "total": money(r["total_due"]),
            "status": statuses.get(r["status"], ("—", ""))[0], "cls": statuses.get(r["status"], ("", ""))[1],
        }
        for r in po_window.annotate(lines=Count("purchasingpurchaseorderdetail"))
        .order_by("-total_due")
        .values("purchase_order_id", "vendor__name", "order_date", "total_due", "status", "lines")[:8]
    ]

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
        rows += [["Purchase order", f"PO{r['id']}", r["total"],
                  f"{r['date']:%Y-%m-%d} · {r['vendor']} · {r['status']}"] for r in biggest]
        return csv_response("cost.csv", ["Section", "Item", "Value", "Detail"], rows)

    return render(request, "core/cost/dashboard.html", {
        "tab": "cost",
        "title": "Cost",
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
        "through": w.last,
        "window_label": w.label,
        "prev_label": w.prev_label,
        "w_from": w.trend_start.strftime("%Y-%m-%d"),
        "w_to": w.last.strftime("%Y-%m-%d"),
    })


@permission_required("core.access_revenue_and_loss", raise_exception=True)
def revenue_and_loss(request):
    """Revenue and loss dashboard: revenue, cost, gross profit and where the money leaks
    (below-cost wholesale lines, discounts, tax collected)."""
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return render(request, "core/revenue-and-loss/dashboard.html",
                      {"tab": "revenue-and-loss", "title": "Revenue and loss"})

    cur, prev, trend_start = w.cur, w.prev, w.trend_start
    detail = SalesOrderDetail.objects.filter(sales_order__order_date__gte=w.window_start)
    cur_f = Q(sales_order__order_date__gte=trend_start, sales_order__order_date__lte=w.last)
    prev_f = Q(sales_order__order_date__gte=w.window_start, sales_order__order_date__lt=trend_start)
    discount = ExpressionWrapper(F("order_qty") * F("unit_price") * F("unit_price_discount"),
                                 output_field=DecimalField(max_digits=25, decimal_places=6))

    sold = detail.aggregate(
        rev=Sum("line_total", filter=cur_f),
        rev_prev=Sum("line_total", filter=prev_f),
        cogs=Sum(line_cost(), filter=cur_f),
        cogs_prev=Sum(line_cost(), filter=prev_f),
        ind_rev=Sum("line_total", filter=cur_f & Q(sales_order__customer__store__isnull=True)),
        ind_cogs=Sum(line_cost(), filter=cur_f & Q(sales_order__customer__store__isnull=True)),
        st_rev=Sum("line_total", filter=cur_f & Q(sales_order__customer__store__isnull=False)),
        st_cogs=Sum(line_cost(), filter=cur_f & Q(sales_order__customer__store__isnull=False)),
    )
    hdr = SalesOrderHeader.objects.filter(order_date__gte=w.window_start).aggregate(
        tax=Sum("tax_amt", filter=cur), freight=Sum("freight", filter=cur),
        due=Sum("total_due", filter=cur), due_prev=Sum("total_due", filter=prev),
    )

    rev, cogs = sold["rev"] or 0, sold["cogs"] or 0
    profit = rev - cogs
    profit_prev = (sold["rev_prev"] or 0) - (sold["cogs_prev"] or 0)
    margin = round(float(profit) / float(rev) * 100, 1) if rev else 0
    prev_margin = round(float(profit_prev) / float(sold["rev_prev"]) * 100, 1) if sold["rev_prev"] else 0
    ind_m = round(float(sold["ind_rev"] - sold["ind_cogs"]) / float(sold["ind_rev"]) * 100, 1) if sold["ind_rev"] else 0
    st_m = round(float(sold["st_rev"] - sold["st_cogs"]) / float(sold["st_rev"]) * 100, 1) if sold["st_rev"] else 0

    losses = detail.filter(cur_f, line_total__lt=F("order_qty") * F("product__standard_cost"))
    loss = losses.aggregate(n=Count("pk"), rev=Sum("line_total"), cost=Sum(line_cost()))
    short = (loss["cost"] or 0) - (loss["rev"] or 0)

    kpis = []
    for label, value, change, cap in (
        ("Revenue", money(rev), delta(rev, sold["rev_prev"]), "merchandise, excl. tax & freight"),
        ("Cost of goods", money(cogs), delta(cogs, sold["cogs_prev"]), "at current standard cost"),
        ("Gross profit", money(profit), delta(profit, profit_prev),
         f"{margin}% margin · was {prev_margin}% · individual {ind_m}% / store {st_m}%"),
        ("Invoiced total", money(hdr["due"]), delta(hdr["due"], hdr["due_prev"]),
         f"incl. {money(hdr['tax'])} tax · {money(hdr['freight'])} freight"),
        ("Below-cost sales", money(short), (None, None), f"{loss['n']:,} store lines below standard cost"),
    ):
        kpis.append({"label": label, "value": value, "delta": change[0], "dir": change[1], "cap": cap})

    months24 = list(
        detail.filter(sales_order__order_date__gte=min(w.window_start, shift_months(trend_start, -MONTHS - 1)),
                      sales_order__order_date__lte=w.last)
        .annotate(month=TruncMonth("sales_order__order_date")).values("month")
        .annotate(rev=Sum("line_total"), cogs=Sum(line_cost())).order_by("month")
    )

    def margin_of(row):
        return round((float(row["rev"]) - float(row["cogs"])) / float(row["rev"]) * 100, 1) if row["rev"] else 0.0

    cur_rows = [r for r in months24 if r["month"] >= trend_start]
    cur_dates = [r["month"] for r in cur_rows]
    prev_map = {r["month"]: margin_of(r) for r in months24 if r["month"] < trend_start}
    prev_dates = [shift_months(m, -12) for m in cur_dates]  # the same month a year earlier
    cur_vals = [margin_of(r) for r in cur_rows]
    prev_vals = [prev_map.get(m, 0.0) for m in prev_dates]

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

    cats = list(
        detail.filter(cur_f)
        .values("product__product_subcategory__product_category__name")
        .annotate(rev=Sum("line_total"), cogs=Sum(line_cost())).order_by("-rev")
    )
    total_rev = float(rev) or 1
    mix = [
        {
            "name": r["product__product_subcategory__product_category__name"],
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

    terr = list(detail.filter(cur_f).values("sales_order__territory__name")
                .annotate(rev=Sum("line_total"), cogs=Sum(line_cost())))
    terr.sort(key=lambda r: -(float(r["rev"]) - float(r["cogs"])))
    top_profit = float(terr[0]["rev"]) - float(terr[0]["cogs"]) if terr else 0
    territories = []
    for r in terr:
        p = float(r["rev"]) - float(r["cogs"])
        territories.append({
            "name": r["sales_order__territory__name"] or "—",
            "value": ("-" if p < 0 else "") + money(abs(p)),
            "pct": max(round(p / top_profit * 100), 2) if top_profit else 0,
            "note": f"{round(p / float(r['rev']) * 100, 1)}% margin" if r["rev"] else "",
        })

    leak_rows = list(losses.values("product__name")
                     .annotate(gap=Sum(line_cost()) - Sum("line_total"), n=Count("pk")).order_by("-gap")[:6])
    leaks = rank(leak_rows, "product__name", "gap", lambda v: f"-{money(v)}")
    for r, s in zip(leaks, leak_rows):
        r["note"] = f"{s['n']:,} lines"

    offer_rows = list(detail.filter(cur_f, unit_price_discount__gt=0)
                      .values("special_offer__description")
                      .annotate(d=Sum(discount), n=Count("pk")).order_by("-d")[:6])
    discounts = rank(offer_rows, "special_offer__description", "d", money)
    for r, s in zip(discounts, offer_rows):
        r["note"] = f"{s['n']:,} lines"

    rates = {}
    for name, rate in SalesTaxRate.objects.values_list("state_province__name", "tax_rate"):
        rates.setdefault(name, rate)
    tax_rows = list(SalesOrderHeader.objects.filter(cur)
                    .values("ship_to_address__state_province__name")
                    .annotate(tax=Sum("tax_amt")).order_by("-tax")[:6])
    taxes = rank(tax_rows, "ship_to_address__state_province__name", "tax", money)
    for r, s in zip(taxes, tax_rows):
        rate = rates.get(s["ship_to_address__state_province__name"])
        r["note"] = f"{float(rate):g}% rate" if rate is not None else "no tax rate on file"

    prods = list(detail.filter(cur_f).values("product__product_id", "product__name")
                 .annotate(rev=Sum("line_total"), cogs=Sum(line_cost())).order_by("-rev")[:12])
    prods.sort(key=lambda r: -(float(r["rev"]) - float(r["cogs"])))
    products = [
        {
            "id": r["product__product_id"], "name": r["product__name"],
            "rev": money(r["rev"]), "cost": money(r["cogs"]),
            "profit": money(float(r["rev"]) - float(r["cogs"])),
            "margin": f"{round((float(r['rev']) - float(r['cogs'])) / float(r['rev']) * 100, 1)}%",
        }
        for r in prods[:8]
    ]

    if request.GET.get("export") == "csv":
        rows = [["Period", w.label, "compare", w.prev_label]]
        rows += [["KPI", k["label"], k["value"], f"{k['delta']} · {k['cap']}" if k["delta"] else k["cap"]]
                 for k in kpis]
        rows += [["Category", m["name"], m["money"], f"{m['pct']}% of revenue · {m['margin']}% margin"]
                 for m in mix]
        rows += [["Territory", r["name"], r["value"], r["note"]] for r in territories]
        rows += [["Below-cost product", r["name"], r["value"], r["note"]] for r in leaks]
        rows += [["Discount", r["name"], r["value"], r["note"]] for r in discounts]
        rows += [["Tax", r["name"], r["value"], r["note"]] for r in taxes]
        rows += [["Product", r["name"], r["rev"], f"cost {r['cost']} · profit {r['profit']} · {r['margin']} margin"]
                 for r in products]
        return csv_response("revenue-and-loss.csv", ["Section", "Item", "Value", "Detail"], rows)

    return render(request, "core/revenue-and-loss/dashboard.html", {
        "tab": "revenue-and-loss",
        "title": "Revenue and loss",
        "kpis": kpis,
        "combo": combo,
        "donut": donut,
        "donut_mid": {"big": money(rev), "small": "revenue"},
        "mix": mix,
        "territories": territories,
        "leaks": leaks,
        "discounts": discounts,
        "taxes": taxes,
        "products": products,
        "through": w.last,
        "window_label": w.label,
        "prev_label": w.prev_label,
        "w_from": w.trend_start.strftime("%Y-%m-%d"),
        "w_to": w.last.strftime("%Y-%m-%d"),
    })


# ---------------------------------------------------------------------------
# The generic table browser: one set of views drives every table in every tab.

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
                widget.is_required = field.required
                widget.queryset = qs
                widget.url = reverse("table_autocomplete", args=[self.tab, self.model.__name__, name])
                field.widget = widget
                field.queryset = qs
        return form

    def form_valid(self, form):
        if hasattr(form.instance, "modified_date"):
            form.instance.modified_date = timezone.now()
        messages.success(self.request, f"Saved {form.instance}.")
        return super().form_valid(form)


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
        try:
            return super().post(request, *args, **kwargs)
        except ProtectedError as e:
            kinds = ", ".join(sorted({type(o).__name__ for o in e.protected_objects}))
            messages.error(request, f"Cannot delete: {len(e.protected_objects)} record(s) in {kinds} still point to it.")
            return redirect(request.path)
