import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.config import ACCOUNTS, BASE_URL, HEADLESS, PROJECT_ROOT, VIEWPORT
from tests.helpers import login
from tests.results import RESULTS, short_detail, tc_id_from_name, write_results

REPORT_KEY = pytest.StashKey()


def server_healthy():
    try:
        with urllib.request.urlopen(f"{BASE_URL}/login/", timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


@pytest.fixture(scope="session", autouse=True)
def server():
    if server_healthy():
        yield "existing"
        return
    process = subprocess.Popen(
        [sys.executable, "manage.py", "runserver", "127.0.0.1:8000", "--noreload"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        if server_healthy():
            break
        time.sleep(0.5)
    else:
        process.terminate()
        raise RuntimeError("Django dev server did not become healthy")
    yield "started"
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=HEADLESS)
        yield instance
        instance.close()


@pytest.fixture(scope="session")
def auth_states(browser, server):
    states = {}
    for email, account in ACCOUNTS.items():
        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()
        login(page, email, account["password"])
        expect(page.locator("nav.top")).to_contain_text("Log out")
        states[email] = context.storage_state()
        context.close()
    return states


@pytest.fixture
def open_page(browser, auth_states):
    @contextmanager
    def factory(email=None):
        options = {"viewport": VIEWPORT}
        if email:
            options["storage_state"] = auth_states[email]
        context = browser.new_context(**options)
        page = context.new_page()
        page.set_default_timeout(15000)
        page.set_default_navigation_timeout(15000)
        try:
            yield page
        finally:
            context.close()

    return factory


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    item.stash[REPORT_KEY] = report
    tc_id = tc_id_from_name(item.name)
    if not tc_id:
        return
    entry = RESULTS.setdefault(tc_id, {"outcome": "passed", "details": []})
    if report.failed:
        entry["outcome"] = "failed"
        entry["details"].append(short_detail(report.longreprtext))
    elif report.skipped:
        if entry["outcome"] != "failed":
            entry["outcome"] = "skipped"
        entry["details"].append(short_detail(report.longreprtext))


def pytest_sessionfinish(session, exitstatus):
    target = write_results(RESULTS, int(exitstatus))
    print(f"\nGenerated {target}")
