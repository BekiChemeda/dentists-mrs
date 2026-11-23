"""Referral to another department of the same clinic, within one visit. Synthetic data only."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Department
from apps.audit.models import AuditEvent
from apps.clinical.models import InternalReferral
from apps.notifications.models import Notification
from apps.scheduling.models import Visit

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json() if r.content else None


@pytest.fixture
def setup(staff, make_user, login):
    p = ok(staff.receptionist.post("/api/v1/patients/", {"first_name": "Hirut", "last_name": "Synthetic", "sex": "female",
                                                          "age_years": 33, "confirm_not_duplicate": True}, format="json"), 201)
    visit = ok(staff.receptionist.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    ok(staff.nurse.post(f"/api/v1/visits/{visit['id']}/vitals/", {"chief_complaint": "Toothache", "complaint_duration": "2 days",
                                                                 "systolic": 120, "diastolic": 80, "triage_to": "opd1"},
                        format="json"), 201)
    dental = Department.objects.create(code="dental", name="Dental clinic", receives_triage=True)
    dentist = make_user("doctor", username="dentist.one")
    dentist.department = dental
    dentist.save()
    dentist_client = login(dentist, client=APIClient())
    enc = ok(staff.doctor.post(f"/api/v1/visits/{visit['id']}/encounters/", {}, format="json"), 201)
    return p, visit, enc, dentist, dentist_client


def test_refer_moves_patient_to_other_department_and_is_closed_when_seen(staff, setup):
    p, visit, enc, dentist, dentist_client = setup
    assert Visit.objects.get(pk=visit["id"]).department == "opd1"
    ref = ok(staff.doctor.post(f"/api/v1/encounters/{enc['id']}/internal-referrals/",
                               {"to_department": "dental", "urgency": "urgent", "reason": "Dental abscess"},
                               format="json"), 201)
    assert ref["status"] == "pending" and ref["from_department"] == "opd1" and ref["to_department_name"] == "Dental clinic"

    v = Visit.objects.get(pk=visit["id"])
    assert v.department == "dental" and v.status == "waiting_doctor" and v.priority == "urgent"
    assert v.assigned_doctor_id is None
    # Dental doctors are told.
    assert Notification.objects.filter(user=dentist, kind="internal_referral").exists()
    # The waiting list shows it.
    row = next(x for x in ok(staff.receptionist.get("/api/v1/visits/")) if x["id"] == visit["id"])
    assert row["department"] == "dental" and row["internal_referral"]["reason"] == "Dental abscess"

    # The dentist starts a consultation: the referral is marked seen.
    ok(dentist_client.post(f"/api/v1/visits/{visit['id']}/encounters/", {}, format="json"), 201)
    r = InternalReferral.objects.get(pk=ref["id"])
    assert r.status == "seen" and r.seen_encounter.doctor_id == dentist.pk
    docs = ok(staff.doctor.get(f"/api/v1/patients/{p['id']}/documents/"))
    assert docs["internal_referrals"][0]["seen_by"] == dentist.full_name
    assert AuditEvent.objects.filter(action="internal_referral.create").exists()


def test_refer_to_named_doctor_notifies_only_them(staff, setup):
    _p, visit, enc, dentist, _c = setup
    ok(staff.doctor.post(f"/api/v1/encounters/{enc['id']}/internal-referrals/",
                         {"to_department": "dental", "to_doctor_id": str(dentist.pk), "reason": "Extraction"},
                         format="json"), 201)
    assert Visit.objects.get(pk=visit["id"]).assigned_doctor_id == dentist.pk
    assert Notification.objects.filter(kind="internal_referral").count() == 1


def test_cancel_returns_patient_to_referring_department(staff, setup):
    _p, visit, enc, _d, _c = setup
    ref = ok(staff.doctor.post(f"/api/v1/encounters/{enc['id']}/internal-referrals/",
                               {"to_department": "dental", "reason": "x"}, format="json"), 201)
    assert staff.doctor.post(f"/api/v1/internal-referrals/{ref['id']}/cancel/", {}, format="json").status_code == 400
    ok(staff.doctor.post(f"/api/v1/internal-referrals/{ref['id']}/cancel/", {"reason": "Treated here"}, format="json"))
    v = Visit.objects.get(pk=visit["id"])
    assert v.department == "opd1" and v.assigned_doctor_id == staff.users.doctor.pk


def test_rules(staff, setup):
    _p, visit, enc, dentist, dentist_client = setup
    url = f"/api/v1/encounters/{enc['id']}/internal-referrals/"
    assert staff.doctor.post(url, {"to_department": "dental", "reason": ""}, format="json").status_code == 400
    assert staff.doctor.post(url, {"to_department": "opd1", "reason": "x"}, format="json").status_code == 400
    assert staff.doctor.post(url, {"to_department": "pharmacy", "reason": "x"}, format="json").status_code == 400
    # Another doctor cannot refer from someone else's consultation.
    assert dentist_client.post(url, {"to_department": "dental", "reason": "x"}, format="json").status_code == 409
    # Nurses and reception cannot refer.
    assert staff.nurse.post(url, {"to_department": "dental", "reason": "x"}, format="json").status_code == 403
    ok(staff.doctor.post(url, {"to_department": "dental", "reason": "x"}, format="json"), 201)
    assert staff.doctor.post(url, {"to_department": "opd2", "reason": "y"}, format="json").status_code == 409
