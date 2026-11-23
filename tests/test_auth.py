from playwright.sync_api import expect

from tests.config import ADMIN_EMAIL, BASE_URL
from tests.helpers import expect_login_redirect, visit

PROTECTED = [
    "/dashboard/",
    "/sales/",
    "/customer-profile/",
    "/revenue-and-loss/",
    "/cost/",
    "/users/",
    "/users/audit/",
    "/users/groups/",
]


def test_tc01_authentication(open_page):
    with open_page() as page:
        for path in PROTECTED:
            expect_login_redirect(page, path)

        page.goto(f"{BASE_URL}/login/")
        page.locator('#login-form input[name="username"]').fill(ADMIN_EMAIL)
        page.locator('#login-form input[name="password"]').fill("wrong-password")
        page.locator("#login-form button").click()
        expect(page.locator(".msg.error")).to_have_text("Wrong email or password.")
        assert "/login/" in page.url

        page.locator('button[data-demo-email="admin@example.com"]').click()
        page.wait_for_url("**/dashboard/")
        nav = page.locator("nav.top")
        for label in [
            "Dashboard",
            "Sales",
            "Customer profile",
            "Revenue and loss",
            "Cost",
            "Manage users",
            "Audit Logs",
            "Manage Permissions",
            "admin@example.com (Administrator)",
        ]:
            expect(nav).to_contain_text(label)
        expect(nav.get_by_role("button", name="Log out")).to_be_visible()

        visit(page, "/login/")
        page.wait_for_url("**/dashboard/")
        assert "/login/" not in page.url

        nav.get_by_role("button", name="Log out").click()
        page.wait_for_url("**/login/**")
        expect_login_redirect(page, "/dashboard/")
