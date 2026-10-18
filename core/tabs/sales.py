"""Sales report tab: its title, its tables, and (later) its dashboard data."""
LABEL = "Sales report"

# Tables that get view / edit / delete pages under this tab. Add a class name to add a table.
TABLES = [
    "SalesOrderHeader",
    "SalesOrderDetail",
    "SalesTerritory",
    "SalesPerson",
    "SalesSpecialOffer",
    "SalesSpecialOfferProduct",
    "SalesReason",
    "SalesTaxRate",
]


def context(request):
    """Extra template data for this tab's dashboard page. Bare for now: the KPIs, infographic
    and chart data will be returned from here when the dashboards are built."""
    return {}
