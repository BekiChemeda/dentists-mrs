import pytest
from rest_framework.test import APIClient

from apps.accounts.catalog import PERMISSIONS, ROLES
from apps.accounts.models import Permission, Role, User
from apps.audit.models import AuditEvent
from conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_catalog_seeded_by_migration():
    assert set(Permission.objects.values_list("code", flat=True)) == set(PERMISSIONS)
    assert set(Role.objects.values_list("code", flat=True)) == set(ROLES)
    for code, (_, _, perms) in ROLES.items():
        assert set(Role.objects.get(code=code).permissions.values_list("code", flat=True)) == set(perms)


def test_system_admin_has_no_patient_access():
    perms = set(Role.objects.get(code="system_admin").permissions.values_list("code", flat=True))
    assert not any(p.startswith(("patients.", "clinical.")) for p in perms)


def test_receptionist_cannot_see_clinical_data():
    perms = set(Role.objects.get(code="receptionist").permissions.values_list("code", flat=True))
    assert "clinical.view" not in perms and "lab.view" not in perms


@pytest.mark.parametrize(
    "role, path, expected",
    [
        ("receptionist", "/api/v1/users/", 403),
        ("doctor", "/api/v1/users/", 403),
        ("cashier", "/api/v1/audit-events/", 403),
        ("clinic_admin", "/api/v1/users/", 200),
        ("clinic_admin", "/api/v1/audit-events/", 200),
        ("clinic_admin", "/api/v1/roles/", 200),
        ("clinic_admin", "/api/v1/system/health/", 403),
        ("clinic_admin", "/api/v1/system/security/", 403),
        ("clinic_director", "/api/v1/system/health/", 403),
        ("clinic_director", "/api/v1/reports/", 200),
        ("system_admin", "/api/v1/system/health/", 200),
        ("system_admin", "/api/v1/patients/", 403),
        ("system_admin", "/api/v1/billing/invoices/", 403),
        ("system_admin", "/api/v1/billing/services/", 403),
        ("system_admin", "/api/v1/reports/revenue/", 403),
        ("system_admin", "/api/v1/users/", 200),
        ("system_admin", "/api/v1/roles/", 200),
        ("system_admin", "/api/v1/permissions/", 200),
    ],
)
def test_endpoint_access_by_role(make_user, login, role, path, expected):
    client = login(make_user(role), client=APIClient())
    assert client.get(path).status_code == expected


def test_denied_access_is_audited(api, make_user, login):
    user = make_user("receptionist")
    login(user)
    response = api.get("/api/v1/users/")
    assert response.json()["error"]["code"] == "permission_denied"
    event = AuditEvent.objects.get(action="access.denied", actor=user)
    assert event.details["path"] == "/api/v1/users/"


def test_clinic_director_cannot_create_users(api, make_user, login):
    login(make_user("clinic_director"))
    nurse = Role.objects.get(code="nurse")
    response = api.post("/api/v1/users/", {"username": "x.y", "first_name": "X", "last_name": "Y",
                                           "role_ids": [str(nurse.pk)]}, format="json")
    assert response.status_code == 403


def test_user_with_multiple_roles_gets_union_of_permissions(make_user):
    user = make_user("nurse", "cashier")
    assert user.has_permissions(["triage.record", "billing.payment"])


def test_deactivated_user_has_no_permissions(make_user):
    user = make_user("system_admin", "doctor")
    user.is_active = False
    assert user.permission_codes == frozenset()


def test_permission_change_takes_effect_on_next_request(api, make_user, sysadmin, login):
    receptionist = make_user("receptionist")
    login(receptionist)
    assert api.get("/api/v1/audit-events/").status_code == 403
    role = Role.objects.get(code="receptionist")
    role.permissions.add(Permission.objects.get(code="audit.view"))
    assert api.get("/api/v1/audit-events/").status_code == 200


class TestUserManagement:
    def _create(self, client, **overrides):
        doctor_role = Role.objects.get(code="doctor")
        payload = {"username": "Hana.Tesfaye", "first_name": "Hana", "last_name": "Tesfaye",
                   "phone": "+251 911 000 000", "role_ids": [str(doctor_role.pk)]}
        payload.update(overrides)
        return client.post("/api/v1/users/", payload, format="json")

    def test_create_user_returns_one_time_password_and_audits(self, api, sysadmin, login):
        login(sysadmin)
        response = self._create(api)
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["username"] == "hana.tesfaye"
        assert body["must_change_password"] is True
        assert [r["code"] for r in body["roles"]] == ["doctor"]
        temp = body["temporary_password"]
        user = User.objects.get(username="hana.tesfaye")
        assert user.check_password(temp)
        event = AuditEvent.objects.get(action="user.create", object_id=str(user.pk))
        assert temp not in str(event.details)
        # The new user can sign in but must change password first.
        new_client = APIClient()
        assert new_client.post("/api/v1/auth/login/", {"username": "hana.tesfaye", "password": temp},
                               format="json").status_code == 200
        assert new_client.get("/api/v1/auth/me/").json()["must_change_password"] is True

    def test_duplicate_username_conflict(self, api, sysadmin, login, make_user):
        make_user(username="hana.tesfaye")
        login(sysadmin)
        response = self._create(api)
        assert response.status_code == 409

    def test_invalid_input_rejected(self, api, sysadmin, login):
        login(sysadmin)
        response = self._create(api, username="a", phone="abc", role_ids=[])
        assert response.status_code == 400
        fields = response.json()["error"]["fields"]
        assert {"username", "phone", "role_ids"} <= set(fields)

    def test_unknown_role_rejected(self, api, sysadmin, login):
        login(sysadmin)
        response = self._create(api, role_ids=["00000000-0000-0000-0000-000000000000"])
        assert response.status_code == 400

    def test_update_user_roles_audited_with_diff(self, api, sysadmin, login, make_user):
        user = make_user("nurse")
        login(sysadmin)
        cashier = Role.objects.get(code="cashier")
        response = api.patch(f"/api/v1/users/{user.pk}/", {"role_ids": [str(cashier.pk)], "job_title": "Cashier"},
                             format="json")
        assert response.status_code == 200
        event = AuditEvent.objects.get(action="user.update", object_id=str(user.pk))
        assert event.details["roles"] == {"added": ["cashier"], "removed": ["nurse"]}
        assert event.details["job_title"] == {"from": "", "to": "Cashier"}

    def test_cannot_change_own_roles(self, api, sysadmin, login):
        login(sysadmin)
        response = api.patch(f"/api/v1/users/{sysadmin.pk}/", {"role_ids": []}, format="json")
        assert response.status_code == 409

    def test_cannot_deactivate_self(self, api, sysadmin, login):
        login(sysadmin)
        assert api.post(f"/api/v1/users/{sysadmin.pk}/deactivate/").status_code == 409

    def test_cannot_remove_last_administrator(self, api, sysadmin, login, make_user):
        other_admin = make_user("system_admin")
        login(other_admin)
        # Deactivating the only *other* admin is fine while other_admin remains...
        assert api.post(f"/api/v1/users/{sysadmin.pk}/deactivate/").status_code == 200
        # ...but stripping admin permissions from the role would leave nobody.
        role = Role.objects.get(code="system_admin")
        response = api.patch(f"/api/v1/roles/{role.pk}/", {"permission_codes": ["audit.view"]}, format="json")
        assert response.status_code == 409
        assert role.permissions.filter(code="users.manage").exists()  # rolled back

    def test_deactivation_ends_sessions_and_blocks_login(self, make_user, sysadmin, login):
        user = make_user("doctor")
        user_client = login(user, client=APIClient())
        admin_client = login(sysadmin, client=APIClient())
        assert admin_client.post(f"/api/v1/users/{user.pk}/deactivate/").status_code == 200
        assert user_client.get("/api/v1/auth/me/").status_code == 401
        assert APIClient().post("/api/v1/auth/login/", {"username": user.username, "password": PASSWORD},
                                format="json").status_code == 400
        assert admin_client.post(f"/api/v1/users/{user.pk}/activate/").status_code == 200

    def test_admin_password_reset(self, make_user, sysadmin, login):
        user = make_user("doctor")
        user_client = login(user, client=APIClient())
        admin_client = login(sysadmin, client=APIClient())
        response = admin_client.post(f"/api/v1/users/{user.pk}/reset-password/")
        assert response.status_code == 200
        temp = response.json()["temporary_password"]
        assert user_client.get("/api/v1/auth/me/").status_code == 401
        user.refresh_from_db()
        assert user.must_change_password and user.check_password(temp)

    def test_locked_and_pending_filters(self, api, sysadmin, login, make_user):
        from datetime import timedelta

        from django.utils import timezone

        locked = make_user("doctor")
        User.objects.filter(pk=locked.pk).update(locked_until=timezone.now() + timedelta(minutes=5))
        pending = make_user("nurse", must_change_password=True)
        login(sysadmin)
        assert [u["id"] for u in api.get("/api/v1/users/?locked=true").json()["results"]] == [str(locked.pk)]
        assert [u["id"] for u in api.get("/api/v1/users/?pending_password=true").json()["results"]] == [
            str(pending.pk)
        ]

    def test_user_search(self, api, sysadmin, login, make_user):
        make_user("doctor", username="meron.alemu")
        login(sysadmin)
        results = api.get("/api/v1/users/?search=meron").json()["results"]
        assert [u["username"] for u in results] == ["meron.alemu"]


class TestRoleManagement:
    def test_create_custom_role(self, api, sysadmin, login):
        login(sysadmin)
        response = api.post("/api/v1/roles/", {"code": "triage_assistant", "name": "Triage assistant",
                                               "permission_codes": ["patients.view", "triage.record"]},
                            format="json")
        assert response.status_code == 201
        assert response.json()["permission_codes"] == ["patients.view", "triage.record"]
        assert AuditEvent.objects.filter(action="role.create").exists()

    def test_unknown_permission_code_rejected(self, api, sysadmin, login):
        login(sysadmin)
        role = Role.objects.get(code="cashier")
        response = api.patch(f"/api/v1/roles/{role.pk}/", {"permission_codes": ["billing.view", "make.coffee"]},
                             format="json")
        assert response.status_code == 400
        assert response.json()["error"]["fields"]["permission_codes"] == ["make.coffee"]

    def test_role_permission_change_audited(self, api, sysadmin, login):
        login(sysadmin)
        role = Role.objects.get(code="cashier")
        codes = sorted(set(role.permissions.values_list("code", flat=True)) - {"reports.financial"})
        assert api.patch(f"/api/v1/roles/{role.pk}/", {"permission_codes": codes}, format="json").status_code == 200
        event = AuditEvent.objects.get(action="role.update", object_id=str(role.pk))
        assert event.details["permissions"] == {"added": [], "removed": ["reports.financial"]}

    def test_doctor_cannot_edit_roles(self, api, make_user, login):
        login(make_user("doctor"))
        role = Role.objects.get(code="doctor")
        assert api.patch(f"/api/v1/roles/{role.pk}/", {"permission_codes": []}, format="json").status_code == 403
