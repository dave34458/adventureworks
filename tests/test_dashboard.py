from playwright.sync_api import expect

from tests.config import ADMIN_EMAIL
from tests.helpers import (
    apply_filters,
    data_rows,
    default_dates,
    heading,
    query,
    rows_in_panel,
    select_options,
    shortened_to,
    visit,
)


def test_tc02_dashboard_default_and_filters(open_page):
    with open_page(ADMIN_EMAIL) as page:
        visit(page, "/dashboard/")
        expect(heading(page, "Business performance dashboard")).to_be_visible()

        form = page.locator("#dashboard-filters")
        expect(form.locator('input[name="from"]')).to_be_visible()
        expect(form.locator('input[name="to"]')).to_be_visible()
        expect(form.locator('select[name="category"]')).to_be_visible()
        expect(page.get_by_role("link", name="Reset")).to_be_visible()

        expect(page.locator(".d-kpi").first).to_be_visible()
        expect(page.locator(".d-chart .d-bar").first).to_be_visible()
        assert page.locator(".d-chart .d-bar").count() == 12
        assert page.locator(".d-y-axis span").count() >= 1
        assert page.locator(".d-donut").count() >= 1
        assert page.locator(".d-line .cur").count() >= 1
        assert page.locator(".d-splitbar").count() >= 2
        assert page.locator(".d-table tr").count() > 1

        from_value, to_value = default_dates(page, "dashboard-filters")
        assert from_value and to_value
        shortened = shortened_to(to_value)
        category_options = [option for option in select_options(page, "dashboard-filters", "category") if option["value"]]
        assert category_options
        category = category_options[0]

        apply_filters(
            page,
            "dashboard-filters",
            dates={"to": shortened},
            selects={"category": category["value"], "show_products": "3"},
        )

        params = query(page)
        assert params.get("to") == shortened
        assert params.get("category") == category["value"]
        assert params.get("show_products") == "3"
        expect(heading(page, f"Top products in {category['label']}")).to_be_visible()
        expect(page.get_by_role("link", name="All categories")).to_be_visible()
        count = rows_in_panel(page, f"Top products in {category['label']}")
        assert count == 6, f"unexpected category product rows: {count}"
        table_count = data_rows(page, "Top products by sales")
        assert 1 <= table_count <= 3, f"unexpected all-category product rows: {table_count}"
        expect(page.locator(".d-kpi").first).to_be_visible()
        assert page.locator(".d-chart .d-bar").count() > 0

        with page.expect_navigation():
            page.get_by_role("link", name="Reset").click()
        assert page.locator('select[name="category"]').input_value() == ""
        assert page.locator('#dashboard-filters input[name="from"]').input_value() == from_value
        assert page.locator('#dashboard-filters input[name="to"]').input_value() == to_value
        assert page.locator('select[name="show_products"]').input_value() == "10"
        assert 1 <= page.locator(".d-table tr").count() - 1 <= 10
