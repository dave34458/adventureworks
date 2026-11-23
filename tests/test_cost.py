from playwright.sync_api import expect

from tests.config import ADMIN_EMAIL
from tests.helpers import (
    apply_chart_metric,
    apply_filters,
    checked_values,
    data_rows,
    default_dates,
    heading,
    money_ticks,
    query,
    rows_in_panel,
    select_options,
    shortened_to,
    visit,
)

DEFAULT_HEADINGS = [
    "Cost trends and comparisons",
    "Cost distribution by category",
    "Costs and business performance",
    "Significant cost contributors: vendors",
    "Significant cost contributors: products",
    "Significant cost contributors: scrap",
    "Significant cost contributors: repricing",
    "Biggest purchase orders",
]


def test_tc06_cost_default_and_filters(open_page):
    with open_page(ADMIN_EMAIL) as page:
        visit(page, "/cost/?report=")
        expect(heading(page, "Cost report")).to_be_visible()
        expect(page.locator(".d-kpis")).to_be_visible()
        for name in DEFAULT_HEADINGS:
            expect(heading(page, name)).to_be_visible()

        assert money_ticks(page).count() == 5
        assert page.locator(".d-chart .d-bar").count() == 12
        assert page.locator(".d-donut").count() >= 1
        assert page.locator(".d-splitbar").count() >= 1
        assert page.locator(".d-table tr").count() > 1

        assert rows_in_panel(page, "Significant cost contributors: vendors") == 8
        assert rows_in_panel(page, "Significant cost contributors: products") == 8
        assert rows_in_panel(page, "Significant cost contributors: scrap") == 8
        assert rows_in_panel(page, "Significant cost contributors: repricing") == 6
        assert data_rows(page, "Biggest purchase orders") == 8

        options = [option["label"] for option in select_options(page, "report-chart-filter", "cost_metric")]
        assert "Cost of goods" in options and "Gross margin" in options
        assert page.locator('#report-chart-filter select[name="cost_metric"]').input_value() == "cost"

        _, to_value = default_dates(page, "report-dimensions")
        shortened = shortened_to(to_value)
        panels = [
            value
            for value in checked_values(page, "report-dimensions", "panel")
            if value not in {"kpis", "mix", "changes"}
        ]

        apply_filters(
            page,
            "report-dimensions",
            dates={"to": shortened},
            categories=["1"],
            panels=panels,
            selects={"show_vendors": "3", "show_products": "3", "show_reasons": "3", "show_biggest": "3"},
        )
        apply_chart_metric(page, "report-chart-filter", "cost_metric", "margin")

        params = query(page)
        assert params.get("to") == shortened
        assert params.get("cost_metric") == "margin"
        assert params.get("show_vendors") == "3"
        assert params.get("show_products") == "3"
        assert params.get("show_reasons") == "3"
        assert params.get("show_biggest") == "3"
        assert set(checked_values(page, "report-dimensions", "category")) == {"1"}

        expect(page.locator(".d-kpis")).to_have_count(0)
        for name in ("Cost distribution by category", "Significant cost contributors: repricing"):
            expect(heading(page, name)).to_have_count(0)
        expect(heading(page, "Gross margin trend")).to_be_visible()
        expect(page.get_by_text("Monthly gross margin", exact=False)).to_be_visible()
        assert page.locator(".d-y-axis").count() == 0
        assert page.locator("legend", has_text="Ship-to country").count() == 0

        vendor_rows = rows_in_panel(page, "Significant cost contributors: vendors")
        product_rows = rows_in_panel(page, "Significant cost contributors: products")
        scrap_rows = rows_in_panel(page, "Significant cost contributors: scrap")
        biggest_rows = data_rows(page, "Biggest purchase orders")
        assert max(vendor_rows, product_rows, scrap_rows, biggest_rows) > 0
        assert max(vendor_rows, product_rows, scrap_rows, biggest_rows) <= 3

        with page.expect_navigation():
            page.locator('#report-chart-filter select[name="cost_metric"]').select_option("cost")
        expect(heading(page, "Cost trends and comparisons")).to_be_visible()
        assert money_ticks(page).count() == 5
        expect(page.get_by_text("Selected period")).to_be_visible()
        expect(page.get_by_text("Previous period")).to_be_visible()
        assert query(page).get("cost_metric") == "cost"

        visit(page, "/cost/?report=")
        for name in DEFAULT_HEADINGS:
            expect(heading(page, name)).to_be_visible()
        assert rows_in_panel(page, "Significant cost contributors: vendors") == 8
        assert data_rows(page, "Biggest purchase orders") == 8
