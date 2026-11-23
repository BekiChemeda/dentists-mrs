"""System administrator, clinic administrator and clinic director: separation of duties. Synthetic data only."""

import datetime

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Department, Role, User
from apps.audit.models import AuditEvent
from apps.core.models import ErrorEvent, SystemSettings

pytestmark = pytest.mark.django_db


def _perms(code):
    return set(Role.objects.get(code=code).permissions.values_list("code", flat=True))


def _client(make_user, login, *roles, username=None):
    return login(make_user(*roles, username=username), client=APIClient())


def _new_user(client, *role_codes, **extra):
    ids = [str(Role.objects.get(code=c).pk) for c in role_codes]
    return client.post("/api/v1/users/", {"username": extra.pop("username", "new.person"), "first_name": "New",
                                          "last_name": "Person", "role_ids": ids, **extra}, format="json")


# --- Role defaults ---------------------------------------------------------------------------
def test_system_admin_has_no_clinical_financial_or_clinic_configuration_rights():
    perms = _perms("system_admin")
    assert {"system.health.view", "system.security.manage", "users.manage", "backups.manage"} <= perms
    forbidden = ("patients.", "clinical.", "billing.", "reports.", "prescriptions.", "queue.", "lab.", "pharmacy.")
    assert not any(p.startswith(forbidden) for p in perms)
    assert "settings.manage" not in perms  # clinic services, fees and policies


def test_clinic_admin_runs_operations_without_technical_rights():
    perms = _perms("clinic_admin")
    assert {"staff.manage", "departments.manage", "announcements.manage", "settings.manage",
            "audit.operational", "queue.manage"} <= perms
    assert not perms & {"users.manage", "roles.manage", "system.health.view", "system.security.manage",
                        "backups.manage", "audit.view", "clinical.view", "clinical.write"}


def test_clinic_director_has_oversight_only():
    perms = _perms("clinic_director")
    assert {"reports.financial", "reports.staff", "billing.void.approve", "settings.manage"} <= perms
    assert not perms & {"users.manage", "staff.manage", "system.health.view", "clinical.view", "billing.payment"}


# --- Clinic administrator account limits ------------------------------------------------------
def test_clinic_admin_creates_staff_with_department(make_user, login):
    client = _client(make_user, login, "clinic_admin")
    opd = Department.objects.get(code="opd1")
    r = _new_user(client, "nurse", department_id=str(opd.pk), start_date="2026-11-01")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["department"]["code"] == "opd1" and body["start_date"] == "2026-11-01"
    assert body["temporary_password"]


@pytest.mark.parametrize("role", ["system_admin", "clinic_admin", "clinic_director"])
def test_clinic_admin_cannot_give_privileged_roles(make_user, login, role):
    client = _client(make_user, login, "clinic_admin")
    r = _new_user(client, role)
    assert r.status_code == 403
    assert not User.objects.filter(username="new.person").exists()
    assert AuditEvent.objects.filter(action="access.denied", details__reason__icontains="system administrator").exists()


@pytest.mark.parametrize("role", ["system_admin", "clinic_director"])
def test_clinic_admin_cannot_touch_privileged_accounts(make_user, login, role):
    client = _client(make_user, login, "clinic_admin")
    admin = make_user(role, username="root.admin")
    for path in ("deactivate", "reset-password", "unlock"):
        assert client.post(f"/api/v1/users/{admin.pk}/{path}/").status_code == 403
    assert client.patch(f"/api/v1/users/{admin.pk}/", {"phone": "0911000000"}, format="json").status_code == 403
    admin.refresh_from_db()
    assert admin.is_active


def test_clinic_admin_cannot_promote_ordinary_staff(make_user, login):
    client = _client(make_user, login, "clinic_admin")
    nurse = make_user("nurse")
    sysrole = Role.objects.get(code="system_admin")
    r = client.patch(f"/api/v1/users/{nurse.pk}/", {"role_ids": [str(sysrole.pk)]}, format="json")
    assert r.status_code == 403
    assert list(nurse.roles.values_list("code", flat=True)) == ["nurse"]


def test_clinic_admin_manages_ordinary_staff(make_user, login, sysadmin):
    client = _client(make_user, login, "clinic_admin")
    nurse = make_user("nurse")
    lab = Role.objects.get(code="lab_technician")
    assert client.patch(f"/api/v1/users/{nurse.pk}/", {"role_ids": [str(lab.pk)]}, format="json").status_code == 200
    assert client.post(f"/api/v1/users/{nurse.pk}/reset-password/").status_code == 200
    assert client.post(f"/api/v1/users/{nurse.pk}/deactivate/").status_code == 200


def test_clinic_admin_cannot_change_roles_or_security(make_user, login):
    client = _client(make_user, login, "clinic_admin")
    assert client.post("/api/v1/roles/", {"code": "x", "name": "X", "permission_codes": []},
                       format="json").status_code == 403
    assert client.patch("/api/v1/system/security/", {"maintenance_mode": True}, format="json").status_code == 403


def test_system_admin_can_create_any_account(make_user, login):
    client = _client(make_user, login, "system_admin")
    assert _new_user(client, "clinic_admin").status_code == 201


def test_system_admin_cannot_change_clinic_fees_or_settings(make_user, login):
    client = _client(make_user, login, "system_admin")
    assert client.patch("/api/v1/settings/clinic/", {"facility_name": "X"}, format="json").status_code == 403
    assert client.post("/api/v1/billing/services/", {}, format="json").status_code == 403


# --- Departments ------------------------------------------------------------------------------
def test_departments_seeded_and_drive_triage_destinations(make_user, login):
    client = _client(make_user, login, "nurse")
    codes = [d["code"] for d in client.get("/api/v1/departments/?triage=true").json()]
    assert codes == ["adult_eopd", "pediatric_eopd", "opd1", "opd2", "labour_ward"]


def test_clinic_admin_manages_departments(make_user, login):
    client = _client(make_user, login, "clinic_admin")
    r = client.post("/api/v1/departments/", {"code": "dental", "name": "Dental", "receives_triage": True},
                    format="json")
    assert r.status_code == 201, r.content
    dept_id = r.json()["id"]
    assert client.patch(f"/api/v1/departments/{dept_id}/", {"code": "dent"}, format="json").status_code == 400
    assert client.patch(f"/api/v1/departments/{dept_id}/", {"is_active": False}, format="json").status_code == 200
    assert AuditEvent.objects.filter(action="department.create").exists()
    nurse = _client(make_user, login, "nurse")
    assert nurse.post("/api/v1/departments/", {"code": "y", "name": "Y"}, format="json").status_code == 403


# --- Announcements ----------------------------------------------------------------------------
def test_announcement_reaches_only_its_audience(make_user, login):
    admin = _client(make_user, login, "clinic_admin")
    today = datetime.date.today().isoformat()
    lab_role = Role.objects.get(code="lab_technician")
    r = admin.post("/api/v1/announcements/", {"title": "Analyser service on Saturday", "starts_on": today,
                                              "role_ids": [str(lab_role.pk)], "level": "important"}, format="json")
    assert r.status_code == 201, r.content
    admin.post("/api/v1/announcements/", {"title": "Staff meeting", "starts_on": today}, format="json")
    lab = _client(make_user, login, "lab_technician")
    nurse = _client(make_user, login, "nurse")
    assert [a["title"] for a in lab.get("/api/v1/announcements/current/").json()] == [
        "Analyser service on Saturday", "Staff meeting"]
    assert [a["title"] for a in nurse.get("/api/v1/announcements/current/").json()] == ["Staff meeting"]
    assert nurse.post("/api/v1/announcements/", {"title": "x", "starts_on": today}, format="json").status_code == 403


# --- Audit scopes -----------------------------------------------------------------------------
def test_operational_audit_hides_security_events(make_user, login):
    user = make_user("nurse")
    login(user, client=APIClient())  # creates auth.login
    AuditEvent.objects.create(action="patient.create", object_type="patient", object_id="1")
    clinic = _client(make_user, login, "clinic_admin")
    actions = {e["action"] for e in clinic.get("/api/v1/audit-events/").json()["results"]}
    assert "patient.create" in actions and not any(a.startswith("auth.") for a in actions)
    system = _client(make_user, login, "system_admin")
    actions = {e["action"] for e in system.get("/api/v1/audit-events/").json()["results"]}
    assert "auth.login" in actions


# --- System administration --------------------------------------------------------------------
def test_health_snapshot(make_user, login):
    client = _client(make_user, login, "system_admin")
    body = client.get("/api/v1/system/health/").json()
    assert body["database"]["status"] == "ok"
    assert body["database"]["pending_migrations"] == []
    assert "memory" in body and "disk" in body and "backup" in body


def test_unexpected_error_is_recorded_without_details(make_user, login, monkeypatch):
    from apps.core import system

    def boom():
        raise RuntimeError("synthetic failure\nsecond line with data")

    monkeypatch.setattr(system, "health_snapshot", boom)
    client = _client(make_user, login, "system_admin")
    client.raise_request_exception = False
    r = client.get("/api/v1/system/health/")
    assert r.status_code == 500
    event = ErrorEvent.objects.get()
    assert event.exception_type == "builtins.RuntimeError" and event.message == "synthetic failure"
    listed = client.get("/api/v1/system/errors/").json()["results"]
    assert listed[0]["request_id"] == r.json()["error"]["request_id"]


def test_security_policy_applies_to_lockout_and_password(make_user, login, settings):
    client = _client(make_user, login, "system_admin")
    r = client.patch("/api/v1/system/security/", {"login_max_failures": 3, "password_min_length": 14},
                     format="json")
    assert r.status_code == 200, r.content
    assert client.patch("/api/v1/system/security/", {"password_min_length": settings.PASSWORD_MIN_LENGTH - 1},
                        format="json").status_code == 400
    victim = make_user("nurse", username="victim")
    anon = APIClient()
    for _ in range(3):
        anon.post("/api/v1/auth/login/", {"username": "victim", "password": "wrong"}, format="json")
    victim.refresh_from_db()
    assert victim.locked_until is not None
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        validate_password("Twelve-chars", user=victim)
    assert AuditEvent.objects.filter(action="system.security_update").exists()


def test_maintenance_mode_blocks_everyone_but_system_admins(make_user, login):
    system = _client(make_user, login, "system_admin")
    nurse = _client(make_user, login, "nurse")
    r = system.patch("/api/v1/system/security/", {"maintenance_mode": True,
                                                  "maintenance_message": "Upgrading until 14:00"}, format="json")
    assert r.status_code == 200
    blocked = nurse.get("/api/v1/patients/")
    assert blocked.status_code == 503 and blocked.json()["error"]["code"] == "maintenance"
    assert APIClient().get("/api/v1/system/status/").json() == {"maintenance_mode": True,
                                                                "maintenance_message": "Upgrading until 14:00"}
    assert system.get("/api/v1/users/").status_code == 200
    assert nurse.get("/api/v1/auth/me/").status_code == 200
    system.patch("/api/v1/system/security/", {"maintenance_mode": False}, format="json")
    assert nurse.get("/api/v1/patients/").status_code == 200
    assert AuditEvent.objects.filter(action="system.maintenance_on").exists()


def test_idle_timeout_follows_policy(make_user, login):
    from datetime import timedelta

    from django.utils import timezone

    from apps.accounts.models import UserSession

    SystemSettings.get()
    SystemSettings.objects.filter(pk=1).update(session_idle_minutes=5)
    user = make_user("nurse")
    client = login(user, client=APIClient())
    assert client.get("/api/v1/auth/me/").status_code == 200
    UserSession.objects.filter(user=user).update(last_seen_at=timezone.now() - timedelta(minutes=6))
    assert client.get("/api/v1/auth/me/").status_code == 401
    assert UserSession.objects.get(user=user).end_reason == "expired"


def test_staff_activity_report_is_for_management(make_user, login):
    director = _client(make_user, login, "clinic_director")
    r = director.get("/api/v1/reports/staff_activity/")
    assert r.status_code == 200
    nurse = _client(make_user, login, "nurse")
    assert nurse.get("/api/v1/reports/staff_activity/").status_code == 403
