"""Clinic logo and edit-conflict protection, in a real browser. Synthetic data only."""
import io
import os
import re
import tempfile

from PIL import Image

from conftest import BASE, register_patient

SYSADMIN_PASSWORD = os.environ.get("E2E_SYSADMIN_PASSWORD", "Clinic-Admin-Pass-2026")


def _logo_file() -> str:
    img = Image.new("RGB", (240, 120), (16, 110, 90))
    for x in range(60, 180):
        for y in range(40, 80):
            img.putpixel((x, y), (255, 255, 255))
    path = os.path.join(tempfile.mkdtemp(), "clinic-logo.png")
    img.save(path)
    return path


def test_clinic_logo_on_screens_and_sign_in(as_role, browser):
    admin = as_role("manager")
    admin.goto(f"{BASE}/admin/clinic")
    admin.get_by_role("heading", name="Clinic logo").wait_for()
    admin.set_input_files(".logo-setting input[type=file]", _logo_file())
    admin.wait_for_selector(".logo-preview img")
    admin.wait_for_selector(".sidebar .brand-logo")
    assert admin.locator(".sidebar .brand-name").inner_text().strip()

    # The system administrator manages the logo too, but not the facility details.
    sysadmin = as_role("sysadmin", SYSADMIN_PASSWORD)
    sysadmin.goto(f"{BASE}/admin/clinic")
    sysadmin.get_by_role("heading", name="Clinic logo").wait_for()
    assert sysadmin.locator("#cs-n").count() == 0
    assert sysadmin.get_by_text("The clinic administrator keeps these details up to date.").is_visible()

    # Sign-in page shows it to anyone.
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{BASE}/login")
    page.wait_for_selector(".auth-logo:visible")
    ctx.close()

    # Remove it again so other runs start clean.
    admin.get_by_role("button", name="Remove logo").click()
    admin.click("dialog[open] >> button:has-text('Remove logo')")
    admin.wait_for_selector(".logo-preview img", state="detached")
    admin.wait_for_selector(".sidebar .brand-mark")
    assert not admin.js_errors and not sysadmin.js_errors


def test_two_people_editing_the_same_patient(as_role, unique):
    first = as_role("reception")
    url = register_patient(first, f"Conflict{unique}", "Synthetic")
    second = as_role("manager")

    # Both open the edit form on the same version.
    for page in (first, second):
        page.goto(url)
        page.wait_for_selector(".patient-banner")
        page.get_by_role("button", name="Edit details").click()
        page.wait_for_selector("dialog[open] #f-city")

    second.fill("dialog[open] #f-city", "Hawassa")
    second.click("dialog[open] >> text=Save changes")
    second.wait_for_selector("dialog[open]", state="detached")

    first.fill("dialog[open] #f-city", "Bahir Dar")
    first.click("dialog[open] >> text=Save changes")
    notice = first.locator(".conflict-notice")
    notice.wait_for()
    assert "Someone else saved this record first" in notice.inner_text()
    assert re.search(r"Last saved by .+ at ", notice.inner_text())
    first.get_by_role("button", name="Load the latest version").click()
    first.wait_for_selector("dialog[open]", state="detached")
    first.get_by_text("Hawassa").first.wait_for()  # the other person's change was kept, not overwritten
    assert not first.js_errors and not second.js_errors
