"""Merging duplicate patient records. Synthetic data only."""
import pytest

from apps.audit.models import AuditEvent
from apps.patients.models import Patient

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json() if r.content else None


def _patient(rc, first, **extra):
    body = {"first_name": first, "last_name": "Synthetic", "sex": "female", "age_years": 40, "city": "Adama",
            "confirm_not_duplicate": True, **extra}
    return ok(rc.post("/api/v1/patients/", body, format="json"), 201)


def test_merge_moves_records_and_retires_duplicate(staff):
    rc, admin = staff.receptionist, staff.clinic_admin
    keep = _patient(rc, "Almaz")
    dup = _patient(rc, "Almaz", phone="0911000111", allergies=[{"substance": "Penicillin"}])
    ok(rc.post(f"/api/v1/patients/{keep['id']}/allergies/", {"substance": "penicillin"}, format="json"), 201)
    visit = ok(rc.post("/api/v1/visits/", {"patient_id": dup["id"]}, format="json"), 201)

    # Only holders of patients.merge, and a reason is required.
    assert rc.post(f"/api/v1/patients/{keep['id']}/merge/", {"duplicate_id": dup["id"], "reason": "x"},
                   format="json").status_code == 403
    assert admin.post(f"/api/v1/patients/{keep['id']}/merge/", {"duplicate_id": dup["id"], "reason": ""},
                      format="json").status_code == 400

    res = ok(admin.post(f"/api/v1/patients/{keep['id']}/merge/", {"duplicate_id": dup["id"],
                                                                     "reason": "Registered twice on the same day"}, format="json"))
    assert res["details"]["moved"]["scheduling.Visit"] == 1
    assert res["patient"]["phone"] == "0911000111"  # filled from the duplicate
    active = [a for a in res["patient"]["allergies"] if a["is_active"]]
    assert len(active) == 1  # the same allergy on both records is kept once

    d = Patient.objects.get(pk=dup["id"])
    assert not d.is_active and str(d.merged_into_id) == keep["id"] and d.mrn == dup["mrn"]
    assert ok(rc.get(f"/api/v1/visits/{visit['id']}/"))["patient"]["id"] == keep["id"]
    # Searching the old MRN finds the surviving record.
    found = ok(rc.get(f"/api/v1/patients/?q={dup['mrn']}"))["results"]
    assert [p["id"] for p in found] == [keep["id"]]
    # Nothing new can be recorded on the retired record.
    assert rc.patch(f"/api/v1/patients/{dup['id']}/", {"city": "Bishoftu"}, format="json").status_code == 409
    assert rc.post("/api/v1/visits/", {"patient_id": dup["id"]}, format="json").status_code in (404, 409)
    assert AuditEvent.objects.filter(action="patient.merge").count() == 1


def test_merge_refuses_conflicts(staff):
    rc, admin = staff.receptionist, staff.clinic_admin
    a, b = _patient(rc, "Hiwot"), _patient(rc, "Hiwot")
    ok(rc.post("/api/v1/visits/", {"patient_id": a["id"]}, format="json"), 201)
    ok(rc.post("/api/v1/visits/", {"patient_id": b["id"]}, format="json"), 201)
    r = admin.post(f"/api/v1/patients/{a['id']}/merge/", {"duplicate_id": b["id"], "reason": "Same person"}, format="json")
    assert r.status_code == 409 and "open visit" in r.json()["error"]["message"]
    m = _patient(rc, "Hiwot", sex="male")
    r = admin.post(f"/api/v1/patients/{a['id']}/merge/", {"duplicate_id": m["id"], "reason": "Same person"}, format="json")
    assert r.status_code == 409
    assert admin.post(f"/api/v1/patients/{a['id']}/merge/", {"duplicate_id": a["id"], "reason": "x"},
                      format="json").status_code == 400
