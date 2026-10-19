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
"""
from django.contrib.auth.models import Group, Permission

ROLES = {
    # Superadmin = is_superuser, nothing to define here.

    # --- Placeholders: uncomment a role (and adjust it), then apply the roles as above ---

    # "Sales Manager": {
    #     "tabs": ["sales"],
    #     "view": ["SalesOrderHeader", "SalesOrderDetail", "SalesTerritory", "SalesPerson",
    #              "SalesSpecialOffer", "SalesSpecialOfferProduct", "SalesReason", "SalesTaxRate"],
    #     "change": ["SalesOrderHeader", "SalesOrderDetail"],
    #     "delete": [],
    # },
    # "Customer Service": {
    #     "tabs": ["customer-profile"],
    #     "view": ["SalesCustomer", "Person", "PersonEmailAddress", "PersonPhone", "PersonAddress",
    #              "PersonBusinessEntityAddress", "SalesStore", "PersonStateProvince",
    #              "PersonCountryRegion"],
    #     "change": ["Person", "PersonEmailAddress", "PersonPhone"],
    #     "delete": [],
    # },
    # "Cost Analyst": {
    #     "tabs": ["cost"],
    #     "view": ["PurchasingPurchaseOrderHeader", "PurchasingPurchaseOrderDetail",
    #              "PurchasingVendor", "PurchasingProductVendor", "ProductionWorkOrder",
    #              "ProductionLocation", "ProductionProductCostHistory", "ProductionScrapReason",
    #              "PurchasingShipMethod"],
    #     "change": [],
    #     "delete": [],
    # },
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
