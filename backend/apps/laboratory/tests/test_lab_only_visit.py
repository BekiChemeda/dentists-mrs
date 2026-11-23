"""Laboratory-only visit: tests requested elsewhere, no triage or consultation here. Synthetic data only."""
import pytest

from apps.laboratory.models import LabTest
from apps.scheduling.models import Visit

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json() if r.content else None


def test_lab_only_visit_end_to_end(staff):
    rc, lab, cashier = staff.receptionist, staff.lab_technician, staff.cashier
    p = ok(rc.post("/api/v1/patients/", {"first_name": "Lab", "last_name": "Only", "sex": "male", "age_years": 35,
                                         "city": "Adama", "confirm_not_duplicate": True}, format="json"), 201)
    hgb, bf = (str(LabTest.objects.get(code=c).pk) for c in ("HGB", "BF"))

    # The outside requester is required.
    r = rc.post("/api/v1/lab/walk-in/", {"patient_id": p["id"], "test_ids": [hgb], "requested_by": " "}, format="json")
    assert r.status_code == 400
    res = ok(rc.post("/api/v1/lab/walk-in/", {"patient_id": p["id"], "test_ids": [hgb, bf],
                                              "requested_by": "Dr. Synthetic Requester",
                                              "requesting_facility": "Example Health Centre"}, format="json"), 201)
    visit, order = res["visit"], res["order"]
    assert visit["kind"] == "lab_only" and visit["status"] == "after_consult"
    assert order["encounter"] is None and order["external_requester"] == "Dr. Synthetic Requester"
    # Nobody can be added twice to today's queue.
    assert rc.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json").status_code == 409

    for item in order["items"]:
        ok(lab.post(f"/api/v1/lab/items/{item['id']}/collect/"))
        if item["test"]["code"] == "HGB":
            ok(lab.post(f"/api/v1/lab/items/{item['id']}/result/", {"value": "13.5"}, format="json"))
        else:
            ok(lab.post(f"/api/v1/lab/items/{item['id']}/result/", {"value": "Negative"}, format="json"))
        ok(lab.post(f"/api/v1/lab/items/{item['id']}/verify/", {}, format="json"))

    inv = ok(cashier.post("/api/v1/billing/invoices/", {"patient_id": p["id"], "visit_id": visit["id"]}, format="json"), 201)
    assert sorted(l["kind"] for l in inv["lines"]) == ["lab", "lab"]  # no consultation fee
    inv = ok(cashier.post(f"/api/v1/billing/invoices/{inv['id']}/issue/"))
    ok(cashier.post(f"/api/v1/billing/invoices/{inv['id']}/payments/", {"amount": inv["total"], "method": "cash"},
                    format="json"), 201)
    ok(rc.post(f"/api/v1/visits/{visit['id']}/complete/", {"outcome": "completed"}, format="json"))
    assert Visit.objects.get(pk=visit["id"]).status == "completed"


def test_lab_only_needs_permission(staff):
    p = ok(staff.receptionist.post("/api/v1/patients/", {"first_name": "No", "last_name": "Access", "sex": "male",
                                                         "age_years": 35, "city": "Adama", "confirm_not_duplicate": True},
                                   format="json"), 201)
    hgb = str(LabTest.objects.get(code="HGB").pk)
    r = staff.pharmacist.post("/api/v1/lab/walk-in/", {"patient_id": p["id"], "test_ids": [hgb], "requested_by": "Dr. X"},
                              format="json")
    assert r.status_code == 403
