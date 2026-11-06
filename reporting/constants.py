"""Static report labels, editor metadata, and table column hints."""

META_KEYS = {
    "tab", "title", "through", "window_label", "prev_label", "custom", "period",
    "w_from", "w_to", "snapshot", "snapshots",
    "edit_url", "manage_url", "can_manage",
    "sales_metric", "customer_segment", "cost_metric",
    "category_id", "country_code", "category_ids", "country_codes", "include_country",
    "category_options", "country_options", "has_range_filter",
    "filter_from", "filter_to", "chart_filter_name", "chart_filter_label",
    "chart_filter_value", "chart_filter_options",
}

EDITABLE_KEYS = {
    "sales": ["kpis", "trend", "products", "low_products"],
    "customer-profile": [
        "kpis", "growth", "channels", "countries", "cities", "network", "frequency",
        "biggest", "new_legend", "ret_legend",
    ],
    "revenue-and-loss": [
        "kpis", "rev_trend", "profit_rows", "margin_rows", "mix", "declining", "leaks",
        "products", "donut_mid",
    ],
    "cost": [
        "kpis", "trend", "mix", "vendors", "products", "reasons",
        "changes", "biggest", "performance", "donut_mid",
    ],
}

EDITOR_HIDDEN_FIELDS = {
    ("sales", "trend"): {"height", "prev_h"},
    ("customer-profile", "growth"): {"act", "new_h", "ret_h"},
    ("revenue-and-loss", "rev_trend"): {"height", "prev_h"},
    ("cost", "trend"): {"height", "prev_h"},
}

SECTION_LABELS = {
    "kpis": "KPI cards",
    "trend": "Monthly trend",
    "growth": "New vs returning buyers",
    "rev_trend": "Revenue trend by month",
    "profit_rows": "Gross profit \u00b7 selected period",
    "margin_rows": "Gross margin by month",
    "products": "Product rows",
    "low_products": "Low-performing product rows",
    "channels": "Buyer channels",
    "countries": "Countries",
    "cities": "Cities",
    "network": "Store network",
    "frequency": "Purchase frequency",
    "biggest": "Largest rows",
    "new_legend": "New-buyer legend",
    "ret_legend": "Returning-buyer legend",
    "mix": "Category mix",
    "declining": "Declining products",
    "leaks": "Below-cost products",
    "vendors": "Vendors",
    "reasons": "Scrap reasons",
    "changes": "Standard-cost changes",
    "performance": "Cost performance",
    "donut_mid": "Donut centre",
}

FIELD_LABELS = {
    "act": "Active customers",
    "aov": "Average order value",
    "big": "Value",
    "cap": "Caption",
    "cls": "Style",
    "cost": "Cost",
    "cust_pct": "Buyer share",
    "customers": "Customers",
    "date": "Date",
    "delta": "Change",
    "dir": "Direction",
    "full": "Full label",
    "height": "Bar height",
    "id": "ID",
    "kind": "Unit",
    "label": "Label",
    "lines": "Lines",
    "margin": "Margin",
    "money": "Amount",
    "n": "Count",
    "name": "Name",
    "new_h": "New-customer height",
    "note": "Note",
    "now": "New cost",
    "nw": "New customers",
    "old": "Old cost",
    "orders": "Orders",
    "pct": "Percent",
    "prev_full": "Previous label",
    "prev_h": "Previous height",
    "prev_margin": "Previous margin",
    "prev_money": "Previous amount",
    "prev_orders": "Previous orders",
    "profit": "Gross profit",
    "ret": "Returning customers",
    "ret_h": "Returning height",
    "rev": "Revenue",
    "small": "Small label",
    "status": "Status",
    "store": "Store customer",
    "territory": "Territory",
    "text": "Text",
    "title": "Title",
    "total": "Total",
    "value": "Value",
    "value_kind": "Unit",
    "vendor": "Vendor",
}

EDITOR_INTEGER_FIELDS = {
    "act", "customers", "id", "lines", "n", "nw", "orders", "prev_orders", "ret",
}
EDITOR_NUMBER_FIELDS = {
    "aov", "big", "cost", "cust_pct", "delta", "height", "margin", "money", "new_h",
    "old", "now", "pct", "prev_h", "prev_margin", "prev_money", "profit", "ret_h",
    "rev", "total", "value",
}
EDITOR_CHECKBOX_FIELDS = {"store"}
EDITOR_DATE_FIELDS = {"date"}
KIND_CHOICES = (("money", "Money"), ("count", "Count"), ("percent", "Percent"),
                ("units", "Units"), ("cents", "Cents"))
EDITOR_SELECTS = {
    "value_kind": KIND_CHOICES,
    "kind": KIND_CHOICES,
    "dir": (("", "No change"), ("up", "Up"), ("down", "Down"), ("flat", "Flat")),
    "status": (("Pending", "Pending"), ("Approved", "Approved"),
               ("Rejected", "Rejected"), ("Complete", "Complete")),
}

LABEL_COLUMNS = {
    "SalesOrderHeader": ["sales_order_number"],
    "Person": ["first_name", "last_name"],
    "PersonAddress": ["address_line1", "city"],
}
