import os
import socket
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


BASE_URL = os.getenv("E2E_BASE_URL", f"http://127.0.0.1:{_free_port()}").rstrip("/")
RESULTS_FILE = Path(os.getenv("E2E_RESULTS_FILE", PROJECT_ROOT / "docs" / "test-case-results.md"))
ARTIFACT_DIR = PROJECT_ROOT / "tests" / "artifacts"
VIEWPORT = {"width": 1440, "height": 900}
# Visible browser by default; set E2E_HEADLESS=1 (or "true"/"yes") to hide it.
HEADLESS = os.getenv("E2E_HEADLESS", "0").strip().lower() not in {"0", "false", "no"}
KINDS = ("Admin", "Manager", "Supervisor", "Employee")

DEPARTMENTS = {
    "Sales": {
        "path": "/sales/",
        "tab": "sales",
        "nav": "Sales",
        "title": "Sales report",
        "tables": {
            "SalesOrderHeader": "Sales order header",
            "SalesOrderDetail": "Sales order detail",
            "SalesTerritory": "Sales territory",
        },
    },
    "Marketing": {
        "path": "/customer-profile/",
        "tab": "customer-profile",
        "nav": "Customer profile",
        "title": "Customer profile report",
        "tables": {
            "SalesCustomer": "Sales customer",
            "Person": "Person",
            "PersonBusinessEntity": "Person business entity",
            "PersonAddress": "Person address",
            "SalesStore": "Sales store",
            "PersonStateProvince": "Person state province",
            "PersonCountryRegion": "Person country region",
        },
    },
    "Finance": {
        "path": "/revenue-and-loss/",
        "tab": "revenue-and-loss",
        "nav": "Revenue and loss",
        "title": "Revenue and loss report",
        "tables": {
            "ProductionProduct": "Production product",
            "ProductionProductSubcategory": "Production product subcategory",
            "ProductionProductCategory": "Production product category",
        },
    },
    "Production": {
        "path": "/cost/",
        "tab": "cost",
        "nav": "Cost",
        "title": "Cost report",
        "tables": {
            "PurchasingPurchaseOrderHeader": "Purchasing purchase order header",
            "PurchasingPurchaseOrderDetail": "Purchasing purchase order detail",
            "PurchasingVendor": "Purchasing vendor",
            "ProductionWorkOrder": "Production work order",
            "ProductionProductCostHistory": "Production product cost history",
            "ProductionScrapReason": "Production scrap reason",
        },
    },
}

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin"

ACCOUNTS = {}
for _department in DEPARTMENTS:
    for _kind in KINDS:
        _local = f"{_department.lower()}.{_kind.lower()}"
        _email = f"{_local}@example.com"
        ACCOUNTS[_email] = {
            "email": _email,
            "password": _local,
            "label": f"Log in as {_department} {_kind}",
            "department": _department,
            "kind": _kind,
        }
ACCOUNTS[ADMIN_EMAIL] = {
    "email": ADMIN_EMAIL,
    "password": ADMIN_PASSWORD,
    "label": "Global Administrator",
    "department": "Global",
    "kind": "Administrator",
}

ROLE_CHOICES = [f"{department} {kind}" for department in DEPARTMENTS for kind in KINDS] + ["Administrator"]
