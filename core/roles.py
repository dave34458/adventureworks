"""
Roles (RBAC).

There is exactly one global Administrator: Django's `is_superuser` flag (the shipped
`admin` account). No "Administrator" group is created.

The other roles are 12 scoped Django groups: Manager, Supervisor and Employee for each
of the four in-scope departments. Each department gets exactly one report tab:

    Sales      -> Sales
    Marketing  -> Customer Profile
    Finance    -> Revenue and Loss
    Production -> Cost

Apply the groups with:
    python manage.py shell -c "from core.roles import ROLES, apply_roles; apply_roles(ROLES, prune=True)"
`prune=True` removes groups that are not in ROLES. Assign users to groups on the
"Users and roles" page (/manage/), which only the Administrator can open.

Every role gets its tab's `access_<tab>` permission, read-only access to the tab's
remaining source tables, and view access to the single `Report` table. Managers also get
change/delete on `Report`; Supervisors and Employees are read-only. Only the global
Administrator can edit or delete source-table rows.
"""
from django.contrib.auth.models import Group, Permission

DEPARTMENT_TABS = {
    "Sales": "sales",
    "Marketing": "customer-profile",
    "Finance": "revenue-and-loss",
    "Production": "cost",
}

TABLES = {
    "sales": ["SalesOrderHeader", "SalesOrderDetail", "SalesTerritory"],
    "customer-profile": [
        "SalesCustomer", "Person", "PersonBusinessEntity", "PersonAddress",
        "SalesStore", "PersonStateProvince", "PersonCountryRegion",
    ],
    "revenue-and-loss": [
        "ProductionProduct", "ProductionProductSubcategory", "ProductionProductCategory",
    ],
    "cost": [
        "PurchasingPurchaseOrderHeader", "PurchasingPurchaseOrderDetail",
        "PurchasingVendor", "ProductionWorkOrder", "ProductionProductCostHistory",
        "ProductionScrapReason",
    ],
}

ROLE_KINDS = ("Manager", "Supervisor", "Employee")


def _scope(tab, kind):
    if kind == "Manager":
        return {"tabs": [tab], "view": TABLES[tab] + ["Report"],
                "change": ["Report"], "delete": ["Report"]}
    if kind == "Supervisor":
        return {"tabs": [tab], "view": TABLES[tab] + ["Report"],
                "change": [], "delete": []}
    if kind == "Employee":
        return {"tabs": [tab], "view": ["Report"], "change": [], "delete": []}
    raise ValueError(f"unknown role kind: {kind}")


ROLES = {
    f"{department} {kind}": _scope(tab, kind)
    for department, tab in DEPARTMENT_TABS.items()
    for kind in ROLE_KINDS
}


def apply_roles(roles, prune=False):
    """Create or update one group per role. Returns the group names handled.

    With prune=True, groups whose names are not in `roles` are removed. This is how the
    old department groups are cleaned up; it never touches the Administrator account.
    """
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
    if prune:
        Group.objects.exclude(name__in=done).delete()
    return done
