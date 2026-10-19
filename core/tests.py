"""RBAC tests.

The department matrix is encoded here a second time (that is the point: the tests are
the independent spec). `core.roles` is applied and every role is checked permission by
permission, then over HTTP: dashboards, home redirect, table lists and the edit/delete
gates. HTTP tests run against Django's empty test database; every page renders empty
fine, so no fixtures are needed.
"""
from io import StringIO
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .models import PRIVACY_NOTICE_VERSION, PrivacyAcknowledgment
from .roles import ROLES, apply_roles

ALL_TABS = ["sales", "customer-profile", "revenue-and-loss", "cost"]

TABLES = {
    "sales": [
        "SalesOrderHeader", "SalesOrderDetail", "SalesTerritory", "SalesPerson",
        "SalesSpecialOffer", "SalesSpecialOfferProduct", "SalesReason", "SalesTaxRate",
    ],
    "customer-profile": [
        "SalesCustomer", "Person", "PersonEmailAddress", "PersonPhone", "PersonAddress",
        "PersonBusinessEntityAddress", "SalesStore", "PersonStateProvince", "PersonCountryRegion",
    ],
    "revenue-and-loss": [
        "ProductionProduct", "ProductionProductListPriceHistory", "ProductionProductSubcategory",
        "ProductionProductCategory", "SalesCurrency", "SalesCurrencyRate",
    ],
    "cost": [
        "PurchasingPurchaseOrderHeader", "PurchasingPurchaseOrderDetail", "PurchasingVendor",
        "PurchasingProductVendor", "ProductionWorkOrder", "ProductionLocation",
        "ProductionProductCostHistory", "ProductionScrapReason", "PurchasingShipMethod",
    ],
}

SALES_MANAGER_TABLES = TABLES["sales"] + TABLES["customer-profile"]
SALES_STAFF_TABLES = [m for m in TABLES["sales"] if m != "SalesPerson"] + TABLES["customer-profile"]
ENGINEERING_TABLES = [
    "ProductionProduct", "ProductionProductSubcategory", "ProductionProductCategory",
    "ProductionProductCostHistory", "ProductionWorkOrder", "ProductionLocation",
]
PRODUCT_TABLES = ["ProductionProduct", "ProductionProductSubcategory", "ProductionProductCategory"]

# role -> (tabs, view, change, delete), straight from the department spec.
MATRIX = {
    "Executive": (ALL_TABS, TABLES["sales"] + TABLES["customer-profile"]
                  + TABLES["revenue-and-loss"] + TABLES["cost"], [], []),
    "Finance Manager": (ALL_TABS, TABLES["sales"] + TABLES["customer-profile"]
                        + TABLES["revenue-and-loss"] + TABLES["cost"],
                        ["ProductionProduct", "ProductionProductListPriceHistory",
                         "ProductionProductCostHistory", "SalesCurrencyRate"], []),
    "Finance Staff": (ALL_TABS, TABLES["sales"] + TABLES["customer-profile"]
                      + TABLES["revenue-and-loss"] + TABLES["cost"], ["SalesCurrencyRate"], []),
    "Sales Manager": (["sales", "customer-profile"], SALES_MANAGER_TABLES,
                      ["SalesOrderHeader", "SalesOrderDetail", "SalesCustomer", "SalesStore",
                       "PersonEmailAddress", "PersonPhone", "PersonAddress",
                       "PersonBusinessEntityAddress", "SalesSpecialOffer",
                       "SalesSpecialOfferProduct"],
                      ["SalesSpecialOffer", "SalesSpecialOfferProduct"]),
    "Sales Staff": (["sales", "customer-profile"], SALES_STAFF_TABLES,
                    ["PersonEmailAddress", "PersonPhone", "PersonAddress",
                     "PersonBusinessEntityAddress"], []),
    "Marketing": (["sales", "customer-profile"], SALES_STAFF_TABLES,
                  ["SalesSpecialOffer", "SalesSpecialOfferProduct"], []),
    "Purchasing Manager": (["cost"], TABLES["cost"],
                           ["PurchasingPurchaseOrderHeader", "PurchasingPurchaseOrderDetail",
                            "PurchasingVendor", "PurchasingProductVendor", "PurchasingShipMethod"],
                           ["PurchasingProductVendor"]),
    "Purchasing Staff": (["cost"], TABLES["cost"],
                         ["PurchasingPurchaseOrderHeader", "PurchasingPurchaseOrderDetail",
                          "PurchasingProductVendor"], []),
    "Shipping and Receiving": (["cost"],
                               ["PurchasingPurchaseOrderHeader", "PurchasingPurchaseOrderDetail",
                                "PurchasingVendor", "PurchasingShipMethod", "ProductionLocation"],
                               ["PurchasingPurchaseOrderDetail"], []),
    "Production Manager": (["cost"], TABLES["cost"], ["ProductionWorkOrder"], []),
    "Production Staff": (["cost"], ["ProductionWorkOrder", "ProductionLocation"], [], []),
    "Production Control": (["cost"],
                           ["ProductionWorkOrder", "ProductionScrapReason", "ProductionLocation"],
                           ["ProductionWorkOrder", "ProductionScrapReason", "ProductionLocation"],
                           []),
    "Quality Assurance": (["cost"],
                          ["ProductionWorkOrder", "ProductionScrapReason", "ProductionLocation"],
                          ["ProductionScrapReason"], []),
    "Engineering Manager": (["revenue-and-loss", "cost"], ENGINEERING_TABLES, PRODUCT_TABLES, []),
    "Engineering Staff": (["revenue-and-loss", "cost"], ENGINEERING_TABLES,
                          ["ProductionProduct"], []),
    "Research and Development": (["revenue-and-loss"], PRODUCT_TABLES, [], []),
    "Tool Design": (["revenue-and-loss"], PRODUCT_TABLES, [], []),
}

TAB_OF = {table: tab for tab, tables in TABLES.items() for table in tables}


def expected_codenames(tabs, view, change, delete):
    codes = {f"core.access_{tab.replace('-', '_')}" for tab in tabs}
    for action, tables in (("view", view), ("change", change), ("delete", delete)):
        codes |= {f"core.{action}_{table.lower()}" for table in tables}
    return codes


class RoleMatrixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        apply_roles(ROLES)
        cls.groups = {g.name: g for g in Group.objects.all()}

    def test_role_names_match(self):
        self.assertEqual(list(ROLES), list(MATRIX))

    def test_every_role_has_exactly_the_matrix_permissions(self):
        for role, (tabs, view, change, delete) in MATRIX.items():
            with self.subTest(role=role):
                actual = {
                    f"{p.content_type.app_label}.{p.codename}"
                    for p in self.groups[role].permissions.select_related("content_type")
                }
                self.assertEqual(actual, expected_codenames(tabs, view, change, delete))

    def test_view_change_delete_lists_stay_inside_the_allowed_tabs(self):
        for role, (tabs, view, change, delete) in MATRIX.items():
            allowed = {m for tab in tabs for m in TABLES[tab]}
            with self.subTest(role=role):
                self.assertLessEqual(set(view), allowed)
                self.assertLessEqual(set(change), set(view))
                self.assertLessEqual(set(delete), set(view))

    def test_table_inventory(self):
        self.assertEqual([len(TABLES[t]) for t in ALL_TABS], [8, 9, 6, 9])
        self.assertEqual(len(TAB_OF), 32)
        self.assertEqual(len(MATRIX), 17)

    def test_reapplying_is_idempotent(self):
        def snapshot():
            return {g.name: set(g.permissions.values_list("codename", flat=True))
                    for g in Group.objects.all()}

        before = snapshot()
        apply_roles(ROLES)
        self.assertEqual(snapshot(), before)

    def test_unknown_table_raises_and_creates_nothing(self):
        with self.assertRaisesMessage(ValueError, "Broken"):
            apply_roles({"Broken": {"tabs": ["sales"], "view": ["NoSuchTable"]}})
        self.assertFalse(Group.objects.filter(name="Broken").exists())


class HttpGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        apply_roles(ROLES)
        cls.users = {}
        for role in MATRIX:
            user = User.objects.create_user(username=role, password="x")
            user.groups.add(Group.objects.get(name=role))
            cls.users[role] = user

    def test_dashboards_and_home(self):
        for role, (tabs, view, change, delete) in MATRIX.items():
            self.client.force_login(self.users[role])
            with self.subTest(role=role, page="home"):
                first = next(tab for tab in ALL_TABS if tab in tabs)
                self.assertRedirects(self.client.get("/"), f"/{first}/")
            for tab in ALL_TABS:
                with self.subTest(role=role, page=tab):
                    resp = self.client.get(f"/{tab}/")
                    self.assertEqual(resp.status_code, 200 if tab in tabs else 403)

    def test_table_lists(self):
        for role, (tabs, view, change, delete) in MATRIX.items():
            self.client.force_login(self.users[role])
            for tab, tables in TABLES.items():
                for table in tables:
                    with self.subTest(role=role, table=table):
                        resp = self.client.get(f"/{tab}/data/{table}/")
                        self.assertEqual(resp.status_code, 200 if table in view else 403)

    def test_edit_and_delete_gates(self):
        for role, (tabs, view, change, delete) in MATRIX.items():
            self.client.force_login(self.users[role])
            editable = change[0] if change else None
            deletable = delete[0] if delete else None
            denied = next(m for tab in tabs for m in TABLES[tab] if m not in change)
            for action, allowed, url in (
                ("edit", editable, f"/{TAB_OF[editable]}/data/{editable}/1/edit/" if editable else None),
                ("delete", deletable, f"/{TAB_OF[deletable]}/data/{deletable}/1/delete/" if deletable else None),
                ("edit", None, f"/{TAB_OF[denied]}/data/{denied}/1/edit/"),
                ("delete", None, f"/{TAB_OF[denied]}/data/{denied}/1/delete/"),
            ):
                if url is None:
                    continue
                with self.subTest(role=role, action=action, allowed=allowed is not None, url=url):
                    resp = self.client.get(url)
                    # allowed roles pass the gate and find no rows (empty test DB); others get 403
                    self.assertEqual(resp.status_code, 404 if allowed is not None else 403)


class SeedUsersCommandTests(TestCase):
    @staticmethod
    def username_for(role):
        return role.lower().replace(" and ", " ").replace(" ", ".")

    def test_seeds_one_user_per_role_in_its_group(self):
        call_command("seed_users", stdout=StringIO())
        self.assertEqual(User.objects.count(), len(MATRIX))
        for role in MATRIX:
            username = self.username_for(role)
            with self.subTest(username=username):
                user = User.objects.get(username=username)
                self.assertTrue(user.check_password(username))
                self.assertEqual([g.name for g in user.groups.all()], [role])

    def test_seed_is_idempotent_and_reset_refreshes_passwords(self):
        call_command("seed_users", stdout=StringIO())
        call_command("seed_users", stdout=StringIO())
        self.assertEqual(User.objects.count(), len(MATRIX))
        user = User.objects.get(username="sales.manager")
        user.set_password("changed")
        user.save()
        call_command("seed_users", "--reset", stdout=StringIO())
        self.assertEqual(User.objects.count(), len(MATRIX))
        self.assertTrue(User.objects.get(username="sales.manager").check_password("sales.manager"))


class PrivacyTests(TestCase):
    """The privacy notice is public; the login acknowledges it; the acknowledgment
    is validated server-side and recorded with its version and time."""

    CREDENTIALS = {"username": "u", "password": "p"}

    def setUp(self):
        User.objects.create_user(**self.CREDENTIALS)

    def login(self, **extra):
        return self.client.post("/login/", {**self.CREDENTIALS, **extra})

    def test_notice_page_is_public_and_cites_the_law(self):
        resp = self.client.get("/privacy/")
        self.assertEqual(resp.status_code, 200)
        for phrase in ("Data Privacy Act of 2012", "Republic Act No. 10173",
                       "National Privacy Commission", "Data Protection Officer",
                       f"version {PRIVACY_NOTICE_VERSION}"):
            with self.subTest(phrase=phrase):
                self.assertContains(resp, phrase)

    def test_footer_and_login_link_to_the_notice(self):
        self.assertContains(self.client.get("/login/"), 'href="/privacy/"')

    def test_login_requires_the_acknowledgment(self):
        resp = self.login()
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(PrivacyAcknowledgment.objects.exists())
        self.assertContains(resp, "Acknowledge the Data Privacy Notice to log in")

    def test_acknowledgment_is_recorded_on_login(self):
        resp = self.login(privacy_accepted="on")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)
        ack = PrivacyAcknowledgment.objects.get(user__username="u")
        self.assertEqual(ack.version, PRIVACY_NOTICE_VERSION)
        self.assertIsNotNone(ack.acknowledged_at)

    def test_reacknowledging_refreshes_a_single_record(self):
        self.login(privacy_accepted="on")
        ack = PrivacyAcknowledgment.objects.get(user__username="u")
        PrivacyAcknowledgment.objects.filter(pk=ack.pk).update(
            version="0.9", acknowledged_at=timezone.now() - timedelta(days=30))
        self.login(privacy_accepted="on")
        self.assertEqual(PrivacyAcknowledgment.objects.count(), 1)
        ack.refresh_from_db()
        self.assertEqual(ack.version, PRIVACY_NOTICE_VERSION)

    def test_failed_login_records_nothing(self):
        resp = self.login(password="wrong", privacy_accepted="on")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(PrivacyAcknowledgment.objects.exists())
