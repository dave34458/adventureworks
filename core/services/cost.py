"""Cost report queries and context building."""
from datetime import datetime

from django.db import connection

from ..models import SalesOrderHeader
from ..utils import (
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


def cost(request):
    """Cost report: what the merchandise cost us (standard cost), what we spent
    buying it (purchase orders), and what manufacturing wasted (work order scrap)."""
    saved = _saved_report(request, "cost", "core/cost/report.html")
    if saved:
        return saved
    w = window_for(request, SalesOrderHeader)
    if w is None:
        return _empty_report(request, "cost", "core/cost/report.html", "Cost report")

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
              COALESCE(SUM(CASE WHEN StartDate < %s THEN ScrappedQty ELSE 0 END), 0) AS scr_prev,
              COUNT(*) AS orders
            FROM Production_WorkOrder
            WHERE StartDate >= %s AND StartDate <= %s
            """,
            [cur_lo, cur_lo, cur_lo, cur_lo, w.window_start, w.last],
        )
        qty, scr, qty_prev, scr_prev, wo_count = c.fetchone()

    if (not rev and not cogs and not spend and not po_count and not received
            and not rejected and not wo_count):
        return _empty_report(request, "cost", "core/cost/report.html", "Cost report")

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
        {"k": "Buy", "big": float(proc["spend"] or 0), "kind": "money",
         "cap": f"{proc['orders']:,} purchase orders \u00b7 merchandise, excl. rejected", "cls": ""},
        {"k": "Make", "big": int(scrap["qty"] or 0), "kind": "count",
         "cap": "units started on work orders", "cls": ""},
        {"k": "Waste", "big": int(scrap["scr"] or 0), "kind": "count",
         "cap": f"units scrapped \u00b7 {rate:.2f}%", "cls": "bad"},
        {"k": "Sell", "big": float(cogs or 0), "kind": "money",
         "cap": "cost of goods sold to customers", "cls": ""},
    ]

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
            "money": float(r["cogs"] or 0),
            "margin": round((float(r["rev"]) - float(r["cogs"])) / float(r["rev"]) * 100, 1) if r["rev"] else 0,
        }
        for i, r in enumerate(cats, 1)
    ]
    donut = ring([{"cls": m["cls"], "pct": m["pct"],
                   "t": f"{m['name']} \u00b7 {money(m['money'])} \u00b7 "
                        f"{percent(m['pct'])} of cost \u00b7 {percent(m['margin'])} margin"}
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
    vendors = rank(vendor_rows, "name", "spend")
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
    products = rank(costly, "name", "cogs")
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
    reasons = rank(reason_rows, "name", "scr")
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
            """
            SELECT po.PurchaseOrderID, v.Name, po.OrderDate, po.SubTotal, po.Status,
                   (SELECT COUNT(*) FROM Purchasing_PurchaseOrderDetail d
                    WHERE d.PurchaseOrderID = po.PurchaseOrderID) AS lines
            FROM Purchasing_PurchaseOrderHeader po
            JOIN Purchasing_Vendor v ON v.BusinessEntityID = po.VendorID
            WHERE po.OrderDate >= %s AND po.OrderDate <= %s AND po.Status <> 3
            ORDER BY po.SubTotal DESC
            LIMIT 8
            """,
            [cur_lo, cur_hi],
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

    return _report_response(request, "cost", "core/cost/report.html", {
        "tab": "cost",
        "title": "Cost report",
        "kpis": kpis,
        "pipeline": pipeline,
        "trend": trend,
        "mix": mix,
        "donut": donut,
        "donut_mid": {"big": float(cogs or 0), "small": "cost of goods"},
        "vendors": vendors,
        "products": products,
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
