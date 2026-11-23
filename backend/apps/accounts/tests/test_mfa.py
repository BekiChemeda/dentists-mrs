"""Two-step sign-in. All accounts and secrets are synthetic."""

import base64

import pytest
from rest_framework.test import APIClient

from apps.accounts import mfa
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.core.models import SystemSettings
from conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_rfc6238_vectors():
    # RFC 6238 Appendix B, SHA-1 secret "12345678901234567890", 8 digits.
    secret = base64.b32encode(b"12345678901234567890").decode()
    for t, expected in [(59, "94287082"), (1111111109, "07081804"), (1234567890, "89005924"),
                        (2000000000, "69279037")]:
        assert mfa.hotp(secret, t // 30, digits=8) == expected


def test_code_cannot_be_replayed_and_drift_is_limited():
    secret = mfa.new_secret()
    now = 1_800_000_000
    code = mfa.hotp(secret, now // 30)
    step = mfa.verify_totp(secret, code, last_step=None, now=now)
    assert step == now // 30
    assert mfa.verify_totp(secret, code, last_step=step, now=now) is None  # replay
    assert mfa.verify_totp(secret, mfa.hotp(secret, now // 30 - 3), last_step=None, now=now) is None


def test_secret_is_encrypted_at_rest():
    token = mfa.encrypt_secret("JBSWY3DPEHPK3PXP")
    assert "JBSWY3DPEHPK3PXP" not in token
    assert mfa.decrypt_secret(token) == "JBSWY3DPEHPK3PXP"


def _policy(rule):
    SystemSettings.get()
    SystemSettings.objects.filter(pk=1).update(mfa_required_for=rule)


def _enrol(client):
    setup = client.post("/api/v1/auth/mfa/setup/").json()
    assert setup["uri"].startswith("otpauth://totp/") and "<svg" in setup["qr_svg"]
    code = mfa.hotp(setup["secret"], mfa.current_step())
    r = client.post("/api/v1/auth/mfa/confirm/", {"code": code}, format="json")
    assert r.status_code == 200, r.content
    return setup["secret"], r.json()["recovery_codes"]


def _sign_in(username, code=None):
    c = APIClient()
    r = c.post("/api/v1/auth/login/", {"username": username, "password": PASSWORD}, format="json")
    return c, r


def test_admin_must_enrol_before_doing_anything(make_user, login):
    _policy("admins")
    admin = make_user("system_admin", username="root.admin")
    make_user("system_admin")  # a second admin, so notifications have someone to reach
    client = login(admin, client=APIClient())
    me = client.get("/api/v1/auth/me/").json()
    assert me["mfa_setup_required"] is True
    blocked = client.get("/api/v1/users/")
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "mfa_setup_required"
    _enrol(client)
    assert client.get("/api/v1/users/").status_code == 200
    assert AuditEvent.objects.filter(action="auth.mfa_enabled", object_id=str(admin.pk)).exists()


def test_policy_does_not_force_ordinary_staff(make_user, login):
    _policy("admins")
    client = login(make_user("nurse"), client=APIClient())
    assert client.get("/api/v1/auth/me/").json()["mfa_setup_required"] is False


def test_sign_in_needs_the_code_after_enrolment(make_user, login):
    user = make_user("nurse", username="nurse.mfa")
    secret, recovery = _enrol(login(user, client=APIClient()))
    c, r = _sign_in("nurse.mfa")
    assert r.json() == {"mfa_required": True, "mfa_token": r.json()["mfa_token"]}
    assert c.get("/api/v1/auth/me/").status_code == 401  # password alone is not a session
    bad = c.post("/api/v1/auth/login/mfa/", {"mfa_token": r.json()["mfa_token"], "code": "000000"}, format="json")
    assert bad.status_code == 400
    # A code from the next step (the enrolment used the current one).
    code = mfa.hotp(secret, mfa.current_step() + 1)
    ok = c.post("/api/v1/auth/login/mfa/", {"mfa_token": r.json()["mfa_token"], "code": code}, format="json")
    assert ok.status_code == 200, ok.content
    assert c.get("/api/v1/auth/me/").status_code == 200
    assert AuditEvent.objects.filter(action="auth.login", outcome="success", details__mfa="totp").exists()


def test_recovery_code_works_once(make_user, login):
    user = make_user("nurse", username="nurse.rc")
    _, recovery = _enrol(login(user, client=APIClient()))
    assert len(recovery) == 10
    for expected in (200, 400):
        c, r = _sign_in("nurse.rc")
        res = c.post("/api/v1/auth/login/mfa/", {"mfa_token": r.json()["mfa_token"], "code": recovery[0].upper()},
                     format="json")
        assert res.status_code == expected


def test_wrong_codes_lock_the_account(make_user, login, settings):
    settings.LOGIN_MAX_FAILURES = 3
    user = make_user("nurse", username="nurse.lock")
    _enrol(login(user, client=APIClient()))
    c, r = _sign_in("nurse.lock")
    token = r.json()["mfa_token"]
    codes = [c.post("/api/v1/auth/login/mfa/", {"mfa_token": token, "code": "123456"}, format="json").status_code
             for _ in range(3)]
    assert codes[-1] == 423
    user.refresh_from_db()
    assert user.locked_until is not None


def test_forged_or_stale_token_is_refused(make_user, login):
    user = make_user("nurse", username="nurse.tok")
    secret, _ = _enrol(login(user, client=APIClient()))
    c = APIClient()
    r = c.post("/api/v1/auth/login/mfa/", {"mfa_token": "forged", "code": "123456"}, format="json")
    assert r.status_code == 400
    _, r = _sign_in("nurse.tok")
    token = r.json()["mfa_token"]
    user.set_password("Another-Synthetic-Pass-2026")
    user.save()
    res = c.post("/api/v1/auth/login/mfa/", {"mfa_token": token, "code": mfa.hotp(secret, mfa.current_step() + 1)},
                 format="json")
    assert res.status_code == 400  # password changed after the token was issued


def test_required_mfa_cannot_be_turned_off(make_user, login):
    admin = make_user("system_admin")
    client = login(admin, client=APIClient())
    secret, _ = _enrol(client)
    _policy("admins")
    r = client.post("/api/v1/auth/mfa/disable/", {"password": PASSWORD,
                                                 "code": mfa.hotp(secret, mfa.current_step() + 1)}, format="json")
    assert r.status_code == 409


def test_admin_reset_for_lost_phone(make_user, login, sysadmin):
    user = make_user("nurse", username="nurse.lost")
    _enrol(login(user, client=APIClient()))
    admin = login(sysadmin, client=APIClient())
    assert admin.post(f"/api/v1/users/{user.pk}/reset-mfa/").status_code == 200
    user.refresh_from_db()
    assert not user.mfa_enabled and not user.recovery_codes.exists()
    _, r = _sign_in("nurse.lost")
    assert r.json().get("mfa_required") is None  # signs in with password, then sets up again


def test_clinic_admin_cannot_reset_admin_mfa(make_user, login):
    target = make_user("system_admin", username="other.admin")
    client = login(make_user("clinic_admin"), client=APIClient())
    assert client.post(f"/api/v1/users/{target.pk}/reset-mfa/").status_code == 403


def test_secret_never_returned_after_setup(make_user, login):
    user = make_user("nurse")
    client = login(user, client=APIClient())
    _enrol(client)
    body = str(client.get("/api/v1/auth/mfa/").json()) + str(client.get("/api/v1/auth/me/").json())
    stored = User.objects.get(pk=user.pk).mfa_secret_encrypted
    assert mfa.decrypt_secret(stored) not in body
