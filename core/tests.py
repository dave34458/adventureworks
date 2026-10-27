"""Fast RBAC, access, and report-semantics tests."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase, TestCase

from .models import (
    PRIVACY_NOTICE_VERSION,
    PersonAddress,
    PersonBusinessEntity,
    PersonCountryRegion,
    PersonStateProvince,
    ProductionProduct,
    ProductionProductCategory,
    ProductionProductSubcategory,
    PurchasingPurchaseOrderDetail,
    PurchasingPurchaseOrderHeader,
    PurchasingVendor,
    Report,
    SalesCustomer,
    SalesOrderDetail,
    SalesOrderHeader,
    SalesStore,
    SalesTerritory,
)
from .roles import ROLES, TABLES, apply_roles
from .services import (
    PayloadValidationError,
    humanize_payload_error,
    report_generate,
    validate_report_payload,
)
from .services.cost import cost
from .services.customer_profile import customer_profile
from .services.dashboard import dashboard
from .services.revenue_and_loss import revenue_and_loss
from .services.sales import sales
from .utils import range_window, rank, rolling_window

User = get_user_model()

ALL_TABS = ["sales", "customer-profile", "revenue-and-loss", "cost"]

DEPARTMENTS = {
    "Sales": "sales",
    "Marketing": "customer-profile",
    "Finance": "revenue-and-loss",
    "Production": "cost",
}

MATRIX = {}
for _department, _tab in DEPARTMENTS.items():
    _tables = {f"view_{name.lower()}" for name in TABLES[_tab]}
    MATRIX[f"{_department} Manager"] = (
        [_tab], _tables | {"view_report"}, {"change_report"}, {"delete_report"})
    MATRIX[f"{_department} Supervisor"] = (
        [_tab], _tables | {"view_report"}, set(), set())
    MATRIX[f"{_department} Employee"] = (
        [_tab], {"view_report"}, set(), set())


def kpi_row(label="Revenue", value=100.0, kind="money"):
    return {
        "label": label,
        "value": value,
        "value_kind": kind,
        "delta": 1.0,
        "dir": "up",
        "cap": "test",
    }


def sales_payload():
    return {
        "kpis": [kpi_row()],
        "trend": [{
            "label": "Jan",
            "full": "Jan 2024",
            "money": 100.0,
            "orders": 1,
            "height": 50,
            "prev_full": "Jan 2023",
            "prev_money": 90.0,
            "prev_orders": 1,
            "prev_h": 40,
        }],
        "products": [{"name": "Product", "value": 100.0, "pct": 100}],
        "low_products": [{"name": "Product", "value": 10.0, "pct": 10}],
    }


def customer_payload():
    return {
        "kpis": [kpi_row()],
        "growth": [],
        "channels": [],
        "countries": [],
        "bubbles": [],
        "cities": [],
        "network": [],
        "frequency": [{"name": "1 order", "value": 1, "pct": 100}],
        "biggest": [],
        "new_legend": {"n": 0, "rev": 0.0},
        "ret_legend": {"n": 0, "rev": 0.0},
    }


def revenue_payload():
    return {
        "kpis": [kpi_row()],
        "combo": {
            "bars": [],
            "cur_pts": "",
            "prev_pts": "",
            "dots": [],
            "xticks": [],
            "lticks": [],
            "rticks": [],
        },
        "donut": [],
        "donut_mid": {"big": 0.0, "small": "revenue"},
        "mix": [],
        "rev_trend": [],
        "declining": [],
        "leaks": [],
        "products": [],
    }


def cost_payload():
    return {
        "kpis": [kpi_row()],
        "pipeline": [],
        "trend": [],
        "mix": [],
        "donut": [],
        "donut_mid": {"big": 0.0, "small": "cost of goods"},
        "vendors": [],
        "products": [],
        "scrap_metric": "cost",
        "reasons": [],
        "changes": [],
        "biggest": [],
        "performance": None,
    }


VALID_PAYLOADS = {
    "sales": sales_payload,
    "customer-profile": customer_payload,
    "revenue-and-loss": revenue_payload,
    "cost": cost_payload,
}


def email_for(role):
    return f"{role.lower().replace(' ', '.')}@example.com"


def make_user(email, role="", password="x"):
    user = User.objects.create_user(email=email, password=password)
    if role:
        user.groups.set([Group.objects.get(name=role)])
    return user


def make_superuser(email="root@example.com", password="x"):
    return User.objects.create_superuser(email=email, password=password)


def expected_codenames(tabs, view, change, delete):
    codes = {f"core.access_{tab.replace('-', '_')}" for tab in tabs}
    codes |= {f"core.{code}" for code in view | change | delete}
    return codes


class RoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        apply_roles(ROLES)
        cls.groups = {group.name: group for group in Group.objects.all()}

    def test_matrix(self):
        self.assertEqual(list(ROLES), list(MATRIX))
        for role, (tabs, view, change, delete) in MATRIX.items():
            with self.subTest(role=role):
                actual = {
                    f"{permission.content_type.app_label}.{permission.codename}"
                    for permission in self.groups[role].permissions.select_related(
                        "content_type")
                }
                self.assertEqual(actual, expected_codenames(tabs, view, change, delete))

    def test_counts_and_no_administrator_group(self):
        self.assertEqual(len(MATRIX), 12)
        self.assertEqual(Group.objects.count(), 12)
        self.assertFalse(Group.objects.filter(name="Administrator").exists())

    def test_prune_removes_legacy_groups(self):
        Group.objects.create(name="Legacy")
        apply_roles(ROLES, prune=True)
        self.assertFalse(Group.objects.filter(name="Legacy").exists())
        self.assertEqual(Group.objects.count(), 12)

    def test_unknown_permission_creates_nothing(self):
        with self.assertRaisesMessage(ValueError, "Broken"):
            apply_roles({"Broken": {"tabs": ["sales"], "view": ["NoSuchReport"]}})
        self.assertFalse(Group.objects.filter(name="Broken").exists())


class HttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        apply_roles(ROLES)
        cls.users = {}
        for role in ("Sales Manager", "Sales Supervisor", "Sales Employee"):
            cls.users[role] = make_user(email_for(role), role=role)

    def test_sales_roles_see_only_the_sales_tab(self):
        for role, user in self.users.items():
            self.client.force_login(user)
            with self.subTest(role=role, page="sales"):
                self.assertEqual(self.client.get("/sales/").status_code, 200)
            with self.subTest(role=role, page="cost"):
                self.assertEqual(self.client.get("/cost/").status_code, 403)
            with self.subTest(role=role, page="dashboard"):
                self.assertEqual(self.client.get("/dashboard/").status_code, 200)

    def test_snapshot_manage_gate(self):
        self.client.force_login(self.users["Sales Manager"])
        self.assertEqual(self.client.get("/sales/reports/1/edit/").status_code, 404)
        self.client.force_login(self.users["Sales Supervisor"])
        self.assertEqual(self.client.get("/sales/reports/1/edit/").status_code, 403)
        self.assertEqual(self.client.get("/sales/reports/1/delete/").status_code, 403)

    def test_report_tab_opens_latest_snapshot_but_live_link_is_live(self):
        self.make_report(title="Older")
        latest = self.make_report(
            title="Latest", range_start=date(2024, 8, 1), range_end=date(2024, 9, 30))
        self.client.force_login(self.users["Sales Manager"])

        response = self.client.get("/sales/")
        self.assertEqual(response.context["snapshot"].pk, latest.pk)

        response = self.client.get("/sales/?report=")
        self.assertNotIn("snapshot", response.context)
        self.assertContains(response, "Live data")

        response = self.client.get("/sales/?from=2024-01-01&to=2024-06-30")
        self.assertNotIn("snapshot", response.context)

    def test_administrator_has_full_access(self):
        root = make_superuser()
        self.client.force_login(root)
        for tab in ALL_TABS:
            with self.subTest(tab=tab):
                self.assertEqual(self.client.get(f"/{tab}/").status_code, 200)
                self.assertEqual(self.client.get(f"/{tab}/reports/").status_code, 200)
        self.assertEqual(self.client.get("/manage/").status_code, 200)

    def test_table_browser_still_works_for_remaining_tables(self):
        self.client.force_login(self.users["Sales Manager"])
        self.assertEqual(self.client.get("/sales/data/SalesOrderHeader/").status_code, 200)
        self.assertEqual(
            self.client.get("/sales/data/SalesOrderHeader/1/edit/").status_code, 403)

    def make_report(self, **overrides):
        values = {
            "module": "sales",
            "title": "Sales snapshot",
            "range_start": date(2024, 1, 1),
            "range_end": date(2024, 6, 30),
            "compare_start": date(2023, 1, 1),
            "compare_end": date(2023, 12, 31),
            "source_through": date(2024, 12, 31),
            "window_label": "Jan-Jun 2024",
            "prev_label": "Jan-Dec 2023",
            "period": "the selected range",
            "payload": sales_payload(),
        }
        values.update(overrides)
        return Report.objects.create(**values)

    def edit_data(self, report, **overrides):
        values = {
            "title": report.title,
            "range_start": report.range_start.isoformat(),
            "range_end": report.range_end.isoformat(),
            "compare_start": report.compare_start.isoformat() if report.compare_start else "",
            "compare_end": report.compare_end.isoformat() if report.compare_end else "",
            "source_through": report.source_through.isoformat(),
            "window_label": report.window_label,
            "prev_label": report.prev_label,
            "period": report.period,
            "custom": "on" if report.custom else "",
        }
        values.update(overrides)
        return values

    def test_snapshot_edit_updates_metadata_and_payload(self):
        report = self.make_report()
        self.client.force_login(self.users["Sales Manager"])
        response = self.client.post(
            f"/sales/reports/{report.pk}/edit/",
            self.edit_data(
                report,
                title="Updated snapshot",
                range_start="2024-02-01",
                range_end="2024-07-31",
                compare_start="2023-02-01",
                compare_end="2024-01-31",
                window_label="Feb-Jul 2024",
                prev_label="Feb 2023-Jan 2024",
                custom="on",
                **{"editor-products-0-pct": "55"},
            ),
        )
        self.assertEqual(response.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.title, "Updated snapshot")
        self.assertEqual(report.range_start, date(2024, 2, 1))
        self.assertEqual(report.range_end, date(2024, 7, 31))
        self.assertEqual(report.payload["products"][0]["pct"], 55)

    def test_snapshot_edit_rejects_invalid_range(self):
        report = self.make_report()
        self.client.force_login(self.users["Sales Manager"])
        response = self.client.post(
            f"/sales/reports/{report.pk}/edit/",
            self.edit_data(report, range_start="2024-07-01", range_end="2024-01-01"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "End date must be on or after the start date.")
        report.refresh_from_db()
        self.assertEqual(report.range_start, date(2024, 1, 1))

    def test_snapshot_edit_rejects_blank_label(self):
        report = self.make_report()
        self.client.force_login(self.users["Sales Manager"])
        response = self.client.post(
            f"/sales/reports/{report.pk}/edit/",
            self.edit_data(report, title="   "),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        report.refresh_from_db()
        self.assertEqual(report.title, "Sales snapshot")

    def test_snapshot_edit_rejects_comparison_after_range_start(self):
        report = self.make_report()
        self.client.force_login(self.users["Sales Manager"])
        response = self.client.post(
            f"/sales/reports/{report.pk}/edit/",
            self.edit_data(report, compare_end="2024-02-01"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Comparison end must be before the report start.")
        report.refresh_from_db()
        self.assertEqual(report.compare_end, date(2023, 12, 31))

    def test_snapshot_edit_rejects_duplicate_range(self):
        report = self.make_report()
        self.make_report(
            range_start=date(2024, 8, 1), range_end=date(2024, 9, 30),
            source_through=date(2024, 12, 31),
        )
        self.client.force_login(self.users["Sales Manager"])
        response = self.client.post(
            f"/sales/reports/{report.pk}/edit/",
            self.edit_data(report, range_start="2024-08-01", range_end="2024-09-30"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A saved report already exists for this range.")

    def test_snapshot_edit_rejects_invalid_payload_number(self):
        report = self.make_report()
        self.client.force_login(self.users["Sales Manager"])
        response = self.client.post(
            f"/sales/reports/{report.pk}/edit/",
            self.edit_data(report, **{"editor-products-0-pct": "not a number"}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Product rows, row 1, Percent: must be a number.")
        report.refresh_from_db()
        self.assertEqual(report.payload["products"][0]["pct"], 100)

    def test_snapshot_edit_rejects_percentage_over_100(self):
        report = self.make_report()
        self.client.force_login(self.users["Sales Manager"])
        response = self.client.post(
            f"/sales/reports/{report.pk}/edit/",
            self.edit_data(report, **{"editor-products-0-pct": "900"}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Product rows, row 1, Percent: must be at most 100")
        report.refresh_from_db()
        self.assertEqual(report.payload["products"][0]["pct"], 100)

    def cost_report(self):
        payload = cost_payload()
        payload["biggest"] = [{
            "id": 1,
            "vendor": "Vendor",
            "date": "2024-01-01",
            "lines": 1,
            "total": 1.0,
            "status": "Approved",
            "cls": "online",
        }]
        return self.make_report(module="cost", payload=payload)

    def test_snapshot_editor_uses_numeric_and_date_inputs(self):
        report = self.cost_report()
        self.client.force_login(make_superuser("cost-root@example.com"))
        response = self.client.get(f"/cost/reports/{report.pk}/edit/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="number"')
        self.assertContains(response, 'type="date"')
        self.assertContains(response, '<select name="editor-kpis-0-value_kind">')
        self.assertContains(response, '<select name="editor-biggest-0-status">')

    def test_snapshot_edit_keeps_date_only(self):
        report = self.cost_report()
        self.client.force_login(make_superuser("cost-root@example.com"))
        response = self.client.post(
            f"/cost/reports/{report.pk}/edit/",
            self.edit_data(report, **{"editor-biggest-0-date": "2024-02-03"}),
        )
        self.assertEqual(response.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.payload["biggest"][0]["date"], "2024-02-03")


class ReportDataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        apply_roles(ROLES)
        us = PersonCountryRegion.objects.create(country_region_code="US", name="United States")
        canada = PersonCountryRegion.objects.create(country_region_code="CA", name="Canada")
        west = SalesTerritory.objects.create(name="Northwest", country_region=us, group="North America")
        canada_west = SalesTerritory.objects.create(
            name="Canada West", country_region=canada, group="North America")
        wa = PersonStateProvince.objects.create(
            state_province_code="WA", country_region=us, name="Washington", territory=west)
        bc = PersonStateProvince.objects.create(
            state_province_code="BC", country_region=canada, name="British Columbia",
            territory=canada_west)
        addr_wa = PersonAddress.objects.create(
            address_line1="1 Main", city="Springfield", state_province=wa, postal_code="11111")
        addr_bc = PersonAddress.objects.create(
            address_line1="2 Main", city="Springfield", state_province=bc, postal_code="22222")

        category = ProductionProductCategory.objects.create(name="Bikes")
        subcategory = ProductionProductSubcategory.objects.create(
            product_category=category, name="Road Bikes")
        product = ProductionProduct.objects.create(
            name="Test Bike", product_number="TB-1", safety_stock_level=1, reorder_point=1,
            standard_cost=Decimal(50), list_price=Decimal(100), days_to_manufacture=1,
            product_subcategory=subcategory, sell_start_date=datetime(2022, 1, 1),
        )

        active_store = SalesStore.objects.create(
            business_entity=PersonBusinessEntity.objects.create(), name="Active Store",
            demographics=("<BusinessType>BS</BusinessType><SquareFeet>1000</SquareFeet>"
                          "<NumberEmployees>10</NumberEmployees>"))
        SalesStore.objects.create(
            business_entity=PersonBusinessEntity.objects.create(), name="Inactive Store",
            demographics=("<BusinessType>BS</BusinessType><SquareFeet>2000</SquareFeet>"
                          "<NumberEmployees>20</NumberEmployees>"))
        SalesStore.objects.create(
            business_entity=PersonBusinessEntity.objects.create(), name="Specialty Store",
            demographics=("<BusinessType>OS</BusinessType><SquareFeet>3000</SquareFeet>"
                          "<NumberEmployees>30</NumberEmployees>"))
        customer = SalesCustomer.objects.create(
            store=active_store, territory=west, account_number="AW00000001")

        orders = (
            (date(2023, 12, 1), addr_wa, "SO0", 100),
            (date(2024, 5, 15), addr_wa, "SO1", 10),
            (date(2024, 11, 20), addr_wa, "SO2", 100),
            (date(2024, 12, 10), addr_bc, "SO3", 100),
            (date(2025, 1, 5), addr_wa, "SO4", 100),
            (date(2025, 1, 20), addr_wa, "SO5", 10),
            (date(2025, 2, 10), addr_bc, "SO6", 100),
            (date(2025, 3, 5), addr_wa, "SO7", 100),
        )
        for order_date, address, number, price in orders:
            header = SalesOrderHeader.objects.create(
                order_date=datetime.combine(order_date, datetime.min.time()),
                due_date=datetime.combine(order_date + timedelta(days=5), datetime.min.time()),
                customer=customer,
                bill_to_address=address,
                ship_to_address=address,
                sales_order_number=number,
            )
            SalesOrderDetail.objects.create(
                sales_order=header, order_qty=1, product=product, unit_price=Decimal(price))

        vendor = PurchasingVendor.objects.create(
            business_entity=PersonBusinessEntity.objects.create(),
            account_number="VEN1", name="Vendor One", credit_rating=1,
        )
        cls.po_ok = PurchasingPurchaseOrderHeader.objects.create(
            vendor=vendor, order_date=datetime(2025, 2, 1), sub_total=Decimal(100),
            tax_amt=Decimal(10), freight=Decimal(5), status=2,
        )
        PurchasingPurchaseOrderDetail.objects.create(
            purchase_order=cls.po_ok, due_date=datetime(2025, 2, 10), order_qty=1,
            product=product, unit_price=Decimal(100), received_qty=Decimal(1),
            rejected_qty=Decimal(0),
        )
        cls.po_rejected = PurchasingPurchaseOrderHeader.objects.create(
            vendor=vendor, order_date=datetime(2025, 2, 2), sub_total=Decimal(1000),
            tax_amt=Decimal(100), freight=Decimal(50), status=3,
        )
        cls.po_future = PurchasingPurchaseOrderHeader.objects.create(
            vendor=vendor, order_date=datetime(2025, 7, 15), sub_total=Decimal(500),
            tax_amt=Decimal(50), freight=Decimal(25), status=2,
        )

        cls.root = make_superuser("report-root@example.com")
        cls.cost_user = make_user("report-cost@example.com", role="Production Manager")

    def report_context(self, service, **params):
        request = RequestFactory().get("/", {"report": "", **params})
        request.user = self.root
        return service(request).context

    def test_custom_cost_range_after_sales_max_includes_purchase_orders(self):
        context = self.report_context(
            cost, **{"from": "2025-07-01", "to": "2025-09-30"})
        self.assertIsNone(context.get("empty_message"))
        self.assertIn("Sep 30, 2025", context["window_label"])
        self.assertEqual([row["id"] for row in context["biggest"]], [self.po_future.pk])
        self.assertAlmostEqual(context["biggest"][0]["total"], 500.0)

    def test_cost_biggest_uses_merchandise_and_excludes_rejected(self):
        context = self.report_context(cost)
        ids = [row["id"] for row in context["biggest"]]
        self.assertIn(self.po_ok.pk, ids)
        self.assertNotIn(self.po_rejected.pk, ids)
        row = next(row for row in context["biggest"] if row["id"] == self.po_ok.pk)
        self.assertAlmostEqual(row["total"], 100.0)
        cost_kpi = next(
            kpi for kpi in context["kpis"] if kpi["label"] == "Cost of goods sold")
        self.assertEqual(cost_kpi["dir"], "down")

    def test_city_grouping_keeps_same_name_cities_separate(self):
        context = self.report_context(customer_profile)
        names = [row["name"] for row in context["cities"]]
        self.assertIn("Springfield, WA", names)
        self.assertIn("Springfield, BC", names)

    def test_store_network_counts_only_stores_with_sales(self):
        context = self.report_context(customer_profile)
        bike_shops = next(row for row in context["network"] if row["name"] == "Bike shops")
        self.assertIn("1 of 2 stores had sales", bike_shops["note"])
        specialty = next(
            row for row in context["network"] if row["name"] == "Other specialty stores")
        self.assertEqual(specialty["note"], "0 of 1 stores had sales in the period")

    def test_partial_month_combo_keeps_first_month(self):
        context = self.report_context(
            revenue_and_loss, **{"from": "2025-01-16", "to": "2025-03-15"})
        self.assertEqual([tick["lab"] for tick in context["combo"]["xticks"]],
                         ["Jan", "Feb", "Mar"])
        self.assertEqual(len(context["combo"]["bars"]), 3)

    def test_margin_chart_compares_selected_and_previous_like_dashboard(self):
        context = self.report_context(
            revenue_and_loss, **{"from": "2025-01-01", "to": "2025-09-30"})
        combo = context["combo"]
        self.assertEqual(len(combo["xticks"]), 9)
        self.assertEqual(len(combo["cur_pts"].split()), 3)
        self.assertEqual(len(combo["prev_pts"].split()), 3)
        self.assertEqual({dot["cls"] for dot in combo["dots"]}, {"dotc", "dotp"})
        self.assertTrue(any(tick["lab"].startswith("-") for tick in combo["rticks"]))
        self.assertIn("May 2024",
                      next(dot["t"] for dot in combo["dots"] if dot["cls"] == "dotp"))

    def test_empty_months_are_zero_filled(self):
        sales_context = self.report_context(sales)
        self.assertEqual(len(sales_context["trend"]), 12)
        sales_by_full = {row["full"]: row for row in sales_context["trend"]}
        self.assertEqual(sales_by_full["Apr 2024"]["money"], 0.0)
        self.assertEqual(sales_by_full["Apr 2024"]["height"], 0)
        self.assertEqual(sales_by_full["Jun 2024"]["orders"], 0)

        cost_context = self.report_context(cost)
        self.assertEqual(len(cost_context["trend"]), 12)
        cost_by_full = {row["full"]: row for row in cost_context["trend"]}
        self.assertEqual(cost_by_full["Apr 2024"]["money"], 0.0)
        self.assertEqual(cost_by_full["Apr 2024"]["height"], 0)

        rl_context = self.report_context(revenue_and_loss)
        self.assertEqual(len(rl_context["rev_trend"]), 12)
        rl_by_full = {row["full"]: row for row in rl_context["rev_trend"]}
        self.assertEqual(rl_by_full["Apr 2024"]["money"], 0.0)
        self.assertEqual(rl_by_full["Apr 2024"]["height"], 0)
        self.assertEqual(len(rl_context["combo"]["bars"]), 12)
        self.assertEqual(len(rl_context["combo"]["xticks"]), 12)

        request = RequestFactory().get("/", {"report": ""})
        request.user = self.root
        dashboard_context = dashboard(request).context
        self.assertEqual(len(dashboard_context["trend"]), 12)
        dashboard_by_full = {row["full"]: row for row in dashboard_context["trend"]}
        self.assertEqual(dashboard_by_full["Apr 2024"]["height"], 0)

        customer_context = self.report_context(customer_profile)
        self.assertEqual(len(customer_context["growth"]), 12)
        customer_by_full = {row["full"]: row for row in customer_context["growth"]}
        self.assertEqual(customer_by_full["Apr 2024"]["act"], 0)
        self.assertEqual(customer_by_full["Apr 2024"]["new_h"], 0)

    def test_margin_points_skip_months_without_revenue(self):
        context = self.report_context(
            revenue_and_loss, **{"from": "2025-01-01", "to": "2025-09-30"})
        self.assertEqual(len(context["combo"]["bars"]), 9)
        self.assertEqual(len(context["combo"]["cur_pts"].split()), 3)
        current_dots = [d for d in context["combo"]["dots"] if d["cls"] == "dotc"]
        self.assertEqual(len(current_dots), 3)
        self.assertEqual(len(context["combo"]["xticks"]), 9)

        request = RequestFactory().get(
            "/", {"report": "", "from": "2025-01-01", "to": "2025-09-30"})
        request.user = self.root
        chart = dashboard(request).context["margin_chart"]
        self.assertEqual(len(chart["cur_pts"].split()), 3)
        self.assertEqual(len(chart["dots"]), 3)

    def test_negative_profit_bars_have_a_negative_axis(self):
        context = self.report_context(revenue_and_loss)
        labels = [tick["lab"] for tick in context["combo"]["lticks"]]
        self.assertTrue(any(label.startswith("-") for label in labels))
        self.assertTrue(any("-$40" in bar["t"] for bar in context["combo"]["bars"]))

    def test_cost_only_dashboard_uses_cost_direction(self):
        request = RequestFactory().get("/", {"report": ""})
        request.user = self.cost_user
        context = dashboard(request).context
        cost_kpi = next(kpi for kpi in context["kpis"] if kpi["label"] == "Cost of goods")
        self.assertEqual(cost_kpi["dir"], "down")

    def test_invalid_range_gets_an_empty_message(self):
        context = self.report_context(
            cost, **{"from": "2025-07-01", "to": "2025-06-30"})
        self.assertEqual(context["empty_message"],
                         "No data is available for the selected range.")
        self.assertFalse(context["has_data"])

    def test_valid_empty_ranges_show_empty_message(self):
        for service in (sales, revenue_and_loss, customer_profile):
            with self.subTest(service=service.__name__):
                context = self.report_context(
                    service, **{"from": "2025-07-01", "to": "2025-09-30"})
                self.assertEqual(context["empty_message"],
                                 "No data is available for the selected range.")
                self.assertFalse(context["has_data"])

    def test_valid_empty_cost_range_shows_empty_message(self):
        context = self.report_context(
            cost, **{"from": "2025-10-01", "to": "2025-12-31"})
        self.assertEqual(context["empty_message"],
                         "No data is available for the selected range.")
        self.assertFalse(context["has_data"])

    def test_valid_empty_dashboard_range_uses_the_empty_message(self):
        self.client.force_login(self.root)
        response = self.client.get(
            "/dashboard/", {"report": "", "from": "2025-07-01", "to": "2025-09-30"})
        self.assertContains(response, "No data is available for this report.")
        self.assertNotContains(response, "No sales data is available in the database.")

    def test_dashboard_invalid_range_uses_the_empty_message(self):
        self.client.force_login(self.root)
        response = self.client.get(
            "/dashboard/", {"report": "", "from": "2025-07-01", "to": "2025-06-30"})
        self.assertContains(response, "No data is available for this report.")
        self.assertNotContains(response, "No sales data is available in the database.")

    def test_high_value_panel_is_labeled_as_segmented(self):
        self.client.force_login(self.root)
        response = self.client.get("/customer-profile/?report=")
        self.assertContains(response, "Top customers by segment")
        self.assertContains(response, "Top 6 stores and top 3 individuals by revenue")

    def test_cost_biggest_panel_labels_merchandise(self):
        self.client.force_login(self.root)
        response = self.client.get("/cost/?report=")
        self.assertContains(response, "Merchandise")
        self.assertContains(response, "Largest non-rejected purchase orders by merchandise value")

    def test_r_and_l_cost_direction_and_below_cost_label(self):
        context = self.report_context(revenue_and_loss)
        cost_kpi = next(kpi for kpi in context["kpis"] if kpi["label"] == "Cost of goods")
        self.assertEqual(cost_kpi["dir"], "down")
        labels = [kpi["label"] for kpi in context["kpis"]]
        self.assertIn("Below-cost shortfall", labels)
        self.assertNotIn("Below-cost sales", labels)
        self.client.force_login(self.root)
        response = self.client.get("/revenue-and-loss/?report=")
        self.assertContains(response, "Below-cost shortfall")
        self.assertNotContains(response, "Below-cost sales")

    def test_negative_margin_lines_fit_the_chart(self):
        context = self.report_context(revenue_and_loss)
        ys = [float(point.split(",")[1]) for point in context["combo"]["cur_pts"].split()]
        self.assertTrue(all(0 <= y <= 260 for y in ys))
        self.assertTrue(any(tick["lab"].startswith("-") for tick in context["combo"]["rticks"]))

        request = RequestFactory().get("/", {"report": ""})
        request.user = self.root
        chart = dashboard(request).context["margin_chart"]
        ys = [float(point.split(",")[1]) for point in chart["cur_pts"].split()]
        self.assertTrue(all(0 <= y <= 260 for y in ys))
        self.assertTrue(any(tick["label"].startswith("-") for tick in chart["ticks"]))

    def test_margin_comparison_handles_missing_previous_revenue(self):
        rl_context = self.report_context(
            revenue_and_loss, **{"from": "2024-05-01", "to": "2024-05-31"})
        cap = next(kpi for kpi in rl_context["kpis"]
                   if kpi["label"] == "Gross profit")["cap"]
        self.assertIn("no revenue in", cap)
        self.assertNotIn("was 0%", cap)

        request = RequestFactory().get(
            "/", {"report": "", "from": "2024-05-01", "to": "2024-05-31"})
        request.user = self.root
        context = dashboard(request).context
        cap = next(kpi for kpi in context["kpis"] if kpi["label"] == "Gross profit")["cap"]
        self.assertIn("no revenue in", cap)

    def test_margin_comparison_handles_missing_current_revenue(self):
        source = SalesOrderHeader.objects.get(sales_order_number="SO1")
        header = SalesOrderHeader.objects.create(
            order_date=datetime(2024, 6, 15),
            due_date=datetime(2024, 6, 20),
            customer=source.customer,
            bill_to_address=source.bill_to_address,
            ship_to_address=source.ship_to_address,
            sales_order_number="SOZ",
        )
        SalesOrderDetail.objects.create(
            sales_order=header, order_qty=1,
            product=ProductionProduct.objects.get(name="Test Bike"),
            unit_price=Decimal(0),
        )

        rl_context = self.report_context(
            revenue_and_loss, **{"from": "2024-06-01", "to": "2024-06-30"})
        cap = next(kpi for kpi in rl_context["kpis"]
                   if kpi["label"] == "Gross profit")["cap"]
        self.assertIn("no revenue in", cap)
        self.assertIn("margin not meaningful", cap)

        request = RequestFactory().get(
            "/", {"report": "", "from": "2024-06-01", "to": "2024-06-30"})
        request.user = self.root
        context = dashboard(request).context
        cap = next(kpi for kpi in context["kpis"] if kpi["label"] == "Gross profit")["cap"]
        self.assertIn("no revenue in", cap)

    def test_custom_range_labels_name_the_actual_previous_period(self):
        cost_context = self.report_context(
            cost, **{"from": "2025-01-01", "to": "2025-03-31"})
        cap = next(kpi for kpi in cost_context["kpis"]
                   if kpi["label"] == "Cost per $1 revenue")["cap"]
        self.assertIn(cost_context["prev_label"], cap)
        self.assertNotIn("last year", cap.lower())
        self.assertIn(cost_context["prev_label"], cost_context["performance"]["note"])

        customer_context = self.report_context(
            customer_profile, **{"from": "2025-01-01", "to": "2025-03-31"})
        cap = next(kpi for kpi in customer_context["kpis"]
                   if kpi["label"] == "Retention")["cap"]
        self.assertIn(customer_context["prev_label"], cap)
        self.assertNotIn("last-year", cap.lower())

    def test_default_window_ends_at_month_end(self):
        window = rolling_window(SalesOrderHeader)
        self.assertEqual(window.last.date(), date(2025, 3, 31))
        self.assertEqual(window.trend_start.date(), date(2024, 4, 1))
        self.assertEqual(window.window_start.date(), date(2023, 4, 1))

    def test_custom_range_previous_period_uses_complete_days(self):
        january = range_window(
            SalesOrderHeader, date(2025, 1, 1), date(2025, 1, 31))
        self.assertEqual(january.window_start.date(), date(2024, 12, 1))
        self.assertEqual(january.prev_label, "Dec 01, 2024 \u2013 Dec 31, 2024")

        quarter = range_window(
            SalesOrderHeader, date(2025, 1, 1), date(2025, 3, 31))
        self.assertEqual(quarter.window_start.date(), date(2024, 10, 3))
        self.assertEqual(quarter.prev_label, "Oct 03, 2024 \u2013 Dec 31, 2024")

    def test_generated_reports_accept_inverted_cost_direction(self):
        for module in ("revenue-and-loss", "cost"):
            with self.subTest(module=module):
                request = RequestFactory().post(
                    f"/{module}/report/generate/",
                    {"from": "2024-07-01", "to": "2025-06-29"},
                )
                request.user = self.root
                report_generate(request, module)
                self.assertIsNotNone(request._captured_snapshot)

    def test_custom_snapshot_compare_start_matches_previous_label(self):
        request = RequestFactory().post(
            "/sales/report/generate/",
            {"from": "2025-01-01", "to": "2025-01-31"},
        )
        request.user = self.root
        report_generate(request, "sales")
        snapshot = request._captured_snapshot
        self.assertEqual(snapshot.compare_start, date(2024, 12, 1))
        self.assertEqual(snapshot.compare_end, date(2024, 12, 31))
        self.assertEqual(snapshot.prev_label, "Dec 01, 2024 \u2013 Dec 31, 2024")

    def test_previous_series_align_by_month_not_position(self):
        sales_context = self.report_context(sales)
        by_full = {row["full"]: row for row in sales_context["trend"]}
        self.assertEqual(by_full["May 2024"]["prev_full"], "")
        self.assertEqual(by_full["Dec 2024"]["prev_full"], "Dec 2023")

        rl_context = self.report_context(revenue_and_loss)
        by_full = {row["full"]: row for row in rl_context["rev_trend"]}
        self.assertEqual(by_full["May 2024"]["prev_full"], "")
        self.assertEqual(by_full["Dec 2024"]["prev_full"], "Dec 2023")

        cost_context = self.report_context(cost)
        by_full = {row["full"]: row for row in cost_context["trend"]}
        self.assertEqual(by_full["May 2024"]["prev_full"], "")
        self.assertEqual(by_full["Dec 2024"]["prev_full"], "Dec 2023")

        request = RequestFactory().get("/", {"report": ""})
        request.user = self.root
        dashboard_context = dashboard(request).context
        by_full = {row["full"]: row for row in dashboard_context["trend"]}
        self.assertNotIn("previous", by_full["May 2024"]["title"])
        self.assertIn("previous Dec 2023", by_full["Dec 2024"]["title"])


class UtilsTests(SimpleTestCase):
    def test_rank_zero_value_has_no_bar(self):
        rows = rank([{"name": "zero", "value": 0},
                     {"name": "ten", "value": 10}], "name", "value")
        self.assertEqual(rows[0]["pct"], 0)
        self.assertEqual(rows[1]["pct"], 100)


class PayloadValidationTests(SimpleTestCase):
    def test_valid_payloads(self):
        for module, factory in VALID_PAYLOADS.items():
            with self.subTest(module=module):
                validate_report_payload(module, factory())

    def test_rejects_non_object(self):
        with self.assertRaisesMessage(PayloadValidationError, "payload: must be an object"):
            validate_report_payload("sales", [])

    def test_rejects_unknown_key(self):
        payload = sales_payload()
        payload["extra"] = 1
        with self.assertRaisesMessage(PayloadValidationError, "unexpected key"):
            validate_report_payload("sales", payload)

    def test_rejects_percentage_over_100(self):
        payload = sales_payload()
        payload["products"][0]["pct"] = 900
        with self.assertRaisesMessage(PayloadValidationError, "must be at most 100"):
            validate_report_payload("sales", payload)

    def test_rejects_non_finite_number(self):
        payload = sales_payload()
        payload["products"][0]["pct"] = float("nan")
        with self.assertRaisesMessage(PayloadValidationError, "must be finite"):
            validate_report_payload("sales", payload)

    def test_rejects_mix_not_100(self):
        payload = revenue_payload()
        payload["mix"] = [{
            "name": "Bikes",
            "cls": "c1",
            "pct": 90,
            "money": 90.0,
            "margin": 10,
        }]
        with self.assertRaisesMessage(PayloadValidationError, "pct values must add up to 100"):
            validate_report_payload("revenue-and-loss", payload)

    def test_rejects_donut_not_100(self):
        payload = revenue_payload()
        payload["donut"] = [{
            "cls": "c1",
            "pct": 90,
            "t": "Bikes",
            "dash": 300,
            "off": 0,
        }]
        with self.assertRaisesMessage(PayloadValidationError, "pct values must add up to 100"):
            validate_report_payload("revenue-and-loss", payload)

    def test_rejects_channel_shares_not_100(self):
        payload = customer_payload()
        payload["channels"] = [{
            "name": "Individuals",
            "pct": 100,
            "cust_pct": 90,
            "cls": "online",
            "money": 100.0,
            "customers": 1,
            "aov": 100.0,
        }]
        with self.assertRaisesMessage(PayloadValidationError, "cust_pct values must add up to 100"):
            validate_report_payload("customer-profile", payload)

    def test_accepts_performance_values_summing_to_100(self):
        payload = cost_payload()
        payload["performance"] = {
            "cost": 80.0,
            "margin": 20.0,
            "note": "test",
        }
        validate_report_payload("cost", payload)

    def test_rejects_performance_values_not_100(self):
        payload = cost_payload()
        payload["performance"] = {
            "cost": 80.0,
            "margin": 10.0,
            "note": "test",
        }
        with self.assertRaisesMessage(
                PayloadValidationError, "cost and margin must add up to 100"):
            validate_report_payload("cost", payload)

    def test_humanizes_payload_path(self):
        message = "payload.mix[0].pct: must be at least 0"
        self.assertEqual(
            humanize_payload_error(message),
            "Category mix, row 1, Percent: must be at least 0",
        )

    def test_rejects_formatted_percentage_string(self):
        payload = revenue_payload()
        payload["products"] = [{
            "id": 1,
            "name": "Product",
            "rev": 100.0,
            "cost": 90.0,
            "profit": 10.0,
            "margin": "900%",
        }]
        with self.assertRaisesMessage(PayloadValidationError, "must be a number"):
            validate_report_payload("revenue-and-loss", payload)

    def test_rejects_formatted_money_string(self):
        payload = sales_payload()
        payload["products"][0]["value"] = "$100"
        with self.assertRaisesMessage(PayloadValidationError, "must be a number"):
            validate_report_payload("sales", payload)

    def test_rejects_bad_class(self):
        payload = customer_payload()
        payload["channels"] = [{
            "name": "Individuals",
            "pct": 100,
            "cust_pct": 100,
            "cls": "bad",
            "money": 100.0,
            "customers": 1,
            "aov": 100.0,
        }]
        with self.assertRaisesMessage(PayloadValidationError, "must be one of"):
            validate_report_payload("customer-profile", payload)

    def test_rejects_bad_date(self):
        payload = cost_payload()
        payload["biggest"] = [{
            "id": 1,
            "vendor": "Vendor",
            "date": "not-a-date",
            "lines": 1,
            "total": 1.0,
            "status": "Approved",
            "cls": "",
        }]
        with self.assertRaisesMessage(PayloadValidationError, "must be an ISO date"):
            validate_report_payload("cost", payload)

    def test_rejects_datetime_date(self):
        payload = cost_payload()
        payload["biggest"] = [{
            "id": 1,
            "vendor": "Vendor",
            "date": "2025-06-23T00:00:00",
            "lines": 1,
            "total": 1.0,
            "status": "Approved",
            "cls": "",
        }]
        with self.assertRaisesMessage(PayloadValidationError, "must be an ISO date"):
            validate_report_payload("cost", payload)

    def test_rejects_negative_cost_kpi(self):
        payload = cost_payload()
        payload["kpis"][0]["label"] = "Cost of goods sold"
        payload["kpis"][0]["value"] = -1
        with self.assertRaisesMessage(PayloadValidationError, "must be at least 0"):
            validate_report_payload("cost", payload)

    def test_allows_negative_gross_profit(self):
        payload = revenue_payload()
        payload["kpis"][0]["label"] = "Gross profit"
        payload["kpis"][0]["value"] = -1
        validate_report_payload("revenue-and-loss", payload)

    def test_rejects_negative_mix_money(self):
        payload = revenue_payload()
        payload["mix"] = [{
            "name": "Bikes",
            "cls": "c1",
            "pct": 100,
            "money": -1,
            "margin": 10,
        }]
        with self.assertRaisesMessage(PayloadValidationError, "must be at least 0"):
            validate_report_payload("revenue-and-loss", payload)


class SeedUsersTests(TestCase):
    def test_seed_creates_one_user_per_role(self):
        call_command("seed_users", stdout=StringIO())
        self.assertEqual(User.objects.count(), 12)
        self.assertFalse(User.objects.filter(is_superuser=True).exists())
        for role in MATRIX:
            user = User.objects.get(email=email_for(role))
            self.assertEqual(
                list(user.groups.values_list("name", flat=True)), [role])

    def test_seed_keeps_administrator(self):
        admin = make_superuser("admin@example.com")
        call_command("seed_users", stdout=StringIO())
        admin.refresh_from_db()
        self.assertTrue(admin.is_superuser)
        self.assertFalse(admin.groups.exists())


class PrivacyTests(TestCase):
    def test_notice_is_public(self):
        response = self.client.get("/privacy/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"version {PRIVACY_NOTICE_VERSION}")

    def test_login_works_without_acknowledgment(self):
        make_user("u@example.com", password="p")
        response = self.client.post(
            "/login/", {"username": "u@example.com", "password": "p"})
        self.assertEqual(response.status_code, 302)
