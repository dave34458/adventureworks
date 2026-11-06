"""Cost report queries and context building."""
from django.db import connection

from core.models import SalesOrderHeader
from ..utils import (
    delta_pct,
    rank,
    shift_months,
    window_for,
)
from .charts import build_donut
from .common import (
    _empty_report,
    _report_response,
    _saved_report,
    dimension_sql,
    purchase_category_sql,
    report_dimension_filters,
)
from .dialect import limit_clause, month_expr


def cost(request):
    """Cost report: what the merchandise cost us (standard cost), what we spent
    buying it (purchase orders), and what manufacturing wasted (work order scrap)."""
    saved = _saved_report(request, "cost", "reporting/cost/report.html")
    if saved:
        return saved
    filters = report_dimension_filters(request, include_country=False)
    line_filter, line_params = dimension_sql(filters, header_ref=None)
    work_filter, work_params = dimension_sql(
        filters, product_ref="w.ProductID", header_ref=None)
    history_filter, history_params = dimension_sql(
        filters, product_ref="h.ProductID", header_ref=None)
    purchase_filter, purchase_params = purchase_category_sql(filters)
    category_selected = bool(filters["category_ids"])
    purchase_detail_join = (
        "JOIN Purchasing_PurchaseOrderDetail pod ON pod.PurchaseOrderID = po.PurchaseOrderID"
        if category_selected else "")
    purchase_total = "pod.LineTotal" if category_selected else "po.SubTotal"
    purchase_orders = (
        "COUNT(DISTINCT CASE WHEN po.OrderDate >= %s AND po.OrderDate <= %s "
        "THEN po.PurchaseOrderID END)" if category_selected else
        "SUM(CASE WHEN po.OrderDate >= %s AND po.OrderDate <= %s THEN 1 ELSE 0 END)")
    purchase_vendor_orders = ("COUNT(DISTINCT po.PurchaseOrderID)" if category_selected
                              else "COUNT(*)")
    biggest_po_total = "SUM(pod.LineTotal)" if category_selected else "po.SubTotal"
    biggest_po_lines = ("COUNT(*)" if category_selected else
                        "(SELECT COUNT(*) FROM Purchasing_PurchaseOrderDetail d "
                        "WHERE d.PurchaseOrderID = po.PurchaseOrderID)")
    biggest_po_group = ("GROUP BY po.PurchaseOrderID, v.Name, po.OrderDate, po.Status"
                        if category_selected else "")
    biggest_po_order = biggest_po_total
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return _empty_report(request, "cost", "reporting/cost/report.html", "Cost report")

    cur_lo, cur_hi = w.trend_start, w.last
    prev_lo, prev_hi = w.window_start, w.trend_start

    with connection.cursor() as c:  # chart 1: cost KPIs (sales lines at standard cost)
        c.execute(
            f"""
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
            WHERE h.OrderDate >= %s{line_filter}
            """,
            [cur_lo, cur_hi, prev_lo, prev_hi, cur_lo, cur_hi, prev_lo, prev_hi,
             w.window_start] + line_params,
        )
        cogs, cogs_prev, rev, rev_prev = c.fetchone()

        c.execute(  # procurement: orders placed for parts
            f"""
            SELECT
              COALESCE(SUM(CASE WHEN po.OrderDate >= %s AND po.OrderDate <= %s
                                THEN {purchase_total} END), 0) AS spend,
              COALESCE(SUM(CASE WHEN po.OrderDate >= %s AND po.OrderDate < %s
                                THEN {purchase_total} END), 0) AS spend_prev,
              {purchase_orders} AS orders
            FROM Purchasing_PurchaseOrderHeader po
            {purchase_detail_join}
            WHERE po.OrderDate >= %s AND po.Status <> 3{purchase_filter}
            """,
            [cur_lo, cur_hi, prev_lo, prev_hi, cur_lo, cur_hi,
             w.window_start] + purchase_params,
        )
        spend, spend_prev, po_count = c.fetchone()

        c.execute(  # receipts against those orders
            f"""
            SELECT COALESCE(SUM(d.ReceivedQty), 0), COALESCE(SUM(d.RejectedQty), 0)
            FROM Purchasing_PurchaseOrderDetail d
            JOIN Purchasing_PurchaseOrderHeader h ON h.PurchaseOrderID = d.PurchaseOrderID
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
            """,
            [cur_lo, cur_hi] + line_params,
        )
        received, rejected = c.fetchone()

        c.execute(  # manufacturing: units started and scrapped
            f"""
            SELECT
              COALESCE(SUM(CASE WHEN StartDate >= %s THEN OrderQty ELSE 0 END), 0) AS qty,
              COALESCE(SUM(CASE WHEN StartDate >= %s THEN ScrappedQty ELSE 0 END), 0) AS scr,
              COALESCE(SUM(CASE WHEN StartDate < %s THEN OrderQty ELSE 0 END), 0) AS qty_prev,
              COALESCE(SUM(CASE WHEN StartDate < %s THEN ScrappedQty ELSE 0 END), 0) AS scr_prev,
              COUNT(*) AS orders
            FROM Production_WorkOrder w
            WHERE w.StartDate >= %s AND w.StartDate <= %s{work_filter}
            """,
            [cur_lo, cur_lo, cur_lo, cur_lo, w.window_start, w.last] + work_params,
        )
        qty, scr, qty_prev, scr_prev, wo_count = c.fetchone()

    if (not rev and not cogs and not spend and not po_count and not received
            and not rejected and not wo_count):
        return _empty_report(request, "cost", "reporting/cost/report.html", "Cost report")

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

    kpis = []
    for label, value, kind, change, cap in (
        ("Cost of goods sold", float(cogs or 0), "money", delta_pct(cogs, cogs_prev),
         "standard cost effective on the sale date"),
        ("Cost per $1 revenue", float(ratio) if ratio is not None else None, "cents",
         delta_pct(ratio, ratio_prev),
         f"was {ratio_prev:.0f}\u00a2 in {w.prev_label}" if ratio_prev is not None
         else f"no revenue in {w.prev_label}"),
        ("Procurement spend", float(proc["spend"] or 0), "money",
         delta_pct(proc["spend"], proc_prev["spend"]),
         f"{proc['orders']:,} non-rejected POs \u00b7 merchandise, excl. tax & freight"),
        ("Scrap rate", float(rate or 0), "percent", delta_pct(rate, rate_prev),
         f"{scrap['scr']:,} units of {scrap['qty']:,} started"),
        ("Rejected receipts", float(rej_pct or 0), "percent", (None, None),
         f"{rec['rej']:,.0f} units of {rec['rec']:,.0f} received \u00b7 all POs"),
    ):
        direction = {"up": "down", "down": "up"}.get(change[1], change[1])
        kpis.append({"label": label, "value": value, "value_kind": kind,
                     "delta": change[0], "dir": direction, "cap": cap})

    with connection.cursor() as c:  # chart 2: monthly cost of goods sold
        c.execute(
            f"""
            SELECT month, side, SUM(cogs) AS cogs, SUM(rev) AS rev
            FROM (
                SELECT {month_expr("h.OrderDate")} AS month,
                       CASE WHEN h.OrderDate < %s THEN 'prev' ELSE 'cur' END AS side,
                       d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost) AS cogs,
                       d.LineTotal AS rev
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
            [w.trend_start, w.window_start, w.last] + line_params,
        )
        series = [
            {"month": m, "side": side, "cogs": cogs, "rev": rev}
            for m, side, cogs, rev in c.fetchall()
        ]
    cur_by_month = {m["month"]: m for m in series if m["side"] == "cur"}
    prev_months = [m for m in series if m["side"] == "prev"]
    months = []
    month = w.trend_start.replace(day=1)
    last_month = w.last.replace(day=1)
    while month <= last_month:
        months.append(cur_by_month.get(
            month, {"month": month, "side": "cur", "cogs": 0, "rev": 0}))
        if month == last_month:
            break
        month = shift_months(month, 1)
    month_offset = ((w.trend_start.year * 12 + w.trend_start.month)
                    - (w.window_start.year * 12 + w.window_start.month))
    prev_by_month = {m["month"]: m for m in prev_months}
    top = max((float(m["cogs"]) for m in months + prev_months), default=0)
    trend = []
    for m in months:
        prev = prev_by_month.get(shift_months(m["month"], -month_offset))
        trend.append({
            "label": m["month"].strftime("%b"), "full": m["month"].strftime("%b %Y"),
            "money": float(m["cogs"] or 0),
            "margin": round((float(m["rev"]) - float(m["cogs"])) / float(m["rev"]) * 100, 1) if m["rev"] else 0,
            "height": round(float(m["cogs"]) / top * 100, 2) if top else 0,
            "prev_full": prev["month"].strftime("%b %Y") if prev else "",
            "prev_money": float(prev["cogs"] or 0) if prev else None,
            "prev_h": (max(round(float(prev["cogs"]) / top * 100), 2)
                       if prev and prev["cogs"] and top else 0),
        })

    with connection.cursor() as c:  # chart 3: where costs sit (category mix)
        c.execute(
            f"""
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
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
            GROUP BY cat.Name
            ORDER BY cogs DESC
            """,
            [cur_lo, cur_hi] + line_params,
        )
        cats = [{"name": name, "cogs": cogs, "rev": rev}
                for name, cogs, rev in c.fetchall()]
    total_cogs = float(cogs) or 1
    mix = [
        {
            "name": r["name"],
            "cls": f"c{i}",
            "pct": round(float(r["cogs"]) / total_cogs * 100, 1),
            "money": float(r["cogs"] or 0),
            "margin": round((float(r["rev"]) - float(r["cogs"])) / float(r["rev"]) * 100, 1) if r["rev"] else 0,
        }
        for i, r in enumerate(cats, 1)
    ]
    donut = build_donut("cost", mix)

    with connection.cursor() as c:  # chart 4: top vendors by procurement spend
        c.execute(
            f"""
            SELECT v.Name, SUM({purchase_total}) AS spend,
                   {purchase_vendor_orders} AS orders, v.ActiveFlag
            FROM Purchasing_PurchaseOrderHeader po
            {purchase_detail_join}
            JOIN Purchasing_Vendor v ON v.BusinessEntityID = po.VendorID
            WHERE po.OrderDate >= %s AND po.OrderDate <= %s AND po.Status <> 3{purchase_filter}
            GROUP BY v.Name, v.ActiveFlag
            ORDER BY spend DESC
            {limit_clause(8)}
            """,
            [cur_lo, cur_hi] + purchase_params,
        )
        vendor_rows = [{"name": name, "spend": vendor_spend, "orders": orders,
                        "active": bool(active)}
                       for name, vendor_spend, orders, active in c.fetchall()]
    vendors = rank(vendor_rows, "name", "spend")
    for r, s in zip(vendors, vendor_rows):
        r["note"] = f"{s['orders']:,} non-rejected purchase orders"
        if not s["active"]:
            r["note"] += " · inactive vendor"

    with connection.cursor() as c:  # chart 5: products that cost us most
        c.execute(
            f"""
            SELECT p.Name, SUM(d.OrderQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cogs,
                   SUM(d.OrderQty) AS units
            FROM Sales_SalesOrderDetail d
            JOIN Sales_SalesOrderHeader h ON h.SalesOrderID = d.SalesOrderID
            JOIN Production_Product p ON p.ProductID = d.ProductID
            LEFT JOIN Production_ProductCostHistory ch
              ON ch.ProductID = d.ProductID
             AND h.OrderDate >= ch.StartDate
             AND (ch.EndDate IS NULL OR h.OrderDate <= ch.EndDate)
            WHERE h.OrderDate >= %s AND h.OrderDate <= %s{line_filter}
            GROUP BY p.Name
            ORDER BY cogs DESC
            {limit_clause(8)}
            """,
            [cur_lo, cur_hi] + line_params,
        )
        costly = [{"name": name, "cogs": product_cogs, "units": units}
                  for name, product_cogs, units in c.fetchall()]
    products = rank(costly, "name", "cogs")
    for r, s in zip(products, costly):
        r["note"] = f"{s['units']:,} units"

    with connection.cursor() as c:  # chart 6: scrap reasons
        c.execute(
            f"""
            SELECT sr.Name,
                   SUM(w.ScrappedQty * COALESCE(ch.StandardCost, p.StandardCost)) AS cost,
                   SUM(w.ScrappedQty) AS scr,
                   COUNT(*) AS orders
            FROM Production_WorkOrder w
            JOIN Production_ScrapReason sr ON sr.ScrapReasonID = w.ScrapReasonID
            JOIN Production_Product p ON p.ProductID = w.ProductID
            LEFT JOIN Production_ProductCostHistory ch
              ON ch.ProductID = w.ProductID
             AND w.StartDate >= ch.StartDate
             AND (ch.EndDate IS NULL OR w.StartDate <= ch.EndDate)
            WHERE w.StartDate >= %s AND w.StartDate <= %s{work_filter}
            GROUP BY sr.Name
            ORDER BY cost DESC
            {limit_clause(8)}
            """,
            [cur_lo, cur_hi] + work_params,
        )
        reason_rows = [{"name": name, "cost": cost, "scr": scrapped, "orders": orders}
                       for name, cost, scrapped, orders in c.fetchall()]
    reasons = rank(reason_rows, "name", "cost")
    for r, s in zip(reasons, reason_rows):
        r["note"] = f"{s['scr']:,} units \u00b7 {s['orders']:,} work orders"

    with connection.cursor() as c:  # chart 7: standard cost changes
        c.execute(
            f"SELECT h.ProductID, h.StandardCost FROM Production_ProductCostHistory h "
            f"WHERE h.EndDate IS NULL{history_filter}", history_params)
        open_cost = dict(c.fetchall())

        c.execute(
            f"""
            SELECT h.ProductID, p.Name, h.StandardCost
            FROM Production_ProductCostHistory h
            JOIN Production_Product p ON p.ProductID = h.ProductID
            WHERE h.EndDate IS NOT NULL{history_filter}
            ORDER BY h.StartDate
            """,
            history_params,
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
    changes = [
        {
            "name": h["name"],
            "old": float(h["old"]),
            "now": float(h["now"]),
            "pct": float(h["pct"]),
            "note": "standard cost per unit",
        }
        for h in hikes
    ]

    statuses = {1: ("Pending", ""), 2: ("Approved", "online"), 3: ("Rejected", "bad"), 4: ("Complete", "")}
    with connection.cursor() as c:  # chart 8: largest purchase orders
        c.execute(
            f"""
            SELECT po.PurchaseOrderID, v.Name, po.OrderDate, {biggest_po_total}, po.Status,
                   {biggest_po_lines} AS lines
            FROM Purchasing_PurchaseOrderHeader po
            {purchase_detail_join}
            JOIN Purchasing_Vendor v ON v.BusinessEntityID = po.VendorID
            WHERE po.OrderDate >= %s AND po.OrderDate <= %s AND po.Status <> 3{purchase_filter}
            {biggest_po_group}
            ORDER BY {biggest_po_order} DESC
            {limit_clause(8)}
            """,
            [cur_lo, cur_hi] + purchase_params,
        )
        biggest = [
            {
                "id": order_id, "vendor": vendor,
                "date": order_date.date().isoformat() if hasattr(order_date, "date") else str(order_date),
                "lines": int(lines or 0), "total": float(total or 0),
                "status": statuses.get(status, ("\u2014", ""))[0], "cls": statuses.get(status, ("", ""))[1],
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
            note += f" In {w.prev_label} cost was {ratio_prev:.0f}\u00a2 per revenue dollar."
        performance = {
            "cost": round(float(ratio), 1),
            "margin": round(float(margin_ratio), 1),
            "note": note,
        }

    return _report_response(request, "cost", "reporting/cost/report.html", {
        "tab": "cost",
        "title": "Cost report",
        "kpis": kpis,
        "trend": trend,
        "mix": mix,
        "donut": donut,
        "donut_mid": {"big": float(cogs or 0), "small": "cost of goods"},
        "vendors": vendors,
        "products": products,
        "scrap_metric": "cost",
        "reasons": reasons,
        "changes": changes,
        "biggest": biggest,
        "performance": performance,
        "through": w.last,
        "window_label": w.label,
        "prev_label": w.prev_label,
        "custom": w.custom,
        "period": "the selected range" if w.custom else "the last 12 months",
        "w_from": w.trend_start.strftime("%Y-%m-%d"),
        "w_to": w.last.strftime("%Y-%m-%d"),
    }, w)
