"""Department activity report and the department filter on non-financial reports. Synthetic data only."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Department
from apps.reports.reports import REPORTS

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json() if r.content else None


def _visit_to(staff, first, dept):
    p = ok(staff.receptionist.post("/api/v1/patients/", {"first_name": first, "last_name": "Synthetic", "sex": "male",
                                                          "age_years": 40, "confirm_not_duplicate": True}, format="json"), 201)
    v = ok(staff.receptionist.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    ok(staff.nurse.post(f"/api/v1/visits/{v['id']}/vitals/", {"chief_complaint": "Cough", "complaint_duration": "1 week",
                                                             "triage_to": dept}, format="json"), 201)
    return v


def test_department_activity_counts_visits_waits_and_referrals(staff, make_user, login):
    Department.objects.create(code="dental", name="Dental clinic", receives_triage=True)
    v1 = _visit_to(staff, "Abel", "opd1")
    _visit_to(staff, "Biruk", "opd1")
    _visit_to(staff, "Chala", "opd2")
    enc = ok(staff.doctor.post(f"/api/v1/visits/{v1['id']}/encounters/", {}, format="json"), 201)
    ok(staff.doctor.post(f"/api/v1/encounters/{enc['id']}/internal-referrals/",
                         {"to_department": "dental", "reason": "Tooth"}, format="json"), 201)

    body = ok(staff.clinic_admin.get("/api/v1/reports/department_activity/"))
    rows = {r["department"]: r for r in body["rows"]}
    opd1 = Department.objects.get(code="opd1").name
    assert rows[opd1]["visits"] == 1 and rows[opd1]["referred_out"] == 1
    assert rows["Dental clinic"]["visits"] == 1 and rows["Dental clinic"]["referred_in"] == 1
    assert rows["Dental clinic"]["seen"] == 1 and rows["Dental clinic"]["median_wait"] is not None

    only = ok(staff.clinic_admin.get("/api/v1/reports/department_activity/?department=opd2"))
    assert [r["department"] for r in only["rows"]] == [Department.objects.get(code="opd2").name]
    assert only["department_name"] == Department.objects.get(code="opd2").name


def test_filter_on_visits_report(staff):
    _visit_to(staff, "Dawit", "opd1")
    _visit_to(staff, "Eden", "opd2")
    total = sum(r["total"] for r in ok(staff.clinic_admin.get("/api/v1/reports/visits/"))["rows"])
    opd1 = sum(r["total"] for r in ok(staff.clinic_admin.get("/api/v1/reports/visits/?department=opd1"))["rows"])
    assert total == 2 and opd1 == 1


def test_financial_reports_have_no_department_filter(staff):
    for key in ("revenue", "revenue_by_category", "outstanding"):
        assert REPORTS[key].by_department is False
        r = staff.clinic_admin.get(f"/api/v1/reports/{key}/?department=opd1")
        assert r.status_code == 400


def test_unknown_department_is_refused(staff):
    assert staff.clinic_admin.get("/api/v1/reports/visits/?department=nope").status_code == 400


def test_every_department_report_runs_with_a_filter(staff):
    for key, report in REPORTS.items():
        if report.by_department:
            ok(staff.clinic_admin.get(f"/api/v1/reports/{key}/?department=opd1"))


def test_catalog_says_which_reports_filter(staff):
    catalog = ok(staff.clinic_admin.get("/api/v1/reports/"))
    flags = {r["key"]: r["by_department"] for r in catalog}
    assert flags["department_activity"] and flags["visits"] and not flags.get("revenue", False)
