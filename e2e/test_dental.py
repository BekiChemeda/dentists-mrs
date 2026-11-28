"""Dental scenarios in the browser (spec §25.3). Synthetic patients only.

Needs the demo dental staff (`seed_demo --with-staff`) and a dental installation (`apply_dental_defaults`: triage,
laboratory and pharmacy off), so a walk-in goes straight to the dentists' waiting list.
"""
import datetime
import re

from playwright.sync_api import Page, expect

from conftest import BASE, register_patient, waiting_row


def _no_js_errors(*pages):
    for p in pages:
        assert not p.js_errors, p.js_errors


def _tab(page: Page, name: str):
    page.get_by_role("tab", name=re.compile("^" + re.escape(name))).click()


def _tooth(page: Page, number: int):
    return page.locator("button.tooth", has=page.locator(".tooth-num", has_text=re.compile(f"^{number}$")))


def _start_exam(rc: Page, dentist: Page, name: str):
    rc.click("text=Add to waiting list")
    rc.click("dialog[open] .form-actions button.btn-primary")
    waiting_row(dentist, name, "doctor").get_by_role("button", name="Start examination").click()
    dentist.wait_for_url(re.compile(r"/dental/encounters/"))
    return dentist.url.split("?")[0]


def _add_plan_item(page: Page, procedure: str, tooth: str, surfaces: list[str]):
    page.locator("main").get_by_role("button", name="Add to plan").click()
    dialog = page.locator("dialog[open]")
    options = dialog.locator("#f-procedure_id option").all_inner_texts()
    dialog.locator("#f-procedure_id").select_option(label=next(o for o in options if procedure in o))
    if surfaces:
        dialog.locator("#f-scope").select_option("surfaces")
    dialog.locator("#f-tooth").fill(tooth)
    for s in surfaces:
        dialog.locator("button.surface-toggle", has_text=s).click()
    dialog.locator(".form-actions button.btn-primary").click()
    expect(page.locator("dialog[open]")).to_have_count(0)


def test_toothache_to_filling_invoice_and_follow_up(as_role, unique):
    """Scenario 1: new adult with toothache → examination → chart → diagnosis → plan (one item deferred, §25.3
    case 8) → filling → signed → invoice paid → visit completed. Also checks that typing survives a tab change and
    a materials save (unsaved text must never be lost)."""
    name = f"Meron E2E Tooth{unique}"
    rc = as_role("reception")
    chart = register_patient(rc, "Meron", f"Tooth{unique}", birth="1992-03-04")
    dr = as_role("dentist")
    exam = _start_exam(rc, dr, name)

    # Medical history review.
    review = dr.locator("section.panel", has_text="Medical history review before treatment")
    review.locator("select").first.wait_for()
    for select in review.locator("select").all():
        select.select_option(index=1)
    review.locator("label.check input").first.check()
    dr.get_by_role("button", name="Record review").click()
    expect(dr.locator(".alert-strip")).to_contain_text("Medical history reviewed")

    # Complaint: type, look at the chart, come back: the text is still there and the tab shows unsaved work.
    _tab(dr, "Examination")
    dr.get_by_label("Chief complaint").fill("Pain in a lower left back tooth with sweets")
    _tab(dr, "Chart")
    expect(dr.get_by_role("tab", name=re.compile("Examination •"))).to_be_visible()
    _tab(dr, "Sign")
    expect(dr.locator("main")).to_contain_text("unsaved changes")
    _tab(dr, "Examination")
    expect(dr.get_by_label("Chief complaint")).to_have_value("Pain in a lower left back tooth with sweets")
    dr.locator(".action-bar").get_by_role("button", name="Save").click()
    expect(dr.locator(".action-bar")).to_contain_text("All changes saved")

    # Chart: caries on 36 OD, 46 missing.
    _tab(dr, "Chart")
    _tooth(dr, 36).click()
    dr.get_by_role("button", name="Surfaces").click()
    dr.locator("button.surface-toggle", has_text="O").click()
    dr.locator("button.surface-toggle", has_text="D").click()
    dr.select_option("#f-finding_type_id", label="C — Caries")
    dr.get_by_role("button", name="Record finding").click()
    expect(_tooth(dr, 36).locator(".sym")).to_have_text("C")
    _tooth(dr, 46).click()
    dr.select_option("#f-finding_type_id", label="X — Missing")
    dr.get_by_role("button", name="Record finding").click()
    expect(_tooth(dr, 46).locator(".tooth-missing")).to_have_count(1)

    # A new periodontal chart starts with the teeth the dental chart records as missing.
    _tab(dr, "Periodontal")
    dr.locator("main .segmented").get_by_role("button", name="Lower").click()
    expect(dr.get_by_label("46 missing")).to_be_checked()
    expect(dr.get_by_label("36 missing")).not_to_be_checked()

    # Diagnosis on 36.
    _tab(dr, "Diagnoses")
    dr.fill("#f-q", "dentine")
    dr.get_by_role("radio", name=re.compile("dentine")).first.click()
    dr.locator("main #f-tooth").fill("36")
    dr.get_by_role("button", name=re.compile(r"^Add K02")).click()
    expect(dr.get_by_role("tab", name=re.compile("Diagnoses 1"))).to_be_visible()

    # Plan: filling (accepted) and implant consultation (deferred).
    _tab(dr, "Treatment plan")
    dr.get_by_role("button", name="New treatment plan").click()
    dr.fill("#f-title", "Restore 36, consider 46")
    dr.locator("dialog[open] label.check input").first.check()
    dr.locator("dialog[open] .form-actions button.btn-primary").click()
    _add_plan_item(dr, "Composite restoration, two or more surfaces", "36", ["O", "D"])
    _add_plan_item(dr, "Implant consultation", "46", [])
    dr.locator("main").get_by_role("button", name="Present to patient").click()
    dr.locator("main").get_by_role("button", name="Record decision").click()
    dr.locator("dialog[open] select").nth(1).select_option("deferred")
    dr.locator("dialog[open] .form-actions button.btn-primary").click()
    expect(dr.locator("main")).to_contain_text("Partially accepted")
    expect(dr.locator("main")).to_contain_text("Deferred")

    # Procedure from the plan; notes typed, then materials saved, then signed: the notes must survive.
    _tab(dr, "Procedures")
    dr.get_by_role("button", name="Record a procedure").click()
    dr.locator("dialog[open] #f-plan_item_id").select_option(index=1)
    dr.locator("dialog[open]").get_by_role("button", name="Start the record").click()
    record = dr.locator("dialog[open]")
    record.get_by_label("Procedure notes").fill("Caries removed, composite placed DO.")
    record.get_by_role("button", name="Save materials").click()
    expect(record.get_by_label("Procedure notes")).to_have_value("Caries removed, composite placed DO.")
    record.get_by_role("button", name="Sign", exact=True).click()
    expect(record).to_contain_text("Completed")
    expect(record).to_contain_text("Caries removed, composite placed DO.")
    dr.keyboard.press("Escape")

    # Book the post-operative review on the recall list, then sign the examination.
    _tab(dr, "Sign")
    dr.select_option("#f-kind", "post_op")
    dr.fill("#f-due_date", (datetime.date.today() + datetime.timedelta(days=14)).isoformat())
    dr.get_by_role("button", name="Add to recall list").click()
    rc.goto(f"{BASE}/dental/recalls")
    expect(rc.locator("main")).to_contain_text(name)
    _tab(dr, "Sign")
    dr.locator("main .form-actions").get_by_role("button", name="Sign").click()
    confirm = dr.locator("dialog[open]")
    if confirm.count():
        confirm.locator(".form-actions button.btn-primary").click()
    expect(dr.locator("main")).to_contain_text("Examination report")

    # Cashier: the signed procedure is on the invoice once; the deferred item is not.
    cashier = as_role("cashier")
    cashier.goto(f"{BASE}/billing")
    cashier.click("text=New invoice")
    cashier.fill("dialog[open] input[placeholder^='Find a patient']", name)
    cashier.click("dialog[open] button.search-item")
    cashier.select_option("#ni-v", index=1)
    cashier.click("dialog[open] >> text=Create invoice")
    cashier.wait_for_url(re.compile(r"/billing/invoices/"))
    lines = cashier.locator("main table").first
    expect(lines).to_contain_text("Composite restoration, two or more surfaces")
    expect(lines).not_to_contain_text("Implant consultation")
    cashier.get_by_role("button", name="Issue invoice").click()
    cashier.get_by_role("button", name="Take payment").click()
    cashier.select_option("#p-m", "cash")
    cashier.click("dialog[open] >> text=Record payment")
    cashier.wait_for_selector("#receipt")

    # Reception closes the visit.
    waiting_row(rc, name, "finishing").get_by_role("button", name="Complete visit").click()
    rc.locator("dialog[open] .form-actions").get_by_role("button", name="Complete visit").click()
    expect(waiting_row(rc, name, "done")).to_contain_text("Care completed")

    # Return visit: new caries on 37; the comparison with the first examination shows only that change.
    rc.goto(chart)
    rc.wait_for_selector(".patient-banner")
    second = _start_exam(rc, dr, name)
    assert second != exam
    _tab(dr, "Chart")
    _tooth(dr, 37).click()
    dr.get_by_role("button", name="Surfaces").click()
    dr.locator("button.surface-toggle", has_text="O").click()
    dr.select_option("#f-finding_type_id", label="C — Caries")
    dr.get_by_role("button", name="Record finding").click()
    expect(_tooth(dr, 37).locator(".sym")).to_have_text("C")
    dr.get_by_text("Compare with an earlier examination").click()
    compare = dr.locator("details", has_text="Compare with an earlier examination")
    expect(compare).to_contain_text("37 O")
    added = compare.locator("div", has=dr.locator("strong", has_text="Added")).last
    expect(added).not_to_contain_text("36")
    _no_js_errors(rc, dr, cashier)


def test_receptionist_cannot_open_the_dental_chart(as_role, unique):
    """Scenario 11: reception sees demographics, never the chart; the API refuses it too."""
    rc = as_role("reception")
    chart = register_patient(rc, "Saron", f"Rc{unique}")
    patient_id = chart.rstrip("/").split("/")[-1]
    expect(rc.get_by_role("link", name="Dental record")).to_have_count(0)
    status = rc.evaluate(
        "async (id) => (await fetch(`/api/v1/dental/patients/${id}/chart/`, {credentials: 'include'})).status",
        patient_id,
    )
    assert status == 403
    _no_js_errors(rc)


def test_assistant_cannot_sign_an_examination(as_role, unique):
    """Scenario 10: an assistant may open the dentist's examination but has no Sign button, and the API refuses."""
    name = f"Lidya E2E Asst{unique}"
    rc = as_role("reception")
    register_patient(rc, "Lidya", f"Asst{unique}")
    dr = as_role("dentist")
    exam = _start_exam(rc, dr, name)
    encounter_id = exam.rstrip("/").split("/")[-1]
    asst = as_role("assistant")
    asst.goto(exam + "?tab=sign")
    expect(asst.locator("main .form-actions").get_by_role("button", name="Sign")).to_have_count(0)
    status = asst.evaluate(
        """async (id) => {
            const csrf = document.cookie.split('; ').find((c) => c.startsWith('mrs_csrftoken='))?.split('=')[1] ?? '';
            const r = await fetch(`/api/v1/dental/encounters/${id}/sign/`, {method: 'POST', credentials: 'include',
              headers: {'X-CSRFToken': csrf, 'Content-Type': 'application/json'}, body: '{}'});
            return r.status;
        }""",
        encounter_id,
    )
    assert status == 403
    _no_js_errors(rc, dr, asst)


# --------------------------------------------------------------------------------------------- orthodontics
def _ortho_tab(page: Page):
    _tab(page, "Orthodontics")
    expect(page.locator("main")).to_contain_text("Orthodontic assessment")


def _cashier_invoice(as_role, name: str):
    cashier = as_role("cashier")
    cashier.goto(f"{BASE}/billing")
    cashier.click("text=New invoice")
    cashier.fill("dialog[open] input[placeholder^='Find a patient']", name)
    cashier.click("dialog[open] button.search-item")
    cashier.select_option("#ni-v", index=1)
    cashier.click("dialog[open] >> text=Create invoice")
    cashier.wait_for_url(re.compile(r"/billing/invoices/"))
    return cashier


def test_orthodontic_package_with_instalments(as_role, unique):
    """Braces paid as a package: assessment, case with deposit and instalments, braces fitted, deposit invoiced and
    paid, the next instalment taken early."""
    name = f"Bethel E2E Ortho{unique}"
    rc = as_role("reception")
    register_patient(rc, "Bethel", f"Ortho{unique}", birth="2011-05-02")
    dr = as_role("dentist")
    _start_exam(rc, dr, name)
    _ortho_tab(dr)
    dr.select_option("#oa-molar_right", "class_ii")
    dr.select_option("#oa-molar_left", "class_ii")
    dr.select_option("#oa-incisor_relationship", "class_ii_div1")
    dr.fill("#oa-overjet_mm", "7")
    dr.fill("#oa-overbite_mm", "5")
    dr.select_option("#oa-crowding_upper", "moderate")
    dr.fill("#oa-objectives", "Reduce overjet, relieve upper crowding")
    dr.get_by_role("button", name="Save assessment").click()
    expect(dr.locator("main")).to_contain_text("All changes saved")

    dr.get_by_role("button", name="Start orthodontic case").click()
    form = dr.locator("dialog[open]")
    expect(form.locator("#f-objectives")).to_have_value("Reduce overjet, relieve upper crowding")
    form.locator("#f-expected_months").fill("18")
    form.locator("#f-package_price").fill("60000")
    form.locator("#f-deposit").fill("15000")
    form.locator("#f-instalment_count").fill("9")
    expect(form).to_contain_text("9 × about 5,000.00 ETB every 30 days")
    form.get_by_role("button", name="Create case").click()
    expect(dr.locator("dialog[open]")).to_have_count(0)
    panel = dr.locator("main")
    expect(panel).to_contain_text("Planned")
    expect(panel).to_contain_text("Deposit")
    expect(panel).to_contain_text("Instalment 9 of 9")

    dr.get_by_role("button", name="Record orthodontic visit").click()
    visit = dr.locator("dialog[open]")
    expect(visit.locator("#f-kind")).to_have_value("bonding")
    visit.locator("#f-upper_wire").fill("0.014 NiTi")
    visit.locator("#f-lower_wire").fill("0.014 NiTi")
    expect(visit).to_contain_text("Covered by the package price")
    visit.get_by_role("button", name="Record visit").click()
    expect(dr.locator("dialog[open]")).to_have_count(0)
    expect(panel).to_contain_text("Active treatment")
    expect(panel).to_contain_text("0.014 NiTi / 0.014 NiTi")

    # The cashier collects the deposit only (other instalments are not due yet), then takes payment.
    cashier = _cashier_invoice(as_role, name)
    lines = cashier.locator("main table").first
    expect(lines).to_contain_text("Deposit")
    expect(lines).not_to_contain_text("Instalment 1 of 9")
    cashier.get_by_role("button", name="Issue invoice").click()
    cashier.get_by_role("button", name="Take payment").click()
    cashier.select_option("#p-m", "cash")
    cashier.click("dialog[open] >> text=Record payment")
    cashier.wait_for_selector("#receipt")

    dr.reload()
    _tab(dr, "Orthodontics")
    row = dr.locator("tr", has_text="Deposit")
    expect(row).to_contain_text("Paid")
    # The patient pays the first instalment early.
    dr.locator("tr", has_text="Instalment 1 of 9").get_by_role("button", name="Take payment today").click()
    expect(dr.locator("tr", has_text="Instalment 1 of 9")).to_contain_text("Due today")
    _no_js_errors(rc, dr, cashier)


def test_orthodontic_case_charged_per_visit(as_role, unique):
    """Braces charged per visit: the adjustment is on the invoice, the fitting (a separate procedure) is not."""
    name = f"Abel E2E PerVisit{unique}"
    rc = as_role("reception")
    register_patient(rc, "Abel", f"PerVisit{unique}", birth="2009-01-12")
    dr = as_role("dentist")
    _start_exam(rc, dr, name)
    _ortho_tab(dr)
    dr.get_by_role("button", name="Start orthodontic case").click()
    form = dr.locator("dialog[open]")
    form.get_by_role("button", name="Charged per visit").click()
    form.locator("#f-per_visit_price").fill("1200")
    form.get_by_role("button", name="Create case").click()
    expect(dr.locator("main")).to_contain_text("Price per visit")
    for kind, charged in (("bonding", False), ("adjustment", True)):
        dr.get_by_role("button", name="Record orthodontic visit").click()
        visit = dr.locator("dialog[open]")
        visit.locator("#f-kind").select_option(kind)
        expect(visit.get_by_label(re.compile("Charge this visit"))).to_be_checked(checked=charged)
        if not charged:
            visit.locator("#f-no_charge_reason").fill("Fitting charged as a procedure")
        visit.get_by_role("button", name="Record visit").click()
        expect(dr.locator("dialog[open]")).to_have_count(0)
    expect(dr.locator("main")).to_contain_text("Charged on visits so far")
    cashier = _cashier_invoice(as_role, name)
    lines = cashier.locator("main table").first
    expect(lines).to_contain_text("Orthodontic visit")
    expect(lines).to_contain_text("Adjustment")
    expect(lines).not_to_contain_text("Braces or appliance fitted")
    _no_js_errors(rc, dr, cashier)


def test_allergy_is_flagged_while_prescribing(as_role, unique):
    """QA run 5: the penicillin allergy shows as soon as amoxicillin is chosen, and a refused save says so."""
    name = f"Kalkidan E2E Allergy{unique}"
    rc = as_role("reception")
    register_patient(rc, "Kalkidan", f"Allergy{unique}", allergy="Penicillin")
    dr = as_role("dentist")
    _start_exam(rc, dr, name)
    _tab(dr, "Prescriptions")
    dr.fill("#f-drug-0", "Amox")
    dr.locator("button", has_text="Amoxicillin").first.click()
    expect(dr.locator(".banner", has_text="Recorded allergy: Penicillin")).to_be_visible()
    expect(dr.locator("#f-ovr-0")).to_be_visible()
    dr.fill("#f-dose-0", "500 mg")
    dr.fill("#f-qty-0", "15")
    dr.get_by_role("button", name="Save prescription").click()
    expect(dr.locator(".toast", has_text="Not saved: a medicine matches a recorded allergy")).to_be_visible()
    _no_js_errors(rc, dr)
