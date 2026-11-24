"""Treatment plans, procedure records, materials, billing and recalls. Synthetic data only."""

import datetime
from decimal import Decimal

import pytest

from apps.billing.models import InvoiceLine
from apps.dental.models import ProcedureRecord, Recall, TreatmentPlanRevision
from apps.inventory.models import StockMovement

from .conftest import ok, procedure, term

pytestmark = pytest.mark.django_db


def _price(dental, catalog_data, code, price):
    p = procedure(catalog_data, code)
    full = next(x for x in ok(dental.clinic_admin.get("/api/v1/dental/procedures/?all=1")) if x["id"] == p["id"])
    return ok(dental.clinic_admin.patch(f"/api/v1/dental/procedures/{p['id']}/",
                                        {"price": price, "row_version": full["row_version"]}, format="json"))


def _sign_exam(dental, enc):
    enc = ok(dental.dentist.get(f"/api/v1/dental/encounters/{enc['id']}/"))
    ok(dental.dentist.patch(f"/api/v1/dental/encounters/{enc['id']}/", {
        "version": enc["version"], "chief_complaint": "Toothache", "assessment": "See chart"}, format="json"))
    return ok(dental.dentist.post(f"/api/v1/dental/encounters/{enc['id']}/sign/"))


def _plan(dental, patient_id, items, catalog_data, enc=None):
    plan = ok(dental.dentist.post(f"/api/v1/dental/patients/{patient_id}/plans/", {
        "title": "Restore lower left", "encounter_id": enc["id"] if enc else None}, format="json"), 201)
    for code, where in items:
        plan = ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/items/",
                                      {"procedure_id": procedure(catalog_data, code)["id"], **where},
                                      format="json"), 201)
    return plan


# --------------------------------------------------------------------------- plans
def test_plan_lifecycle_partial_acceptance_and_revisions(dental, exam, catalog_data):
    _price(dental, catalog_data, "RS-COMP2", "1500.00")
    _price(dental, catalog_data, "OS-EXT", "800.00")
    _price(dental, catalog_data, "CO-WHITE", "5000.00")
    p, _, enc = exam()
    plan = _plan(dental, p["id"], [("RS-COMP2", {"scope": "surfaces", "tooth": 36, "surfaces": "DO"}),
                                   ("OS-EXT", {"scope": "tooth", "tooth": 48}),
                                   ("CO-WHITE", {})], catalog_data, enc)
    assert plan["status"] == "draft" and plan["estimated_total"] == "7300.00"
    fees = [i["estimated_fee"] for i in plan["items"]]
    assert fees == ["1500.00", "800.00", "5000.00"]
    # A tooth is required for an extraction; whitening is not tooth-specific.
    r = dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/items/",
                            {"procedure_id": procedure(catalog_data, "OS-EXT")["id"]}, format="json")
    assert r.status_code == 400
    # Draft: an item can be removed outright.
    extra = ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/items/",
                                   {"procedure_id": procedure(catalog_data, "PR-FLU")["id"]}, format="json"), 201)
    flu = next(i for i in extra["items"] if i["procedure"]["code"] == "PR-FLU")
    plan = ok(dental.dentist.post(f"/api/v1/dental/plan-items/{flu['id']}/remove/", {}, format="json"))
    assert len(plan["items"]) == 3

    # The decision needs a presented plan.
    comp, ext, white = plan["items"]
    assert dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/decision/",
                               {"decisions": {comp["id"]: "accepted"}}, format="json").status_code == 409
    plan = ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/present/"))
    assert plan["status"] == "presented" and plan["revision"] == 1
    plan = ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/decision/", {
        "decisions": {comp["id"]: "accepted", ext["id"]: "deferred", white["id"]: "declined"},
        "note": "Patient will think about the extraction"}, format="json"))
    assert plan["status"] == "partially_accepted"
    # Estimates follow what was accepted; declined and deferred items stay visible.
    assert plan["estimated_total"] == "1500.00"
    assert {i["status"] for i in plan["items"]} == {"accepted", "deferred", "declined"}

    # After presentation, changes need a reason and are kept as revisions.
    r = dental.dentist.patch(f"/api/v1/dental/plan-items/{comp['id']}/", {"estimated_fee": "1700.00"}, format="json")
    assert r.status_code == 400
    plan = ok(dental.dentist.patch(f"/api/v1/dental/plan-items/{comp['id']}/",
                                   {"estimated_fee": "1700.00", "reason": "Material cost changed"}, format="json"))
    revs = ok(dental.dentist.get(f"/api/v1/dental/plans/{plan['id']}/revisions/"))
    assert [r["revision"] for r in revs] == [1, 2]
    assert revs[0]["snapshot"]["items"][0]["estimated_fee"] == "1500.00"  # the original proposal is kept
    assert revs[1]["snapshot"]["items"][0]["estimated_fee"] == "1700.00"
    # The assistant cannot plan.
    assert dental.dental_assistant.post(f"/api/v1/dental/plans/{plan['id']}/present/").status_code == 403


def _record(dental, enc, item=None, code=None, client=None, **extra):
    client = client or dental.dentist
    body = {"plan_item_id": item["id"]} if item else {"procedure_id": code, **extra}
    return client.post(f"/api/v1/dental/encounters/{enc['id']}/procedures/", body, format="json")


def _sign(dental, rec, outcome="completed", client=None, **extra):
    client = client or dental.dentist
    return client.post(f"/api/v1/dental/procedure-records/{rec['id']}/sign/", {"outcome": outcome, **extra},
                       format="json")


def _invoice(dental, visit):
    r = dental.cashier.post("/api/v1/billing/invoices/", {"patient_id": visit["patient"]["id"],
                                                          "visit_id": visit["id"]}, format="json")
    assert r.status_code in (200, 201), r.content  # 200: the visit's open draft is reused
    return ok(dental.cashier.post(f"/api/v1/billing/invoices/{r.json()['id']}/pull-charges/"))


def test_filling_flow_with_stock_billing_and_no_double_billing(dental, exam, catalog_data):
    _price(dental, catalog_data, "RS-COMP2", "1500.00")
    p, v, enc = exam()
    plan = _plan(dental, p["id"], [("RS-COMP2", {"scope": "surfaces", "tooth": 36, "surfaces": "MO"})], catalog_data, enc)
    plan = ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/present/"))
    item = plan["items"][0]
    # Not accepted yet: cannot be carried out.
    assert _record(dental, enc, item).status_code == 409
    ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/decision/", {"decisions": {item["id"]: "accepted"}},
                           format="json"))
    # Material: a consumable with stock; an instrument is refused.
    comp = ok(dental.inventory_manager.post("/api/v1/inventory/items/", {
        "code": "COMP-A2", "name": "Composite A2", "category": "restorative", "unit": "g", "pack_unit": "syringe",
        "units_per_pack": "4"}, format="json"), 201)
    mirror = ok(dental.inventory_manager.post("/api/v1/inventory/items/", {
        "code": "MIRROR", "name": "Mouth mirror", "category": "instrument", "unit": "unit"}, format="json"), 201)
    sup = ok(dental.inventory_manager.post("/api/v1/inventory/suppliers/", {"name": "Synthetic Dental Supply"},
                                          format="json"), 201)
    ok(dental.inventory_manager.post("/api/v1/inventory/purchases/", {
        "supplier_id": sup["id"], "purchase_date": str(datetime.date.today()),
        "lines": [{"item_id": comp["id"], "batch_number": "B1", "quantity": "8", "unit_cost": "100",
                   "expiry_date": str(datetime.date.today() + datetime.timedelta(days=400))}]}, format="json"), 201)
    # The assistant prepares the record for the dentist; only the dentist can sign it.
    rec = ok(_record(dental, enc, item, client=dental.dental_assistant), 201)
    assert rec["performed_by"]["username"] == "dentist" and rec["session_number"] == 1
    r = dental.dental_assistant.put(f"/api/v1/dental/procedure-records/{rec['id']}/materials/",
                                    {"materials": [{"item_id": mirror["id"], "quantity": "1"}]}, format="json")
    assert r.status_code == 400
    ok(dental.dental_assistant.put(f"/api/v1/dental/procedure-records/{rec['id']}/materials/",
                                   {"materials": [{"item_id": comp["id"], "quantity": "0.5"}]}, format="json"))
    assert not StockMovement.objects.filter(reference_type="dental_procedure").exists()  # nothing until signed
    assert _sign(dental, rec, client=dental.dental_assistant).status_code == 403
    assert _sign(dental, rec, client=dental.dentist2).status_code == 403  # not the performer
    # Unsigned: visit completion is blocked.
    signed_exam = _sign_exam(dental, enc)
    r = dental.receptionist.post(f"/api/v1/visits/{v['id']}/complete/", {"outcome": "completed",
                                                                         "acknowledge_outstanding": True,
                                                                         "note": "x"}, format="json")
    assert r.status_code == 409 and "procedure record" in str(r.json())
    rec = ok(_sign(dental, rec))
    assert rec["status"] == "completed" and rec["price"] == "1500.00"
    mv = StockMovement.objects.get(reference_type="dental_procedure", reference_id=rec["id"])
    assert mv.quantity == Decimal("-0.5")
    plan = ok(dental.dentist.get(f"/api/v1/dental/plans/{plan['id']}/"))
    assert plan["status"] == "completed" and plan["items"][0]["status"] == "completed"
    # Billing pulls the procedure once; a second invoice cannot bill it again.
    inv = _invoice(dental, {**v, "patient": p})
    lines = [l for l in inv["lines"] if l["kind"] == "procedure"]
    assert len(lines) == 1 and lines[0]["unit_price"] == "1500.00" and "36 MO" in lines[0]["description"]
    # Pulling again, or after issuing on a new invoice, never adds the procedure a second time.
    inv2 = _invoice(dental, {**v, "patient": p})
    assert len([l for l in inv2["lines"] if l["kind"] == "procedure"]) == 1
    ok(dental.cashier.post(f"/api/v1/billing/invoices/{inv['id']}/issue/"))
    inv3 = _invoice(dental, {**v, "patient": p})
    assert inv3["id"] != inv["id"] and not [l for l in inv3["lines"] if l["kind"] == "procedure"]
    assert InvoiceLine.objects.filter(source_type="dental_procedure", source_id=rec["id"], is_void=False).count() == 1
    detail = ok(dental.dentist.get(f"/api/v1/dental/procedure-records/{rec['id']}/"))
    assert detail["billed"]["invoice_number"] == inv["number"]
    # A price change later does not change what was charged.
    _price(dental, catalog_data, "RS-COMP2", "2000.00")
    assert ProcedureRecord.objects.get(pk=rec["id"]).price == Decimal("1500.00")
    # Signed: corrections by amendment only.
    r = dental.dentist.patch(f"/api/v1/dental/procedure-records/{rec['id']}/", {"version": rec["version"], "notes": "x"},
                             format="json")
    assert r.status_code == 409
    ok(dental.dentist.post(f"/api/v1/dental/procedure-records/{rec['id']}/amendments/",
                           {"field_name": "notes", "text": "Rubber dam used", "reason": "Omitted"}, format="json"))
    assert signed_exam["status"] == "signed"


def test_root_canal_over_three_sessions_billed_per_session(dental, exam, catalog_data):
    _price(dental, catalog_data, "EN-RCT", "1200.00")
    p, v, enc = exam()
    plan = _plan(dental, p["id"], [("EN-RCT", {"scope": "tooth", "tooth": 46})], catalog_data, enc)
    ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/present/"))
    item = plan["items"][0]
    ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/decision/", {"decisions": {item["id"]: "accepted"}},
                           format="json"))
    rec1 = ok(_record(dental, enc, item), 201)
    # Only one unsigned record per item at a time.
    assert _record(dental, enc, item).status_code == 409
    rec1 = ok(_sign(dental, rec1, "session_completed"))
    plan = ok(dental.dentist.get(f"/api/v1/dental/plans/{plan['id']}/"))
    assert plan["status"] == "in_progress" and plan["items"][0]["status"] == "in_progress"
    assert plan["items"][0]["sessions_done"] == 1
    # The follow-up recall for the next session was created.
    assert Recall.objects.filter(patient_id=p["id"], kind="rct_continuation", source_procedure_id=rec1["id"]).exists()
    rec2 = ok(_record(dental, enc, item), 201)
    assert rec2["session_number"] == 2
    ok(_sign(dental, rec2, "session_completed"))
    rec3 = ok(_record(dental, enc, item), 201)
    ok(_sign(dental, rec3, "completed"))
    plan = ok(dental.dentist.get(f"/api/v1/dental/plans/{plan['id']}/"))
    assert plan["status"] == "completed"
    _sign_exam(dental, enc)
    inv = _invoice(dental, {**v, "patient": p})
    assert len([l for l in inv["lines"] if l["kind"] == "procedure"]) == 3  # per-session billing
    # A completed item cannot be carried out again.
    assert _record(dental, enc, item).status_code in (409, 400)


def test_not_performed_is_not_billed_and_needs_reason(dental, exam, catalog_data):
    _price(dental, catalog_data, "OS-EXT", "800.00")
    p, v, enc = exam()
    rec = ok(_record(dental, enc, code=procedure(catalog_data, "OS-EXT")["id"], scope="tooth", tooth=38), 201)
    assert _sign(dental, rec, "not_performed").status_code == 400
    rec = ok(_sign(dental, rec, "not_performed", reason="Patient too anxious; referred"))
    assert rec["price"] is None
    _sign_exam(dental, enc)
    inv = _invoice(dental, {**v, "patient": p})
    assert not [l for l in inv["lines"] if l["kind"] == "procedure"]


def test_discard_draft_and_role_policy(dental, exam, catalog_data):
    p, v, enc = exam()
    ext = procedure(catalog_data, "OS-SEXT")
    full = next(x for x in ok(dental.clinic_admin.get("/api/v1/dental/procedures/?all=1")) if x["id"] == ext["id"])
    ok(dental.clinic_admin.patch(f"/api/v1/dental/procedures/{ext['id']}/",
                                 {"performer_roles": ["dentist"], "row_version": full["row_version"]}, format="json"))
    # A hygienist may not perform a surgical extraction under this clinic's policy.
    r = _record(dental, enc, code=ext["id"], scope="tooth", tooth=38,
                performed_by_id=str(dental.users.dental_hygienist.pk))
    assert r.status_code == 403
    rec = ok(_record(dental, enc, code=ext["id"], scope="tooth", tooth=38), 201)
    assert dental.dentist.post(f"/api/v1/dental/procedure-records/{rec['id']}/discard/", {"reason": ""},
                               format="json").status_code == 400
    ok(dental.dentist.post(f"/api/v1/dental/procedure-records/{rec['id']}/discard/", {"reason": "Wrong tooth"},
                           format="json"), 204)
    assert not ProcedureRecord.objects.filter(pk=rec["id"]).exists()


def test_dental_prescription_with_and_without_pharmacy(dental, exam, sysadmin, login):
    from rest_framework.test import APIClient

    from apps.inventory.models import Item

    amox = Item.objects.filter(category="medicine").first()
    p, v, enc = exam()
    rx = ok(dental.dentist.post(f"/api/v1/dental/encounters/{enc['id']}/prescriptions/", {"items": [
        {"item_id": str(amox.pk), "dose": "1 tab", "frequency": "TID", "duration_days": 5, "quantity": "15"}]},
        format="json"), 201)
    assert rx["status"] == "active" and rx["dental_encounter"] == enc["id"] and rx["visit_id"] == v["id"]
    assert dental.dental_assistant.post(f"/api/v1/dental/encounters/{enc['id']}/prescriptions/", {"items": []},
                                        format="json").status_code == 403
    # Without the pharmacy module: printed for an outside pharmacy, and closing the visit does not wait for it.
    admin = login(sysadmin, client=APIClient())
    from apps.clinical.models import Prescription

    Prescription.objects.filter(pk=rx["id"]).update(status="cancelled")
    ok(admin.patch("/api/v1/system/modules/pharmacy/", {"enabled": False}, format="json"))
    rx2 = ok(dental.dentist.post(f"/api/v1/dental/encounters/{enc['id']}/prescriptions/", {"items": [
        {"drug_name": "Ibuprofen 400 mg", "dose": "1 tab", "frequency": "TID", "quantity": "10"}]}, format="json"), 201)
    assert rx2["status"] == "external"
    _sign_exam(dental, enc)
    out = ok(dental.receptionist.get(f"/api/v1/visits/{v['id']}/outstanding/"))
    assert not out["medicines_pending"]


def test_consultation_fee_setting_for_dental_visits(dental, exam, catalog_data):
    p, v, enc = exam()
    _sign_exam(dental, enc)
    inv = _invoice(dental, {**v, "patient": p})
    assert not [l for l in inv["lines"] if l["kind"] == "consultation"]  # billed by procedure by default
    s = ok(dental.clinic_admin.get("/api/v1/settings/clinic/"))
    ok(dental.clinic_admin.patch("/api/v1/settings/clinic/", {"bill_consultation_for_dental": True,
                                                              "row_version": s["row_version"]}, format="json"))
    inv = ok(dental.cashier.post(f"/api/v1/billing/invoices/{inv['id']}/pull-charges/"))
    assert [l for l in inv["lines"] if l["kind"] == "consultation"]


def test_recall_worklist_book_and_attend(dental, exam, catalog_data, patient):
    p = patient("Tigist", sex="female")
    ok(dental.dentist.post(f"/api/v1/dental/patients/{p['id']}/recalls/", {
        "kind": "preventive", "due_date": str(datetime.date.today() + datetime.timedelta(days=1)),
        "note": "Six-month check"}, format="json"), 201)
    rows = ok(dental.receptionist.get("/api/v1/dental/recalls/"))["results"]
    row = next(r for r in rows if r["patient"]["id"] == p["id"])
    assert row["note"] == "" and row["kind_label"] == "Preventive recall"  # reception does not see clinical notes
    # Unreachable needs a logged attempt.
    assert dental.receptionist.post(f"/api/v1/dental/recalls/{row['id']}/status/",
                                    {"status": "unreachable", "reason": "No answer"}, format="json").status_code == 409
    ok(dental.receptionist.post(f"/api/v1/dental/recalls/{row['id']}/contact/", {"outcome": "reached"}, format="json"))
    when = (datetime.datetime.now().astimezone() + datetime.timedelta(days=1)).replace(hour=10, minute=0, second=0,
                                                                                         microsecond=0)
    appt = ok(dental.receptionist.post("/api/v1/appointments/", {
        "patient_id": p["id"], "doctor_id": str(dental.users.dentist.pk), "scheduled_at": when.isoformat()},
        format="json"), 201)
    booked = ok(dental.receptionist.post(f"/api/v1/dental/recalls/{row['id']}/book/", {"appointment_id": appt["id"]},
                                         format="json"))
    assert booked["status"] == "booked"
    # The appointment is cancelled: the recall is due again.
    ok(dental.receptionist.post(f"/api/v1/appointments/{appt['id']}/cancel/", {"reason": "Travelling"}, format="json"))
    rows = ok(dental.receptionist.get("/api/v1/dental/recalls/"))["results"]
    assert next(r for r in rows if r["id"] == row["id"])["status"] == "due"


def test_appointment_types_and_chair_conflicts(dental, patient):
    from apps.accounts.models import Room

    chair = Room.objects.create(name="Chair 1")
    types = ok(dental.receptionist.get("/api/v1/appointment-types/"))
    rct = next(t for t in types if t["code"] == "root-canal")
    assert rct["default_minutes"] == 60
    a, b = patient("Almaz", sex="female"), patient("Kebede")
    when = (datetime.datetime.now().astimezone() + datetime.timedelta(days=2)).replace(hour=9, minute=0, second=0,
                                                                                         microsecond=0)
    while when.weekday() >= 5:
        when += datetime.timedelta(days=1)
    first = ok(dental.receptionist.post("/api/v1/appointments/", {
        "patient_id": a["id"], "doctor_id": str(dental.users.dentist.pk), "scheduled_at": when.isoformat(),
        "appointment_type_id": rct["id"], "room_id": str(chair.pk)}, format="json"), 201)
    assert first["duration_minutes"] == 60 and first["room"]["name"] == "Chair 1"
    assert first["appointment_type"]["code"] == "root-canal"
    # Another dentist, same chair, overlapping: refused.
    r = dental.receptionist.post("/api/v1/appointments/", {
        "patient_id": b["id"], "doctor_id": str(dental.users.dentist2.pk),
        "scheduled_at": (when + datetime.timedelta(minutes=30)).isoformat(), "room_id": str(chair.pk)}, format="json")
    assert r.status_code == 409 and "Chair 1" in r.json()["error"]["message"]
    ok(dental.receptionist.post("/api/v1/appointments/", {
        "patient_id": b["id"], "doctor_id": str(dental.users.dentist2.pk),
        "scheduled_at": (when + datetime.timedelta(minutes=60)).isoformat(), "room_id": str(chair.pk)}, format="json"),
       201)
    # Clinic administrators maintain appointment types; reception cannot.
    assert dental.receptionist.post("/api/v1/appointment-types/", {"code": "x", "name": "X", "category": "review"},
                                    format="json").status_code == 403
    ok(dental.clinic_admin.post("/api/v1/appointment-types/", {"code": "implant-review", "name": "Implant review",
                                                                "category": "review", "default_minutes": 20},
                                format="json"), 201)


def test_plan_item_links_to_appointments_without_completing(dental, exam, catalog_data):
    p, v, enc = exam()
    plan = _plan(dental, p["id"], [("PS-CRPREP", {"scope": "tooth", "tooth": 16}),
                                   ("PS-CRFIT", {"scope": "tooth", "tooth": 16})], catalog_data, enc)
    ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/present/"))
    prep, fit = plan["items"]
    ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/decision/",
                           {"decisions": {prep["id"]: "accepted", fit["id"]: "accepted"}}, format="json"))
    when = (datetime.datetime.now().astimezone() + datetime.timedelta(days=14)).replace(hour=9, minute=0, second=0,
                                                                                          microsecond=0)
    while when.weekday() >= 5:
        when += datetime.timedelta(days=1)
    appt = ok(dental.dentist.post("/api/v1/appointments/", {
        "patient_id": p["id"], "doctor_id": str(dental.users.dentist.pk), "scheduled_at": when.isoformat()},
        format="json"), 201)
    plan = ok(dental.dentist.post(f"/api/v1/dental/plan-items/{fit['id']}/appointments/",
                                  {"appointment_id": appt["id"]}, format="json"))
    fit_now = next(i for i in plan["items"] if i["id"] == fit["id"])
    assert fit_now["status"] == "accepted" and fit_now["appointments"][0]["id"] == appt["id"]
    # Cancelling the plan needs a reason and keeps the history.
    assert dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/cancel/", {"reason": ""},
                               format="json").status_code == 400
    plan = ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/cancel/", {"reason": "Patient moved"},
                                  format="json"))
    assert plan["status"] == "cancelled" and all(i["status"] == "cancelled" for i in plan["items"])
    assert TreatmentPlanRevision.objects.filter(plan_id=plan["id"]).count() == 2


def test_diagnosis_linked_to_plan_cannot_be_removed(dental, exam, catalog_data):
    p, v, enc = exam()
    dx = ok(dental.dentist.post(f"/api/v1/dental/encounters/{enc['id']}/diagnoses/", {
        "term_id": term(dental, "K04.0")["id"], "scope": "tooth", "tooth": 46}, format="json"), 201)
    ok(dental.dentist.post(f"/api/v1/dental/patients/{p['id']}/plans/", {"title": "RCT 46", "diagnosis_ids": [dx["id"]]},
                           format="json"), 201)
    assert dental.dentist.post(f"/api/v1/dental/diagnoses/{dx['id']}/remove/").status_code == 409


def test_deferred_item_keeps_the_plan_open_until_decided(dental, exam, catalog_data):
    """A deferred item may be accepted later (clinical-workflows.md): finishing the accepted work must not close the
    plan while something is still deferred."""
    p, _, enc = exam()
    plan = _plan(dental, p["id"], [("RS-COMP2", {"scope": "surfaces", "tooth": 36, "surfaces": "DO"}),
                                   ("OS-EXT", {"scope": "tooth", "tooth": 48})], catalog_data, enc)
    comp, ext = plan["items"]
    ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/present/"))
    ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/decision/",
                           {"decisions": {comp["id"]: "accepted", ext["id"]: "deferred"}}, format="json"))
    rec = ok(_record(dental, enc, item=comp), 201)
    ok(_sign(dental, rec))
    plan = ok(dental.dentist.get(f"/api/v1/dental/plans/{plan['id']}/"))
    assert plan["status"] == "in_progress"
    # The patient comes back for the extraction: it can still be accepted and carried out.
    plan = ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/decision/",
                                  {"decisions": {ext["id"]: "accepted"}}, format="json"))
    assert {i["status"] for i in plan["items"]} == {"completed", "accepted"}
    rec = ok(_record(dental, enc, item=ext), 201)
    ok(_sign(dental, rec))
    plan = ok(dental.dentist.get(f"/api/v1/dental/plans/{plan['id']}/"))
    assert plan["status"] == "completed"


def test_declining_the_deferred_item_completes_the_plan(dental, exam, catalog_data):
    p, _, enc = exam()
    plan = _plan(dental, p["id"], [("RS-COMP2", {"scope": "surfaces", "tooth": 36, "surfaces": "DO"}),
                                   ("OS-EXT", {"scope": "tooth", "tooth": 48})], catalog_data, enc)
    comp, ext = plan["items"]
    ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/present/"))
    ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/decision/",
                           {"decisions": {comp["id"]: "accepted", ext["id"]: "deferred"}}, format="json"))
    ok(_sign(dental, ok(_record(dental, enc, item=comp), 201)))
    plan = ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/decision/",
                                  {"decisions": {ext["id"]: "declined"}}, format="json"))
    assert plan["status"] == "completed"
    assert {i["status"] for i in plan["items"]} == {"completed", "declined"}


def test_procedure_price_edits_are_audited_with_before_and_after(dental, catalog_data):
    from apps.audit.models import AuditEvent

    for price in ("501", "500"):
        _price(dental, catalog_data, "OS-EXT", price)
    events = AuditEvent.objects.filter(action="dental_procedure_type.update").order_by("occurred_at")
    trail = [e.details["changes"]["price"] for e in events if "price" in e.details["changes"]]
    assert trail[-2:][1] == {"from": "501.00", "to": "500.00"}
    assert trail[-2:][0]["to"] == "501.00"
    # Fields that did not change are not reported as changes.
    assert set(events.last().details["changes"]) == {"price"}
