"""Static report labels, report filters, and table column hints."""

META_KEYS = {
    "tab", "title", "through", "window_label", "prev_label", "custom", "period",
    "w_from", "w_to", "snapshot", "snapshots",
    "manage_url", "can_manage",
    "sales_metric", "cost_metric",
    "category_id", "category_ids",
    "country_code", "country_codes", "include_country",
    "category_options", "country_options", "has_range_filter",
    "filter_from", "filter_to", "filter_preview", "chart_filter_name", "chart_filter_label",
    "chart_filter_value", "chart_filter_options", "chart_has_previous",
    "show_values", "show_options",
    "panel_options", "visible_panels",
    "category_filter", "country_filter",
}

REPORT_COUNTRIES = (
    ("AU", "Australia"), ("CA", "Canada"), ("FR", "France"),
    ("DE", "Germany"), ("GB", "United Kingdom"), ("US", "United States"),
)

CHART_FILTERS = {
    "sales": ("sales_metric", "Sales trend", "revenue", (
        ("revenue", "Sales dollars"), ("orders", "Order count"),
    )),
    "cost": ("cost_metric", "Trend metric", "cost", (
        ("cost", "Cost of goods"), ("margin", "Gross margin"),
    )),
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

LABEL_COLUMNS = {
    "SalesOrderHeader": ["sales_order_number"],
    "Person": ["first_name", "last_name"],
    "PersonAddress": ["address_line1", "city"],
}
