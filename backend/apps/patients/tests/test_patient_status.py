"""Marking patient records inactive (moved away) or deceased, and reactivating them. Synthetic data only."""

import datetime

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.patients.models import Patient

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json() if r.content else None


def _patient(rc, first="Tsion", **extra):
    body = {"first_name": first, "last_name": "Synthetic", "sex": "female", "birth_date": "1980-03-04",
            "phone": "0911555444", "city": "Adama", "confirm_not_duplicate": True, **extra}
    return ok(rc.post("/api/v1/patients/", body, format="json"), 201)


def test_doctor_marks_deceased_and_record_is_kept_but_hidden(staff):
    p = _patient(staff.receptionist)
    died = (timezone.localdate() - datetime.timedelta(days=2)).isoformat()
    body = ok(staff.doctor.post(f"/api/v1/patients/{p['id']}/deactivate/",
                                {"kind": "deceased", "date_of_death": died, "note": "Informed by family"}, format="json"))
    assert body["is_active"] is False and body["inactive_kind"] == "deceased" and body["date_of_death"] == died
    assert body["inactivated_by_name"]

    # Hidden from everyday search, found when asked for.
    assert not ok(staff.receptionist.get("/api/v1/patients/?q=Tsion"))["results"]
    found = ok(staff.receptionist.get("/api/v1/patients/?q=Tsion&include_inactive=true"))["results"]
    assert found and found[0]["inactive_kind"] == "deceased"
    # The chart still opens, with everything in it.
    assert ok(staff.receptionist.get(f"/api/v1/patients/{p['id']}/"))["mrn"] == p["mrn"]

    # Nothing new can be added.
    r = staff.receptionist.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json")
    assert r.status_code == 409 and "deceased" in r.json()["error"]["message"]
    assert staff.receptionist.patch(f"/api/v1/patients/{p['id']}/", {"city": "X"}, format="json").status_code == 409
    assert AuditEvent.objects.filter(action="patient.deactivate", object_id=p["id"]).exists()


def test_deceased_needs_a_sensible_date(staff):
    p = _patient(staff.receptionist)
    url = f"/api/v1/patients/{p['id']}/deactivate/"
    assert staff.doctor.post(url, {"kind": "deceased"}, format="json").status_code == 400
    future = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
    assert staff.doctor.post(url, {"kind": "deceased", "date_of_death": future}, format="json").status_code == 400
    assert staff.doctor.post(url, {"kind": "deceased", "date_of_death": "1970-01-01"}, format="json").status_code == 400


def test_moved_away_needs_a_reason_and_cancels_future_appointments(staff):
    p = _patient(staff.receptionist)
    doctor = staff.users.doctor
    when = (timezone.now() + datetime.timedelta(days=3)).replace(hour=9, minute=0, second=0, microsecond=0)
    appt = ok(staff.receptionist.post("/api/v1/appointments/", {"patient_id": p["id"], "doctor_id": str(doctor.pk),
                                                                 "scheduled_at": when.isoformat()}, format="json"), 201)
    url = f"/api/v1/patients/{p['id']}/deactivate/"
    assert staff.clinic_admin.post(url, {"kind": "moved"}, format="json").status_code == 400
    ok(staff.clinic_admin.post(url, {"kind": "moved", "note": "Moved to Dire Dawa"}, format="json"))
    from apps.scheduling.models import Appointment

    cancelled = Appointment.objects.get(pk=appt["id"])
    assert cancelled.status == "cancelled" and "inactive" in cancelled.cancel_reason


def test_open_visit_must_be_closed_first(staff):
    p = _patient(staff.receptionist)
    ok(staff.receptionist.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    r = staff.doctor.post(f"/api/v1/patients/{p['id']}/deactivate/", {"kind": "other", "note": "x"}, format="json")
    assert r.status_code == 409 and "open visit" in r.json()["error"]["message"]


@pytest.mark.parametrize("role", ["receptionist", "nurse", "cashier", "lab_technician"])
def test_only_permitted_roles_change_status(staff, role):
    p = _patient(staff.receptionist)
    r = getattr(staff, role).post(f"/api/v1/patients/{p['id']}/deactivate/", {"kind": "moved", "note": "x"},
                                  format="json")
    assert r.status_code == 403


def test_reactivate_with_reason_and_history(staff):
    p = _patient(staff.receptionist)
    ok(staff.clinic_admin.post(f"/api/v1/patients/{p['id']}/deactivate/", {"kind": "moved", "note": "Moved"},
                               format="json"))
    assert staff.clinic_admin.post(f"/api/v1/patients/{p['id']}/reactivate/", {}, format="json").status_code == 400
    body = ok(staff.clinic_admin.post(f"/api/v1/patients/{p['id']}/reactivate/", {"reason": "Came back to Adama"},
                                      format="json"))
    assert body["is_active"] is True and body["inactive_kind"] == ""
    history = ok(staff.receptionist.get(f"/api/v1/patients/{p['id']}/history/"))
    assert [h["field"] for h in history[:2]] == ["status", "status"]
    ok(staff.receptionist.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)


def test_returning_patient_is_offered_the_inactive_record(staff):
    p = _patient(staff.receptionist)
    ok(staff.clinic_admin.post(f"/api/v1/patients/{p['id']}/deactivate/", {"kind": "moved", "note": "Moved"},
                               format="json"))
    r = staff.receptionist.post("/api/v1/patients/", {"first_name": "Tsion", "last_name": "Synthetic", "sex": "female",
                                                      "birth_date": "1980-03-04", "phone": "0911555444"}, format="json")
    assert r.status_code == 409
    candidates = r.json()["error"]["candidates"]
    assert candidates[0]["id"] == p["id"] and "inactive record" in candidates[0]["reason"]


def test_merged_records_cannot_be_reactivated(staff):
    keep, dup = _patient(staff.receptionist, "Almaz"), _patient(staff.receptionist, "Almaz", phone="0911000999")
    ok(staff.clinic_admin.post(f"/api/v1/patients/{keep['id']}/merge/", {"duplicate_id": dup["id"], "reason": "same"},
                               format="json"))
    r = staff.clinic_admin.post(f"/api/v1/patients/{dup['id']}/reactivate/", {"reason": "x"}, format="json")
    assert r.status_code == 409
    assert Patient.objects.get(pk=dup["id"]).merged_into_id
