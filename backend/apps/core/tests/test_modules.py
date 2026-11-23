"""Switching modules off for a small clinic: permissions, visit flow, open-work checks. Synthetic data only."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.catalog import PERMISSIONS
from apps.audit.models import AuditEvent
from apps.core.modules import AREAS, MODULES, disabled_modules
from apps.core.models import SystemSettings

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json() if r.content else None


@pytest.fixture
def admin(sysadmin, login):
    return login(sysadmin, client=APIClient())


def switch(admin, key, enabled, code=200):
    return ok(admin.patch(f"/api/v1/system/modules/{key}/", {"enabled": enabled}, format="json"), code)


def _patient_visit(staff, first="Abebech"):
    p = ok(staff.receptionist.post("/api/v1/patients/", {"first_name": first, "last_name": "Synthetic", "sex": "female",
                                                          "age_years": 30, "confirm_not_duplicate": True}, format="json"), 201)
    v = ok(staff.receptionist.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    return p, v


def test_every_permission_is_in_the_matrix_once():
    placed = [code for _k, _n, _m, perms in AREAS for code in perms]
    assert sorted(placed) == sorted(PERMISSIONS) and len(placed) == len(set(placed))
    for m in MODULES.values():
        assert m.permissions <= set(PERMISSIONS)


def test_only_system_admin_switches_modules(staff, admin):
    assert staff.clinic_admin.patch("/api/v1/system/modules/laboratory/", {"enabled": False},
                                    format="json").status_code == 403
    modules = ok(staff.receptionist.get("/api/v1/system/modules/"))
    assert all(m["enabled"] for m in modules)
    switch(admin, "laboratory", False)
    assert AuditEvent.objects.filter(action="system.module_off", object_id="laboratory").exists()
    assert "laboratory" in ok(staff.doctor.get("/api/v1/auth/me/"))["modules_off"]


def test_switched_off_module_disappears_and_comes_back(staff, admin):
    switch(admin, "laboratory", False)
    me = ok(staff.lab_technician.get("/api/v1/auth/me/"))
    assert not any(p.startswith("lab.") for p in me["permissions"])
    r = staff.lab_technician.get("/api/v1/lab/orders/")
    assert r.status_code == 403 and "Laboratory module is switched off" in r.json()["error"]["message"]
    # Roles are untouched: switching back on restores everything.
    switch(admin, "laboratory", True)
    assert any(p.startswith("lab.") for p in ok(staff.lab_technician.get("/api/v1/auth/me/"))["permissions"])
    ok(staff.lab_technician.get("/api/v1/lab/orders/"))


def test_open_work_blocks_switching_off(staff, admin):
    _p, v = _patient_visit(staff)
    r = admin.patch("/api/v1/system/modules/triage/", {"enabled": False}, format="json")
    assert r.status_code == 409 and "waiting for triage" in r.json()["error"]["open_work"][0]
    ok(staff.receptionist.patch(f"/api/v1/visits/{v['id']}/", {"status": "waiting_doctor"}, format="json"))
    switch(admin, "triage", False)


def test_without_triage_patients_go_straight_to_doctors(staff, admin):
    switch(admin, "triage", False)
    _p, v = _patient_visit(staff)
    assert v["status"] == "waiting_doctor"


def test_stock_off_takes_pharmacy_with_it(staff, admin):
    switch(admin, "inventory", False)
    off = disabled_modules()
    assert {"inventory", "pharmacy"} <= off
    pharm = next(m for m in ok(admin.get("/api/v1/system/modules/")) if m["key"] == "pharmacy")
    assert pharm["enabled"] is False and pharm["off_because_of"] == ["inventory"]
    # Pharmacy cannot be switched on alone while stock is off.
    assert admin.patch("/api/v1/system/modules/pharmacy/", {"enabled": True}, format="json").status_code == 409
    switch(admin, "inventory", True)
    assert "pharmacy" not in disabled_modules()


def test_without_pharmacy_prescriptions_are_printed_and_do_not_block_closing(staff, admin):
    switch(admin, "pharmacy", False)
    _p, v = _patient_visit(staff)
    ok(staff.receptionist.patch(f"/api/v1/visits/{v['id']}/", {"status": "waiting_doctor"}, format="json"))
    enc = ok(staff.doctor.post(f"/api/v1/visits/{v['id']}/encounters/", {}, format="json"), 201)
    ok(staff.doctor.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": "B54"}, format="json"), 201)
    rx = ok(staff.doctor.post(f"/api/v1/encounters/{enc['id']}/prescriptions/", {"items": [
        {"drug_name": "Paracetamol 500 mg tablet", "dose": "1 g", "frequency": "TID", "duration_days": 3, "quantity": 18,
         "route": "oral"}]}, format="json"), 201)
    assert rx["status"] == "external" and rx["number"].startswith("RX-")
    out = ok(staff.receptionist.get(f"/api/v1/visits/{v['id']}/outstanding/"))
    assert out["medicines_pending"] == []
    assert staff.pharmacist.get("/api/v1/pharmacy/dispensations/").status_code == 403


def test_without_billing_closing_does_not_check_payment(staff, admin):
    switch(admin, "billing", False)
    _p, v = _patient_visit(staff)
    out = ok(staff.receptionist.get(f"/api/v1/visits/{v['id']}/outstanding/"))
    assert out["unbilled"] == [] and out["balance_due"] == "0.00"
    assert staff.cashier.get("/api/v1/billing/invoices/").status_code == 403
    assert staff.clinic_admin.get("/api/v1/reports/revenue/").status_code == 403


def test_lab_only_visits_refused_when_lab_off(staff, admin):
    switch(admin, "laboratory", False)
    p = ok(staff.receptionist.post("/api/v1/patients/", {"first_name": "Lab", "last_name": "Only", "sex": "male",
                                                          "age_years": 50, "confirm_not_duplicate": True}, format="json"), 201)
    r = staff.receptionist.post("/api/v1/lab/walk-in/", {"patient_id": p["id"], "test_ids": [], "requested_by": "Dr X"},
                                format="json")
    assert r.status_code in (400, 409)


def test_permission_layout(admin, staff):
    switch(admin, "billing", False)
    body = ok(staff.clinic_admin.get("/api/v1/system/permission-layout/"))
    billing = next(a for a in body["areas"] if a["key"] == "billing")
    assert billing["module_on"] is False and {p["action"] for p in billing["permissions"]} >= {"view", "approve"}
    assert [a["key"] for a in body["actions"]][0] == "view"


def test_setting_is_kept(admin):
    switch(admin, "appointments", False)
    assert SystemSettings.get().disabled_modules == ["appointments"]
