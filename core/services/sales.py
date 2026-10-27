"""Sales report queries and context building."""
from django.db import connection

from ..models import SalesOrderHeader
from ..utils import delta_pct, money, rank, shift_months, window_for
from .common import (
    _empty_report,
    _report_response,
    _saved_report,
)
from .dialect import limit_clause, month_expr


def sales(request):
    """Sales report: one aggregate query per panel, all windows anchored to the
    data's own last order date (the sample data is historical, so "today" would be empty)."""
    saved = _saved_report(request, "sales", "core/sales/report.html")
    if saved:
        return saved
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return _empty_report(request, "sales", "core/sales/report.html", "Sales report")

    cur_lo, cur_hi = w.trend_start, w.last
    prev_lo, prev_hi = w.window_start, w.trend_start

    with connection.cursor() as c:  # panel 1: total sales and summary KPIs
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

    if not orders:
        return _empty_report(request, "sales", "core/sales/report.html", "Sales report")

    aov = (rev / orders) if orders else None
    aov_prev = (rev_prev / orders_prev) if orders_prev else None

    kpis = []
    for label, value, kind, change, cap in (
        ("Total sales", float(rev or 0), "money", delta_pct(rev, rev_prev),
         "merchandise, excl. tax & freight"),
        ("Orders", int(orders or 0), "count", delta_pct(orders, orders_prev),
         "sales orders placed"),
        ("Avg order value", float(aov or 0), "money", delta_pct(aov, aov_prev),
         "sales per order"),
        ("Customers", int(customers or 0), "count", delta_pct(customers, customers_prev),
         "distinct buyers"),
    ):
        kpis.append({"label": label, "value": value, "value_kind": kind,
                     "delta": change[0], "dir": change[1], "cap": cap})

    with connection.cursor() as c:  # panel 2: sales trend, current vs previous window
        c.execute(
            f"""
            SELECT month, side, SUM(rev) AS rev, COUNT(DISTINCT order_id) AS orders
            FROM (
                SELECT {month_expr("h.OrderDate")} AS month,
                       CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
                       d.LineTotal AS rev,
                       h.SalesOrderID AS order_id
                FROM Sales_SalesOrderDetail d
                JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            ) base
            GROUP BY month, side
            ORDER BY month
            """,
            [w.trend_start, w.window_start, w.last],
        )
        series = [
            {"month": m, "side": side, "rev": rev, "orders": orders}
            for m, side, rev, orders in c.fetchall()
        ]
    cur_by_month = {m["month"]: m for m in series if m["side"] == "cur"}
    prev_months = [m for m in series if m["side"] == "prev"]
    months = []
    month = w.trend_start.replace(day=1)
    last_month = w.last.replace(day=1)
    while month <= last_month:
        months.append(cur_by_month.get(
            month, {"month": month, "side": "cur", "rev": 0, "orders": 0}))
        if month == last_month:
            break
        month = shift_months(month, 1)
    month_offset = ((w.trend_start.year * 12 + w.trend_start.month)
                    - (w.window_start.year * 12 + w.window_start.month))
    prev_by_month = {m["month"]: m for m in prev_months}
    top = max((float(m["rev"] or 0) for m in months + prev_months), default=0)
    trend = []
    for m in months:
        prev = prev_by_month.get(shift_months(m["month"], -month_offset))
        trend.append({
            "label": m["month"].strftime("%b"),
            "full": m["month"].strftime("%b %Y"),
            "money": float(m["rev"] or 0),
            "orders": int(m["orders"] or 0),
            "height": max(round(float(m["rev"] or 0) / top * 100), 2)
                      if m["rev"] and top else 0,
            "prev_full": prev["month"].strftime("%b %Y") if prev else "",
            "prev_money": float(prev["rev"] or 0) if prev else None,
            "prev_orders": int(prev["orders"] or 0) if prev else None,
            "prev_h": (max(round(float(prev["rev"] or 0) / top * 100), 2)
                       if prev and prev["rev"] and top else 0),
        })

    with connection.cursor() as c:  # panel 3: sales by product, high performers
        c.execute(
            f"""
            SELECT pr.Name, SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product pr ON pr.ProductID = d.ProductID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY pr.Name
            ORDER BY rev DESC
            {limit_clause(8)}
            """,
            [cur_lo, cur_hi],
        )
        products = rank([{"name": name, "rev": rev} for name, rev in c.fetchall()],
                        "name", "rev")

    with connection.cursor() as c:  # panel 4: sales by product, low performers
        c.execute(
            f"""
            SELECT pr.Name, SUM(d.LineTotal) AS rev
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product pr ON pr.ProductID = d.ProductID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s
            GROUP BY pr.Name
            ORDER BY rev ASC
            {limit_clause(6)}
            """,
            [cur_lo, cur_hi],
        )
        low_products = rank([{"name": name, "rev": rev} for name, rev in c.fetchall()],
                            "name", "rev")

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
