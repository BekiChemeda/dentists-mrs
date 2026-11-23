"""Focused tests for module rules not covered by the end-to-end workflow."""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.inventory.models import Batch, Item
from apps.patients.services import normalize_phone

pytestmark = pytest.mark.django_db


def ok(response, code=200):
    assert response.status_code == code, response.content
    return response.json()


BASE = {"first_name": "Kebede", "middle_name": "Alemu", "sex": "male", "age_years": 40, "phone": "0944556677"}


@pytest.mark.parametrize("raw, expected", [("+251911223344", "0911223344"), ("911223344", "0911223344"),
                                           ("0911 22 33 44", "0911223344"), ("", "")])
def test_phone_normalisation(raw, expected):
    assert normalize_phone(raw) == expected


def test_estimated_age_and_audited_update(staff):
    p = ok(staff.receptionist.post("/api/v1/patients/", BASE, format="json"), 201)
    assert p["birth_date_estimated"] is True and p["age"] in (39, 40)
    ok(staff.receptionist.patch(f"/api/v1/patients/{p['id']}/", {"city": "Hawassa", "blood_group": "O+"},
                                format="json"))
    event = AuditEvent.objects.get(action="patient.update", object_id=p["id"])
    assert event.details["city"] == {"from": "", "to": "Hawassa"}
    ok(staff.receptionist.get(f"/api/v1/patients/{p['id']}/"))
    assert AuditEvent.objects.filter(action="patient.view", object_id=p["id"]).exists()


def test_patient_validation(staff):
    bad = staff.receptionist.post("/api/v1/patients/", {"first_name": "X", "sex": "male"}, format="json")
    assert bad.status_code == 400  # neither birth date nor age
    future = staff.receptionist.post("/api/v1/patients/", {**BASE, "age_years": None,
                                                           "birth_date": "2999-01-01"}, format="json")
    assert future.status_code == 400
    assert staff.pharmacist.post("/api/v1/patients/", BASE, format="json").status_code == 403


def test_doctor_slot_overlap_and_cancel_reason(staff):
    p1 = ok(staff.receptionist.post("/api/v1/patients/", BASE, format="json"), 201)
    p2 = ok(staff.receptionist.post("/api/v1/patients/", {**BASE, "first_name": "Sara", "sex": "female",
                                                          "phone": "0955000000", "confirm_not_duplicate": True},
                                    format="json"), 201)
    at = timezone.localtime() + datetime.timedelta(days=1)
    doctor = str(staff.users.doctor.pk)
    a1 = ok(staff.receptionist.post("/api/v1/appointments/", {"patient_id": p1["id"], "doctor_id": doctor,
                                                               "scheduled_at": at.isoformat(), "duration_minutes": 30},
                                    format="json"), 201)
    clash = staff.receptionist.post("/api/v1/appointments/", {
        "patient_id": p2["id"], "doctor_id": doctor, "scheduled_at": (at + datetime.timedelta(minutes=10)).isoformat()},
        format="json")
    assert clash.status_code == 409
    assert staff.receptionist.post(f"/api/v1/appointments/{a1['id']}/cancel/", {}, format="json").status_code == 400
    ok(staff.receptionist.post(f"/api/v1/appointments/{a1['id']}/cancel/", {"reason": "Patient request"},
                               format="json"))
    not_doctor = staff.receptionist.post("/api/v1/appointments/", {
        "patient_id": p2["id"], "doctor_id": str(staff.users.nurse.pk), "scheduled_at": at.isoformat()}, format="json")
    assert not_doctor.status_code == 400


def test_stock_adjustment_and_receipt_rules(staff):
    item = Item.objects.get(code="IBU400")
    supplier = ok(staff.inventory_manager.post("/api/v1/inventory/suppliers/", {"name": "Supplier A"},
                                               format="json"), 201)
    expired = staff.inventory_manager.post("/api/v1/inventory/purchases/", {
        "supplier_id": supplier["id"], "purchase_date": str(timezone.localdate()), "lines": [
            {"item_id": str(item.pk), "batch_number": "X1", "expiry_date": "2020-01-01", "quantity": "10"}]},
        format="json")
    assert expired.status_code == 400
    ok(staff.inventory_manager.post("/api/v1/inventory/purchases/", {
        "supplier_id": supplier["id"], "purchase_date": str(timezone.localdate()), "lines": [
            {"item_id": str(item.pk), "batch_number": "OK1",
             "expiry_date": str(timezone.localdate() + datetime.timedelta(days=30)), "quantity": "10"}]},
        format="json"), 201)
    batch = Batch.objects.get(batch_number="OK1")
    too_much = staff.inventory_manager.post("/api/v1/inventory/movements/", {
        "batch_id": str(batch.pk), "quantity": "-11", "kind": "adjustment", "reason": "Count"}, format="json")
    assert too_much.status_code == 409
    ok(staff.inventory_manager.post("/api/v1/inventory/movements/", {
        "batch_id": str(batch.pk), "quantity": "-2", "kind": "expired", "reason": "Broken"}, format="json"), 201)
    alerts = ok(staff.pharmacist.get("/api/v1/inventory/alerts/?days=60"))
    assert any(b["batch_number"] == "OK1" for b in alerts["expiring"])
    assert any(i["code"] == "IBU400" for i in alerts["low_stock"])  # 8 left, reorder level 200
    assert Decimal(ok(staff.pharmacist.get(f"/api/v1/inventory/items/{item.pk}/"))["on_hand"]) == Decimal("8")
    assert staff.pharmacist.post("/api/v1/inventory/movements/", {
        "batch_id": str(batch.pk), "quantity": "-1", "kind": "adjustment", "reason": "x"},
        format="json").status_code == 403


def test_reports_catalogue_respects_permissions(staff):
    cashier_reports = {r["key"] for r in ok(staff.cashier.get("/api/v1/reports/"))}
    assert "revenue" in cashier_reports and "diagnoses" not in cashier_reports
    assert staff.cashier.get("/api/v1/reports/diagnoses/").status_code == 403
    assert staff.clinic_admin.get("/api/v1/reports/visits/?date_from=2026-02-01&date_to=2026-01-01").status_code == 400


def test_notifications_are_private(staff):
    from apps.notifications.services import notify_user

    notify_user(staff.users.doctor, kind="test", title="Hello")
    assert ok(staff.doctor.get("/api/v1/notifications/"))["unread"] == 1
    assert ok(staff.nurse.get("/api/v1/notifications/"))["count"] == 0
    ok(staff.doctor.post("/api/v1/notifications/read/", {}, format="json"))
    assert ok(staff.doctor.get("/api/v1/notifications/"))["unread"] == 0
