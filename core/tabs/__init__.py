"""The four nav tabs. Each tab has its own module (sales.py, customers.py, costs.py, finance.py)."""
from django.apps import apps

from . import costs, customers, finance, sales

TAB_MODULES = {"sales": sales, "customers": customers, "costs": costs, "finance": finance}
TABS = {slug: module.TABLES for slug, module in TAB_MODULES.items()}
LABELS = {slug: module.LABEL for slug, module in TAB_MODULES.items()}
TAB_OF = {table: slug for slug, tables in TABS.items() for table in tables}


def table_label(name):
    return apps.get_model("core", name)._meta.verbose_name.capitalize()


def visible_tables(user, tab):
    """(class name, readable label) for each table in the tab that the user may view."""
    return [(n, table_label(n)) for n in TABS[tab] if user.has_perm(f"core.view_{n.lower()}")]
