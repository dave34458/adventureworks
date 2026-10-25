"""Fast RBAC and access tests."""
from datetime import date
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase

from .models import PRIVACY_NOTICE_VERSION, PrivacyAcknowledgment, Report
from .roles import ROLES, TABLES, apply_roles

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
            "payload": {"kpis": [{"label": "Revenue", "value": "100", "score": 5}]},
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
                **{"editor-kpis-0-score": "7"},
            ),
        )
        self.assertEqual(response.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.title, "Updated snapshot")
        self.assertEqual(report.range_start, date(2024, 2, 1))
        self.assertEqual(report.range_end, date(2024, 7, 31))
        self.assertEqual(report.payload["kpis"][0]["score"], 7)

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
            self.edit_data(report, **{"editor-kpis-0-score": "not a number"}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Score must be a whole number.")
        report.refresh_from_db()
        self.assertEqual(report.payload["kpis"][0]["score"], 5)


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
