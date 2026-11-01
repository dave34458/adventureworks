"""Role matrix and demo-user command tests."""
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from accounts.roles import ROLES, TABLES, apply_roles


User = get_user_model()

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


def email_for(role):
    return f"{role.lower().replace(' ', '.')}@example.com"


def make_superuser(email="root@example.com", password="x"):
    return User.objects.create_superuser(email=email, password=password)


def expected_codenames(tabs, view, change, delete):
    codes = {f"reporting.access_{tab.replace('-', '_')}" for tab in tabs}
    for code in view | change | delete:
        app = "reporting" if code.endswith("_report") else "core"
        codes.add(f"{app}.{code}")
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
