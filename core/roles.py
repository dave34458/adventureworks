"""
Roles (RBAC).

SUPERADMIN is not defined here: it is Django's `is_superuser` flag (create one with
`python manage.py createsuperuser`). A superuser automatically has every permission.

Every other role is a Django group. Define it in ROLES below, then apply it with
    python manage.py shell -c "from core.roles import ROLES, apply_roles; apply_roles(ROLES)"
which creates or updates the groups (it is safe to run again). Assign users to groups on the
"Users and roles" page (/manage/) that only the superadmin can open.

Each role has:
    "tabs":   tabs the role can open        -> "sales", "customer-profile", "revenue-and-loss", "cost"
    "view":   tables the role can see       -> model class names, e.g. "SalesOrderHeader"
    "change": tables the role can edit      -> same
    "delete": tables the role can delete    -> same ([] = none)
There is no "create" action.

The 17 roles below are the department matrix; core/tests.py encodes the same matrix a
second time, so any drift between the two fails the test suite.
"""
from django.contrib.auth.models import Group, Permission

ALL_TABS = ["sales", "customer-profile", "revenue-and-loss", "cost"]

SALES_TABLES = [
    "SalesOrderHeader", "SalesOrderDetail", "SalesTerritory", "SalesPerson",
    "SalesSpecialOffer", "SalesSpecialOfferProduct", "SalesReason", "SalesTaxRate",
]
CUSTOMER_PROFILE_TABLES = [
    "SalesCustomer", "Person", "PersonEmailAddress", "PersonPhone", "PersonAddress",
    "PersonBusinessEntityAddress", "SalesStore", "PersonStateProvince", "PersonCountryRegion",
]
REVENUE_AND_LOSS_TABLES = [
    "ProductionProduct", "ProductionProductListPriceHistory", "ProductionProductSubcategory",
    "ProductionProductCategory", "SalesCurrency", "SalesCurrencyRate",
]
COST_TABLES = [
    "PurchasingPurchaseOrderHeader", "PurchasingPurchaseOrderDetail", "PurchasingVendor",
    "PurchasingProductVendor", "ProductionWorkOrder", "ProductionLocation",
    "ProductionProductCostHistory", "ProductionScrapReason", "PurchasingShipMethod",
]
ALL_TABLES = SALES_TABLES + CUSTOMER_PROFILE_TABLES + REVENUE_AND_LOSS_TABLES + COST_TABLES

SALES_MANAGER_TABLES = SALES_TABLES + CUSTOMER_PROFILE_TABLES
SALES_STAFF_TABLES = [name for name in SALES_TABLES if name != "SalesPerson"] + CUSTOMER_PROFILE_TABLES
ENGINEERING_TABLES = [
    "ProductionProduct", "ProductionProductSubcategory", "ProductionProductCategory",
    "ProductionProductCostHistory", "ProductionWorkOrder", "ProductionLocation",
]
PRODUCT_TABLES = ["ProductionProduct", "ProductionProductSubcategory", "ProductionProductCategory"]

ROLES = {
    "Executive": {
        "tabs": ALL_TABS,
        "view": ALL_TABLES,
        "change": [],
        "delete": [],
    },
    "Finance Manager": {
        "tabs": ALL_TABS,
        "view": ALL_TABLES,
        "change": ["ProductionProduct", "ProductionProductListPriceHistory",
                   "ProductionProductCostHistory", "SalesCurrencyRate"],
        "delete": [],
    },
    "Finance Staff": {
        "tabs": ALL_TABS,
        "view": ALL_TABLES,
        "change": ["SalesCurrencyRate"],
        "delete": [],
    },
    "Sales Manager": {
        "tabs": ["sales", "customer-profile"],
        "view": SALES_MANAGER_TABLES,
        "change": ["SalesOrderHeader", "SalesOrderDetail", "SalesCustomer", "SalesStore",
                   "PersonEmailAddress", "PersonPhone", "PersonAddress",
                   "PersonBusinessEntityAddress", "SalesSpecialOffer", "SalesSpecialOfferProduct"],
        "delete": ["SalesSpecialOffer", "SalesSpecialOfferProduct"],
    },
    "Sales Staff": {
        "tabs": ["sales", "customer-profile"],
        "view": SALES_STAFF_TABLES,
        "change": ["PersonEmailAddress", "PersonPhone", "PersonAddress",
                   "PersonBusinessEntityAddress"],
        "delete": [],
    },
    "Marketing": {
        "tabs": ["sales", "customer-profile"],
        "view": SALES_STAFF_TABLES,
        "change": ["SalesSpecialOffer", "SalesSpecialOfferProduct"],
        "delete": [],
    },
    "Purchasing Manager": {
        "tabs": ["cost"],
        "view": COST_TABLES,
        "change": ["PurchasingPurchaseOrderHeader", "PurchasingPurchaseOrderDetail",
                   "PurchasingVendor", "PurchasingProductVendor", "PurchasingShipMethod"],
        "delete": ["PurchasingProductVendor"],
    },
    "Purchasing Staff": {
        "tabs": ["cost"],
        "view": COST_TABLES,
        "change": ["PurchasingPurchaseOrderHeader", "PurchasingPurchaseOrderDetail",
                   "PurchasingProductVendor"],
        "delete": [],
    },
    "Shipping and Receiving": {
        "tabs": ["cost"],
        "view": ["PurchasingPurchaseOrderHeader", "PurchasingPurchaseOrderDetail",
                 "PurchasingVendor", "PurchasingShipMethod", "ProductionLocation"],
        "change": ["PurchasingPurchaseOrderDetail"],
        "delete": [],
    },
    "Production Manager": {
        "tabs": ["cost"],
        "view": COST_TABLES,
        "change": ["ProductionWorkOrder"],
        "delete": [],
    },
    "Production Staff": {
        "tabs": ["cost"],
        "view": ["ProductionWorkOrder", "ProductionLocation"],
        "change": [],
        "delete": [],
    },
    "Production Control": {
        "tabs": ["cost"],
        "view": ["ProductionWorkOrder", "ProductionScrapReason", "ProductionLocation"],
        "change": ["ProductionWorkOrder", "ProductionScrapReason", "ProductionLocation"],
        "delete": [],
    },
    "Quality Assurance": {
        "tabs": ["cost"],
        "view": ["ProductionWorkOrder", "ProductionScrapReason", "ProductionLocation"],
        "change": ["ProductionScrapReason"],
        "delete": [],
    },
    "Engineering Manager": {
        "tabs": ["revenue-and-loss", "cost"],
        "view": ENGINEERING_TABLES,
        "change": PRODUCT_TABLES,
        "delete": [],
    },
    "Engineering Staff": {
        "tabs": ["revenue-and-loss", "cost"],
        "view": ENGINEERING_TABLES,
        "change": ["ProductionProduct"],
        "delete": [],
    },
    "Research and Development": {
        "tabs": ["revenue-and-loss"],
        "view": PRODUCT_TABLES,
        "change": [],
        "delete": [],
    },
    "Tool Design": {
        "tabs": ["revenue-and-loss"],
        "view": PRODUCT_TABLES,
        "change": [],
        "delete": [],
    },
}


def apply_roles(roles):
    """Create or update one group per role. Returns the group names handled."""
    done = []
    for role, spec in roles.items():
        codenames = [f"access_{tab.replace('-', '_')}" for tab in spec.get("tabs", [])]
        for action in ("view", "change", "delete"):
            codenames += [f"{action}_{name.lower()}" for name in spec.get(action, [])]
        found = Permission.objects.filter(content_type__app_label="core", codename__in=codenames)
        missing = set(codenames) - set(found.values_list("codename", flat=True))
        if missing:
            raise ValueError(f"{role}: no such permission(s) {sorted(missing)}")
        Group.objects.get_or_create(name=role)[0].permissions.set(found)
        done.append(role)
    return done
