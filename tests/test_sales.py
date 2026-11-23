from playwright.sync_api import expect

from tests.config import ADMIN_EMAIL
from tests.helpers import (
    apply_chart_metric,
    apply_filters,
    checked_values,
    default_dates,
    heading,
    money_ticks,
    query,
    rows_in_panel,
    select_options,
    shortened_to,
    visit,
)


def test_tc03_sales_default_and_filters(open_page):
    with open_page(ADMIN_EMAIL) as page:
        visit(page, "/sales/?report=")
        expect(heading(page, "Sales report")).to_be_visible()
        expect(page.locator("#report-dimensions")).to_be_visible()
        expect(page.locator("#report-chart-filter")).to_be_visible()

        options = [option["label"] for option in select_options(page, "report-chart-filter", "sales_metric")]
        assert "Sales dollars" in options and "Order count" in options
        assert page.locator('#report-chart-filter select[name="sales_metric"]').input_value() == "revenue"

        expect(page.locator(".d-kpi").first).to_be_visible()
        expect(heading(page, "Total sales and sales trend")).to_be_visible()
        assert page.locator(".d-chart .d-bar").count() == 12
        assert money_ticks(page).count() == 5
        expect(page.get_by_text("Monthly merchandise sales")).to_be_visible()
        assert rows_in_panel(page, "High-performing products") == 8
        assert rows_in_panel(page, "Low-performing products") == 6
        expect(page.get_by_text("Selected period")).to_be_visible()
        expect(page.get_by_text("Previous period")).to_be_visible()

        _, to_value = default_dates(page, "report-dimensions")
        shortened = shortened_to(to_value)
        panels = [value for value in checked_values(page, "report-dimensions", "panel") if value not in {"kpis", "low_products"}]

        apply_filters(
            page,
            "report-dimensions",
            dates={"to": shortened},
            categories=["1"],
            countries=["US"],
            panels=panels,
            selects={"show_products": "3"},
        )
        apply_chart_metric(page, "report-chart-filter", "sales_metric", "orders")

        params = query(page)
        assert params.get("to") == shortened
        assert params.get("show_products") == "3"
        assert params.get("sales_metric") == "orders"
        assert "category" in params and "country" in params
        assert set(checked_values(page, "report-dimensions", "category")) == {"1"}
        assert set(checked_values(page, "report-dimensions", "country")) == {"US"}
        assert page.locator(".d-kpis").count() == 0
        expect(heading(page, "Low-performing products")).to_have_count(0)
        assert rows_in_panel(page, "High-performing products") == 3
        expect(page.get_by_text("Monthly order count")).to_be_visible()
        assert page.locator(".d-y-axis").count() == 0

        with page.expect_navigation():
            page.locator('#report-chart-filter select[name="sales_metric"]').select_option("revenue")
        expect(page.get_by_text("Monthly merchandise sales")).to_be_visible()
        assert money_ticks(page).count() == 5
        assert query(page).get("sales_metric") == "revenue"

        visit(page, "/sales/?report=")
        assert set(checked_values(page, "report-dimensions", "category")) == {"1", "2", "3", "4"}
        assert set(checked_values(page, "report-dimensions", "country")) == {"AU", "CA", "FR", "DE", "GB", "US"}
        expect(page.locator(".d-kpis")).to_be_visible()
        assert rows_in_panel(page, "High-performing products") == 8
        assert rows_in_panel(page, "Low-performing products") == 6
