"""Fast RBAC and access tests."""
from datetime import date
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from .models import PRIVACY_NOTICE_VERSION, PrivacyAcknowledgment, Report
from .roles import ROLES, TABLES, apply_roles
from .views import (
    PayloadValidationError,
    humanize_payload_error,
    validate_report_payload,
)

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
        "reasons": [],
        "changes": [],
        "biggest": [],
        "performance": None,
        "recommendations": [],
    }


VALID_PAYLOADS = {
    "sales": sales_payload,
    "customer-profile": customer_payload,
    "revenue-and-loss": revenue_payload,
    "cost": cost_payload,
}


def username_for(role):
    return role.lower().replace(" ", ".")


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
            user = User.objects.create_user(username_for(role), password="x")
            user.groups.add(Group.objects.get(name=role))
            cls.users[role] = user

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

    def test_administrator_has_full_access(self):
        root = User.objects.create_superuser("root", password="x")
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
        self.client.force_login(User.objects.create_superuser("cost-root", password="x"))
        response = self.client.get(f"/cost/reports/{report.pk}/edit/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="number"')
        self.assertContains(response, 'type="date"')
        self.assertContains(response, '<select name="editor-kpis-0-value_kind">')
        self.assertContains(response, '<select name="editor-biggest-0-status">')

    def test_snapshot_edit_keeps_date_only(self):
        report = self.cost_report()
        self.client.force_login(User.objects.create_superuser("cost-root", password="x"))
        response = self.client.post(
            f"/cost/reports/{report.pk}/edit/",
            self.edit_data(report, **{"editor-biggest-0-date": "2024-02-03"}),
        )
        self.assertEqual(response.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.payload["biggest"][0]["date"], "2024-02-03")


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
            user = User.objects.get(username=username_for(role))
            self.assertEqual([group.name for group in user.groups.all()], [role])

    def test_seed_keeps_administrator(self):
        admin = User.objects.create_superuser("admin", password="x")
        call_command("seed_users", stdout=StringIO())
        admin.refresh_from_db()
        self.assertTrue(admin.is_superuser)
        self.assertEqual(admin.groups.count(), 0)


class PrivacyTests(TestCase):
    def test_notice_is_public(self):
        response = self.client.get("/privacy/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"version {PRIVACY_NOTICE_VERSION}")

    def test_login_records_acknowledgment(self):
        User.objects.create_user(username="u", password="p")
        response = self.client.post(
            "/login/", {"username": "u", "password": "p", "privacy_accepted": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PrivacyAcknowledgment.objects.filter(user__username="u").exists())
