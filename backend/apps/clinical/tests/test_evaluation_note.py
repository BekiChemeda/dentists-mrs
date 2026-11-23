"""Triage destination, evaluation note rules, prescription frequency and the waiting-list data. Synthetic data only."""
import pytest

from apps.inventory.models import Item

pytestmark = pytest.mark.django_db


def ok(response, code=200):
    assert response.status_code == code, response.content
    return response.json() if response.content else None


def _visit(staff, name="Tigist"):
    rc = staff.receptionist
    p = ok(rc.post("/api/v1/patients/", {"first_name": name, "last_name": "Synthetic", "sex": "female",
                                         "age_years": 30, "city": "Adama", "subcity_woreda": "Bole",
                                         "confirm_not_duplicate": True}, format="json"), 201)
    return p, ok(rc.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)


def test_mrn_is_a_running_five_digit_number(staff):
    a, _ = _visit(staff, "Almaz")
    b, _ = _visit(staff, "Bethel")
    assert len(a["mrn"]) == 5 and a["mrn"].isdigit()
    assert int(b["mrn"]) == int(a["mrn"]) + 1


def test_triage_destination_and_waiting_list_columns(staff):
    p, v = _visit(staff)
    bad = staff.nurse.post(f"/api/v1/visits/{v['id']}/vitals/", {"temperature_c": "37.2", "triage_to": "icu"},
                           format="json")
    assert bad.status_code == 400
    vit = ok(staff.nurse.post(f"/api/v1/visits/{v['id']}/vitals/", {
        "temperature_c": "38.4", "chief_complaint": "Fever", "complaint_duration": "3 days",
        "general_appearance": "acute_sick", "triage_to": "opd1"}, format="json"), 201)
    assert vit["triage_to"] == "opd1" and vit["complaint_duration"] == "3 days"

    queue = ok(staff.receptionist.get("/api/v1/visits/?open=true"))
    row = next(r for r in queue if r["id"] == v["id"])
    assert row["patient"]["address"] == "Bole, Adama"
    assert row["triage"]["triage_to"] == "opd1" and row["triage"]["chief_complaint"] == "Fever"
    assert row["diagnoses"] == []

    # The evaluation note starts from the triage findings.
    enc = ok(staff.doctor.post(f"/api/v1/visits/{v['id']}/encounters/"), 201)
    assert enc["complaint_duration"] == "3 days" and enc["general_appearance"] == "acute_sick"
    ok(staff.doctor.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": "B54"}, format="json"), 201)
    row = next(r for r in ok(staff.receptionist.get("/api/v1/visits/?open=true")) if r["id"] == v["id"])
    assert row["diagnoses"] == [{"code": "B54", "description": "Unspecified malaria"}]


def test_prescribing_and_signing_need_diagnosis_and_plan(staff):
    _, v = _visit(staff)
    dr = staff.doctor
    enc = ok(dr.post(f"/api/v1/visits/{v['id']}/encounters/"), 201)
    enc = ok(dr.patch(f"/api/v1/encounters/{enc['id']}/", {"version": enc["version"], "chief_complaint": "Fever"},
                      format="json"))
    pcm = str(Item.objects.get(code="PCM500").pk)
    line = {"item_id": pcm, "dose": "1 g", "frequency": "TID", "quantity": "9"}
    r = dr.post(f"/api/v1/encounters/{enc['id']}/prescriptions/", {"items": [line]}, format="json")
    assert r.status_code == 400 and "diagnoses" in r.json()["error"]["fields"]

    r = dr.post(f"/api/v1/encounters/{enc['id']}/sign/")
    assert r.status_code == 400 and {"diagnoses", "plan"} <= set(r.json()["error"]["fields"])

    ok(dr.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": "B54"}, format="json"), 201)
    # Frequency is one of the standard abbreviations; instructions are optional.
    bad = dr.post(f"/api/v1/encounters/{enc['id']}/prescriptions/",
                  {"items": [{**line, "frequency": "three times a day"}]}, format="json")
    assert bad.status_code == 400
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/prescriptions/", {"items": [line]}, format="json"), 201)

    r = dr.post(f"/api/v1/encounters/{enc['id']}/sign/")
    assert r.status_code == 400 and set(r.json()["error"]["fields"]) == {"plan"}
    enc = ok(dr.get(f"/api/v1/encounters/{enc['id']}/"))
    ok(dr.patch(f"/api/v1/encounters/{enc['id']}/", {"version": enc["version"], "plan": "Antimalarial, review in 3 days"},
                format="json"))
    assert ok(dr.post(f"/api/v1/encounters/{enc['id']}/sign/"))["status"] == "signed"


def test_investigations_and_prescription_after_signing_while_visit_open(staff):
    from apps.laboratory.models import LabTest

    _, v = _visit(staff, "Kidist")
    dr = staff.doctor
    enc = ok(dr.post(f"/api/v1/visits/{v['id']}/encounters/"), 201)
    enc = ok(dr.patch(f"/api/v1/encounters/{enc['id']}/", {"version": enc["version"], "chief_complaint": "Fever",
                                                           "plan": "Blood film, then treat"}, format="json"))
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": "R50.9"}, format="json"), 201)
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/sign/"))
    hgb = str(LabTest.objects.get(code="HGB").pk)
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/lab-orders/", {"test_ids": [hgb]}, format="json"), 201)
    pcm = str(Item.objects.get(code="PCM500").pk)
    line = {"item_id": pcm, "dose": "1 g", "frequency": "TID", "quantity": "9"}
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/prescriptions/", {"items": [line]}, format="json"), 201)
    # The signed note itself stays locked.
    assert dr.patch(f"/api/v1/encounters/{enc['id']}/", {"version": 99, "plan": "x"}, format="json").status_code == 409
    # Another doctor cannot order from it; nobody can once the visit is closed.
    from apps.accounts.models import Role, User
    from rest_framework.test import APIClient
    other = User.objects.create(username="dr.two", first_name="Two", last_name="Doctor", must_change_password=False)
    other.set_password("Synthetic-Pass-2026!"); other.save(); other.roles.set(Role.objects.filter(code="doctor"))
    c = APIClient(); c.post("/api/v1/auth/login/", {"username": "dr.two", "password": "Synthetic-Pass-2026!"}, format="json")
    assert c.post(f"/api/v1/encounters/{enc['id']}/lab-orders/", {"test_ids": [hgb]}, format="json").status_code == 409
    ok(staff.receptionist.post(f"/api/v1/visits/{v['id']}/complete/", {
        "outcome": "left_early", "note": "Left", "acknowledge_outstanding": True}, format="json"))
    assert dr.post(f"/api/v1/encounters/{enc['id']}/lab-orders/", {"test_ids": [hgb]}, format="json").status_code == 409
