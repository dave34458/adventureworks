from playwright.sync_api import expect

from tests.config import ADMIN_EMAIL
from tests.helpers import (
    apply_filters,
    bubble_data,
    checked_values,
    data_rows,
    default_dates,
    heading,
    query,
    rows_in_panel,
    shortened_to,
    visit,
)

DEFAULT_HEADINGS = [
    "Purchasing patterns and trends",
    "Who buys: segmentation and spending",
    "Customer distribution",
    "Customer distribution by city",
    "Customer segmentation by business type",
    "Purchase frequency",
    "Top customers",
]


def test_tc04_customer_profile_default_and_filters(open_page):
    with open_page(ADMIN_EMAIL) as page:
        visit(page, "/customer-profile/?report=")
        expect(heading(page, "Customer profile report")).to_be_visible()
        expect(page.locator(".d-kpis")).to_be_visible()
        for name in DEFAULT_HEADINGS:
            expect(heading(page, name)).to_be_visible()

        growth = page.locator(".d-chart.has-count-axis")
        expect(growth).to_be_visible()
        assert growth.locator(".d-y-axis span").count() == 5
        assert growth.locator(".d-bar").count() == 12
        expect(page.get_by_text("Returning", exact=True)).to_be_visible()
        expect(page.get_by_text("New", exact=True)).to_be_visible()

        map_node = page.locator("#cust-map.leaflet-container")
        expect(map_node).to_be_visible(timeout=15000)
        assert len(bubble_data(page)) > 0

        assert rows_in_panel(page, "Customer distribution") == 6
        assert rows_in_panel(page, "Customer distribution by city") == 8
        assert data_rows(page, "Top customers") == 8

        _, to_value = default_dates(page, "report-dimensions")
        shortened = shortened_to(to_value)
        panels = [
            value
            for value in checked_values(page, "report-dimensions", "panel")
            if value not in {"kpis", "frequency", "network"}
        ]

        apply_filters(
            page,
            "report-dimensions",
            dates={"to": shortened},
            categories=["1"],
            countries=["US"],
            panels=panels,
            selects={"show_countries": "3", "show_cities": "3", "show_biggest": "3"},
        )

        params = query(page)
        assert params.get("to") == shortened
        assert params.get("show_countries") == "3"
        assert params.get("show_cities") == "3"
        assert params.get("show_biggest") == "3"
        assert set(checked_values(page, "report-dimensions", "category")) == {"1"}
        assert set(checked_values(page, "report-dimensions", "country")) == {"US"}

        expect(page.locator(".d-kpis")).to_have_count(0)
        for name in ("Purchase frequency", "Customer segmentation by business type"):
            expect(heading(page, name)).to_have_count(0)
        for name in DEFAULT_HEADINGS:
            if name not in ("Purchase frequency", "Customer segmentation by business type"):
                expect(heading(page, name)).to_be_visible()

        assert 1 <= rows_in_panel(page, "Customer distribution") <= 3
        assert 1 <= rows_in_panel(page, "Customer distribution by city") <= 3
        assert 1 <= data_rows(page, "Top customers") <= 3
        assert page.locator(".d-chart.has-count-axis .d-y-axis span").count() >= 1
        assert page.locator(".d-chart.has-count-axis .d-bar").count() > 0
        expect(map_node).to_be_visible(timeout=15000)
        assert len(bubble_data(page)) > 0

        visit(page, "/customer-profile/?report=")
        for name in DEFAULT_HEADINGS:
            expect(heading(page, name)).to_be_visible()
        assert rows_in_panel(page, "Customer distribution") == 6
        assert rows_in_panel(page, "Customer distribution by city") == 8
        assert data_rows(page, "Top customers") == 8
