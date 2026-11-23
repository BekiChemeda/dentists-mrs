"""
Attack-surface regression tests: walks every URL the API exposes, so a new endpoint that forgets its
permission check fails here.
"""

import re
import uuid

import pytest
from django.urls import get_resolver
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

# Reachable without signing in, on purpose.
PUBLIC = {"api/v1/health/", "api/v1/auth/csrf/", "api/v1/auth/login/", "api/v1/auth/login/mfa/",
          "api/v1/system/status/", "api/v1/branding/logo/",
          # Android app sign-in: no cookie is set or read, so there is nothing for CSRF to protect.
          "api/v1/auth/app/login/", "api/v1/auth/app/login/mfa/",
          # Phone activation and its sign-in challenge: protected by one-time codes and hardware keys.
          "api/v1/auth/app/challenge/", "api/v1/mobile/activate/", "api/v1/mobile/licence/",
          # Payment providers' notices: Chapa's is signed (HMAC) and only triggers a verify call; telebirr's
          # arrives at a secret address and only settles a request still waiting.
          "api/v1/payments/chapa/webhook/", "api/v1/payments/telebirr/result/x/"}
# Accept only the app's bearer token, never the browser cookie: a cookie-signed-in page gets 401.
TOKEN_ONLY = {"api/v1/auth/app/logout/"}


def _routes():
    out = []

    def walk(patterns, prefix=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                walk(p.url_patterns, prefix + str(p.pattern))
            else:
                out.append(prefix + str(p.pattern))
    walk(get_resolver().url_patterns)
    paths = set()
    for raw in out:
        path = re.sub(r"\(\?P<[^>]+>\[0-9a-f-\]\{36\}\)", str(uuid.uuid4()), raw)
        path = re.sub(r"\(\?P<[^>]+>([a-z_-]+)(\|[^)]*)?\)", r"\1", path)
        path = re.sub(r"<uuid:[^>]+>", str(uuid.uuid4()), path)
        path = re.sub(r"<int:[^>]+>", "1", path)
        path = re.sub(r"<(str:)?[^>]+>", "x", path)
        path = path.replace("^", "").replace("$", "")
        if path.startswith("api/"):
            paths.add(path)
    return sorted(paths)


ROUTES = _routes()


def test_public_routes_are_read_only():
    client = APIClient()
    for path in ("api/v1/system/status/", "api/v1/branding/logo/"):
        for method in ("post", "patch", "put", "delete"):
            r = getattr(client, method)("/" + path, {}, format="json")
            assert r.status_code in (403, 405), f"{method.upper()} /{path} -> {r.status_code}"


def test_routes_found():
    assert len(ROUTES) > 60


@pytest.mark.parametrize("path", ROUTES)
def test_anonymous_requests_are_refused(path):
    if path in PUBLIC:
        return
    client = APIClient()
    for method in ("get", "post", "patch", "delete"):
        r = getattr(client, method)("/" + path, {}, format="json")
        assert r.status_code in (401, 403, 405), f"{method.upper()} /{path} -> {r.status_code}"


@pytest.mark.parametrize("path", [p for p in ROUTES if p not in PUBLIC])
def test_writes_without_csrf_token_are_refused(path, make_user):
    from conftest import PASSWORD

    client = APIClient(enforce_csrf_checks=True)
    user = make_user("system_admin", "doctor", "cashier", "clinic_admin", username="csrf.probe")
    client.get("/api/v1/auth/csrf/")
    token = client.cookies["mrs_csrftoken"].value
    signed_in = client.post("/api/v1/auth/login/", {"username": user.username, "password": PASSWORD},
                            format="json", HTTP_X_CSRFTOKEN=token)
    assert signed_in.status_code == 200
    r = client.post("/" + path, {}, format="json")  # signed in, but no X-CSRFToken header
    allowed = (401, 403, 405) if path in TOKEN_ONLY else (403, 405)
    assert r.status_code in allowed, f"POST /{path} without CSRF -> {r.status_code}"


def test_login_without_csrf_token_is_refused():
    r = APIClient(enforce_csrf_checks=True).post("/api/v1/auth/login/", {"username": "a", "password": "b"}, format="json")
    assert r.status_code == 403


def test_error_responses_do_not_leak_internals():
    r = APIClient().get("/api/v1/does-not-exist/")
    assert b"Traceback" not in r.content and b"settings" not in r.content.lower()
