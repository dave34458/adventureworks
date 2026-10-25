"""Dashboard aggregation and context building."""
from datetime import datetime

from django.db import connection

from ..models import SalesOrderHeader
from ..utils import delta, money, ring, shift_months, window_for
from .common import ReportResult


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
        return ReportResult("core/no_access.html")

    # panel 1: category filter
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
         "Revenue, gross profit, margin and below-cost shortfall"),
        ("cost", "Cost report", "cost", "Cost structure, contributors and recommendations"),
    )
    reports = [{"key": key, "name": name, "url": url, "text": text}
               for key, name, url, text in report_rows if access[key]]

    context = {
        "tab": "dashboard",
        "title": "Business performance dashboard",
        "reports": reports,
        "categories": categories,
        "category_id": category_id,
        "selected_category": selected_category,
        "show_profit": show_profit,
        "has_data": False,
        "empty_message": "No data is available for this report.",
    }
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return ReportResult("core/dashboard.html", context)

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

    if not orders and not customers:
        context.update({
            "w_from": w.trend_start.strftime("%Y-%m-%d"),
            "w_to": w.last.strftime("%Y-%m-%d"),
        })
        return ReportResult("core/dashboard.html", context)

    if not rev:
        margin_cap = "no revenue in this period"
    elif not rev_prev:
        margin_cap = f"{margin}% margin \u00b7 no revenue in {w.prev_label}"
    else:
        margin_cap = f"{margin}% margin \u00b7 was {prev_margin}%"

    # panel 3: KPI cards (derived from panel 2)
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
        add_kpi("Gross profit", money(profit), delta(profit, profit_prev), margin_cap)
    if show_cost:
        cost_change = delta(cogs, cogs_prev)
        cost_direction = {"up": "down", "down": "up"}.get(cost_change[1], cost_change[1])
        add_kpi("Cost of goods", money(cogs), (cost_change[0], cost_direction),
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
        # panel 4: monthly trend
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
        top = max((row[metric_key] for row in cur_series + prev_series), default=0)
        for row in cur_series:
            prev = prev_by_month.get(shift_months(row["month"], -month_offset))
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
                "height": max(round(value / top * 100), 2) if value and top else 0,
                "title": title,
                "prev_h": (max(round(prev[metric_key] / top * 100), 2)
                           if prev and prev[metric_key] and top else 0),
            })

        def margin_of(row):
            value = row["rev"]
            return (round((value - row["cogs"]) / value * 100, 1)
                    if value else None)

        if show_profit and cur_series:
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
            px_w, px_h, pad_l, pad_r, pad_t, pad_b = 960, 260, 52, 16, 12, 28
            plot_w, plot_h = px_w - pad_l - pad_r, px_h - pad_t - pad_b
            xs = [round(pad_l + i * plot_w / max(n - 1, 1), 1) for i in range(n)]

            def y_at(value):
                return round(pad_t + (m_max - value) / m_span * plot_h, 1)

            margin_ticks = ((m_min, 0, m_max) if m_min < 0 else (0, m_max / 2, m_max))
            ticks = [{"y": y_at(value), "label": f"{value:g}%"}
                     for value in margin_ticks]
            step = max(1, (n + 11) // 12)
            xticks = [{"x": xs[i], "label": f"{cur_series[i]['month']:%b}"}
                      for i in range(0, n, step)]
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
                             "t": f"{row['month']:%b %Y} \u00b7 margin {cur_margins[i]}%"
                                  f" \u00b7 gross profit {money(gross)}"})
            prev_dots = [{"x": xs[i], "y": y_at(v),
                          "t": f"{prev_rows[i]['month']:%b %Y} \u00b7 margin {v}%"}
                         for i, v in enumerate(prev_margins) if v is not None]
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
        # panel 5: product ranking
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
            # panel 6: category ring
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
        # panel 7: customer mix
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
            best_label = "strongest month" if show_revenue else "highest-cost month"
            insights.append({"title": f"{metric_name} trend",
                             "text": f"{lead} The {best_label} was {best['month']:%b %Y} "
                                     f"at {money(best[metric_key])}."})
    if show_profit:
        points = margin - prev_margin
        below = (f"{below_n:,} sales lines sold below standard cost, a {money(short)} shortfall."
                 if below_n else "No sales line sold below standard cost.")
        if not rev:
            margin_text = f"No revenue in {w.label}; gross margin has no meaningful comparison."
        elif not rev_prev:
            margin_text = (f"Gross margin is {margin}% in {w.label}; "
                           f"no revenue in {w.prev_label}, so no prior comparison.")
        else:
            margin_text = f"Gross margin is {margin}% ({points:+.1f} pts versus {w.prev_label})."
        insights.append({"title": "Profitability", "text": f"{margin_text} {below}"})
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
    return ReportResult("core/dashboard.html", context)
