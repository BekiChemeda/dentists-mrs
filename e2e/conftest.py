"""Browser end-to-end scenarios against a running Clinic MRS (demo data, synthetic patients only).

Start the stack and load the demo staff first (see e2e/README.md), then run:
    pytest e2e -q
"""
import os
import re
import time

import pytest
from playwright.sync_api import Page, sync_playwright

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:4173")
PASSWORD = os.environ.get("E2E_PASSWORD", "Demo-Clinic-2026")
CHROME = os.environ.get("E2E_CHROME")  # optional path to a Chrome/Chromium binary


@pytest.fixture(scope="session", autouse=True)
def demo_stock():
    """Repeated runs dispense the demo medicines; receive a synthetic delivery when stock runs low, so the
    pharmacy step tests dispensing, not an empty shelf. Uses the store account through the normal API."""
    import datetime
    import http.cookiejar
    import json
    import urllib.request

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def call(method, path, body=None):
        token = next((c.value for c in jar if c.name == "mrs_csrftoken"), "")
        req = urllib.request.Request(f"{BASE}/api/v1{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "X-CSRFToken": token,
                                              "Referer": BASE + "/"})
        with opener.open(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}

    call("GET", "/auth/csrf/")
    call("POST", "/auth/login/", {"username": "store", "password": PASSWORD})
    items = call("GET", "/inventory/items/?page_size=100")
    items = items["results"] if isinstance(items, dict) else items
    low = [i for i in items if i.get("category") == "medicine" and float(i.get("on_hand") or 0) < 200]
    if low:
        suppliers = call("GET", "/inventory/suppliers/")
        suppliers = suppliers["results"] if isinstance(suppliers, dict) else suppliers
        supplier = suppliers[0]["id"] if suppliers else call("POST", "/inventory/suppliers/", {"name": "E2E synthetic supplier"})["id"]
        expiry = (datetime.date.today() + datetime.timedelta(days=700)).isoformat()
        call("POST", "/inventory/purchases/", {"supplier_id": supplier, "purchase_date": datetime.date.today().isoformat(),
             "lines": [{"item_id": i["id"], "batch_number": f"E2E{datetime.date.today():%m%d}", "expiry_date": expiry,
                        "quantity": "500", "unit_cost": "1.00"} for i in low]})


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        kwargs = {"args": ["--no-sandbox"]}
        if CHROME:
            kwargs["executable_path"] = CHROME
        b = p.chromium.launch(**kwargs)
        yield b
        b.close()


@pytest.fixture
def as_role(browser):
    """as_role("nurse") -> a signed-in page for that demo account; closed after the test."""
    contexts = []

    def _open(username: str, password: str | None = None) -> Page:
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        contexts.append(ctx)
        page = ctx.new_page()
        page.set_default_timeout(15_000)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{BASE}/login")
        page.fill("#username", username)
        page.fill("#password", password or PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_selector(".sidebar")
        page.js_errors = errors  # checked by tests at the end
        return page

    yield _open
    for c in contexts:
        c.close()


@pytest.fixture
def unique():
    """A suffix that keeps each run's synthetic patients apart."""
    return time.strftime("%H%M%S")


def register_patient(page: Page, first: str, last: str, *, sex="female", birth="1990-05-01", phone="",
                     allergy="") -> str:
    """Register a synthetic patient through the form; returns the chart URL."""
    page.goto(f"{BASE}/patients")
    page.click("text=Register a new patient")
    page.wait_for_selector("#f-first_name")
    page.fill("#f-first_name", first)
    page.fill("#f-middle_name", "E2E")
    page.fill("#f-last_name", last)
    page.select_option("#f-sex", sex)
    page.fill("#f-birth_date", birth)
    if phone:
        page.fill("#f-phone", phone)
    page.fill("#f-city", "Adama")
    if allergy:
        page.fill("#f-allergy", allergy)
    page.click("dialog[open] >> text=Register patient")
    try:
        page.click("text=It is a different person", timeout=2500)
    except Exception:
        pass
    page.wait_for_url(re.compile(r"/patients/[0-9a-f-]+$"))
    page.wait_for_selector(".patient-banner")
    return page.url


def waiting_row(page: Page, name: str, tab: str):
    page.goto(f"{BASE}/queue?tab={tab}")
    row = page.locator("table.waiting-list tbody tr", has_text=name)
    row.wait_for()
    return row


def lab_complete(page: Page, name: str, results: dict[str, str]):
    """Collect, enter and verify every test for the patient. results: test name -> value (select or number)."""
    page.goto(f"{BASE}/laboratory")
    card = page.locator("section.panel", has_text=name)
    card.wait_for()
    for test, value in results.items():
        row = card.locator("tr", has_text=test)
        if row.get_by_role("button", name="Collect").count():
            row.get_by_role("button", name="Collect").click()
            row.get_by_role("button", name="Enter result").wait_for()
        row.get_by_role("button", name="Enter result").click()
        field = page.locator("#r-v")
        if field.evaluate("el => el.tagName") == "SELECT":
            field.select_option(value)
        else:
            field.fill(value)
        page.click("dialog[open] >> text=Save result")
        row.get_by_role("button", name="Verify").wait_for()
        row.get_by_role("button", name="Verify").click()
        # Verified: the button goes (and the whole order leaves the worklist once every test is done).
        row.get_by_role("button", name="Verify").wait_for(state="detached")


def pay_visit(page: Page, name: str, reference="E2E-REF-1") -> None:
    page.goto(f"{BASE}/billing")
    page.click("text=New invoice")
    page.fill("dialog[open] input[placeholder^='Find a patient']", name)
    page.click("dialog[open] button.search-item")
    page.select_option("#ni-v", index=1)
    page.click("dialog[open] >> text=Create invoice")
    page.wait_for_url(re.compile(r"/billing/invoices/"))
    page.get_by_role("button", name="Issue invoice").click()
    page.get_by_role("button", name="Take payment").click()
    page.select_option("#p-m", "telebirr")
    page.fill("#p-r", reference)
    page.click("dialog[open] >> text=Record payment")
    page.wait_for_selector("#receipt")
