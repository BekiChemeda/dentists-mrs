"""Shared test fixtures. All data is synthetic."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User

PASSWORD = "Synthetic-Pass-2026"  # gitleaks:allow (synthetic test password, used only by the test suite)


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Login throttling uses the cache; isolate tests from each other's request counts."""
    from django.core.cache import cache

    def clear():
        try:
            cache.clear()
        except RuntimeError:  # test without database access: it cannot have used the database cache
            pass

    clear()
    yield
    clear()


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def make_user(db):
    counter = {"n": 0}

    def _make(*role_codes, username=None, password=PASSWORD, must_change_password=False, is_active=True, email=""):
        counter["n"] += 1
        user = User(
            username=username or f"user{counter['n']}",
            email=email,
            first_name="Test",
            last_name=f"Person{counter['n']}",
            must_change_password=must_change_password,
            is_active=is_active,
        )
        user.set_password(password)
        user.save()
        if role_codes:
            user.roles.set(Role.objects.filter(code__in=role_codes))
        return user

    return _make


@pytest.fixture
def login(api):
    def _login(user, password=PASSWORD, client=None):
        client = client or api
        response = client.post("/api/v1/auth/login/", {"username": user.username, "password": password},
                               format="json")
        assert response.status_code == 200, response.content
        return client

    return _login


@pytest.fixture
def sysadmin(make_user):
    return make_user("system_admin", username="sysadmin")


@pytest.fixture
def catalog(db):
    from django.core.management import call_command

    call_command("load_starter_catalog", verbosity=0)


@pytest.fixture
def staff(make_user, catalog):
    """One signed-in API client per role, plus the user objects. All synthetic."""
    from types import SimpleNamespace

    roles = ["receptionist", "nurse", "doctor", "lab_technician", "pharmacist", "cashier", "inventory_manager",
             "clinic_admin"]
    users, clients = {}, {}
    for role in roles:
        user = make_user(role, username=role.replace("_", "."))
        client = APIClient()
        response = client.post("/api/v1/auth/login/", {"username": user.username, "password": PASSWORD},
                               format="json")
        assert response.status_code == 200, response.content
        users[role], clients[role] = user, client
    return SimpleNamespace(users=SimpleNamespace(**users), **clients)


@pytest.fixture(autouse=True)
def _mfa_policy_off_by_default(settings):
    """Most tests sign in as administrators without an authenticator; MFA tests turn the policy on."""
    settings.MFA_DEFAULT_POLICY = "off"
