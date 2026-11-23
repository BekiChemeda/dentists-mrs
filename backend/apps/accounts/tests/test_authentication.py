from datetime import timedelta

import pytest
from django.contrib.sessions.models import Session
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import LoginAttempt, User, UserSession
from apps.audit.models import AuditEvent
from conftest import PASSWORD

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login/"
ME = "/api/v1/auth/me/"


def _post_login(client, username, password):
    return client.post(LOGIN, {"username": username, "password": password}, format="json")


class TestLogin:
    def test_success_returns_user_with_permissions_and_records_attempt(self, api, make_user):
        user = make_user("doctor")
        response = _post_login(api, user.username, PASSWORD)
        assert response.status_code == 200
        body = response.json()
        assert body["username"] == user.username
        assert "clinical.write" in body["permissions"]
        assert "users.manage" not in body["permissions"]
        assert LoginAttempt.objects.filter(user=user, succeeded=True).count() == 1
        assert AuditEvent.objects.filter(action="auth.login", actor=user, outcome="success").exists()
        assert UserSession.objects.filter(user=user, ended_at__isnull=True).count() == 1
        assert api.get(ME).status_code == 200

    def test_username_is_case_insensitive(self, api, make_user):
        user = make_user("doctor", username="abebe.k")
        assert _post_login(api, "ABEBE.K", PASSWORD).status_code == 200
        assert user.pk

    def test_wrong_password_and_unknown_user_give_same_generic_error(self, api, make_user):
        user = make_user("doctor")
        wrong = _post_login(api, user.username, "nope-nope-nope")
        unknown = _post_login(api, "no.such.user", "nope-nope-nope")
        assert wrong.status_code == unknown.status_code == 400
        assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "invalid_credentials"
        assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
        assert LoginAttempt.objects.filter(succeeded=False).count() == 2
        assert AuditEvent.objects.filter(action="auth.login", outcome="failure").count() == 2

    def test_password_never_written_to_audit(self, api, make_user):
        user = make_user("doctor")
        _post_login(api, user.username, "Secret-Wrong-123")
        for event in AuditEvent.objects.all():
            assert "Secret-Wrong-123" not in str(event.details)

    def test_inactive_user_cannot_sign_in(self, api, make_user):
        user = make_user("doctor", is_active=False)
        response = _post_login(api, user.username, PASSWORD)
        assert response.status_code == 400
        assert LoginAttempt.objects.get(user=user).failure_reason == "inactive"

    def test_login_requires_csrf_token(self, make_user):
        user = make_user("doctor")
        client = APIClient(enforce_csrf_checks=True)
        assert _post_login(client, user.username, PASSWORD).json()["error"]["code"] == "csrf_failed"
        client.get("/api/v1/auth/csrf/")
        token = client.cookies["mrs_csrftoken"].value
        response = client.post(LOGIN, {"username": user.username, "password": PASSWORD}, format="json",
                               HTTP_X_CSRFTOKEN=token)
        assert response.status_code == 200


class TestLockout:
    def test_account_locks_after_max_failures_and_rejects_correct_password(self, api, make_user, settings):
        settings.LOGIN_MAX_FAILURES = 3
        user = make_user("doctor")
        for _ in range(2):
            assert _post_login(api, user.username, "wrong-password-x").status_code == 400
        third = _post_login(api, user.username, "wrong-password-x")
        assert third.status_code == 423
        assert third.json()["error"]["code"] == "account_locked"
        assert _post_login(api, user.username, PASSWORD).status_code == 423
        assert AuditEvent.objects.filter(action="auth.account_locked", actor=user).exists()

    def test_lock_expires(self, api, make_user):
        user = make_user("doctor")
        User.objects.filter(pk=user.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
        assert _post_login(api, user.username, PASSWORD).status_code == 200

    def test_successful_login_resets_failure_counter(self, api, make_user, settings):
        settings.LOGIN_MAX_FAILURES = 3
        user = make_user("doctor")
        _post_login(api, user.username, "wrong-password-x")
        _post_login(api, user.username, "wrong-password-x")
        assert _post_login(api, user.username, PASSWORD).status_code == 200
        user.refresh_from_db()
        assert user.failed_login_count == 0

    def test_admin_can_unlock(self, api, make_user, sysadmin, login):
        user = make_user("doctor")
        User.objects.filter(pk=user.pk).update(locked_until=timezone.now() + timedelta(minutes=10))
        login(sysadmin)
        response = api.post(f"/api/v1/users/{user.pk}/unlock/")
        assert response.status_code == 200
        assert response.json()["is_locked"] is False


class TestSessions:
    def test_logout_ends_session(self, api, make_user, login):
        user = make_user("doctor")
        login(user)
        assert api.post("/api/v1/auth/logout/").status_code == 204
        assert api.get(ME).status_code == 401
        assert UserSession.objects.get(user=user).end_reason == "logout"
        assert AuditEvent.objects.filter(action="auth.logout", actor=user).exists()

    def test_revoked_session_is_rejected_immediately(self, make_user, sysadmin, login):
        user = make_user("nurse")
        user_client = login(user, client=APIClient())
        admin_client = login(sysadmin, client=APIClient())
        response = admin_client.post(f"/api/v1/users/{user.pk}/revoke-sessions/")
        assert response.status_code == 200
        assert response.json()["sessions_ended"] == 1
        assert user_client.get(ME).status_code == 401

    def test_session_hijack_after_revocation_fails_even_if_django_session_survives(self, make_user, login):
        """If the UserSession row is ended, a still-valid Django session cookie must not work."""
        user = make_user("nurse")
        client = login(user, client=APIClient())
        UserSession.objects.filter(user=user).update(ended_at=timezone.now(), end_reason="revoked")
        assert Session.objects.exists()
        assert client.get(ME).status_code == 401

    def test_absolute_session_lifetime_enforced(self, make_user, login, settings):
        user = make_user("nurse")
        client = login(user, client=APIClient())
        UserSession.objects.filter(user=user).update(
            created_at=timezone.now() - timedelta(hours=settings.SESSION_ABSOLUTE_TIMEOUT_HOURS, minutes=1)
        )
        assert client.get(ME).status_code == 401
        assert UserSession.objects.get(user=user).end_reason == "expired"

    def test_my_sessions_lists_only_own_active_sessions(self, make_user, login):
        user = make_user("nurse")
        other = make_user("doctor")
        login(other, client=APIClient())
        client = login(user, client=APIClient())
        login(user, client=APIClient())
        sessions = client.get("/api/v1/auth/sessions/").json()
        assert len(sessions) == 2
        assert sum(s["is_current"] for s in sessions) == 1


class TestPasswords:
    def test_temporary_password_blocks_everything_except_me_change_and_logout(self, api, make_user, login):
        user = make_user("system_admin", must_change_password=True)
        login(user)
        assert api.get(ME).status_code == 200
        blocked = api.get("/api/v1/users/")
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "password_change_required"

    def test_change_password_flow(self, api, make_user, login):
        user = make_user("system_admin", must_change_password=True)
        other_device = login(user, client=APIClient())
        login(user)
        response = api.post("/api/v1/auth/password/change/",
                            {"current_password": PASSWORD, "new_password": "Brand-New-Pass-77"}, format="json")
        assert response.status_code == 200, response.content
        assert response.json()["must_change_password"] is False
        # This session continues; the other device is signed out.
        assert api.get("/api/v1/users/").status_code == 200
        assert other_device.get(ME).status_code == 401
        user.refresh_from_db()
        assert user.check_password("Brand-New-Pass-77")
        assert AuditEvent.objects.filter(action="auth.password_change", outcome="success").exists()

    def test_wrong_current_password_rejected_and_audited(self, api, make_user, login):
        user = make_user("doctor")
        login(user)
        response = api.post("/api/v1/auth/password/change/",
                            {"current_password": "not-it-123", "new_password": "Brand-New-Pass-77"}, format="json")
        assert response.status_code == 400
        assert "current_password" in response.json()["error"]["fields"]
        assert AuditEvent.objects.filter(action="auth.password_change", outcome="failure").exists()

    @pytest.mark.parametrize("weak", ["short1", "1234567890123", "password1234"])
    def test_weak_passwords_rejected(self, api, make_user, login, weak):
        login(make_user("doctor"))
        response = api.post("/api/v1/auth/password/change/",
                            {"current_password": PASSWORD, "new_password": weak}, format="json")
        assert response.status_code == 400
        assert "new_password" in response.json()["error"]["fields"]

    def test_passwords_stored_with_argon2(self, make_user):
        assert make_user().password.startswith("argon2")
