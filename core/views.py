"""All views for the app: home, the four dashboards, and the generic table browser
(list / detail / edit / delete / autocomplete) used by every table."""
import re
from datetime import date, datetime, time

from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import FieldDoesNotExist
from django.db import connection
from django.db.models import ProtectedError, Q, TextField
from django.db.models.functions import Cast
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DeleteView, DetailView, ListView, UpdateView

from .forms import PrivacyAuthenticationForm
from .models import (
    AuditLog,
    PRIVACY_NOTICE_VERSION,
    PrivacyAcknowledgment,
    SalesOrderHeader,
)
from .utils import csv_response, delta, money, rank, ring, shift_months, window_for
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


@permission_required("core.access_sales", raise_exception=True)
def sales(request):
    """Sales dashboard: one aggregate query per panel, all windows anchored to the
    data's own last order date (the sample data is historical, so "today" would be empty)."""
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return render(request, "core/sales/dashboard.html",
                      {"tab": "sales", "title": "Sales"})

    cur_lo, cur_hi = w.trend_start, w.last
    prev_lo, prev_hi = w.window_start, w.trend_start

    with connection.cursor() as c:  # chart 1: the five KPI cards
        c.execute(
            """
            SELECT
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate <= %s THEN SubTotal END), 0) AS rev,
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate < %s THEN SubTotal END), 0) AS rev_prev,
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate <= %s THEN 1 ELSE 0 END), 0) AS orders,
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate < %s THEN 1 ELSE 0 END), 0) AS orders_prev,
              COUNT(DISTINCT CASE WHEN OrderDate >= %s AND OrderDate <= %s THEN CustomerID END) AS customers,
              COUNT(DISTINCT CASE WHEN OrderDate >= %s AND OrderDate < %s THEN CustomerID END) AS customers_prev,
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate <= %s AND OnlineOrderFlag = 1
                                THEN SubTotal END), 0) AS online_rev,
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate <= %s AND OnlineOrderFlag = 1
                                THEN 1 ELSE 0 END), 0) AS online_orders
            FROM Sales_SalesOrderHeader
            WHERE OrderDate >= %s
            """,
            [cur_lo, cur_hi, prev_lo, prev_hi, cur_lo, cur_hi, prev_lo, prev_hi,
             cur_lo, cur_hi, prev_lo, prev_hi, cur_lo, cur_hi, cur_lo, cur_hi, w.window_start],
        )
        (rev, rev_prev, orders, orders_prev, customers, customers_prev,
         online_rev, online_orders) = c.fetchone()

    aov = (rev / orders) if orders else None
    aov_prev = (rev_prev / orders_prev) if orders_prev else None
    share = round(float(online_rev) / float(rev) * 100) if rev else 0

    kpis = []
    for label, value, change, cap in (
        ("Revenue", money(rev), delta(rev, rev_prev), "merchandise, excl. tax & freight"),
        ("Orders", f"{orders:,}", delta(orders, orders_prev), "sales orders placed"),
        ("Avg order value", money(aov), delta(aov, aov_prev), "revenue per order"),
        ("Customers", f"{customers or 0:,}", delta(customers, customers_prev), "distinct buyers"),
        ("Online share", f"{share}%", (None, None), f"{money(online_rev)} · {online_orders:,} orders"),
    ):
        kpis.append({"label": label, "value": value, "delta": change[0], "dir": change[1], "cap": cap})

    with connection.cursor() as c:  # chart 2: monthly revenue, current vs previous window
        c.execute(
            """
            SELECT substr(OrderDate, 1, 7) AS month,
                   CASE WHEN OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
                   SUM(SubTotal) AS rev,
                   COUNT(*) AS orders
            FROM Sales_SalesOrderHeader
            WHERE OrderDate >= %s AND OrderDate <= %s
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
            "prev_money": money(prev_months[i]["rev"]) if i < len(prev_months) else "—",
            "prev_orders": f"{prev_months[i]['orders']:,}" if i < len(prev_months) else "—",
            "prev_h": (max(round(float(prev_months[i]["rev"] or 0) / top * 100), 2)
                       if i < len(prev_months) and prev_months[i]["rev"] and top else 0),
        }
        for i, m in enumerate(months)
    ]

    channels = [
        {"name": "Online", "pct": share, "money": money(online_rev), "orders": f"{online_orders:,}",
         "aov": money((online_rev / online_orders) if online_orders else None), "cls": "online"},
        {"name": "Assisted", "pct": 100 - share, "money": money(rev - online_rev), "orders": f"{orders - online_orders:,}",
         "aov": money(((rev - online_rev) / (orders - online_orders)) if orders - online_orders else None), "cls": "store"},
    ]

    with connection.cursor() as c:  # chart 3: top territories
        c.execute(
            """
            SELECT t.Name, SUM(h.SubTotal) AS rev
            FROM Sales_SalesOrderHeader h
            JOIN Sales_SalesTerritory t ON t.TerritoryID = h.TerritoryID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY t.Name
            ORDER BY rev DESC
            LIMIT 8
            """,
            [cur_lo, cur_hi],
        )
        territories = rank([{"name": name, "rev": rev} for name, rev in c.fetchall()],
                           "name", "rev", money)

    with connection.cursor() as c:  # chart 4: top salespeople
        c.execute(
            """
            SELECT p.FirstName, p.LastName, SUM(h.SubTotal) AS rev
            FROM Sales_SalesOrderHeader h
            JOIN Sales_SalesPerson sp ON sp.BusinessEntityID = h.SalesPersonID
            JOIN HumanResources_Employee e ON e.BusinessEntityID = sp.BusinessEntityID
            JOIN Person_Person p ON p.BusinessEntityID = e.BusinessEntityID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY p.FirstName, p.LastName
            ORDER BY rev DESC
            LIMIT 8
            """,
            [cur_lo, cur_hi],
        )
        salespeople = rank(
            [{"name": " ".join(x for x in (first, last) if x), "rev": rev}
             for first, last, rev in c.fetchall()],
            "name", "rev", money,
        )

    with connection.cursor() as c:  # chart 5: top products
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

    with connection.cursor() as c:  # chart 6: promotions that sold
        c.execute(
            """
            SELECT o.Description, SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Sales_SpecialOffer o ON o.SpecialOfferID = d.SpecialOfferID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
              AND o.Description <> 'No Discount'
            GROUP BY o.Description
            ORDER BY rev DESC
            LIMIT 6
            """,
            [cur_lo, cur_hi],
        )
        offers = rank([{"name": name, "rev": rev} for name, rev in c.fetchall()],
                      "name", "rev", money)

    with connection.cursor() as c:  # chart 7: biggest orders
        c.execute(
            """
            SELECT h.SalesOrderID, h.SalesOrderNumber, h.OrderDate, t.Name,
                   h.SubTotal, h.OnlineOrderFlag, p.FirstName, p.LastName
            FROM Sales_SalesOrderHeader h
            LEFT JOIN Sales_SalesTerritory t ON t.TerritoryID = h.TerritoryID
            LEFT JOIN Sales_SalesPerson sp ON sp.BusinessEntityID = h.SalesPersonID
            LEFT JOIN HumanResources_Employee e ON e.BusinessEntityID = sp.BusinessEntityID
            LEFT JOIN Person_Person p ON p.BusinessEntityID = e.BusinessEntityID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            ORDER BY h.SubTotal DESC
            LIMIT 8
            """,
            [cur_lo, cur_hi],
        )
        biggest = [
            {
                "id": order_id,
                "number": number,
                "date": order_date,
                "territory": territory or "—",
                "who": " ".join(x for x in (first, last) if x) or "—",
                "total": money(total),
                "online": online,
            }
            for order_id, number, order_date, territory, total, online, first, last in c.fetchall()
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
        "custom": w.custom,
        "period": "the selected range" if w.custom else "the last 12 months",
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

    cur_lo, cur_hi = w.trend_start, w.last
    prev_lo, prev_hi = w.window_start, w.trend_start

    with connection.cursor() as c:  # chart 1: the five KPI cards
        c.execute(
            """
            WITH firsts AS (
                SELECT CustomerID, MIN(OrderDate) AS first_date
                FROM Sales_SalesOrderHeader GROUP BY CustomerID
            )
            SELECT
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                                THEN h.SubTotal END), 0) AS rev,
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate < %s
                                THEN h.SubTotal END), 0) AS rev_prev,
              COUNT(DISTINCT CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                                  THEN h.CustomerID END) AS actives,
              COUNT(DISTINCT CASE WHEN h.OrderDate >= %s AND h.OrderDate < %s
                                  THEN h.CustomerID END) AS actives_prev,
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                                 AND f.first_date >= %s AND f.first_date <= %s
                                THEN h.SubTotal END), 0) AS new_rev
            FROM Sales_SalesOrderHeader h
            JOIN firsts f ON f.CustomerID = h.CustomerID
            WHERE h.OrderDate >= %s
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
              COALESCE(SUM(CASE WHEN cu.StoreID IS NULL THEN h.SubTotal END), 0) AS ind_rev,
              COALESCE(SUM(CASE WHEN cu.StoreID IS NOT NULL THEN h.SubTotal END), 0) AS st_rev,
              COALESCE(SUM(CASE WHEN cu.StoreID IS NULL THEN 1 ELSE 0 END), 0) AS ind_orders,
              COALESCE(SUM(CASE WHEN cu.StoreID IS NOT NULL THEN 1 ELSE 0 END), 0) AS st_orders,
              COUNT(DISTINCT CASE WHEN cu.StoreID IS NULL THEN h.CustomerID END) AS ind_customers,
              COUNT(DISTINCT CASE WHEN cu.StoreID IS NOT NULL THEN h.CustomerID END) AS st_customers
            FROM Sales_SalesOrderHeader h
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
            SELECT co.Name, SUM(h.SubTotal) AS rev, COUNT(*) AS orders
            FROM Sales_SalesOrderHeader h
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
            SELECT a.City, SUM(h.SubTotal) AS rev
            FROM Sales_SalesOrderHeader h
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
            SELECT s.Demographics, SUM(h.SubTotal) AS rev
            FROM Sales_SalesOrderHeader h
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
                   COUNT(*) AS orders, SUM(h.SubTotal) AS rev
            FROM Sales_SalesOrderHeader h
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
                   COUNT(*) AS orders, SUM(h.SubTotal) AS rev
            FROM Sales_SalesOrderHeader h
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

    return render(request, "core/customer-profile/dashboard.html", {
        "tab": "customer-profile",
        "title": "Customer profile",
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
    })


@permission_required("core.access_cost", raise_exception=True)
def cost(request):
    """Cost dashboard: what the merchandise cost us (standard cost), what we spent
    buying it (purchase orders), and what manufacturing wasted (work order scrap)."""
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return render(request, "core/cost/dashboard.html",
                      {"tab": "cost", "title": "Cost"})

    cur_lo, cur_hi = w.trend_start, w.last
    prev_lo, prev_hi = w.window_start, w.trend_start

    with connection.cursor() as c:  # chart 1: cost KPIs (sales lines at standard cost)
        c.execute(
            """
            SELECT
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                                THEN d.OrderQty * p.StandardCost END), 0) AS cogs,
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate < %s
                                THEN d.OrderQty * p.StandardCost END), 0) AS cogs_prev,
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate <= %s
                                THEN d.LineTotal END), 0) AS rev,
              COALESCE(SUM(CASE WHEN h.OrderDate >= %s AND h.OrderDate < %s
                                THEN d.LineTotal END), 0) AS rev_prev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
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
            WHERE OrderDate >= %s
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
        {"k": "Buy", "big": money(proc["spend"]), "cap": f"{proc['orders']:,} purchase orders", "cls": ""},
        {"k": "Make", "big": f"{scrap['qty']:,}", "cap": "units started on work orders", "cls": ""},
        {"k": "Waste", "big": f"{scrap['scr']:,}", "cap": f"units scrapped · {rate:.2f}%", "cls": "bad"},
        {"k": "Sell", "big": money(cogs), "cap": "cost of goods sold to customers", "cls": ""},
    ]

    kpis = []
    for label, value, change, cap in (
        ("Cost of goods sold", money(cogs), delta(cogs, cogs_prev), "standard cost of merchandise sold"),
        ("Cost per $1 revenue", f"{ratio:.0f}¢" if ratio is not None else "—",
         delta(ratio, ratio_prev),
         f"was {ratio_prev:.0f}¢ last year" if ratio_prev is not None else "no revenue last year"),
        ("Procurement spend", money(proc["spend"]), delta(proc["spend"], proc_prev["spend"]),
         f"{proc['orders']:,} purchase orders"),
        ("Scrap rate", f"{rate:.2f}%", delta(rate, rate_prev),
         f"{scrap['scr']:,} units of {scrap['qty']:,} started"),
        ("Rejected receipts", f"{rej_pct:.1f}%", (None, None),
         f"{rec['rej']:,.0f} units of {rec['rec']:,.0f} received"),
    ):
        kpis.append({"label": label, "value": value, "delta": change[0], "dir": change[1], "cap": cap})

    with connection.cursor() as c:  # chart 3: monthly cost of goods sold
        c.execute(
            """
            SELECT substr(h.OrderDate, 1, 7) AS month,
                   CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
                   SUM(d.OrderQty * p.StandardCost) AS cogs,
                   SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
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

    with connection.cursor() as c:  # chart 4: where costs sit (category mix)
        c.execute(
            """
            SELECT cat.Name, SUM(d.OrderQty * p.StandardCost) AS cogs,
                   SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
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

    with connection.cursor() as c:  # chart 5: top vendors by procurement spend
        c.execute(
            """
            SELECT v.Name, SUM(po.SubTotal) AS spend, COUNT(*) AS orders
            FROM Purchasing_PurchaseOrderHeader po
            JOIN Purchasing_Vendor v ON v.BusinessEntityID = po.VendorID
            WHERE po.OrderDate >= %s AND po.OrderDate <= %s
            GROUP BY v.Name
            ORDER BY spend DESC
            LIMIT 8
            """,
            [cur_lo, cur_hi],
        )
        vendor_rows = [{"name": name, "spend": vendor_spend, "orders": orders}
                       for name, vendor_spend, orders in c.fetchall()]
    vendors = rank(vendor_rows, "name", "spend", money)
    for r, s in zip(vendors, vendor_rows):
        r["note"] = f"{s['orders']:,} purchase orders"

    with connection.cursor() as c:  # chart 6: products that cost us most
        c.execute(
            """
            SELECT p.Name, SUM(d.OrderQty * p.StandardCost) AS cogs,
                   SUM(d.OrderQty) AS units
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
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

    with connection.cursor() as c:  # chart 7: scrap reasons
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

    with connection.cursor() as c:  # chart 8: standard cost changes
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
        row["value"] = f"{h['old']:,.2f} → {h['now']:,.2f}"
        row["note"] = "standard cost per unit"

    statuses = {1: ("Pending", ""), 2: ("Approved", "online"), 3: ("Rejected", "bad"), 4: ("Complete", "")}
    with connection.cursor() as c:  # chart 9: largest purchase orders
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
        "custom": w.custom,
        "period": "the selected range" if w.custom else "the last 12 months",
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

    cur_lo, cur_hi = w.trend_start, w.last
    prev_lo, prev_hi = w.window_start, w.trend_start

    with connection.cursor() as c:  # chart 1: the five KPI cards
        c.execute(
            """
            WITH lines AS (
                SELECT d.LineTotal AS rev,
                       d.OrderQty * p.StandardCost AS cost,
                       cu.StoreID AS store_id,
                       CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side
                FROM Sales_SalesOrderDetail d
                JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
                JOIN Production_Product p ON p.ProductID = d.ProductID
                LEFT JOIN Sales_Customer cu ON cu.CustomerID = h.CustomerID
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            )
            SELECT
              COALESCE(SUM(CASE WHEN side = 'cur' THEN rev END), 0) AS rev,
              COALESCE(SUM(CASE WHEN side = 'prev' THEN rev END), 0) AS rev_prev,
              COALESCE(SUM(CASE WHEN side = 'cur' THEN cost END), 0) AS cogs,
              COALESCE(SUM(CASE WHEN side = 'prev' THEN cost END), 0) AS cogs_prev,
              COALESCE(SUM(CASE WHEN side = 'cur' AND store_id IS NULL THEN rev END), 0) AS ind_rev,
              COALESCE(SUM(CASE WHEN side = 'cur' AND store_id IS NULL THEN cost END), 0) AS ind_cogs,
              COALESCE(SUM(CASE WHEN side = 'cur' AND store_id IS NOT NULL THEN rev END), 0) AS st_rev,
              COALESCE(SUM(CASE WHEN side = 'cur' AND store_id IS NOT NULL THEN cost END), 0) AS st_cogs
            FROM lines
            """,
            [w.trend_start, w.window_start, w.last],
        )
        (rev, rev_prev, cogs, cogs_prev,
         ind_rev, ind_cogs, st_rev, st_cogs) = c.fetchone()

        c.execute(  # invoiced totals from the order headers
            """
            SELECT
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate <= %s THEN TaxAmt END), 0) AS tax,
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate <= %s THEN Freight END), 0) AS freight,
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate <= %s THEN TotalDue END), 0) AS due,
              COALESCE(SUM(CASE WHEN OrderDate >= %s AND OrderDate < %s THEN TotalDue END), 0) AS due_prev
            FROM Sales_SalesOrderHeader
            WHERE OrderDate >= %s
            """,
            [cur_lo, cur_hi, cur_lo, cur_hi, cur_lo, cur_hi, prev_lo, prev_hi, w.window_start],
        )
        tax, freight, due, due_prev = c.fetchone()

        c.execute(  # lines sold below their standard cost
            """
            SELECT COUNT(*), COALESCE(SUM(d.LineTotal), 0),
                   COALESCE(SUM(d.OrderQty * p.StandardCost), 0)
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
              AND d.LineTotal < d.OrderQty * p.StandardCost
            """,
            [cur_lo, cur_hi],
        )
        loss_n, loss_rev, loss_cost = c.fetchone()

    rev, cogs = rev or 0, cogs or 0
    profit = rev - cogs
    profit_prev = (rev_prev or 0) - (cogs_prev or 0)
    margin = round(float(profit) / float(rev) * 100, 1) if rev else 0
    prev_margin = round(float(profit_prev) / float(rev_prev) * 100, 1) if rev_prev else 0
    ind_m = round(float(ind_rev - ind_cogs) / float(ind_rev) * 100, 1) if ind_rev else 0
    st_m = round(float(st_rev - st_cogs) / float(st_rev) * 100, 1) if st_rev else 0
    short = (loss_cost or 0) - (loss_rev or 0)

    kpis = []
    for label, value, change, cap in (
        ("Revenue", money(rev), delta(rev, rev_prev), "merchandise, excl. tax & freight"),
        ("Cost of goods", money(cogs), delta(cogs, cogs_prev), "at current standard cost"),
        ("Gross profit", money(profit), delta(profit, profit_prev),
         f"{margin}% margin · was {prev_margin}% · individual {ind_m}% / store {st_m}%"),
        ("Invoiced total", money(due), delta(due, due_prev),
         f"incl. {money(tax)} tax · {money(freight)} freight"),
        ("Below-cost sales", money(short), (None, None), f"{loss_n:,} store lines below standard cost"),
    ):
        kpis.append({"label": label, "value": value, "delta": change[0], "dir": change[1], "cap": cap})

    with connection.cursor() as c:  # chart 2: profit and margin by month (24 months)
        c.execute(
            """
            SELECT substr(h.OrderDate, 1, 7) AS month,
                   SUM(d.LineTotal) AS rev,
                   SUM(d.OrderQty * p.StandardCost) AS cogs
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
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
    cur_dates = [r["month"] for r in cur_rows]
    prev_map = {r["month"]: margin_of(r) for r in months24 if r["month"] < w.trend_start}
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

    with connection.cursor() as c:  # chart 3: revenue by category
        c.execute(
            """
            SELECT cat.Name, SUM(d.LineTotal) AS rev,
                   SUM(d.OrderQty * p.StandardCost) AS cogs
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
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

    with connection.cursor() as c:  # chart 4: profit by territory
        c.execute(
            """
            SELECT t.Name, SUM(d.LineTotal) AS rev,
                   SUM(d.OrderQty * p.StandardCost) AS cogs
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            LEFT JOIN Sales_SalesTerritory t ON t.TerritoryID = h.TerritoryID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY t.Name
            """,
            [cur_lo, cur_hi],
        )
        terr = [{"name": name, "rev": rev, "cogs": cogs} for name, rev, cogs in c.fetchall()]
    terr.sort(key=lambda r: -(float(r["rev"]) - float(r["cogs"])))
    top_profit = float(terr[0]["rev"]) - float(terr[0]["cogs"]) if terr else 0
    territories = []
    for r in terr:
        p = float(r["rev"]) - float(r["cogs"])
        territories.append({
            "name": r["name"] or "—",
            "value": ("-" if p < 0 else "") + money(abs(p)),
            "pct": max(round(p / top_profit * 100), 2) if top_profit else 0,
            "note": f"{round(p / float(r['rev']) * 100, 1)}% margin" if r["rev"] else "",
        })

    with connection.cursor() as c:  # chart 5: below-cost products
        c.execute(
            """
            SELECT p.Name, SUM(d.OrderQty * p.StandardCost) - SUM(d.LineTotal) AS gap,
                   COUNT(*) AS n
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
              AND d.LineTotal < d.OrderQty * p.StandardCost
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

    with connection.cursor() as c:  # chart 6: discount cost by offer
        c.execute(
            """
            SELECT o.Description,
                   SUM(d.OrderQty * d.UnitPrice * d.UnitPriceDiscount) AS d,
                   COUNT(*) AS n
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Sales_SpecialOffer o ON o.SpecialOfferID = d.SpecialOfferID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
              AND d.UnitPriceDiscount > 0
            GROUP BY o.Description
            ORDER BY d DESC
            LIMIT 6
            """,
            [cur_lo, cur_hi],
        )
        offer_rows = [{"name": name, "d": amount, "n": n} for name, amount, n in c.fetchall()]
    discounts = rank(offer_rows, "name", "d", money)
    for r, s in zip(discounts, offer_rows):
        r["note"] = f"{s['n']:,} lines"

    with connection.cursor() as c:  # chart 7: tax collected by state
        c.execute(
            """
            SELECT sp.Name, r.TaxRate
            FROM Sales_SalesTaxRate r
            JOIN Person_StateProvince sp ON sp.StateProvinceID = r.StateProvinceID
            ORDER BY r.SalesTaxRateID
            """
        )
        rates = {}
        for name, tax_rate in c.fetchall():
            rates.setdefault(name, tax_rate)

        c.execute(
            """
            SELECT sp.Name, SUM(h.TaxAmt) AS tax
            FROM Sales_SalesOrderHeader h
            JOIN Person_Address a ON a.AddressID = h.ShipToAddressID
            JOIN Person_StateProvince sp ON sp.StateProvinceID = a.StateProvinceID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY sp.Name
            ORDER BY tax DESC
            LIMIT 6
            """,
            [cur_lo, cur_hi],
        )
        tax_rows = [{"name": name, "tax": tax} for name, tax in c.fetchall()]
    taxes = rank(tax_rows, "name", "tax", money)
    for r, s in zip(taxes, tax_rows):
        rate = rates.get(s["name"])
        r["note"] = f"{float(rate):g}% rate" if rate is not None else "no tax rate on file"

    with connection.cursor() as c:  # chart 8: product profitability table
        c.execute(
            """
            SELECT p.ProductID, p.Name, SUM(d.LineTotal) AS rev,
                   SUM(d.OrderQty * p.StandardCost) AS cogs
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY p.ProductID, p.Name
            ORDER BY rev DESC
            LIMIT 12
            """,
            [cur_lo, cur_hi],
        )
        prods = [{"product_id": product_id, "name": name, "rev": rev, "cogs": cogs}
                 for product_id, name, rev, cogs in c.fetchall()]
    prods.sort(key=lambda r: -(float(r["rev"]) - float(r["cogs"])))
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
        "custom": w.custom,
        "period": "the selected range" if w.custom else "the last 12 months",
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
