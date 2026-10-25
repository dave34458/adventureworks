"""Customer profile report queries and context building."""
import re
from datetime import datetime

from django.db import connection

from ..models import SalesOrderHeader
from ..utils import delta_pct, money, rank, shift_months, window_for
from .common import (
    _empty_report,
    _report_response,
    _saved_report,
)


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

        if not actives:
            return _empty_report(request, "customer-profile",
                                 "core/customer-profile/report.html",
                                 "Customer profile report")

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
    cur_by_month = {m["month"]: m for m in months}
    months = []
    month = w.trend_start.replace(day=1)
    last_month = w.last.replace(day=1)
    while month <= last_month:
        months.append(cur_by_month.get(month, {"month": month, "act": 0}))
        if month == last_month:
            break
        month = shift_months(month, 1)
    top = max((m["act"] for m in months), default=0)
    growth = [
        {
            "label": m["month"].strftime("%b"), "full": m["month"].strftime("%b %Y"),
            "act": int(m["act"] or 0), "nw": int(new_per_month.get(m["month"], 0)),
            "ret": int((m["act"] or 0) - new_per_month.get(m["month"], 0)),
            "new_h": round(new_per_month.get(m["month"], 0) / top * 100, 2) if top else 0,
            "ret_h": round(((m["act"] or 0) - new_per_month.get(m["month"], 0)) / top * 100, 2)
                     if top else 0,
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
         "money": float(ind_rev or 0), "customers": int(ind_n or 0),
         "aov": float(ind_rev / ind_orders) if ind_orders else None},
        {"name": "Stores", "pct": st_share, "cust_pct": 100 - ind_buyers, "cls": "store",
         "money": float(st_rev or 0), "customers": int(st_n or 0),
         "aov": float(st_rev / st_orders) if st_orders else None},
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
    countries = rank(country_rows, "name", "rev")
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
            SELECT a.City, sp.StateProvinceCode, sp.CountryRegionCode,
                   SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Person_Address a ON a.AddressID = h.ShipToAddressID
            JOIN Person_StateProvince sp ON sp.StateProvinceID = a.StateProvinceID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY a.City, sp.StateProvinceCode, sp.CountryRegionCode
            ORDER BY rev DESC
            LIMIT 8
            """,
            [cur_lo, cur_hi],
        )
        cities = rank([
            {"name": f"{city}, {state_code or country_code}", "rev": rev}
            for city, state_code, country_code, rev in c.fetchall()
        ], "name", "rev")

    total_stores, type_stats, store_rev = {}, {}, {}
    with connection.cursor() as c:  # chart 6: stores with sales in the window
        c.execute("SELECT Demographics FROM Sales_Store WHERE Demographics IS NOT NULL")
        for (demo,) in c.fetchall():
            m = re.search(r"<BusinessType>([^<]*)</BusinessType>", demo)
            if m:
                total_stores[m.group(1)] = total_stores.get(m.group(1), 0) + 1

        c.execute(
            """
            SELECT s.BusinessEntityID, s.Demographics, SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Sales_Customer cu ON cu.CustomerID = h.CustomerID
            JOIN Sales_Store s ON s.BusinessEntityID = cu.StoreID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY s.BusinessEntityID, s.Demographics
            """,
            [cur_lo, cur_hi],
        )
        for _store_id, demo, store_total in c.fetchall():
            m = re.search(r"<BusinessType>([^<]*)</BusinessType>", demo or "")
            if not m:
                continue
            b = type_stats.setdefault(m.group(1), {"n": 0, "sqft": 0.0})
            b["n"] += 1
            sqft = re.search(r"<SquareFeet>(\d+)</SquareFeet>", demo or "")
            if sqft:
                b["sqft"] += int(sqft.group(1))
            store_rev[m.group(1)] = store_rev.get(m.group(1), 0) + float(store_total or 0)
    names = {"BS": "Bike shops", "BM": "Bike manufacturers", "OS": "Other specialty stores"}
    network_rows = []
    for store_type, total in total_stores.items():
        active = type_stats.get(store_type, {"n": 0, "sqft": 0.0})
        network_rows.append({
            "name": names.get(store_type, store_type),
            "rev": store_rev.get(store_type, 0),
            "n": active["n"],
            "total": total,
            "sqft": round(active["sqft"] / active["n"]) if active["n"] else 0,
        })
    network_rows.sort(key=lambda r: -r["rev"])
    network = rank(network_rows, "name", "rev")
    for r, s in zip(network, network_rows):
        if s["n"]:
            r["note"] = (f"{s['n']} of {s['total']} stores had sales in the period "
                         f"\u00b7 avg {s['sqft']:,} sq ft")
        else:
            r["note"] = f"0 of {s['total']} stores had sales in the period"

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
    frequency = rank([{"name": k, "n": v} for k, v in buckets.items()], "name", "n")

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
                "territory": territory or "\u2014", "orders": int(orders or 0),
                "rev": float(buyer_total or 0),
            })

    avg_spend = (rev / actives) if actives else None
    prev_spend = (rev_prev / actives_prev) if actives_prev else None
    ind_avg = (ind_rev / ind_n) if ind_n else None
    st_avg = (st_rev / st_n) if st_n else None
    retention = round(kept / actives_prev * 100) if actives_prev else 0

    kpis = []
    for label, value, kind, change, cap in (
        ("Active customers", int(actives or 0), "count", delta_pct(actives, actives_prev),
         "distinct buyers in the window"),
        ("New customers", int(new_count or 0), "count", delta_pct(new_count, prev_new),
         f"{money(new_rev)} \u00b7 {round(new_count / actives * 100) if actives else 0}% of buyers"),
        ("Repeat revenue share",
         round(float(repeat_rev) / float(rev) * 100) if rev else 0, "percent", (None, None),
         f"{money(repeat_rev)} from {repeat:,} returning buyers"),
        ("Avg spend per customer", float(avg_spend) if avg_spend is not None else None,
         "money", delta_pct(avg_spend, prev_spend),
         f"individual {money(ind_avg)} \u00b7 store {money(st_avg)}"),
        ("Retention", int(retention or 0), "percent", (None, None),
         f"{kept:,} of {actives_prev:,} buyers in {w.prev_label} returned"),
    ):
        kpis.append({"label": label, "value": value, "value_kind": kind,
                     "delta": change[0], "dir": change[1], "cap": cap})

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
        "new_legend": {"n": int(new_count or 0), "rev": float(new_rev or 0)},
        "ret_legend": {"n": int(repeat or 0), "rev": float(repeat_rev or 0)},
        "through": w.last,
        "window_label": w.label,
        "prev_label": w.prev_label,
        "custom": w.custom,
        "period": "the selected range" if w.custom else "the last 12 months",
        "w_from": w.trend_start.strftime("%Y-%m-%d"),
        "w_to": w.last.strftime("%Y-%m-%d"),
    }, w)
