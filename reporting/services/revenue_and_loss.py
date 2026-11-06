"""Revenue and loss report queries and context building."""
from datetime import datetime, time

from django.db import connection

from core.models import SalesOrderHeader
from ..utils import (
    count,
    delta_pct,
    money,
    percent,
    rank,
    shift_months,
    window_for,
)
from .charts import build_combo, build_donut
from .common import (
    _empty_report,
    dimension_sql,
    _report_response,
    report_dimension_filters,
    _saved_report,
)
from .dialect import limit_clause, month_expr


def profit_margin_rows_for_dates(start, end, compare_start, filters=None):
    if not isinstance(start, datetime):
        start = datetime.combine(start, time.min)
    if not isinstance(end, datetime):
        end = datetime.combine(end, time.max)
    if compare_start is None:
        compare_start = shift_months(start, -12)
    elif not isinstance(compare_start, datetime):
        compare_start = datetime.combine(compare_start, time.min)

    line_filter, filter_params = dimension_sql(filters or {})
    with connection.cursor() as c:
        c.execute(
            f"""
            SELECT month, side, SUM(rev) AS rev, SUM(cogs) AS cogs
            FROM (
                SELECT {month_expr("h.OrderDate")} AS month,
                       CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
                       d.LineTotal AS rev,
                       d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) AS cogs
                FROM Sales_SalesOrderDetail d
                JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
                JOIN Production_Product p ON p.ProductID = d.ProductID
                LEFT JOIN Production_ProductCostHistory ch
                  ON ch.ProductID = d.ProductID
                 AND h.OrderDate >= ch.StartDate
                 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
            ) base
            GROUP BY month, side
            ORDER BY month
            """,
            [start, compare_start, end] + filter_params,
        )
        months24 = [{"month": month, "side": side, "rev": rev, "cogs": cogs}
                    for month, side, rev, cogs in c.fetchall()]

    def margin_of(row):
        return (round((float(row["rev"]) - float(row["cogs"])) / float(row["rev"]) * 100, 1)
                if row["rev"] else None)

    cur_by_month = {row["month"]: row for row in months24 if row["side"] == "cur"}
    prev_by_month = {row["month"]: row for row in months24 if row["side"] == "prev"}
    month_offset = ((start.year * 12 + start.month)
                    - (compare_start.year * 12 + compare_start.month))
    cur_rows = []
    month = start.replace(day=1)
    last_month = end.replace(day=1)
    while month <= last_month:
        cur_rows.append(cur_by_month.get(
            month, {"month": month, "side": "cur", "rev": 0, "cogs": 0}))
        if month == last_month:
            break
        month = shift_months(month, 1)

    profit_rows = []
    margin_rows = []
    for row in cur_rows:
        previous = prev_by_month.get(shift_months(row["month"], -month_offset))
        label = row["month"].strftime("%b")
        full = row["month"].strftime("%b %Y")
        profit_rows.append({
            "label": label,
            "full": full,
            "profit": float(row["rev"]) - float(row["cogs"]),
        })
        margin_rows.append({
            "label": label,
            "full": full,
            "margin": margin_of(row),
            "prev_full": previous["month"].strftime("%b %Y") if previous else "",
            "prev_margin": margin_of(previous) if previous else None,
        })
    return profit_rows, margin_rows


def revenue_and_loss(request):
    """Revenue and loss report: revenue, cost, gross profit and where the money leaks
    (below-cost wholesale lines); the page also states how each figure is calculated."""
    saved = _saved_report(request, "revenue-and-loss", "reporting/revenue-and-loss/report.html")
    if saved:
        return saved
    filters = report_dimension_filters(request, include_country=True)
    line_filter, filter_params = dimension_sql(filters)
    order_filter, order_filter_params = dimension_sql(
        filters, product_ref=None, order_ref="h.SalesOrderID")
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return _empty_report(request, "revenue-and-loss",
                             "reporting/revenue-and-loss/report.html", "Revenue and loss report")

    cur_lo, cur_hi = w.trend_start, w.last
    prev_lo, prev_hi = w.window_start, w.trend_start

    with connection.cursor() as c:  # chart 1: the five KPI cards
        c.execute(
            f"""
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
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
            )
            SELECT
              COALESCE(SUM(CASE WHEN side = 'cur' THEN rev END), 0) AS rev,
              COALESCE(SUM(CASE WHEN side = 'prev' THEN rev END), 0) AS rev_prev,
              COALESCE(SUM(CASE WHEN side = 'cur' THEN cost END), 0) AS cogs,
              COALESCE(SUM(CASE WHEN side = 'prev' THEN cost END), 0) AS cogs_prev
            FROM lines
            """,
            [w.trend_start, w.window_start, w.last] + filter_params,
        )
        rev, rev_prev, cogs, cogs_prev = c.fetchone()

        if not rev and not cogs:
            return _empty_report(request, "revenue-and-loss",
                                 "reporting/revenue-and-loss/report.html",
                                 "Revenue and loss report")

        c.execute(  # invoiced totals from the order headers
            f"""
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
            WHERE h.OrderDate >= %s{order_filter}
            """,
            [cur_lo, cur_hi, cur_lo, cur_hi, cur_lo, cur_hi, prev_lo, prev_hi,
             w.window_start] + order_filter_params,
        )
        tax, freight, due, due_prev = c.fetchone()

        c.execute(  # lines sold below their standard cost
            f"""
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
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
              AND d.LineTotal
                  < d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)
            """,
            [cur_lo, cur_hi] + filter_params,
        )
        loss_n, loss_rev, loss_cost = c.fetchone()

    rev, cogs = rev or 0, cogs or 0
    profit = rev - cogs
    profit_prev = (rev_prev or 0) - (cogs_prev or 0)
    margin = round(float(profit) / float(rev) * 100, 1) if rev else 0
    prev_margin = round(float(profit_prev) / float(rev_prev) * 100, 1) if rev_prev else 0
    if not rev:
        margin_cap = f"no revenue in {w.label} \u00b7 margin not meaningful"
    elif not rev_prev:
        margin_cap = f"{percent(margin)} margin \u00b7 no revenue in {w.prev_label}"
    else:
        margin_cap = f"{percent(margin)} margin \u00b7 was {percent(prev_margin)}"
    short = (loss_cost or 0) - (loss_rev or 0)
    cogs_change = delta_pct(cogs, cogs_prev)
    cogs_direction = {"up": "down", "down": "up"}.get(cogs_change[1], cogs_change[1])

    kpis = []
    for label, value, kind, change, cap in (
        ("Total revenue", float(rev or 0), "money", delta_pct(rev, rev_prev),
         "merchandise, excl. tax & freight"),
        ("Cost of goods", float(cogs or 0), "money", (cogs_change[0], cogs_direction),
         "at standard cost on the sale date"),
        ("Gross profit", float(profit or 0), "money", delta_pct(profit, profit_prev),
         margin_cap),
        ("Invoiced total", float(due or 0), "money", delta_pct(due, due_prev),
         f"incl. {money(tax)} tax \u00b7 {money(freight)} freight"),
        ("Below-cost shortfall", float(short or 0), "money", (None, None),
         f"{count(loss_n)} sales lines below standard cost"),
    ):
        kpis.append({"label": label, "value": value, "value_kind": kind,
                     "delta": change[0], "dir": change[1], "cap": cap})

    with connection.cursor() as c:  # chart 2: revenue trend, current vs previous window
        c.execute(
            f"""
            SELECT month, side, SUM(rev) AS rev
            FROM (
                SELECT {month_expr("h.OrderDate")} AS month,
                       CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
                       d.LineTotal AS rev
                FROM Sales_SalesOrderDetail d
                JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
            ) base
            GROUP BY month, side
            ORDER BY month
            """,
            [w.trend_start, w.window_start, w.last] + filter_params,
        )
        rev_series = [{"month": m, "side": side, "rev": rev}
                      for m, side, rev in c.fetchall()]
    cur_by_month = {m["month"]: m for m in rev_series if m["side"] == "cur"}
    prev_rev_months = [m for m in rev_series if m["side"] == "prev"]
    rev_months = []
    month = w.trend_start.replace(day=1)
    last_month = w.last.replace(day=1)
    while month <= last_month:
        rev_months.append(cur_by_month.get(
            month, {"month": month, "side": "cur", "rev": 0}))
        if month == last_month:
            break
        month = shift_months(month, 1)
    month_offset = ((w.trend_start.year * 12 + w.trend_start.month)
                    - (w.window_start.year * 12 + w.window_start.month))
    prev_by_month = {m["month"]: m for m in prev_rev_months}
    rev_top = max((float(m["rev"] or 0) for m in rev_series), default=0)
    rev_trend = []
    for m in rev_months:
        prev = prev_by_month.get(shift_months(m["month"], -month_offset))
        rev_trend.append({
            "label": m["month"].strftime("%b"),
            "full": m["month"].strftime("%b %Y"),
            "money": float(m["rev"] or 0),
            "height": max(round(float(m["rev"] or 0) / rev_top * 100), 2)
                      if m["rev"] and rev_top else 0,
            "prev_full": prev["month"].strftime("%b %Y") if prev else "",
            "prev_money": float(prev["rev"] or 0) if prev else None,
            "prev_h": (max(round(float(prev["rev"] or 0) / rev_top * 100), 2)
                       if prev and prev["rev"] and rev_top else 0),
        })

    profit_rows, margin_rows = profit_margin_rows_for_dates(
        w.trend_start, w.last, w.window_start, filters)
    combo = build_combo(profit_rows, margin_rows)

    with connection.cursor() as c:  # chart 4: revenue by category
        c.execute(
            f"""
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
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
            GROUP BY cat.Name
            ORDER BY rev DESC
            """,
            [cur_lo, cur_hi] + filter_params,
        )
        cats = [{"name": name, "rev": rev, "cogs": cogs} for name, rev, cogs in c.fetchall()]
    total_rev = float(rev) or 1
    mix = [
        {
            "name": r["name"],
            "cls": f"c{i}",
            "pct": round(float(r["rev"]) / total_rev * 100, 1),
            "money": float(r["rev"] or 0),
            "margin": round((float(r["rev"]) - float(r["cogs"])) / float(r["rev"]) * 100, 1) if r["rev"] else 0,
        }
        for i, r in enumerate(cats, 1)
    ]

    donut = build_donut("revenue-and-loss", mix)

    with connection.cursor() as c:  # chart 5: products with declining revenue vs previous window
        c.execute(
            f"""
            SELECT Name, cur_rev, prev_rev
            FROM (
                SELECT p.Name, p.ProductID,
                       SUM(CASE WHEN h.OrderDate >= %s
                                THEN d.LineTotal ELSE 0 END) AS cur_rev,
                       SUM(CASE WHEN h.OrderDate < %s
                                THEN d.LineTotal ELSE 0 END) AS prev_rev
                FROM Sales_SalesOrderDetail d
                JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
                JOIN Production_Product p ON p.ProductID = d.ProductID
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
                GROUP BY p.ProductID, p.Name
            ) product_rev
            WHERE prev_rev > 0 AND cur_rev < prev_rev
            ORDER BY (prev_rev - cur_rev) DESC
            {limit_clause(8)}
            """,
            [cur_lo, cur_lo, w.window_start, w.last] + filter_params,
        )
        decline_rows = [{"name": name, "cur": cur_rev, "prev": prev_rev,
                         "drop": float(prev_rev) - float(cur_rev)}
                        for name, cur_rev, prev_rev in c.fetchall()]
    declining = rank(decline_rows, "name", "drop")
    for r, s_row in zip(declining, decline_rows):
        pct = round(s_row["drop"] / float(s_row["prev"]) * 100, 1)
        r["note"] = f"{money(s_row['cur'])} vs {money(s_row['prev'])} \u00b7 -{percent(pct)}"

    with connection.cursor() as c:  # chart 6: below-cost products
        c.execute(
            f"""
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
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
              AND d.LineTotal
                  < d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)
            GROUP BY p.Name
            ORDER BY gap DESC
            {limit_clause(6)}
            """,
            [cur_lo, cur_hi] + filter_params,
        )
        leak_rows = [{"name": name, "gap": gap, "n": n} for name, gap, n in c.fetchall()]
    leaks = rank(leak_rows, "name", "gap")
    for r, s in zip(leaks, leak_rows):
        r["note"] = f"{count(s['n'])} lines"

    with connection.cursor() as c:  # chart 7: product profitability table
        c.execute(
            f"""
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
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
            GROUP BY p.ProductID, p.Name
            ORDER BY rev DESC
            {limit_clause(12)}
            """,
            [cur_lo, cur_hi] + filter_params,
        )
        prods = [{"product_id": product_id, "name": name, "rev": rev, "cogs": cogs}
                 for product_id, name, rev, cogs in c.fetchall()]
    products = [
        {
            "id": r["product_id"], "name": r["name"],
            "rev": float(r["rev"] or 0), "cost": float(r["cogs"] or 0),
            "profit": float(r["rev"] or 0) - float(r["cogs"] or 0),
            "margin": round((float(r["rev"]) - float(r["cogs"])) / float(r["rev"]) * 100, 1)
                      if r["rev"] else 0,
        }
        for r in prods[:8]
    ]

    return _report_response(request, "revenue-and-loss",
                            "reporting/revenue-and-loss/report.html", {
        "tab": "revenue-and-loss",
        "title": "Revenue and loss report",
        "kpis": kpis,
        "combo": combo,
        "profit_rows": profit_rows,
        "margin_rows": margin_rows,
        "donut": donut,
        "donut_mid": {"big": float(rev or 0), "small": "revenue"},
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
