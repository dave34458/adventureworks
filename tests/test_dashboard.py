from playwright.sync_api import expect

from tests.config import ADMIN_EMAIL
from tests.helpers import (
    apply_filters,
    checked_values,
    data_rows,
    default_dates,
    heading,
    query,
    rows_in_panel,
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
        expect(form.locator('input[name="category"]').first).to_be_visible()
        expect(form.locator('input[name="country"]').first).to_be_visible()
        expect(form.locator('input[name="panel"]').first).to_be_visible()
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
        category_all = checked_values(page, "dashboard-filters", "category")
        country_all = checked_values(page, "dashboard-filters", "country")
        panel_all = checked_values(page, "dashboard-filters", "panel")
        assert category_all and country_all and panel_all
        category = category_all[0]
        country = country_all[0]
        category_label = page.locator(
            f'#dashboard-filters input[name="category"][value="{category}"]'
        ).evaluate("el => el.parentElement.textContent.trim()")

        apply_filters(
            page,
            "dashboard-filters",
            dates={"to": shortened},
            categories=[category],
            countries=[country],
            selects={"show_products": "3"},
        )

        params = query(page)
        assert params.get("to") == shortened
        assert params.get("category") == category
        assert params.get("country") == country
        assert params.get("show_products") == "3"
        expect(heading(page, f"Top products in {category_label}")).to_be_visible()
        all_link = page.get_by_role("link", name="All categories")
        expect(all_link).to_be_visible()
        assert f"country={country}" in all_link.get_attribute("href")
        count = rows_in_panel(page, f"Top products in {category_label}")
        assert count == 6, f"unexpected category product rows: {count}"
        table_count = data_rows(page, "Top products by sales")
        assert 1 <= table_count <= 3, f"unexpected all-category product rows: {table_count}"
        expect(page.locator(".d-kpi").first).to_be_visible()
        assert page.locator(".d-chart .d-bar").count() > 0

        apply_filters(page, "dashboard-filters",
                      panels=[panel for panel in panel_all if panel != "margin"])
        expect(heading(page, "Gross margin by month")).to_have_count(0)
        expect(heading(page, "Customer mix and spending")).to_be_visible()

        with page.expect_navigation():
            page.get_by_role("link", name="Reset").click()
        assert checked_values(page, "dashboard-filters", "category") == category_all
        assert checked_values(page, "dashboard-filters", "country") == country_all
        assert checked_values(page, "dashboard-filters", "panel") == panel_all
        assert page.locator('#dashboard-filters input[name="from"]').input_value() == from_value
        assert page.locator('#dashboard-filters input[name="to"]').input_value() == to_value
        assert page.locator('select[name="show_products"]').input_value() == "10"
        assert 1 <= page.locator(".d-table tr").count() - 1 <= 10
