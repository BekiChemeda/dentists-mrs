"""Two people editing the same record: the second save is refused, never silently overwrites. Synthetic data."""

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.patients.models import Patient

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json() if r.content else None


def _second_client(login, make_user, *roles, username):
    return login(make_user(*roles, username=username), client=APIClient())


def _patient(rc):
    body = {"first_name": "Selam", "last_name": "Synthetic", "sex": "female", "age_years": 30, "city": "Adama",
            "confirm_not_duplicate": True}
    return ok(rc.post("/api/v1/patients/", body, format="json"), 201)


def test_patient_edit_conflict_is_refused_and_names_who_changed_it(staff, login, make_user):
    a = staff.receptionist
    b = _second_client(login, make_user, "receptionist", username="second.reception")
    p = _patient(a)
    loaded = ok(a.get(f"/api/v1/patients/{p['id']}/"))
    version = loaded["row_version"]

    # B saves first.
    saved = ok(b.patch(f"/api/v1/patients/{p['id']}/", {"phone": "0911223344", "row_version": version}, format="json"))
    assert saved["row_version"] == version + 1

    # A saves with the version they loaded: refused, nothing overwritten.
    r = a.patch(f"/api/v1/patients/{p['id']}/", {"city": "Hawassa", "row_version": version}, format="json")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "edit_conflict"
    assert err["current_version"] == version + 1 and err["your_version"] == version
    assert err["changed_by"].startswith("Test Person") and err["changed_at"]
    assert "not saved" in err["message"]
    row = Patient.objects.get(pk=p["id"])
    assert row.city == "Adama" and row.phone == "0911223344"

    # After reloading, A's change goes through.
    fresh = ok(a.get(f"/api/v1/patients/{p['id']}/"))
    ok(a.patch(f"/api/v1/patients/{p['id']}/", {"city": "Hawassa", "row_version": fresh["row_version"]}, format="json"))
    assert Patient.objects.get(pk=p["id"]).city == "Hawassa"


def test_if_match_header_works_too(staff):
    rc = staff.receptionist
    p = _patient(rc)
    v = ok(rc.get(f"/api/v1/patients/{p['id']}/"))["row_version"]
    ok(rc.patch(f"/api/v1/patients/{p['id']}/", {"city": "Bahir Dar"}, format="json", HTTP_IF_MATCH=f'"{v}"'))
    r = rc.patch(f"/api/v1/patients/{p['id']}/", {"city": "Gondar"}, format="json", HTTP_IF_MATCH=f'"{v}"')
    assert r.status_code == 409


def test_saving_without_changes_does_not_count_as_a_change(staff):
    rc = staff.receptionist
    p = _patient(rc)
    v = ok(rc.get(f"/api/v1/patients/{p['id']}/"))["row_version"]
    same = ok(rc.patch(f"/api/v1/patients/{p['id']}/", {"city": "Adama", "row_version": v}, format="json"))
    assert same["row_version"] == v


def test_viewing_or_unrelated_columns_do_not_cause_false_conflicts(staff, make_user, login):
    """Signing in updates last_login; that must not make an administrator's open form stale."""
    admin = staff.clinic_admin
    nurse = make_user("nurse", username="nurse.two")
    v = ok(admin.get(f"/api/v1/users/{nurse.pk}/"))["row_version"]
    login(nurse, client=APIClient())  # last_login changes
    ok(admin.patch(f"/api/v1/users/{nurse.pk}/", {"job_title": "Senior nurse", "row_version": v}, format="json"))


def test_bad_version_value_is_a_validation_error(staff):
    rc = staff.receptionist
    p = _patient(rc)
    r = rc.patch(f"/api/v1/patients/{p['id']}/", {"city": "X", "row_version": "abc"}, format="json")
    assert r.status_code == 400


def test_requests_without_a_version_still_work(staff):
    rc = staff.receptionist
    p = _patient(rc)
    ok(rc.patch(f"/api/v1/patients/{p['id']}/", {"city": "Dire Dawa"}, format="json"))


def test_trigger_counts_changes_made_outside_the_web_app(staff):
    """A script or bulk update still moves the version on, so an open form cannot overwrite it."""
    rc = staff.receptionist
    p = _patient(rc)
    v = ok(rc.get(f"/api/v1/patients/{p['id']}/"))["row_version"]
    Patient.objects.filter(pk=p["id"]).update(city="Mekelle")
    r = rc.patch(f"/api/v1/patients/{p['id']}/", {"city": "Jimma", "row_version": v}, format="json")
    assert r.status_code == 409


def test_role_permission_change_conflicts(sysadmin, login, make_user):
    a = login(sysadmin, client=APIClient())
    b = _second_client(login, make_user, "system_admin", username="sysadmin.two")
    role = next(r for r in ok(a.get("/api/v1/roles/")) if r["code"] == "cashier")
    perms = role["permission_codes"]
    ok(b.patch(f"/api/v1/roles/{role['id']}/", {"permission_codes": perms + ["inventory.view"],
                                                 "row_version": role["row_version"]}, format="json"))
    r = a.patch(f"/api/v1/roles/{role['id']}/", {"permission_codes": perms[:-1], "row_version": role["row_version"]},
                format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "edit_conflict"


def test_user_role_change_moves_version(sysadmin, login, make_user):
    a = login(sysadmin, client=APIClient())
    target = make_user("nurse", username="nurse.three")
    body = ok(a.get(f"/api/v1/users/{target.pk}/"))
    doctor_role = next(r for r in ok(a.get("/api/v1/roles/")) if r["code"] == "doctor")
    after = ok(a.patch(f"/api/v1/users/{target.pk}/", {"role_ids": [doctor_role["id"]], "row_version": body["row_version"]},
                       format="json"))
    assert after["row_version"] == body["row_version"] + 1


@pytest.mark.parametrize("path,field,first,second", [
    ("/api/v1/settings/clinic/", "phone", "0111000001", "0111000002"),
    ("/api/v1/system/security/", "maintenance_message", "Back at 2", "Back at 3"),
])
def test_singleton_settings_conflict(path, field, first, second, sysadmin, staff, login, make_user):
    client = staff.clinic_admin if "clinic" in path else login(sysadmin, client=APIClient())
    other = (_second_client(login, make_user, "clinic_admin", username="admin.two") if "clinic" in path
             else _second_client(login, make_user, "system_admin", username="sysadmin.three"))
    v = ok(client.get(path))["row_version"]
    ok(other.patch(path, {field: first, "row_version": v}, format="json"))
    r = client.patch(path, {field: second, "row_version": v}, format="json")
    assert r.status_code == 409


def test_catalogue_records_conflict(staff, login, make_user):
    admin = staff.clinic_admin
    other = _second_client(login, make_user, "clinic_admin", username="admin.three")
    svc = ok(admin.post("/api/v1/billing/services/", {"code": "DRS", "name": "Dressing", "category": "procedure",
                                                       "price": "50.00"}, format="json"), 201)
    ok(other.patch(f"/api/v1/billing/services/{svc['id']}/", {"price": "60.00", "row_version": svc["row_version"]},
                   format="json"))
    r = admin.patch(f"/api/v1/billing/services/{svc['id']}/", {"price": "55.00", "row_version": svc["row_version"]},
                    format="json")
    assert r.status_code == 409

    dept = ok(admin.post("/api/v1/departments/", {"code": "dental", "name": "Dental"}, format="json"), 201)
    ok(other.patch(f"/api/v1/departments/{dept['id']}/", {"name": "Dental clinic", "row_version": dept["row_version"]},
                   format="json"))
    assert admin.patch(f"/api/v1/departments/{dept['id']}/", {"sort_order": 3, "row_version": dept["row_version"]},
                       format="json").status_code == 409


def test_lab_test_and_ranges_share_one_version(staff):
    lab = staff.lab_technician
    body = ok(lab.get("/api/v1/lab/tests/"))
    test = (body["results"] if isinstance(body, dict) else body)[0]
    v = test["row_version"]
    r = lab.put(f"/api/v1/lab/tests/{test['id']}/ranges/", [], format="json", HTTP_IF_MATCH=f'"{v}"')
    assert r.status_code == 200 and r["ETag"] == f'"{v + 1}"'
    # The test form loaded before the ranges changed is now behind.
    assert lab.patch(f"/api/v1/lab/tests/{test['id']}/", {"unit": "g/dL", "row_version": v},
                     format="json").status_code == 409


def test_conflicts_are_not_audited_as_changes(staff, login, make_user):
    rc = staff.receptionist
    other = _second_client(login, make_user, "receptionist", username="reception.three")
    p = _patient(rc)
    v = ok(rc.get(f"/api/v1/patients/{p['id']}/"))["row_version"]
    ok(other.patch(f"/api/v1/patients/{p['id']}/", {"city": "Adama2", "row_version": v}, format="json"))
    before = AuditEvent.objects.filter(action="patient.update", object_id=p["id"]).count()
    rc.patch(f"/api/v1/patients/{p['id']}/", {"city": "Adama3", "row_version": v}, format="json")
    assert AuditEvent.objects.filter(action="patient.update", object_id=p["id"]).count() == before
