import json
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect

from tests.config import BASE_URL


def visit(page, path, status=200):
    response = page.goto(f"{BASE_URL}{path}")
    assert response is not None, f"no response for {path}"
    assert response.status == status, f"{path}: expected {status}, got {response.status}"
    return response


def query(page):
    return {key: values[0] for key, values in parse_qs(urlparse(page.url).query).items()}


def heading(page, name):
    return page.get_by_role("heading", name=name, exact=True)


def panel(page, name):
    return page.locator(".d-panel").filter(has=heading(page, name))


def visible_heading(page, name):
    expect(heading(page, name)).to_be_visible()


def absent_heading(page, name):
    expect(heading(page, name)).to_have_count(0)


def default_dates(page, form_id):
    form = page.locator(f"#{form_id}")
    return (
        form.locator('input[name="from"]').input_value(),
        form.locator('input[name="to"]').input_value(),
    )


def shortened_to(to_value, days=30):
    return (date.fromisoformat(to_value) - timedelta(days=days)).isoformat()


def checked_values(page, form_id, name):
    return page.evaluate(
        "([formId, name]) => Array.from(document.getElementById(formId).querySelectorAll(`input[name=\"${name}\"]:checked`)).map(el => el.value)",
        [form_id, name],
    )


def select_options(page, form_id, name):
    return page.evaluate(
        "([formId, name]) => Array.from(document.getElementById(formId).querySelectorAll(`select[name=\"${name}\"] option`)).map(el => ({ value: el.value, label: el.textContent.trim() }))",
        [form_id, name],
    )


def apply_filters(page, form_id, dates=None, categories=None, countries=None, panels=None, selects=None):
    values = {
        "dates": dates or {},
        "category": categories,
        "country": countries,
        "panel": panels,
        "selects": selects or {},
    }
    script = """
    ([formId, values]) => {
      const form = document.getElementById(formId);
      if (!form) throw new Error('missing form ' + formId);
      for (const [name, value] of Object.entries(values.dates)) {
        const el = form.querySelector(`[name="${name}"]`);
        if (el) el.value = value;
      }
      for (const name of ['category', 'country', 'panel']) {
        const wanted = values[name];
        if (wanted === null || wanted === undefined) continue;
        form.querySelectorAll(`input[name="${name}"]`).forEach(el => {
          el.checked = wanted.includes(el.value);
        });
      }
      for (const [name, value] of Object.entries(values.selects)) {
        const el = document.querySelector(`select[name="${name}"]`);
        if (el) el.value = value;
      }
      form.requestSubmit();
    }
    """
    with page.expect_navigation():
        page.evaluate(script, [form_id, values])


def apply_chart_metric(page, form_id, name, value):
    script = """
    ([formId, name, value]) => {
      const form = document.getElementById(formId);
      const el = form.querySelector(`select[name="${name}"]`);
      el.value = value;
      form.requestSubmit();
    }
    """
    with page.expect_navigation():
        page.evaluate(script, [form_id, name, value])


def login(page, email, password):
    page.goto(f"{BASE_URL}/login/")
    page.locator('#login-form input[name="username"]').fill(email)
    page.locator('#login-form input[name="password"]').fill(password)
    page.locator("#login-form button").click()
    page.wait_for_url("**/dashboard/")


def expect_login_redirect(page, path):
    page.goto(f"{BASE_URL}{path}")
    page.wait_for_url("**/login/**")
    assert "/login/" in page.url and "next=" in page.url, page.url
    params = parse_qs(urlparse(page.url).query)
    assert params.get("next", [None])[0] == path, f"wrong next for {path}: {page.url}"


def expect_status(page, path, status):
    visit(page, path, status=status)


def money_ticks(page):
    return page.locator(".d-y-axis span")


def bubble_data(page):
    return json.loads(page.locator("#cust-bubbles").text_content())


def rows_in_panel(page, name):
    return panel(page, name).locator(".d-rank li").count()


def data_rows(page, name):
    return panel(page, name).locator(".d-table tr").count() - 1
