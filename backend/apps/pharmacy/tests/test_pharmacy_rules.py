"""Allergy checks, controlled medicines (EFDA Directive 1121/2025), batch choice. Synthetic data only."""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.inventory.models import Batch, Item, StockMovement

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json()


def _stock(staff, code, *batches):
    item = Item.objects.get(code=code)
    sup = ok(staff.inventory_manager.post("/api/v1/inventory/suppliers/", {"name": f"Supplier {code}"}, format="json"), 201)
    today = timezone.localdate()
    ok(staff.inventory_manager.post("/api/v1/inventory/purchases/", {
        "supplier_id": sup["id"], "purchase_date": today.isoformat(), "supplier_invoice_no": "SI-1",
        "lines": [{"item_id": str(item.pk), "batch_number": b, "expiry_date": str(today + datetime.timedelta(days=d)),
                   "quantity": q, "unit_cost": "1"} for b, d, q in batches]}, format="json"), 201)
    return item


def _encounter(staff, *, age=40, allergies=(), city="Adama", weight="62", icd="F41.1"):
    rc = staff.receptionist
    p = ok(rc.post("/api/v1/patients/", {"first_name": "Rx", "sex": "female", "age_years": age, "city": city,
                                         "allergies": [{"substance": a} for a in allergies],
                                         "confirm_not_duplicate": True}, format="json"), 201)
    v = ok(rc.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    if weight:
        ok(staff.nurse.post(f"/api/v1/visits/{v['id']}/vitals/", {"weight_kg": weight}, format="json"), 201)
    enc = ok(staff.doctor.post(f"/api/v1/visits/{v['id']}/encounters/"), 201)
    if icd:
        ok(staff.doctor.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": icd}, format="json"), 201)
    return enc


def _rx(staff, enc, code, qty="10", days=5, **extra):
    item = Item.objects.get(code=code)
    line = {"item_id": str(item.pk), "dose": "1 tab", "frequency": "BID", "quantity": qty, "duration_days": days,
            **extra.pop("line", {})}
    return staff.doctor.post(f"/api/v1/encounters/{enc['id']}/prescriptions/", {"items": [line], **extra}, format="json")


def test_allergy_group_match_needs_reason(staff):
    enc = _encounter(staff, allergies=["Penicillin"])
    r = _rx(staff, enc, "AMOX500")
    assert r.status_code == 409 and r.json()["error"]["code"] == "allergy_warning"
    assert r.json()["error"]["conflicts"]["0"][0].startswith("Penicillin")
    rx = ok(_rx(staff, enc, "AMOX500", line={"allergy_override_reason": "Allergy disproved by previous tolerance"}), 201)
    line = rx["items"][0]
    assert line["strength"] == "500 mg" and line["dosage_form"] == "Capsule" and line["route"] == "oral"
    assert ok(_rx(staff, enc, "PCM500"), 201)["items"][0]["warnings"] == "Do not exceed 4 g a day"


def test_controlled_prescribing_rules(staff):
    from apps.core.models import ClinicSettings

    enc = _encounter(staff)
    # No registration number on the prescriber yet.
    assert _rx(staff, enc, "DZP5", special_form_serial="PS-0001").status_code == 409
    dr = staff.users.doctor
    dr.registration_number = "MD-0001"
    dr.save()
    # Must be alone on the prescription.
    both = staff.doctor.post(f"/api/v1/encounters/{enc['id']}/prescriptions/", {"items": [
        {"item_id": str(Item.objects.get(code="DZP5").pk), "dose": "1", "frequency": "Daily", "quantity": "5", "duration_days": 5},
        {"item_id": str(Item.objects.get(code="PCM500").pk), "dose": "1", "frequency": "TID", "quantity": "9"}],
        "special_form_serial": "PS-0001"}, format="json")
    assert both.status_code == 400
    # Needs the form serial; more than 90 days is refused.
    r = _rx(staff, enc, "DZP5", days=120)
    assert r.status_code == 400 and {"special_form_serial", "duration_days"} <= set(r.json()["error"]["fields"])
    rx = ok(_rx(staff, enc, "DZP5", qty="5", special_form_serial="PS-0001"), 201)
    assert rx["controlled_class"] == "psychotropic" and Decimal(rx["patient_weight_kg"]) == Decimal("62")
    # Narcotics are refused at a medium clinic.
    narcotic = Item.objects.create(code="MORPH10", name="Morphine", category="medicine", strength="10 mg",
                                   controlled_class="narcotic")
    assert ClinicSettings.get().facility_level == "medium_clinic"
    assert _rx(staff, enc, "MORPH10", special_form_serial="PN-1").status_code == 409
    # Under 18: refused.
    young = _encounter(staff, age=16, icd="G40.9")
    assert _rx(staff, young, "DZP5", special_form_serial="PS-2").status_code == 409
    assert narcotic


def test_controlled_dispensing_and_register(staff):
    dr = staff.users.doctor
    dr.registration_number = "MD-0001"
    dr.save()
    _stock(staff, "DZP5", ("DZ-A", 200, "30"))
    enc = _encounter(staff)
    rx = ok(_rx(staff, enc, "DZP5", qty="5", special_form_serial="PS-0009"), 201)
    line = rx["items"][0]["id"]
    ph = staff.pharmacist
    url = f"/api/v1/prescription-items/{line}/dispense/"
    assert ph.post(url, {"quantity": "5", "special_form_checked": True, "counselling_given": True},
                   format="json").status_code == 409  # pharmacist has no registration number
    p = staff.users.pharmacist
    p.registration_number = "PH-0002"
    p.save()
    assert ph.post(url, {"quantity": "3", "special_form_checked": True, "counselling_given": True},
                   format="json").status_code == 409  # must be dispensed in full, once
    r = ph.post(url, {"quantity": "5"}, format="json")
    assert r.status_code == 400 and {"special_form_checked", "counselling_given"} <= set(r.json()["error"]["fields"])
    ok(ph.post(url, {"quantity": "5", "special_form_checked": True, "counselling_given": True}, format="json"), 201)
    assert ph.post(url, {"quantity": "1", "special_form_checked": True, "counselling_given": True},
                   format="json").status_code == 409
    item = Item.objects.get(code="DZP5")
    reg = ok(ph.get(f"/api/v1/pharmacy/controlled-register/?item={item.pk}"))
    assert [r["kind"] for r in reg["rows"]] == ["Receipt", "Dispensed"] and reg["balance"] == "25.000"
    last = reg["rows"][-1]
    assert last["form_serial"] == "PS-0009" and last["prescriber_reg"] == "MD-0001" and last["issued"] == "5.000"
    csv = ph.get(f"/api/v1/pharmacy/controlled-register/?item={item.pk}&export=csv")
    assert csv.status_code == 200 and b"PS-0009" in csv.content
    assert staff.cashier.get(f"/api/v1/pharmacy/controlled-register/?item={item.pk}").status_code == 403


def test_pharmacist_batch_choice_needs_reason_when_not_fefo(staff):
    item = _stock(staff, "PCM500", ("EARLY", 30, "20"), ("LATE", 300, "20"))
    enc = _encounter(staff)
    rx = ok(_rx(staff, enc, "PCM500", qty="6"), 201)
    late = Batch.objects.get(batch_number="LATE")
    url = f"/api/v1/prescription-items/{rx['items'][0]['id']}/dispense/"
    r = staff.pharmacist.post(url, {"quantity": "6", "batch_id": str(late.pk)}, format="json")
    assert r.status_code == 400 and "batch_reason" in r.json()["error"]["fields"]
    ok(staff.pharmacist.post(url, {"quantity": "6", "batch_id": str(late.pk), "batch_reason": "Early batch in other store"},
                             format="json"), 201)
    moved = StockMovement.objects.filter(item=item, kind="dispense").get()
    assert moved.batch.batch_number == "LATE"
