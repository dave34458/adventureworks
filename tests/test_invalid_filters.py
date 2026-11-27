import re

from playwright.sync_api import expect

from tests.config import ADMIN_EMAIL
from tests.helpers import checked_values, heading, money_ticks, rows_in_panel, visit

PAGES = [
    "/dashboard/",
    "/sales/",
    "/customer-profile/",
    "/revenue-and-loss/",
    "/cost/",
]


def empty_report(page):
    assert page.locator(".d-kpi").count() == 0
    assert page.locator(".d-bar").count() == 0
    assert page.locator(".d-rank li:not(.note)").count() == 0


def date_inputs_are_valid(page):
    for name in ("from", "to"):
        value = page.locator(f'input[name="{name}"]').first.input_value()
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), f"{name}={value}"


def test_tc07_invalid_and_empty_filters(open_page):
    with open_page(ADMIN_EMAIL) as page:
        for path in PAGES:
            visit(page, f"{path}?from=2014-12-31&to=2014-01-01")
            if path == "/dashboard/":
                expect(page.get_by_text("No data is available for this report.").first).to_be_visible()
                expect(heading(page, "No dashboard figures")).to_be_visible()
                assert page.locator(".d-kpi").count() == 0
            else:
                empty_report(page)

        for path in PAGES:
            visit(page, f"{path}?from=not-a-date&to=also-bad")
            date_inputs_are_valid(page)
            expect(page.locator(".d-kpi").first).to_be_visible()

        visit(page, "/dashboard/?category=999999&category_filter=1&country=ZZZ&country_filter=1&panel=bogus&panel_filter=1")
        assert checked_values(page, "dashboard-filters", "category") == []
        assert checked_values(page, "dashboard-filters", "country") == []
        assert checked_values(page, "dashboard-filters", "panel") == []
        expect(page.get_by_text("No data is available for this report.").first).to_be_visible()
        expect(heading(page, "No dashboard figures")).to_be_visible()

        visit(page, "/dashboard/?show_products=not-a-number")
        assert page.locator('select[name="show_products"]').input_value() == "10"
        expect(page.locator(".d-kpi").first).to_be_visible()

        for path, query in [
            ("/sales/", "?report=&category=999999&category_filter=1"),
            ("/sales/", "?report=&country=ZZZ&country_filter=1"),
            ("/sales/", "?report=&panel=bogus&panel_filter=1"),
            ("/sales/", "?report=&from=2030-01-01&to=2030-01-31"),
        ]:
            visit(page, f"{path}{query}")
            empty_report(page)
            expect(page.locator("#report-dimensions")).to_be_visible()

        visit(page, "/sales/?report=&show_products=999&sales_metric=bogus")
        assert page.locator('#report-chart-filter select[name="sales_metric"]').input_value() == "revenue"
        assert page.locator('select[name="show_products"]').input_value() == "8"
        assert rows_in_panel(page, "High-performing products") == 8
        assert money_ticks(page).count() == 5

        visit(page, "/cost/?report=&show_vendors=999&cost_metric=bogus")
        assert page.locator('#report-chart-filter select[name="cost_metric"]').input_value() == "cost"
        assert page.locator('select[name="show_vendors"]').input_value() == "8"
        assert rows_in_panel(page, "Significant cost contributors: vendors") == 8
        assert money_ticks(page).count() == 5

        visit(page, "/dashboard/?from=2030-01-01&to=2030-01-31")
        expect(page.get_by_text("No data is available for this report.").first).to_be_visible()
        expect(heading(page, "No dashboard figures")).to_be_visible()
