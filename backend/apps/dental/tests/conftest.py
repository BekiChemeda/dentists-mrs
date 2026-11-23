"""Dental test fixtures. All data is synthetic."""

from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from conftest import PASSWORD

DENTAL_ROLES = ["dentist", "dental_assistant", "dental_hygienist", "dental_technician", "imaging_staff",
                "receptionist", "cashier", "clinic_admin", "inventory_manager", "clinic_director"]


@pytest.fixture
def dental_catalog(catalog):
    from django.core.management import call_command

    call_command("load_dental_catalog", verbosity=0)


@pytest.fixture(autouse=True)
def _image_root(settings, tmp_path):
    settings.DENTAL_IMAGE_ROOT = tmp_path / "images"


@pytest.fixture
def dental(make_user, dental_catalog):
    """One signed-in client per dental role (attribute = role code), plus `.users`."""
    users, clients = {}, {}
    for role in DENTAL_ROLES:
        user = make_user(role, username=role.replace("_", "."))
        if role == "dentist":
            user.first_name, user.last_name = "Selam", "Dentist"
            user.save()
        client = APIClient()
        r = client.post("/api/v1/auth/login/", {"username": user.username, "password": PASSWORD}, format="json")
        assert r.status_code == 200, r.content
        users[role], clients[role] = user, client
    second = make_user("dentist", username="dentist.two")
    c2 = APIClient()
    assert c2.post("/api/v1/auth/login/", {"username": second.username, "password": PASSWORD},
                   format="json").status_code == 200
    users["dentist2"], clients["dentist2"] = second, c2
    return SimpleNamespace(users=SimpleNamespace(**users), **clients)


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.content[:2000])
    return r.json() if r.content else None


@pytest.fixture
def patient(dental):
    def _make(first="Abebe", age=34, sex="male"):
        return ok(dental.receptionist.post("/api/v1/patients/", {
            "first_name": first, "last_name": "Synthetic", "sex": sex, "age_years": age, "phone": "0911000000",
            "confirm_not_duplicate": True}, format="json"), 201)
    return _make


@pytest.fixture
def visit(dental, patient):
    def _make(p=None):
        p = p or patient()
        v = ok(dental.receptionist.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
        return p, v
    return _make


@pytest.fixture
def exam(dental, visit):
    """A patient checked in and a draft dental examination started by the dentist."""
    def _make(p=None):
        p, v = visit(p)
        enc = ok(dental.dentist.post(f"/api/v1/dental/visits/{v['id']}/encounters/"), 201)
        return p, v, enc
    return _make


@pytest.fixture
def catalog_data(dental):
    return ok(dental.dentist.get("/api/v1/dental/catalog/"))


def finding_type(catalog_data, code):
    return next(f for f in catalog_data["finding_types"] if f["code"] == code)


def procedure(catalog_data, code):
    return next(p for p in catalog_data["procedures"] if p["code"] == code)


def term(dental, code):
    rows = ok(dental.dentist.get(f"/api/v1/dental/diagnosis-terms/?q={code}"))
    return next(r for r in rows if r["code"] == code)
