from playwright.sync_api import expect

from tests.config import ADMIN_EMAIL, DEPARTMENTS, KINDS, ROLE_CHOICES
from tests.helpers import heading, visit

MODULE_PATHS = [info["path"] for info in DEPARTMENTS.values()]


def email_for(department, kind):
    return f"{department.lower()}.{kind.lower()}@example.com"


def nav_labels(page):
    return [text.strip() for text in page.locator("nav.top a").all_text_contents()]


def assert_department_nav(page, department, kind, email):
    labels = nav_labels(page)
    expected = ["Dashboard", DEPARTMENTS[department]["nav"], email]
    if kind == "Admin":
        expected += ["Manage users", "Audit Logs"]
    for label in expected:
        assert label in labels, f"missing nav label {label} for {email}: {labels}"
    for info in DEPARTMENTS.values():
        if info["nav"] != DEPARTMENTS[department]["nav"]:
            assert info["nav"] not in labels, f"unexpected tab {info['nav']} for {email}"
    assert "Manage Permissions" not in labels


def test_tc08_report_tab_access(open_page):
    for department, info in DEPARTMENTS.items():
        for kind in KINDS:
            email = email_for(department, kind)
            with open_page(email) as page:
                visit(page, "/dashboard/")
                assert_department_nav(page, department, kind, email)
                visit(page, f"{info['path']}?report=")
                expect(heading(page, info["title"])).to_be_visible()
                for other in DEPARTMENTS.values():
                    if other["path"] != info["path"]:
                        visit(page, other["path"], status=403)


def test_tc09_source_table_access(open_page):
    for department, info in DEPARTMENTS.items():
        for kind in KINDS:
            email = email_for(department, kind)
            with open_page(email) as page:
                visit(page, f"{info['path']}?report=")
                links = [text.strip() for text in page.locator("nav.sub a").all_text_contents()]
                if kind == "Employee":
                    assert links == []
                else:
                    for label in info["tables"].values():
                        assert label in links, f"missing table link {label} for {email}"

                for model in info["tables"]:
                    path = f"/{info['tab']}/data/{model}/"
                    visit(page, path, status=200 if kind != "Employee" else 403)
                    if kind != "Employee":
                        assert page.get_by_role("link", name="edit", exact=True).count() == 0
                        assert page.get_by_role("link", name="delete", exact=True).count() == 0

                other = next(item for item in DEPARTMENTS.values() if item["tab"] != info["tab"])
                other_model = next(iter(other["tables"]))
                visit(page, f"/{other['tab']}/data/{other_model}/", status=403)


def test_tc10_report_generation_and_saved_reports(open_page):
    for department, info in DEPARTMENTS.items():
        for kind in KINDS:
            email = email_for(department, kind)
            with open_page(email) as page:
                visit(page, f"{info['path']}?report=")
                button = page.locator("#save-report-button")
                if kind in ("Admin", "Manager"):
                    expect(button).to_be_visible()
                else:
                    expect(button).to_have_count(0)

                link = page.get_by_role("link", name="Manage saved reports")
                expect(link).to_be_visible()
                with page.expect_navigation():
                    link.click()
                assert page.url.endswith(f"/{info['tab']}/reports/")
                expect(heading(page, "Saved reports")).to_be_visible()
                body = page.locator("body").inner_text()
                assert (
                    "No saved reports for this module." in body
                    or page.locator("table tr").count() > 0
                ), body[:200]

                delete_links = page.get_by_role("link", name="delete", exact=True)
                if page.locator("table tr").count() > 1 and kind not in ("Admin", "Manager"):
                    assert delete_links.count() == 0


def test_tc11_department_users_and_audit(open_page):
    for department in DEPARTMENTS:
        for kind in KINDS:
            email = email_for(department, kind)
            with open_page(email) as page:
                visit(page, "/dashboard/")
                labels = nav_labels(page)
                if kind == "Admin":
                    assert "Manage users" in labels and "Audit Logs" in labels
                else:
                    assert "Manage users" not in labels and "Audit Logs" not in labels

                status = 200 if kind == "Admin" else 403
                for path in ("/users/", "/users/add/", "/users/audit/"):
                    visit(page, path, status=status)

                visit(page, "/users/groups/", status=403)

                if kind == "Admin":
                    visit(page, "/users/")
                    expect(heading(page, f"{department} users")).to_be_visible()
                    body = page.locator("main").inner_text()
                    for other_department in DEPARTMENTS:
                        if other_department != department:
                            for other_kind in KINDS:
                                assert email_for(other_department, other_kind) not in body
                    assert email_for(department, "Admin") not in body

                    visit(page, "/users/add/")
                    options = page.locator('select[name="role"] option')
                    values = options.evaluate_all("els => els.map(el => el.value)")
                    expected_roles = {f"{department} {role}" for role in ("Manager", "Supervisor", "Employee")}
                    assert set(values) == expected_roles

                    visit(page, "/users/audit/")
                    expect(heading(page, f"{department} audit log")).to_be_visible()


def test_tc12_global_administrator(open_page):
    with open_page(ADMIN_EMAIL) as page:
        visit(page, "/dashboard/")
        labels = nav_labels(page)
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
            assert label in labels, f"missing nav label {label}: {labels}"

        for info in DEPARTMENTS.values():
            visit(page, f"{info['path']}?report=")
            expect(heading(page, info["title"])).to_be_visible()

        visit(page, "/users/")
        expect(heading(page, "All users")).to_be_visible()
        body = page.locator("body").inner_text()
        for department in DEPARTMENTS:
            assert email_for(department, "Manager") in body

        visit(page, "/users/add/")
        values = page.locator('select[name="role"] option').evaluate_all("els => els.map(el => el.value)")
        assert set(values) == set(ROLE_CHOICES)

        visit(page, "/users/audit/")
        expect(heading(page, "All departments audit log")).to_be_visible()

        visit(page, "/users/groups/")
        expect(heading(page, "Manage Permissions")).to_be_visible()
        assert page.locator("table tbody tr").count() == 16
        with page.expect_navigation():
            page.locator("table tbody tr").first.locator("a").click()
        assert page.locator('input[type="checkbox"][name="permissions"]').count() > 0
        expect(page.get_by_role("button", name="Save permissions")).to_be_visible()

        for info in DEPARTMENTS.values():
            model = next(iter(info["tables"]))
            visit(page, f"/{info['tab']}/data/{model}/")
            assert page.locator("table tr").count() > 1
            expect(page.get_by_role("link", name="edit", exact=True).first).to_be_visible()
            expect(page.get_by_role("link", name="delete", exact=True).first).to_be_visible()
