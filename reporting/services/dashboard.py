"""Dashboard aggregation and context building."""

from django.db import connection

from core.models import SalesOrderHeader

from ..constants import REPORT_COUNTRIES
from ..utils import (
    delta,
    money,
    money_axis_ticks,
    money_exact,
    ring,
    shift_months,
    window_for,
)
from .charts import compact_money
from .common import (
    PANEL_OPTIONS,
    SHOW_OPTIONS,
    ReportResult,
    dimension_sql,
    show_amount,
    visible_panels,
)
from .dialect import limit_clause, month_expr


def dashboard(request):
    """Central dashboard: one integrated view of the four reports.

    The figures use the same sales-line base and report window as the Revenue and
    Cost reports; the category and ship-to country filters narrow every figure on
    the page so the comparisons stay like-for-like.
    """
    # panel 1: category and country filters
    with connection.cursor() as c:
        c.execute("SELECT ProductCategoryID, Name FROM [Production].[ProductCategory] ORDER BY Name")
        categories = [{"id": row[0], "name": row[1]} for row in c.fetchall()]

    params = request.GET
    valid_category_ids = {c["id"] for c in categories}
    category_ids = set()
    for value in params.getlist("category"):
        try:
            category_id = int(value)
        except (TypeError, ValueError):
            continue
        if category_id in valid_category_ids:
            category_ids.add(category_id)
    category_requested = "category_filter" in params or bool(params.getlist("category"))
    if not category_requested:
        category_ids = valid_category_ids.copy()
    category_ids = sorted(category_ids)

    countries = [{"code": code, "name": name} for code, name in REPORT_COUNTRIES]
    valid_country_codes = {c["code"] for c in countries}
    country_codes = {
        value.strip().upper() for value in params.getlist("country")
        if value.strip().upper() in valid_country_codes
    }
    country_requested = "country_filter" in params or bool(params.getlist("country"))
    if not country_requested:
        country_codes = valid_country_codes.copy()
    country_codes = sorted(country_codes)

    row_limit = show_amount(params, "products", 10)
    panel_options = PANEL_OPTIONS["dashboard"]
    selected_panels = visible_panels(params, "dashboard")
    dimensions = {
        "category_ids": category_ids,
        "category_filter": category_requested,
        "country_codes": country_codes,
        "country_filter": country_requested,
    }
    dimension_clause, dimension_params = dimension_sql(
        dimensions, product_ref="d.ProductID", header_ref="h")

    show_ring = not category_requested or set(category_ids) == valid_category_ids
    selected_categories = [c for c in categories if c["id"] in set(category_ids)]
    if category_requested and not show_ring:
        if len(selected_categories) == 1:
            products_title = f"Top products in {selected_categories[0]['name']}"
            category_caption = selected_categories[0]["name"]
        else:
            products_title = "Top products in selected categories"
            category_caption = "selected categories"
    else:
        products_title = None
        category_caption = None

    metric_name = "Sales"
    metric_lower = metric_name.lower()

    context = {
        "tab": "dashboard",
        "title": "Business performance dashboard",
        "categories": categories,
        "category_ids": category_ids,
        "countries": countries,
        "country_codes": country_codes,
        "products_title": products_title,
        "category_caption": category_caption,
        "show_values": {"products": row_limit},
        "show_options": SHOW_OPTIONS,
        "panel_options": panel_options,
        "visible_panels": selected_panels,
        "has_data": False,
        "empty_message": "No data is available for this report.",
    }
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return ReportResult("reporting/dashboard.html", context)

    # panel 2: totals
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
                FROM [Sales].[SalesOrderDetail] d
                JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
                JOIN [Production].[Product] p ON p.ProductID = d.ProductID
                LEFT JOIN [Production].[ProductCostHistory] ch
                  ON ch.ProductID = d.ProductID
                 AND h.OrderDate >= ch.StartDate
                 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
                LEFT JOIN [Production].[ProductSubcategory] sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
                LEFT JOIN [Production].[ProductCategory] pc ON pc.ProductCategoryID = sc.ProductCategoryID
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s{dimension_clause}
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
            [w.trend_start, w.window_start, w.last] + dimension_params,
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
    margin = round(profit / rev * 100, 2) if rev else 0.0
    prev_margin = round(profit_prev / rev_prev * 100, 2) if rev_prev else 0.0

    if not orders and not customers:
        context.update({
            "w_from": w.trend_start.strftime("%Y-%m-%d"),
            "w_to": w.last.strftime("%Y-%m-%d"),
        })
        return ReportResult("reporting/dashboard.html", context)

    if not rev:
        margin_cap = "no revenue in this period"
    elif not rev_prev:
        margin_cap = f"{margin:.2f}% margin \u00b7 no revenue in {w.prev_label}"
    else:
        margin_cap = f"{margin:.2f}% margin \u00b7 was {prev_margin:.2f}%"

    # panel 3: KPI cards (derived from panel 2)
    kpis = []

    def add_kpi(label, value, change, cap):
        kpis.append({"label": label, "value": value, "delta": change[0],
                     "dir": change[1], "cap": cap})

    add_kpi("Total sales", money(rev), delta(rev, rev_prev),
            "merchandise, excl. tax & freight")
    add_kpi("Orders", f"{orders:,}", delta(orders, orders_prev), "orders in the period")
    add_kpi("Gross profit", money(profit), delta(profit, profit_prev), margin_cap)
    cost_change = delta(cogs, cogs_prev)
    cost_direction = {"up": "down", "down": "up"}.get(cost_change[1], cost_change[1])
    add_kpi("Cost of goods", money(cogs), (cost_change[0], cost_direction),
            "at standard cost on the sale date")
    add_kpi("Active customers", f"{customers:,}", delta(customers, customers_prev),
            "distinct buyers")
    add_kpi("Below-cost shortfall", money(short), (None, None),
            f"{below_n:,} sales lines below standard cost")

    trend = []
    margin_chart = None
    # panel 4: monthly trend
    with connection.cursor() as c:
        c.execute(
            f"""
            SELECT month, side, SUM(rev) AS rev, SUM(cogs) AS cogs,
                   COUNT(DISTINCT order_id) AS orders
            FROM (
                SELECT {month_expr("h.OrderDate")} AS month,
                       CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
                       d.LineTotal AS rev,
                       d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) AS cogs,
                       h.SalesOrderID AS order_id
                FROM [Sales].[SalesOrderDetail] d
                JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
                JOIN [Production].[Product] p ON p.ProductID = d.ProductID
                LEFT JOIN [Production].[ProductCostHistory] ch
                  ON ch.ProductID = d.ProductID
                 AND h.OrderDate >= ch.StartDate
                 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
                LEFT JOIN [Production].[ProductSubcategory] sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
                LEFT JOIN [Production].[ProductCategory] pc ON pc.ProductCategoryID = sc.ProductCategoryID
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s{dimension_clause}
            ) base
            GROUP BY month, side
            ORDER BY month
            """,
            [w.trend_start, w.window_start, w.last] + dimension_params,
        )
        series = [
            {"month": month, "side": side,
             "rev": float(rev or 0), "cogs": float(cogs or 0), "orders": int(orders or 0)}
            for month, side, rev, cogs, orders in c.fetchall()
        ]
    cur_by_month = {row["month"]: row for row in series if row["side"] == "cur"}
    prev_series = [row for row in series if row["side"] == "prev"]
    cur_series = []
    month = w.trend_start.replace(day=1)
    last_month = w.last.replace(day=1)
    while month <= last_month:
        cur_series.append(cur_by_month.get(
            month, {"month": month, "side": "cur",
                    "rev": 0.0, "cogs": 0.0, "orders": 0}))
        if month == last_month:
            break
        month = shift_months(month, 1)
    month_offset = ((w.trend_start.year * 12 + w.trend_start.month)
                    - (w.window_start.year * 12 + w.window_start.month))
    prev_by_month = {row["month"]: row for row in prev_series}
    top = max((row["rev"] for row in cur_series + prev_series), default=0)
    context["money_axis"] = money_axis_ticks(top, compact_money)
    for row in cur_series:
        prev = prev_by_month.get(shift_months(row["month"], -month_offset))
        value = row["rev"]
        title = f"{row['month']:%b %Y} \u00b7 {money_exact(value)}"
        title += f" \u00b7 {row['orders']:,} orders"
        if row["rev"]:
            title += f" \u00b7 {(row['rev'] - row['cogs']) / row['rev'] * 100:.2f}% margin"
        if prev:
            title += f" \u00b7 previous {prev['month']:%b %Y}: {money_exact(prev['rev'])}"
        trend.append({
            "label": f"{row['month']:%b}",
            "year_label": (f"{prev['month']:%Y} vs {row['month']:%Y}" if prev
                           else f"{row['month']:%Y}"),
            "full": f"{row['month']:%b %Y}",
            "money": money(value),
            "height": max(round(value / top * 100), 2) if value and top else 0,
            "title": title,
            "prev_h": (max(round(prev["rev"] / top * 100), 2)
                       if prev and prev["rev"] and top else 0),
        })

    def margin_of(row):
        value = row["rev"]
        return (round((value - row["cogs"]) / value * 100, 2)
                if value else None)

    if cur_series:
        n = len(cur_series)
        cur_margins = [margin_of(row) for row in cur_series]
        prev_rows = [prev_by_month.get(shift_months(row["month"], -month_offset))
                     for row in cur_series]
        prev_margins = [margin_of(row) if row else None for row in prev_rows]
        m_values = [v for v in cur_margins + prev_margins if v is not None] + [0]
        high = max(m_values)
        low = min(m_values)
        m_max = 60 if high <= 60 else (int(high / 10) + 1) * 10
        m_min = 0 if low >= 0 else (int(low / 10) - 1) * 10
        m_span = m_max - m_min
        px_w, px_h, pad_l, pad_r, pad_t, pad_b = 960, 260, 96, 16, 12, 28
        plot_w, plot_h = px_w - pad_l - pad_r, px_h - pad_t - pad_b
        xs = [round(pad_l + i * plot_w / max(n - 1, 1), 1) for i in range(n)]

        def y_at(value):
            return round(pad_t + (m_max - value) / m_span * plot_h, 1)

        margin_ticks = ((m_min, 0, m_max) if m_min < 0 else (0, m_max / 2, m_max))
        ticks = [{"y": y_at(value), "label": f"{value:g}%"}
                 for value in margin_ticks]
        step = max(1, (n + 11) // 12)
        xticks = [{
            "x": xs[i], "label": f"{cur_series[i]['month']:%b}",
            "year_label": (f"{prev_rows[i]['month']:%Y} vs "
                           f"{cur_series[i]['month']:%Y}" if prev_rows[i]
                           else f"{cur_series[i]['month']:%Y}"),
        } for i in range(0, n, step)]
        cur_pts = " ".join(f"{xs[i]},{y_at(cur_margins[i])}" for i in range(n)
                           if cur_margins[i] is not None)
        prev_pts = " ".join(f"{xs[i]},{y_at(v)}"
                            for i, v in enumerate(prev_margins) if v is not None)
        dots = []
        for i, row in enumerate(cur_series):
            if cur_margins[i] is None:
                continue
            gross = row["rev"] - row["cogs"]
            dots.append({"x": xs[i], "y": y_at(cur_margins[i]),
                         "t": f"{row['month']:%b %Y} \u00b7 margin {cur_margins[i]:.2f}%"
                              f" \u00b7 gross profit {money(gross)}"})
        prev_dots = [{"x": xs[i], "y": y_at(v),
                      "t": f"{prev_rows[i]['month']:%b %Y} \u00b7 margin {v:.2f}%"}
                     for i, v in enumerate(prev_margins) if v is not None]
        margin_chart = {"ticks": ticks, "xticks": xticks, "cur_pts": cur_pts,
                        "prev_pts": prev_pts, "dots": dots, "prev_dots": prev_dots}

    trend_title = "Sales trend by month"

    category_title = "Revenue contribution by category"
    category_mid_label = "revenue"

    products = []
    products_top = []
    category_rows = []
    # panel 5: product ranking
    with connection.cursor() as c:
        c.execute(
            f"""
            SELECT p.ProductID, p.Name, pc.Name,
                   SUM(d.OrderQty) AS units,
                   SUM(d.LineTotal) AS rev,
                   SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cost
            FROM [Sales].[SalesOrderDetail] d
            JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
            JOIN [Production].[Product] p ON p.ProductID = d.ProductID
            LEFT JOIN [Production].[ProductCostHistory] ch
              ON ch.ProductID = d.ProductID
             AND h.OrderDate >= ch.StartDate
             AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
            LEFT JOIN [Production].[ProductSubcategory] sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
            LEFT JOIN [Production].[ProductCategory] pc ON pc.ProductCategoryID = sc.ProductCategoryID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s{dimension_clause}
            GROUP BY p.ProductID, p.Name, pc.Name
            ORDER BY SUM(d.LineTotal) DESC
            {limit_clause(100)}
            """,
            [w.trend_start, w.last] + dimension_params,
        )
        raw_products = c.fetchall()

    top_product = max((float(rev) for _, _, _, _, rev, cost in raw_products),
                      default=0)
    for product_id, name, category, units, revenue, cost in raw_products:
        value = float(revenue or 0)
        margin_pct = (round((float(revenue) - float(cost)) / float(revenue) * 100, 2)
                      if revenue else 0.0)
        products.append({
            "id": product_id,
            "name": name,
            "category": category or "Uncategorized",
            "units": f"{int(units or 0):,}",
            "value": money(value),
            "profit": money(float(revenue or 0) - float(cost or 0)),
            "margin": f"{margin_pct:.2f}%",
            "pct": max(round(value / top_product * 100), 2) if top_product else 0,
            "share": round(value / rev * 100, 2) if rev else 0,
        })
    products_top = products[:6]
    products = products[:row_limit]

    if show_ring:
        # panel 6: category ring
        with connection.cursor() as c:
            c.execute(
                f"""
                SELECT pc.ProductCategoryID, pc.Name,
                       SUM(d.LineTotal) AS rev,
                       SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cost
                FROM [Sales].[SalesOrderDetail] d
                JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
                JOIN [Production].[Product] p ON p.ProductID = d.ProductID
                    LEFT JOIN [Production].[ProductCostHistory] ch
                  ON ch.ProductID = d.ProductID
                 AND h.OrderDate >= ch.StartDate
                 AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
                LEFT JOIN [Production].[ProductSubcategory] sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
                LEFT JOIN [Production].[ProductCategory] pc ON pc.ProductCategoryID = sc.ProductCategoryID
                WHERE h.OrderDate >= %s AND h.OrderDate <= %s{dimension_clause}
                GROUP BY pc.ProductCategoryID, pc.Name
                ORDER BY SUM(d.LineTotal) DESC
                """,
                [w.trend_start, w.last] + dimension_params,
            )
            raw_categories = c.fetchall()

        palette = ["c1", "c2", "c3", "c4"]
        total_metric = sum(float(rev or 0)
                           for _, _, rev, cost in raw_categories)
        for i, (cat_id, name, revenue, cost) in enumerate(raw_categories):
            value = float(revenue or 0)
            pct = round(value / total_metric * 100) if total_metric else 0
            margin_pct = (round((float(revenue) - float(cost)) / float(revenue) * 100, 2)
                          if revenue else 0.0)
            note = f"{name} \u00b7 {money(value)} \u00b7 {pct}% of {metric_lower}"
            note += f" \u00b7 {margin_pct:.2f}% margin"
            category_rows.append({
                "id": cat_id,
                "name": name or "Uncategorized",
                "value": money(value),
                "pct": pct,
                "cls": palette[i % len(palette)],
                "margin": f"{margin_pct:.2f}",
                "t": note,
            })
        category_rows = ring(category_rows)

    customer_mix = None
    # panel 7: customer mix
    with connection.cursor() as c:
        c.execute(
            f"""
            SELECT CASE WHEN cu.StoreID IS NULL THEN 0 ELSE 1 END AS is_store,
                   SUM(d.LineTotal) AS rev,
                   COUNT(DISTINCT h.SalesOrderID) AS orders,
                   COUNT(DISTINCT h.CustomerID) AS customers
            FROM [Sales].[SalesOrderDetail] d
            JOIN [Sales].[SalesOrderHeader] h ON h.SalesOrderID = d.SalesOrderID
            JOIN [Sales].[Customer] cu ON cu.CustomerID = h.CustomerID
            JOIN [Production].[Product] p ON p.ProductID = d.ProductID
            LEFT JOIN [Production].[ProductSubcategory] sc ON sc.ProductSubcategoryID = p.ProductSubcategoryID
            LEFT JOIN [Production].[ProductCategory] pc ON pc.ProductCategoryID = sc.ProductCategoryID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s{dimension_clause}
            GROUP BY CASE WHEN cu.StoreID IS NULL THEN 0 ELSE 1 END
            """,
            [w.trend_start, w.last] + dimension_params,
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

    context.update({
        "has_data": True,
        "has_kpis": bool(kpis) and "kpis" in selected_panels,
        "has_trend": bool(trend) and "trend" in selected_panels,
        "has_products_panel": ("products" in selected_panels
                               and bool(products_title or category_rows)),
        "has_margin": bool(margin_chart) and "margin" in selected_panels,
        "has_customers": bool(customer_mix) and "customers" in selected_panels,
        "has_table": bool(products) and "table" in selected_panels,
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
        "category_total": money(rev),
        "category_mid_label": category_mid_label,
        "customer_mix": customer_mix,
        "period": "the selected range" if w.custom else "the last 12 months",
        "through": w.last,
        "window_label": w.label,
        "prev_label": w.prev_label,
        "custom": w.custom,
        "w_from": w.trend_start.strftime("%Y-%m-%d"),
        "w_to": w.last.strftime("%Y-%m-%d"),
    })
    return ReportResult("reporting/dashboard.html", context)
