"""OPD morbidity report. Synthetic data only."""
import pytest
from django.utils import timezone

from apps.scheduling.models import Visit

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json() if r.content else None


def _seen(staff, first, sex, age, icd, *, earlier_visit=False):
    rc, dr = staff.receptionist, staff.doctor
    p = ok(rc.post("/api/v1/patients/", {"first_name": first, "last_name": "Synthetic", "sex": sex, "age_years": age,
                                         "city": "Adama", "confirm_not_duplicate": True}, format="json"), 201)
    if earlier_visit:  # a completed visit last year makes today's a repeat visit
        old = ok(rc.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
        Visit.objects.filter(pk=old["id"]).update(visit_date=timezone.localdate().replace(year=timezone.localdate().year - 1),
                                                  status="completed", outcome="completed")
    v = ok(rc.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    enc = ok(dr.post(f"/api/v1/visits/{v['id']}/encounters/"), 201)
    ok(dr.patch(f"/api/v1/encounters/{enc['id']}/", {"version": enc["version"], "chief_complaint": "Fever",
                                                     "plan": "Treat"}, format="json"))
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": icd}, format="json"), 201)
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/sign/"))


def test_opd_morbidity_by_sex_visit_type_and_age(staff):
    _seen(staff, "Abel", "male", 3, "B54")
    _seen(staff, "Bethel", "female", 30, "B54", earlier_visit=True)
    _seen(staff, "Chaltu", "female", 70, "J06.9")
    rows = ok(staff.clinic_admin.get("/api/v1/reports/opd_morbidity/"))["rows"]
    malaria = next(r for r in rows if r["diagnosis"].startswith("B54"))
    assert (malaria["total"], malaria["male"], malaria["female"]) == (2, 1, 1)
    assert (malaria["new"], malaria["repeat"]) == (1, 1)
    assert malaria["age_1_4"] == 1 and malaria["age_30_64"] == 1
    urti = next(r for r in rows if r["diagnosis"].startswith("J06.9"))
    assert urti["age_65"] == 1 and urti["total"] == 1
