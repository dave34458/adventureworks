from playwright.sync_api import expect

from tests.config import ADMIN_EMAIL
from tests.helpers import (
    apply_filters,
    checked_values,
    data_rows,
    default_dates,
    heading,
    money_ticks,
    query,
    rows_in_panel,
    shortened_to,
    visit,
)


def equal_pair_boxes(page):
    groups = page.locator(".d-cols.equal")
    boxes = []
    for index in range(groups.count()):
        group = groups.nth(index)
        assert group.locator(":scope > section.d-panel").count() == 2
        first = group.locator(":scope > section.d-panel").nth(0).bounding_box()
        second = group.locator(":scope > section.d-panel").nth(1).bounding_box()
        assert first and second
        assert abs(first["y"] - second["y"]) <= 2
        assert abs(first["width"] - second["width"]) <= 5
        assert second["x"] > first["x"]
        boxes.append((first, second))
    return boxes


def test_tc05_revenue_loss_default_and_filters(open_page):
    with open_page(ADMIN_EMAIL) as page:
        visit(page, "/revenue-and-loss/?report=")
        expect(heading(page, "Revenue and loss report")).to_be_visible()
        expect(page.locator(".d-kpis")).to_be_visible()

        assert page.locator(".d-cols.equal").count() == 2
        equal_pair_boxes(page)
        for name in [
            "Revenue trend by month",
            "Revenue contribution by category",
            "Gross profit · selected period",
            "Gross margin by month",
        ]:
            expect(heading(page, name)).to_be_visible()

        assert money_ticks(page).count() == 5
        assert page.locator(".d-chart .d-bar").count() == 12

        line_charts = page.locator(".d-line svg")
        assert line_charts.count() == 2
        for index in range(line_charts.count()):
            chart = line_charts.nth(index)
            assert chart.locator('tspan[y="252"]').count() > 0
            assert chart.locator('tspan[y="270"]').count() > 0
            assert chart.locator('tspan[y="244"]').count() == 0
            assert chart.locator('tspan[y="264"]').count() == 0
        assert page.locator(".profitbar").count() > 0
        assert page.locator(".d-line .cur").count() >= 1

        _, to_value = default_dates(page, "report-dimensions")
        shortened = shortened_to(to_value)
        panels = [
            value
            for value in checked_values(page, "report-dimensions", "panel")
            if value not in {"kpis", "leaks", "notes"}
        ]

        apply_filters(
            page,
            "report-dimensions",
            dates={"to": shortened},
            categories=["1"],
            countries=["US"],
            panels=panels,
            selects={"show_declining": "3", "show_leaks": "3", "show_products": "3"},
        )

        params = query(page)
        assert params.get("to") == shortened
        assert params.get("show_declining") == "3"
        assert params.get("show_leaks") == "3"
        assert params.get("show_products") == "3"
        assert set(checked_values(page, "report-dimensions", "category")) == {"1"}
        assert set(checked_values(page, "report-dimensions", "country")) == {"US"}
        expect(page.locator(".d-kpis")).to_have_count(0)
        expect(heading(page, "Below-cost shortfall")).to_have_count(0)
        expect(heading(page, "Calculation method and limitations")).to_have_count(0)
        assert 1 <= rows_in_panel(page, "Declining revenue by product") <= 3
        assert 1 <= data_rows(page, "Revenue contribution by product") <= 3
        expect(page.locator("legend", has_text="Ship-to country")).to_be_visible()
        assert page.locator("#report-chart-filter").count() == 0
        assert money_ticks(page).count() >= 1
        assert page.locator(".d-cols.equal").count() == 2
        equal_pair_boxes(page)

        visit(page, "/revenue-and-loss/?report=")
        expect(page.locator(".d-kpis")).to_be_visible()
        assert rows_in_panel(page, "Declining revenue by product") == 8
        assert data_rows(page, "Revenue contribution by product") == 8
