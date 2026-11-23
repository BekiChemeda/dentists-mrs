"""Consultation prefill, referrals, certificates and the doctor's summary. Synthetic data only."""

import datetime

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json()


def _start(staff):
    rc = staff.receptionist
    p = ok(rc.post("/api/v1/patients/", {"first_name": "Yared", "sex": "male", "age_years": 45,
                                         "known_conditions": "Type 2 diabetes", "past_history": "Hernia repair 2015",
                                         "current_medications": "Metformin 500 mg twice daily",
                                         "confirm_not_duplicate": True}, format="json"), 201)
    v = ok(rc.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    ok(staff.nurse.post(f"/api/v1/visits/{v['id']}/vitals/", {"temperature_c": "38.2", "chief_complaint": "Painful urination"},
                        format="json"), 201)
    enc = ok(staff.doctor.post(f"/api/v1/visits/{v['id']}/encounters/"), 201)
    return p, v, enc


def test_note_prefilled_from_triage_and_record(staff):
    p, v, enc = _start(staff)
    assert enc["chief_complaint"] == "Painful urination"
    assert "Type 2 diabetes" in enc["past_medical_history"] and "Hernia repair" in enc["past_medical_history"]
    assert enc["medication_history"] == "Metformin 500 mg twice daily"
    upd = ok(staff.doctor.patch(f"/api/v1/encounters/{enc['id']}/", {
        "version": enc["version"], "complaint_duration": "3 days", "general_appearance": "acute_sick", "exam_resp": "Clear chest",
        "systems_examination": "Suprapubic tenderness", "differential_diagnosis": "Pyelonephritis",
        "non_drug_treatment": "Plenty of fluids"}, format="json"))
    assert upd["complaint_duration"] == "3 days" and upd["non_drug_treatment"] == "Plenty of fluids"
    assert upd["general_appearance"] == "acute_sick" and upd["exam_resp"] == "Clear chest"
    # General appearance is one of three fixed descriptions.
    assert staff.doctor.patch(f"/api/v1/encounters/{enc['id']}/", {"version": upd["version"],
                              "general_appearance": "Looks fine"}, format="json").status_code == 400
    too_long = staff.doctor.patch(f"/api/v1/encounters/{enc['id']}/", {"version": upd["version"],
                                                                       "complaint_duration": "x" * 61}, format="json")
    assert too_long.status_code == 400


def test_referral_and_certificate(staff):
    p, v, enc = _start(staff)
    dr = staff.doctor
    assert dr.post(f"/api/v1/encounters/{enc['id']}/referrals/", {"to_facility": "", "reason": "x"},
                   format="json").status_code == 400
    ref = ok(dr.post(f"/api/v1/encounters/{enc['id']}/referrals/", {
        "to_facility": "Adama Hospital Medical College", "to_department": "Urology", "urgency": "urgent",
        "reason": "Recurrent UTI with haematuria", "clinical_summary": "3 episodes in 6 months"}, format="json"), 201)
    assert ref["number"].startswith(f"REF-{timezone.localdate().year}-")
    # Another doctor cannot add to or cancel this doctor's documents.
    from apps.accounts.models import Role, User
    other = User.objects.create(username="dr.other", first_name="Other", last_name="Doctor", must_change_password=False)
    other.set_password("Synthetic-Pass-2026!"); other.save(); other.roles.set(Role.objects.filter(code="doctor"))
    from rest_framework.test import APIClient
    c = APIClient(); c.post("/api/v1/auth/login/", {"username": "dr.other", "password": "Synthetic-Pass-2026!"}, format="json")
    assert c.post(f"/api/v1/referrals/{ref['id']}/cancel/", {"reason": "x"}, format="json").status_code == 409

    today = timezone.localdate()
    bad = dr.post(f"/api/v1/encounters/{enc['id']}/certificates/", {"kind": "sick_leave"}, format="json")
    assert bad.status_code == 400
    cert = ok(dr.post(f"/api/v1/encounters/{enc['id']}/certificates/", {
        "kind": "sick_leave", "start_date": today.isoformat(), "end_date": (today + datetime.timedelta(days=2)).isoformat(),
        "include_diagnosis": True, "diagnosis_text": "Urinary tract infection"}, format="json"), 201)
    assert cert["days"] == 3 and cert["diagnosis_text"] == "Urinary tract infection"
    no_dx = ok(dr.post(f"/api/v1/encounters/{enc['id']}/certificates/", {
        "kind": "attendance", "diagnosis_text": "should not be kept"}, format="json"), 201)
    assert no_dx["diagnosis_text"] == ""  # only printed with the patient's agreement
    docs = ok(dr.get(f"/api/v1/patients/{p['id']}/documents/"))
    assert len(docs["referrals"]) == 1 and len(docs["certificates"]) == 2
    ok(dr.post(f"/api/v1/certificates/{cert['id']}/cancel/", {"reason": "Wrong dates"}, format="json"))
    # Receptionists do not see clinical documents.
    assert staff.receptionist.get(f"/api/v1/patients/{p['id']}/documents/").status_code == 403


def test_clinical_summary(staff):
    p, v, enc = _start(staff)
    s = ok(staff.doctor.get(f"/api/v1/patients/{p['id']}/clinical-summary/"))
    assert s["current_medications"].startswith("Metformin") and s["visit_count"] == 1
    assert staff.cashier.get(f"/api/v1/patients/{p['id']}/clinical-summary/").status_code == 403


def test_diagnosis_must_be_icd_coded(staff):
    """The physician diagnosis is chosen from ICD-10; free text alone is refused (and never a server error)."""
    _, _, enc = _start(staff)
    r = staff.doctor.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"description": "Viral syndrome"}, format="json")
    assert r.status_code == 400 and "icd_code" in r.json()["error"]["fields"]
    dx = ok(staff.doctor.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": "b54"}, format="json"), 201)
    assert dx["description"] == "Unspecified malaria"
