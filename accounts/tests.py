"""Role matrix and demo-user command tests."""
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.roles import ROLES, TABLES, apply_roles
from reporting.models import AuditLog


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
    MATRIX[f"{_department} Admin"] = (
        [_tab], _tables | {"view_report"}, {"change_report"}, {"delete_report"})


def email_for(role):
    return f"{role.lower().replace(' ', '.')}@example.com"


def make_superuser(email="root@example.com", password="x"):
    return User.objects.create_superuser(email=email, password=password)


def expected_codenames(tabs, view, change, delete, manage_users=False):
    codes = {f"reporting.access_{tab.replace('-', '_')}" for tab in tabs}
    for code in view | change | delete:
        app = "reporting" if code.endswith("_report") else "core"
        codes.add(f"{app}.{code}")
    if manage_users:
        codes.add("reporting.manage_department_users")
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
                self.assertEqual(actual, expected_codenames(
                    tabs, view, change, delete, role.endswith(" Admin")))

    def test_counts_and_no_administrator_group(self):
        self.assertEqual(len(MATRIX), 16)
        self.assertEqual(Group.objects.count(), 16)
        self.assertFalse(Group.objects.filter(name="Administrator").exists())

    def test_prune_removes_legacy_groups(self):
        Group.objects.create(name="Legacy")
        apply_roles(ROLES, prune=True)
        self.assertFalse(Group.objects.filter(name="Legacy").exists())
        self.assertEqual(Group.objects.count(), 16)

    def test_unknown_permission_creates_nothing(self):
        with self.assertRaisesMessage(ValueError, "Broken"):
            apply_roles({"Broken": {"tabs": ["sales"], "view": ["NoSuchReport"]}})
        self.assertFalse(Group.objects.filter(name="Broken").exists())


class LoginViewTests(TestCase):
    def test_authenticated_user_is_redirected_from_login(self):
        user = User.objects.create_user(email="u@example.com", password="p")
        self.client.force_login(user)
        response = self.client.get(reverse("login"))
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)


class SeedUsersTests(TestCase):
    def test_seed_creates_one_user_per_role(self):
        call_command("seed_users", stdout=StringIO())
        self.assertEqual(User.objects.count(), 16)
        self.assertFalse(User.objects.filter(is_superuser=True).exists())
        for role in MATRIX:
            user = User.objects.get(email=email_for(role))
            self.assertEqual(
                list(user.groups.values_list("name", flat=True)), [role])


class DepartmentUserTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        apply_roles(ROLES)
        cls.sales_admin = User.objects.create_user("sales.admin@test.com", "secretpass1")
        cls.sales_admin.groups.set([Group.objects.get(name="Sales Admin")])
        cls.sales_user = User.objects.create_user("sales.user@test.com", "secretpass1")
        cls.sales_user.groups.set([Group.objects.get(name="Sales Employee")])
        cls.marketing_user = User.objects.create_user("marketing.user@test.com", "secretpass1")
        cls.marketing_user.groups.set([Group.objects.get(name="Marketing Employee")])
        cls.marketing_admin = User.objects.create_user("marketing.admin@test.com", "secretpass1")
        cls.marketing_admin.groups.set([Group.objects.get(name="Marketing Admin")])
        cls.root = make_superuser()

    def test_department_admin_user_crud_is_scoped(self):
        self.client.force_login(self.sales_admin)
        self.assertEqual(self.client.get(reverse("department_users")).status_code, 200)
        response = self.client.get(reverse("department_users"))
        self.assertContains(response, self.sales_user.email)
        self.assertNotContains(response, self.marketing_user.email)
        self.assertNotContains(response, self.marketing_admin.email)
        self.assertEqual(self.client.get(reverse(
            "department_user_edit", args=[self.marketing_user.pk])).status_code, 404)

    def test_create_role_is_limited_to_department_non_admin_roles(self):
        self.client.force_login(self.sales_admin)
        url = reverse("department_user_add")
        data = {"email": "new.user@test.com", "first_name": "New", "last_name": "User",
                "is_active": "on", "role": "Marketing Employee", "password": "long-safe-pass-1",
                "password_confirm": "different-pass-1"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The passwords do not match.")
        data["role"] = "Sales Employee"
        data["password_confirm"] = data["password"]
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="new.user@test.com")
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Sales Employee"])
        audit = AuditLog.objects.get(user=self.sales_admin, model="User", object_pk=str(user.pk))
        self.assertEqual(audit.action, "create")
        self.assertEqual(audit.changes["password"], ["not set", "set"])
        self.assertNotIn("long-safe-pass-1", str(audit.changes))

    def test_deactivate_and_reactivate_account(self):
        self.client.force_login(self.sales_admin)
        self.client.post(reverse("department_user_deactivate", args=[self.sales_user.pk]))
        self.sales_user.refresh_from_db()
        self.assertFalse(self.sales_user.is_active)
        audit = AuditLog.objects.get(user=self.sales_admin, model="User",
                                     object_pk=str(self.sales_user.pk))
        self.assertEqual(audit.changes["is_active"], [True, False])
        self.assertFalse(self.client.login(username=self.sales_user.email, password="secretpass1"))
        self.client.post(reverse("department_user_edit", args=[self.sales_user.pk]), {
            "email": self.sales_user.email, "first_name": "", "last_name": "",
            "is_active": "on", "role": "Sales Employee", "password": "",
            "password_confirm": "",
        })
        self.sales_user.refresh_from_db()
        self.assertTrue(self.sales_user.is_active)

    def test_audit_log_shows_current_department_actors_only(self):
        AuditLog.objects.create(user=self.sales_user, username=self.sales_user.email,
                                action="update", model="Thing", object_pk="1", object_repr="Thing 1")
        AuditLog.objects.create(user=self.marketing_user, username=self.marketing_user.email,
                                action="update", model="Thing", object_pk="2", object_repr="Thing 2")
        self.client.force_login(self.sales_admin)
        response = self.client.get(reverse("department_audit"))
        self.assertContains(response, self.sales_user.email)
        self.assertNotContains(response, self.marketing_user.email)

    def test_user_search_sort_and_pagination(self):
        group = Group.objects.get(name="Sales Employee")
        for i in range(51):
            user = User.objects.create_user(
                email=f"employee-{i:02}@example.com", first_name=f"Employee {i:02}")
            user.groups.set([group])
        self.client.force_login(self.sales_admin)
        response = self.client.get(reverse("department_users"), {
            "q": "employee-50", "col": "email", "sort": "-last_name"})
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertContains(response, "employee-50@example.com")
        response = self.client.get(reverse("department_users"), {"sort": "-email"})
        self.assertEqual(len(response.context["page_obj"].object_list), 50)
        self.assertTrue(response.context["page_obj"].has_next())
        self.assertContains(response, "page=2&amp;q=&amp;col=&amp;sort=-email")

    def test_non_department_admin_cannot_open_manager_and_global_admin_still_can(self):
        self.client.force_login(self.sales_user)
        self.assertEqual(self.client.get(reverse("department_users")).status_code, 403)
        self.assertEqual(self.client.get("/manage/").status_code, 302)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get("/manage/").status_code, 200)

    def test_seed_keeps_administrator(self):
        admin = make_superuser("admin@example.com")
        call_command("seed_users", stdout=StringIO())
        admin.refresh_from_db()
        self.assertTrue(admin.is_superuser)
        self.assertFalse(admin.groups.exists())
