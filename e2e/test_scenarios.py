"""Whole-visit scenarios in the browser, one staff account per step. Synthetic patients only."""
import re

from playwright.sync_api import expect

from conftest import BASE, lab_complete, pay_visit, register_patient, waiting_row


def _no_js_errors(*pages):
    for p in pages:
        assert not p.js_errors, p.js_errors


def test_outpatient_visit_through_every_role(as_role, unique):
    name = f"Tsehay E2E Op{unique}"
    rc = as_role("reception")
    chart = register_patient(rc, "Tsehay", f"Op{unique}", allergy="Sulfa drugs")
    rc.click("text=Add to waiting list")
    rc.click("dialog[open] .form-actions button.btn-primary")
    waiting_row(rc, name, "triage")

    nurse = as_role("nurse")
    waiting_row(nurse, name, "triage").get_by_role("button", name="Triage").click()
    nurse.fill("#v-cc", "Fever")
    nurse.fill("#v-dur", "2 days")
    nurse.select_option("#v-ga", "acute_sick")
    nurse.check("dialog[open] label.check input")
    for k, v in {"systolic": "120", "diastolic": "80", "temperature_c": "38.6", "heart_rate": "96",
                 "respiratory_rate": "18", "spo2": "98", "weight_kg": "60", "height_cm": "160"}.items():
        nurse.fill(f"#v-{k}", v)
    nurse.select_option("#v-to", "opd1")
    nurse.click("text=Save and send")
    row = waiting_row(nurse, name, "doctor")
    assert "OPD 1" in row.inner_text()

    dr = as_role("doctor")
    waiting_row(dr, name, "doctor").get_by_role("button", name="Manage").click()
    dr.wait_for_url(re.compile(r"/consultations/"))
    expect(dr.locator("#n-complaint_duration")).to_have_value("2 days")  # carried over from triage
    dr.fill("#n-history_present_illness", "Fever with chills for two days.")
    dr.fill("#n-exam_resp", "Clear chest")
    dr.fill("input[placeholder^='Search ICD-10']", "malaria")
    dr.click("button:has-text('B54')")
    dr.wait_for_selector("text=Code B54")
    dr.fill("#n-plan", "Haemoglobin, paracetamol")
    dr.click("text=Save draft")
    dr.wait_for_selector("text=All changes saved")
    dr.locator(".action-bar").get_by_role("button", name="Sign note").click()
    dr.locator("dialog[open]").get_by_role("button", name="Sign note").click()
    dr.wait_for_selector("text=Signed. Send investigations")
    dr.get_by_role("tab", name=re.compile("Investigations")).click()
    dr.check("label.check:has-text('Haemoglobin') input")
    dr.click("button:has-text('Request 1 test')")
    dr.wait_for_selector("text=Awaiting specimen")
    dr.get_by_role("tab", name=re.compile("Prescription")).click()
    dr.fill("input[placeholder^='Search the medicine']", "parac")
    dr.click("button.btn-wrap:has-text('Paracetamol')")
    dr.fill("#rx-dose-0", "1 g")
    dr.select_option("#rx-freq-0", "TID")
    dr.fill("#rx-days-0", "3")
    dr.fill("#rx-qty-0", "18")
    dr.click("text=Save prescription")
    dr.wait_for_selector("text=To dispense")

    lab = as_role("lab")
    lab_complete(lab, name, {"Haemoglobin": "12.8"})

    ph = as_role("pharmacy")
    ph.goto(f"{BASE}/pharmacy")
    ph.locator("section.panel", has_text=name).get_by_role("button", name="Dispense").click()
    ph.locator("dialog[open] .form-actions").get_by_role("button", name="Dispense").click()
    ph.locator("section.panel", has_text=name).wait_for(state="detached")

    cashier = as_role("cashier")
    pay_visit(cashier, name)

    rc2 = as_role("reception")
    waiting_row(rc2, name, "done").get_by_role("button", name="Complete visit").click()
    rc2.wait_for_selector("text=Nothing is outstanding")
    rc2.locator("dialog[open] .form-actions").get_by_role("button", name="Complete visit").click()
    assert "Care completed" in waiting_row(rc2, name, "done").inner_text()
    rc2.goto(chart + "?tab=visits")
    rc2.get_by_role("button", name="Timeline").first.click()
    timeline = rc2.locator(".timeline").first.inner_text()
    for step in ("Triage recorded", "sent to OPD 1", "Laboratory requested", "Dispensed", "Payment", "Visit completed"):
        assert step in timeline, step
    _no_js_errors(rc, nurse, dr, lab, ph, cashier, rc2)


def test_laboratory_only_visit(as_role, unique):
    name = f"Gadise E2E Lab{unique}"
    rc = as_role("reception")
    register_patient(rc, "Gadise", f"Lab{unique}", sex="female")
    rc.click("text=Add to waiting list")
    rc.click("dialog[open] .segmented button:has-text('Laboratory only')")
    rc.fill("#lw-by", "Dr. Outside Requester")
    rc.fill("#lw-fac", "Example Health Centre")
    rc.check("dialog[open] label.check:has-text('Haemoglobin') input")
    rc.click("dialog[open] button:has-text('Send to laboratory')")
    row = waiting_row(rc, name, "done")
    assert "Laboratory only" in row.inner_text()

    lab = as_role("lab")
    lab_complete(lab, name, {"Haemoglobin": "13.1"})
    lab.goto(f"{BASE}/laboratory")
    lab.click("text=Completed")
    lab.locator("section.panel", has_text=name).get_by_role("button", name="Result report").click()
    report = lab.locator("#lab-report").inner_text()
    assert "Dr. Outside Requester" in report and "13.1" in report

    cashier = as_role("cashier")
    pay_visit(cashier, name, reference="E2E-LAB-1")
    invoice = cashier.locator("main").inner_text()
    assert "Lab: Haemoglobin" in invoice and "Consultation" not in invoice

    rc2 = as_role("reception")
    waiting_row(rc2, name, "done").get_by_role("button", name="Complete visit").click()
    rc2.wait_for_selector("text=Nothing is outstanding")
    rc2.locator("dialog[open] .form-actions").get_by_role("button", name="Complete visit").click()
    assert "Care completed" in waiting_row(rc2, name, "done").inner_text()
    _no_js_errors(rc, lab, cashier, rc2)


def test_patient_leaves_before_seeing_the_doctor(as_role, unique):
    name = f"Lemlem E2E Left{unique}"
    rc = as_role("reception")
    register_patient(rc, "Lemlem", f"Left{unique}")
    rc.click("text=Add to waiting list")
    rc.click("dialog[open] .form-actions button.btn-primary")
    row = waiting_row(rc, name, "triage")
    row.get_by_role("button", name=re.compile("More actions")).click()
    rc.get_by_role("menuitem", name="Remove from queue…").click()
    rc.fill("dialog[open] #f-reason", "Left without being seen")
    rc.locator("dialog[open]").get_by_role("button", name="Remove").click()
    rc.locator("table.waiting-list tbody tr", has_text=name).wait_for(state="detached")
    rc.reload()
    rc.wait_for_selector(".tabs")
    expect(rc.locator("main")).not_to_contain_text(name)
    _no_js_errors(rc)


def test_refund_needs_a_second_person(as_role, unique):
    name = f"Bilise E2E Refund{unique}"
    rc = as_role("reception")
    register_patient(rc, "Bilise", f"Refund{unique}")
    rc.click("text=Add to waiting list")
    rc.click("dialog[open] .segmented button:has-text('Laboratory only')")
    rc.fill("#lw-by", "Dr. Outside Requester")
    rc.check("dialog[open] label.check:has-text('Haemoglobin') input")
    rc.click("dialog[open] button:has-text('Send to laboratory')")
    lab = as_role("lab")
    lab_complete(lab, name, {"Haemoglobin": "14.0"})

    cashier = as_role("cashier")
    pay_visit(cashier, name, reference="E2E-RF-1")
    invoice_url = cashier.url
    cashier.keyboard.press("Escape")
    cashier.get_by_role("button", name="Request refund").click()
    cashier.fill("#rf-a", "20")
    cashier.fill("#rf-r", "Charged twice by mistake")
    cashier.click("dialog[open] >> text=Send for approval")
    cashier.wait_for_selector("text=waiting for approval")

    manager = as_role("manager")
    manager.goto(f"{BASE}/approvals")
    manager.locator("tr", has_text=name).get_by_role("button", name="Approve").click()
    manager.locator("tr", has_text=name).locator("text=Approved").wait_for()

    cashier.goto(invoice_url)
    cashier.get_by_role("button", name="Pay out refund").first.click()
    cashier.locator("dialog[open]").get_by_role("button", name="Pay out refund").click()
    cashier.wait_for_selector("text=Refunds")
    assert "Charged twice by mistake" in cashier.locator("main").inner_text()
    _no_js_errors(rc, lab, cashier, manager)


def test_merge_duplicate_records(as_role, unique):
    rc = as_role("reception")
    keep = register_patient(rc, "Chaltu", f"Merge{unique}", phone="0912000111")
    dup = register_patient(rc, "Chaltu", f"Merge{unique}", phone="0912000111")
    dup_mrn = rc.locator(".patient-banner .mono").first.inner_text()

    manager = as_role("manager")
    manager.goto(keep)
    manager.get_by_role("button", name="Merge a duplicate record into this one").click()
    manager.fill("dialog[open] input[placeholder^='Find']", dup_mrn)
    manager.click(f"dialog[open] button.search-item:has-text('{dup_mrn}')")
    manager.fill("#mg-r", "Registered twice")
    manager.check("dialog[open] label.check input")
    manager.click("dialog[open] button:has-text('Merge into')")
    manager.wait_for_selector("text=Also known under")
    manager.goto(dup)
    manager.wait_for_selector("text=This record was merged into")
    _no_js_errors(rc, manager)
