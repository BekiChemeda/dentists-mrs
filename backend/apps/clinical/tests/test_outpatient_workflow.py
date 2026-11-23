"""
Integration test of a complete outpatient visit across every department, through the API,
with one signed-in client per role. Synthetic data only.
"""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.inventory.models import Item, StockMovement
from apps.laboratory.models import LabTest
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db

PATIENT = {"first_name": "Almaz", "middle_name": "Tesfaye", "last_name": "Bekele", "sex": "female",
           "birth_date": "1990-03-14", "phone": "+251 911 223 344", "city": "Adama",
           "emergency_contacts": [{"name": "Tesfaye Bekele", "relationship": "Father", "phone": "0912000000"}],
           "allergies": [{"substance": "Penicillin", "reaction": "Rash", "severity": "moderate"}]}


def ok(response, code=200):
    assert response.status_code == code, response.content
    return response.json()


def test_complete_outpatient_visit(staff):
    rc, nurse, dr, lab, ph, cash, inv, admin = (staff.receptionist, staff.nurse, staff.doctor, staff.lab_technician,
                                                staff.pharmacist, staff.cashier, staff.inventory_manager,
                                                staff.clinic_admin)
    doctor = staff.users.doctor

    # --- Registration and duplicate detection -------------------------------------------------
    patient = ok(rc.post("/api/v1/patients/", PATIENT, format="json"), 201)
    assert patient["phone"] == "0911223344"
    assert patient["mrn"].isdigit() and len(patient["mrn"]) >= 5
    dup = rc.post("/api/v1/patients/", {**PATIENT, "first_name": "Almaz", "phone": ""}, format="json")
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "possible_duplicate"
    assert dup.json()["error"]["candidates"][0]["id"] == patient["id"]
    for q in ("almaz", "0911223344", patient["mrn"]):
        assert ok(rc.get(f"/api/v1/patients/?q={q}"))["count"] == 1, q

    # --- Appointment, duplicate prevention, check-in --------------------------------------------
    at = (timezone.localtime() + datetime.timedelta(minutes=30)).isoformat()
    appt = ok(rc.post("/api/v1/appointments/", {"patient_id": patient["id"], "doctor_id": str(doctor.pk),
                                                 "scheduled_at": at, "reason": "Fever"}, format="json"), 201)
    again = rc.post("/api/v1/appointments/", {"patient_id": patient["id"], "doctor_id": str(doctor.pk),
                                              "scheduled_at": at}, format="json")
    assert again.status_code == 409
    visit = ok(rc.post(f"/api/v1/appointments/{appt['id']}/check-in/"), 201)
    assert visit["status"] == "waiting_triage" and visit["queue_number"] >= 1
    assert rc.post("/api/v1/visits/", {"patient_id": patient["id"]}, format="json").status_code == 409

    # --- Triage -----------------------------------------------------------------------------------
    bad = nurse.post(f"/api/v1/visits/{visit['id']}/vitals/", {"systolic": 80, "diastolic": 95}, format="json")
    assert bad.status_code == 400
    vitals = ok(nurse.post(f"/api/v1/visits/{visit['id']}/vitals/",
                           {"systolic": 118, "diastolic": 76, "temperature_c": "38.9", "heart_rate": 102,
                            "respiratory_rate": 20, "spo2": 97, "weight_kg": "60", "height_cm": "165", "pain_score": 3,
                            "priority": "urgent"}, format="json"), 201)
    assert vitals["bmi"] == "22.0"
    assert ok(rc.get(f"/api/v1/visits/{visit['id']}/"))["status"] == "waiting_doctor"

    # --- Consultation -----------------------------------------------------------------------------
    enc = ok(dr.post(f"/api/v1/visits/{visit['id']}/encounters/"), 201)
    assert "Penicillin" in enc["allergy_notes"]
    assert rc.get(f"/api/v1/encounters/{enc['id']}/").status_code == 403  # reception cannot read notes
    enc = ok(dr.patch(f"/api/v1/encounters/{enc['id']}/", {
        "version": enc["version"], "chief_complaint": "Fever and headache for 3 days",
        "physical_examination": "Febrile, no neck stiffness", "plan": "Antimalarial pending smear"}, format="json"))
    stale = dr.patch(f"/api/v1/encounters/{enc['id']}/", {"version": 1, "plan": "x"}, format="json")
    assert stale.status_code == 409
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": "B54", "certainty": "provisional"},
               format="json"), 201)
    amox = Item.objects.get(code="AMOX500")
    line = {"item_id": str(amox.pk), "dose": "500 mg", "frequency": "TID", "duration_days": 7, "quantity": "21"}
    # The patient's recorded penicillin allergy is caught; the doctor must change the medicine or give a reason.
    warned = dr.post(f"/api/v1/encounters/{enc['id']}/prescriptions/", {"items": [line]}, format="json")
    assert warned.status_code == 409 and warned.json()["error"]["code"] == "allergy_warning"
    rx = ok(dr.post(f"/api/v1/encounters/{enc['id']}/prescriptions/", {"items": [
        {**line, "allergy_override_reason": "Rash was with ampicillin in childhood; tolerated amoxicillin in 2024"}]},
        format="json"), 201)
    tests = [str(LabTest.objects.get(code=c).pk) for c in ("BF", "HGB")]
    order = ok(dr.post(f"/api/v1/encounters/{enc['id']}/lab-orders/", {"test_ids": tests, "priority": "urgent"},
                       format="json"), 201)
    assert order["accession_number"].startswith("L")
    enc = ok(dr.post(f"/api/v1/encounters/{enc['id']}/sign/"))
    assert enc["status"] == "signed"
    # Signing moves the patient on to other services; it does not close the visit.
    assert ok(rc.get(f"/api/v1/visits/{visit['id']}/"))["status"] == "after_consult"
    pending = ok(rc.get(f"/api/v1/visits/{visit['id']}/outstanding/"))
    assert pending["any"] and len(pending["lab_pending"]) == 2 and pending["medicines_pending"]
    early = rc.post(f"/api/v1/visits/{visit['id']}/complete/", {"outcome": "completed"}, format="json")
    assert early.status_code == 409 and early.json()["error"]["outstanding"]["lab_pending"]
    assert dr.patch(f"/api/v1/encounters/{enc['id']}/", {"version": enc["version"], "plan": "changed"},
                    format="json").status_code == 409
    enc = ok(dr.post(f"/api/v1/encounters/{enc['id']}/amendments/", {
        "field_name": "plan", "text": "Artemether/lumefantrine started", "reason": "Smear result received"},
        format="json"), 201)
    assert enc["plan"] == "Antimalarial pending smear"  # original preserved
    assert enc["amendments"][0]["original_text"] == "Antimalarial pending smear"

    # --- Laboratory -------------------------------------------------------------------------------
    items = {i["test"]["code"]: i for i in order["items"]}
    for code, value in (("BF", "P. falciparum"), ("HGB", "10.2")):
        ok(lab.post(f"/api/v1/lab/items/{items[code]['id']}/collect/"))
        assert lab.post(f"/api/v1/lab/items/{items[code]['id']}/verify/").status_code == 409  # nothing entered
        ok(lab.post(f"/api/v1/lab/items/{items[code]['id']}/result/", {"value": value}, format="json"))
    seen_by_doctor = ok(dr.get(f"/api/v1/lab/orders/{order['id']}/"))
    assert all(i["display_result"] == "" for i in seen_by_doctor["items"])  # unverified results hidden
    for code in ("BF", "HGB"):
        ok(lab.post(f"/api/v1/lab/items/{items[code]['id']}/verify/"))
    final = ok(dr.get(f"/api/v1/lab/orders/{order['id']}/"))
    flags = {i["test"]["code"]: i["flag"] for i in final["items"]}
    assert final["status"] == "completed" and flags == {"BF": "A", "HGB": "L"}
    assert Notification.objects.filter(user=doctor, kind="lab_result").exists()

    # --- Inventory receipt ---------------------------------------------------------------------
    supplier = ok(inv.post("/api/v1/inventory/suppliers/", {"name": "EPSS Adama Hub"}, format="json"), 201)
    today = timezone.localdate()
    ok(inv.post("/api/v1/inventory/purchases/", {
        "supplier_id": supplier["id"], "purchase_date": today.isoformat(), "lines": [
            {"item_id": str(amox.pk), "batch_number": "LATE", "expiry_date": str(today + datetime.timedelta(days=700)),
             "quantity": "100", "unit_cost": "1.80"},
            {"item_id": str(amox.pk), "batch_number": "EARLY", "expiry_date": str(today + datetime.timedelta(days=60)),
             "quantity": "15", "unit_cost": "1.80"}]}, format="json"), 201)

    # --- Pharmacy: FEFO dispensing ---------------------------------------------------------------
    line_id = rx["items"][0]["id"]
    assert ph.post(f"/api/v1/prescription-items/{line_id}/dispense/", {"quantity": "30"},
                   format="json").status_code == 409  # more than prescribed
    ok(ph.post(f"/api/v1/prescription-items/{line_id}/dispense/", {"quantity": "21"}, format="json"), 201)
    moves = list(StockMovement.objects.filter(kind="dispense").order_by("created_at"))
    assert [(m.batch.batch_number, m.quantity) for m in moves] == [("EARLY", Decimal("-15")), ("LATE", Decimal("-6"))]
    item = ok(ph.get(f"/api/v1/inventory/items/{amox.pk}/"))
    assert Decimal(item["on_hand"]) == Decimal("94")

    # --- Billing ----------------------------------------------------------------------------------
    invoice = ok(rc.post("/api/v1/billing/invoices/", {"patient_id": patient["id"], "visit_id": visit["id"]},
                         format="json"), 201)
    kinds = sorted(l["kind"] for l in invoice["lines"])
    assert kinds == ["consultation", "lab", "lab", "medication"]
    assert Decimal(invoice["subtotal"]) == Decimal("200") + Decimal("70") + Decimal("80") + Decimal("63.00")
    again = ok(rc.post(f"/api/v1/billing/invoices/{invoice['id']}/pull-charges/"))
    assert len(again["lines"]) == 4  # nothing billed twice
    invoice = ok(rc.post(f"/api/v1/billing/invoices/{invoice['id']}/issue/"))
    total = Decimal(invoice["total"])
    assert cash.post(f"/api/v1/billing/invoices/{invoice['id']}/payments/",
                     {"amount": str(total + 1), "method": "cash"}, format="json").status_code == 409
    assert cash.post(f"/api/v1/billing/invoices/{invoice['id']}/payments/",
                     {"amount": "100", "method": "telebirr"}, format="json").status_code == 400  # needs reference
    part = ok(cash.post(f"/api/v1/billing/invoices/{invoice['id']}/payments/",
                        {"amount": "100", "method": "telebirr", "reference": "TB12345"}, format="json"), 201)
    assert part["status"] == "partial" and part["new_payment"]["receipt_number"].startswith("RCT-")
    paid = ok(cash.post(f"/api/v1/billing/invoices/{invoice['id']}/payments/",
                        {"amount": str(total - 100), "method": "cash"}, format="json"), 201)
    assert paid["status"] == "paid" and Decimal(paid["balance"]) == 0
    assert rc.post(f"/api/v1/billing/invoices/{invoice['id']}/payments/", {"amount": "1", "method": "cash"},
                   format="json").status_code == 403  # receptionist cannot take money

    # --- Visit completion -------------------------------------------------------------------------
    pending = ok(rc.get(f"/api/v1/visits/{visit['id']}/outstanding/"))
    assert not pending["any"], pending
    done = ok(rc.post(f"/api/v1/visits/{visit['id']}/complete/", {"outcome": "completed"}, format="json"))
    assert done["status"] == "completed" and done["completed_by"]["id"] == str(staff.users.receptionist.pk)
    assert ok(rc.get(f"/api/v1/appointments/?patient={patient['id']}"))["results"][0]["status"] == "completed"
    timeline = [e["kind"] for e in ok(rc.get(f"/api/v1/visits/{visit['id']}/timeline/"))]
    for kind in ("arrived", "triage", "status.in_consultation", "lab.order", "consultation.signed", "lab.verify",
                 "pharmacy.dispense", "billing.issue", "billing.payment", "completed"):
        assert kind in timeline, (kind, timeline)

    summary = ok(cash.get("/api/v1/billing/daily-summary/"))
    assert Decimal(str(summary["collected_total"])) == total

    # --- Reports and export -----------------------------------------------------------------------
    revenue = ok(admin.get("/api/v1/reports/revenue/"))
    assert Decimal(revenue["rows"][-1]["total"]) == total
    assert cash.get("/api/v1/reports/revenue/?export=csv").status_code == 403  # no export permission
    csv_resp = admin.get("/api/v1/reports/diagnoses/?export=csv")
    assert csv_resp.status_code == 200 and "B54" in csv_resp.content.decode()
    assert AuditEvent.objects.filter(action="report.export", object_id="diagnoses").exists()
    assert AuditEvent.objects.filter(action="patient.register").exists()
    assert AuditEvent.objects.filter(action="encounter.view").exists() is False  # doctor never opened detail


def test_insufficient_stock_needs_second_person_override(staff):
    dr, ph, admin = staff.doctor, staff.pharmacist, staff.clinic_admin
    patient = ok(staff.receptionist.post("/api/v1/patients/", {**PATIENT, "phone": "0922000000"}, format="json"), 201)
    visit = ok(staff.receptionist.post("/api/v1/visits/", {"patient_id": patient["id"]}, format="json"), 201)
    enc = ok(dr.post(f"/api/v1/visits/{visit['id']}/encounters/"), 201)
    pcm = Item.objects.get(code="PCM500")
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": "R50.9"}, format="json"), 201)
    rx = ok(dr.post(f"/api/v1/encounters/{enc['id']}/prescriptions/", {"items": [
        {"item_id": str(pcm.pk), "dose": "1 g", "frequency": "QID", "quantity": "20"}]}, format="json"), 201)
    line = rx["items"][0]["id"]

    refused = ph.post(f"/api/v1/prescription-items/{line}/dispense/", {"quantity": "20"}, format="json")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "insufficient_stock"

    req = ok(ph.post(f"/api/v1/prescription-items/{line}/override-request/",
                     {"quantity": "20", "reason": "Stock delivered, not yet entered"}, format="json"), 201)
    assert ph.post(f"/api/v1/approvals/{req['id']}/approve/").status_code in (403, 409)  # not own request
    assert ok(admin.get("/api/v1/approvals/?status=pending"))["results"][0]["can_decide"] is True
    ok(admin.post(f"/api/v1/approvals/{req['id']}/approve/", {"note": "Confirmed with store"}, format="json"))
    # A batch must exist to book against.
    from apps.inventory.models import Batch

    Batch.objects.create(item=pcm, batch_number="B1", expiry_date=timezone.localdate() + datetime.timedelta(days=300))
    done = ok(ph.post(f"/api/v1/prescription-items/{line}/dispense/",
                      {"quantity": "20", "override_approval_id": req["id"]}, format="json"), 201)
    assert done["override_approval"] == req["id"]
    assert StockMovement.objects.filter(is_override=True, item=pcm).count() == 1
    again = ph.post(f"/api/v1/prescription-items/{line}/dispense/",
                    {"quantity": "1", "override_approval_id": req["id"]}, format="json")
    assert again.status_code == 409  # fully dispensed and approval already used


def test_discount_and_void_require_approval(staff):
    rc, admin = staff.receptionist, staff.clinic_admin
    patient = ok(rc.post("/api/v1/patients/", {**PATIENT, "phone": "0933000000"}, format="json"), 201)
    invoice = ok(rc.post("/api/v1/billing/invoices/", {"patient_id": patient["id"]}, format="json"), 201)
    services = ok(rc.get("/api/v1/billing/services/"))
    dressing = next(s for s in services if s["code"] == "DRESS")
    ok(rc.post(f"/api/v1/billing/invoices/{invoice['id']}/lines/", {"service_id": dressing["id"], "quantity": "2"},
               format="json"))
    invoice = ok(rc.post(f"/api/v1/billing/invoices/{invoice['id']}/issue/"))
    assert Decimal(invoice["total"]) == Decimal("300.00")
    assert rc.post(f"/api/v1/billing/invoices/{invoice['id']}/lines/", {"description": "x", "unit_price": "1"},
                   format="json").status_code == 409  # issued invoices are locked

    req = ok(rc.post(f"/api/v1/billing/invoices/{invoice['id']}/request-discount/",
                     {"amount": "50", "reason": "Hardship"}, format="json"), 201)
    assert rc.post(f"/api/v1/billing/invoices/{invoice['id']}/apply-discount/", {"approval_id": req["id"]},
                   format="json").status_code == 409  # still pending
    ok(admin.post(f"/api/v1/approvals/{req['id']}/approve/"))
    invoice = ok(rc.post(f"/api/v1/billing/invoices/{invoice['id']}/apply-discount/", {"approval_id": req["id"]},
                         format="json"))
    assert Decimal(invoice["total"]) == Decimal("250.00")

    void_req = ok(rc.post(f"/api/v1/billing/invoices/{invoice['id']}/request-void/", {"reason": "Wrong patient"},
                          format="json"), 201)
    rejected = admin.post(f"/api/v1/approvals/{void_req['id']}/reject/", {}, format="json")
    assert rejected.status_code == 400  # rejection needs a reason
    ok(admin.post(f"/api/v1/approvals/{void_req['id']}/approve/"))
    invoice = ok(rc.post(f"/api/v1/billing/invoices/{invoice['id']}/void/", {"approval_id": void_req["id"]},
                         format="json"))
    assert invoice["status"] == "void"
    assert AuditEvent.objects.filter(action="invoice.void").exists()
