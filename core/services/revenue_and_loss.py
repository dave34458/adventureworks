"""Revenue and loss report queries and context building."""
from datetime import datetime

from django.db import connection

from ..models import SalesOrderHeader
from ..utils import (
    count,
    delta_pct,
    money,
    percent,
    rank,
    ring,
    shift_months,
    window_for,
)
from .common import (
    _empty_report,
    _report_response,
    _saved_report,
)


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

        if not rev and not cogs:
            return _empty_report(request, "revenue-and-loss",
                                 "core/revenue-and-loss/report.html",
                                 "Revenue and loss report")

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

    with connection.cursor() as c:  # chart 3: profit and margin by month (24 months)
        c.execute(
            """
            SELECT substr(h.OrderDate, 1, 7) AS month,
                   CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
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
            GROUP BY month, side
            ORDER BY month
            """,
            [w.trend_start, w.window_start, w.last],
        )
        months24 = [{"month": datetime.strptime(m, "%Y-%m"), "side": side, "rev": rev, "cogs": cogs}
                    for m, side, rev, cogs in c.fetchall()]

    def margin_of(row):
        return (round((float(row["rev"]) - float(row["cogs"])) / float(row["rev"]) * 100, 1)
                if row["rev"] else None)

    cur_by_month = {r["month"]: r for r in months24 if r["side"] == "cur"}
    prev_rows = [r for r in months24 if r["side"] == "prev"]
    cur_rows = []
    month = w.trend_start.replace(day=1)
    last_month = w.last.replace(day=1)
    while month <= last_month:
        cur_rows.append(cur_by_month.get(
            month, {"month": month, "side": "cur", "rev": 0, "cogs": 0}))
        if month == last_month:
            break
        month = shift_months(month, 1)
    cur_dates = [r["month"] for r in cur_rows]
    cur_vals = [margin_of(r) for r in cur_rows]
    month_offset = ((w.trend_start.year * 12 + w.trend_start.month)
                    - (w.window_start.year * 12 + w.window_start.month))
    prev_by_month = {r["month"]: r for r in prev_rows}
    prev_dates = []
    prev_vals = []
    for m in cur_dates:
        prev = prev_by_month.get(shift_months(m, -month_offset))
        prev_dates.append(prev["month"] if prev else None)
        prev_vals.append(margin_of(prev) if prev else None)

    profits = [float(r["rev"]) - float(r["cogs"]) for r in cur_rows]
    vmax = max(profits + [0.0])
    vmin = min(profits + [0.0])
    span = max(vmax - vmin, 1)
    m_values = [v for v in cur_vals + prev_vals if v is not None] + [0]
    m_high = max(m_values)
    m_low = min(m_values)
    m_max = 60 if m_high <= 60 else (int(m_high / 10) + 1) * 10
    m_min = 0 if m_low >= 0 else (int(m_low / 10) - 1) * 10
    m_span = m_max - m_min
    px_w, px_h, pad_l, pad_r, pad_t, pad_b = 960, 260, 72, 40, 10, 24
    plot_w, plot_h = px_w - pad_l - pad_r, px_h - pad_t - pad_b
    barw = round(min(44, plot_w / max(len(cur_dates) - 1, 1) * 0.65), 1)  # bars shrink when a range has many months

    def x_at(i):
        return round(pad_l + i * plot_w / max(len(cur_dates) - 1, 1), 1)

    zero_y = round(pad_t + (vmax / span) * plot_h, 1)

    def y_money(v):
        return round(zero_y - v / span * plot_h, 1)

    def y_pct(v):
        return round(pad_t + (m_max - v) / m_span * plot_h, 1)

    def axis_money(v):
        return money(v)

    bars = []
    for i, (m, p) in enumerate(zip(cur_dates, profits)):
        h = round(abs(p) / span * plot_h, 1)
        y = y_money(p) if p >= 0 else zero_y
        bars.append({"x": round(x_at(i) - barw / 2, 1), "y": y, "h": h, "w": barw,
                     "t": f"{m:%b %Y} \u00b7 {money(p)} gross profit"})
    dots = []
    for i, (m, v) in enumerate(zip(cur_dates, cur_vals)):
        if v is not None:
            dots.append({"cls": "dotc", "x": x_at(i), "y": y_pct(v), "t": f"{m:%b %Y} \u00b7 {v}% margin"})
    for i, (m, v) in enumerate(zip(prev_dates, prev_vals)):
        if v is not None:
            dots.append({"cls": "dotp", "x": x_at(i), "y": y_pct(v), "t": f"{m:%b %Y} \u00b7 {v}% margin"})
    tick_values = ((vmin, 0, vmax) if vmin < 0 < vmax
                   else (vmin, vmin / 2, 0) if vmin < 0
                   else (0, vmax / 2, vmax))
    margin_ticks = ((m_min, 0, m_max) if m_min < 0
                    else (0, 20, 40, 60) if m_max == 60
                    else (0, m_max / 2, m_max))
    combo = {
        "bars": bars,
        "cur_pts": " ".join(f"{x_at(i)},{y_pct(v)}" for i, v in enumerate(cur_vals)
                            if v is not None),
        "prev_pts": " ".join(f"{x_at(i)},{y_pct(v)}" for i, v in enumerate(prev_vals) if v is not None),
        "dots": dots,
        "xticks": [{"x": x_at(i), "lab": m.strftime("%b")} for i, m in enumerate(cur_dates)],
        "lticks": [{"y": y_money(v), "lab": axis_money(v)} for v in tick_values],
        "rticks": [{"y": y_pct(v), "lab": f"{v:g}%"} for v in margin_ticks],
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
            "money": float(r["rev"] or 0),
            "margin": round((float(r["rev"]) - float(r["cogs"])) / float(r["rev"]) * 100, 1) if r["rev"] else 0,
        }
        for i, r in enumerate(cats, 1)
    ]

    donut = ring([{"cls": m["cls"], "pct": m["pct"],
                   "t": f"{m['name']} \u00b7 {money(m['money'])} \u00b7 "
                        f"{percent(m['pct'])} of revenue \u00b7 {percent(m['margin'])} margin"}
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
    declining = rank(decline_rows, "name", "drop")
    for r, s_row in zip(declining, decline_rows):
        pct = round(s_row["drop"] / float(s_row["prev"]) * 100, 1)
        r["note"] = f"{money(s_row['cur'])} vs {money(s_row['prev'])} \u00b7 -{percent(pct)}"

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
    leaks = rank(leak_rows, "name", "gap")
    for r, s in zip(leaks, leak_rows):
        r["note"] = f"{count(s['n'])} lines"

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
            "rev": float(r["rev"] or 0), "cost": float(r["cogs"] or 0),
            "profit": float(r["rev"] or 0) - float(r["cogs"] or 0),
            "margin": round((float(r["rev"]) - float(r["cogs"])) / float(r["rev"]) * 100, 1)
                      if r["rev"] else 0,
        }
        for r in prods[:8]
    ]

    return _report_response(request, "revenue-and-loss",
                            "core/revenue-and-loss/report.html", {
        "tab": "revenue-and-loss",
        "title": "Revenue and loss report",
        "kpis": kpis,
        "combo": combo,
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
