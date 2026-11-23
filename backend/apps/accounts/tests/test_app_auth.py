"""Android app sign-in with bearer tokens. Synthetic accounts only."""
from datetime import timedelta

import time

from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import UserSession
from conftest import PASSWORD

import pytest


@pytest.fixture(autouse=True)
def _without_phone_activation(settings):
    """These tests cover the token itself; activated phones are covered in apps/devices/tests."""
    settings.MOBILE_ACTIVATION_REQUIRED = False


def _login(username, password=PASSWORD, device="Pixel test"):
    return APIClient().post("/api/v1/auth/app/login/", {"username": username, "password": password, "device": device},
                            format="json")


def _bearer(token):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return c


def test_sign_in_and_use_the_api_without_cookies_or_csrf(make_user):
    make_user("nurse", username="app.nurse")
    r = _login("app.nurse")
    assert r.status_code == 200, r.content
    token = r.json()["token"]
    assert token.startswith("mrsapp_") and r.json()["user"]["username"] == "app.nurse"
    assert "mrs_session" not in r.cookies
    app = _bearer(token)
    assert app.get("/api/v1/auth/me/").json()["username"] == "app.nurse"
    s = UserSession.objects.get(user__username="app.nurse")
    assert s.user_agent == "App: Pixel test" and token not in s.session_key  # only a hash is stored


def test_wrong_password_and_bad_tokens_are_refused(make_user):
    make_user("nurse", username="app.nurse2")
    assert _login("app.nurse2", "wrong").status_code in (400, 401)
    assert _bearer("mrsapp_" + "x" * 40).get("/api/v1/auth/me/").status_code == 401
    assert _bearer("not-ours").get("/api/v1/auth/me/").status_code == 401


def test_sign_out_and_administrator_revocation_end_the_token(make_user, sysadmin, login, api):
    user = make_user("doctor", username="app.doc")
    token = _login("app.doc").json()["token"]
    app = _bearer(token)
    assert app.post("/api/v1/auth/app/logout/").status_code == 204
    assert app.get("/api/v1/auth/me/").status_code == 401
    token2 = _login("app.doc").json()["token"]
    admin = login(sysadmin, client=api)
    assert admin.post(f"/api/v1/users/{user.pk}/revoke-sessions/", {}, format="json").status_code in (200, 204)
    assert _bearer(token2).get("/api/v1/auth/me/").status_code == 401


def test_idle_timeout_applies_to_the_app(make_user):
    make_user("nurse", username="app.idle")
    token = _login("app.idle").json()["token"]
    UserSession.objects.filter(user__username="app.idle").update(last_seen_at=timezone.now() - timedelta(days=2))
    r = _bearer(token).get("/api/v1/auth/me/")
    assert r.status_code == 401
    assert UserSession.objects.get(user__username="app.idle").end_reason == "expired"


def test_two_step_sign_in(make_user, settings):
    user = make_user("doctor", username="app.mfa")
    from apps.accounts import mfa

    secret = mfa.new_secret()
    user.mfa_secret_encrypted = mfa.encrypt_secret(secret)
    user.mfa_enabled_at = timezone.now()
    user.save()
    first = _login("app.mfa").json()
    assert first["mfa_required"] and "token" not in first
    done = APIClient().post("/api/v1/auth/app/login/mfa/", {"mfa_token": first["mfa_token"],
                                                             "code": mfa.hotp(secret, int(time.time()) // 30), "device": "Tecno"},
                            format="json")
    assert done.status_code == 200 and done.json()["token"].startswith("mrsapp_")


def test_permissions_still_apply(make_user):
    make_user("receptionist", username="app.rc")
    app = _bearer(_login("app.rc").json()["token"])
    assert app.get("/api/v1/encounters/").status_code == 403  # reception cannot read clinical notes
