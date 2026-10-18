"""
Roles (RBAC).

SUPERADMIN is not defined here: it is Django's `is_superuser` flag (create one with
`python manage.py createsuperuser`). A superuser automatically has every permission.

Every other role is a Django group. Define it in ROLES below, then run
    python manage.py setup_roles
which creates or updates the groups (it is safe to run again). Assign users to groups on the
"Users and roles" page (/manage/) that only the superadmin can open.

Each role has:
    "tabs":   tabs the role can open        -> "sales", "customers", "costs", "finance"
    "view":   tables the role can see       -> "*" (every table in its tabs) or a list of class names
    "change": tables the role can edit      -> "*" or a list of class names ([] = none)
    "delete": tables the role can delete    -> "*" or a list of class names ([] = none)
Table names are the model class names, e.g. "SalesOrderHeader". There is no "create" action.
"""
from django.contrib.auth.models import Group, Permission

from .tabs import TABS

ROLES = {
    # Superadmin = is_superuser, nothing to define here.

    # --- Placeholders: uncomment a role (and adjust it), then run `python manage.py setup_roles` ---

    # "Sales Manager": {
    #     "tabs": ["sales"],
    #     "view": "*",
    #     "change": ["SalesOrderHeader", "SalesOrderDetail"],
    #     "delete": [],
    # },
    # "Customer Service": {
    #     "tabs": ["customers"],
    #     "view": "*",
    #     "change": ["Person", "PersonEmailAddress", "PersonPhone"],
    #     "delete": [],
    # },
    # "Cost Analyst": {
    #     "tabs": ["costs"],
    #     "view": "*",
    #     "change": [],
    #     "delete": [],
    # },
    # "Finance": {
    #     "tabs": ["finance"],
    #     "view": "*",
    #     "change": [],
    #     "delete": [],
    # },
    # "Read-only": {
    #     "tabs": ["sales", "customers", "costs", "finance"],
    #     "view": "*",
    #     "change": [],
    #     "delete": [],
    # },
}


def apply_roles(roles):
    """Create or update one group per role. Returns the group names handled."""
    done = []
    for role, spec in roles.items():
        tabs = spec.get("tabs", [])
        unknown = [t for t in tabs if t not in TABS]
        if unknown:
            raise ValueError(f"{role}: unknown tab(s) {unknown}; use {list(TABS)}")
        in_tabs = [name for t in tabs for name in TABS[t]]
        codenames = [f"access_{t}" for t in tabs]
        for action in ("view", "change", "delete"):
            names = spec.get(action, [])
            names = in_tabs if names == "*" else names
            outside = [n for n in names if n not in in_tabs]
            if outside:
                raise ValueError(f"{role}: {outside} are not in the role's tabs {tabs}")
            codenames += [f"{action}_{n.lower()}" for n in names]
        found = Permission.objects.filter(content_type__app_label="core", codename__in=codenames)
        missing = set(codenames) - set(found.values_list("codename", flat=True))
        if missing:
            raise ValueError(f"{role}: no such permission(s) {sorted(missing)}")
        Group.objects.get_or_create(name=role)[0].permissions.set(found)
        done.append(role)
    return done
