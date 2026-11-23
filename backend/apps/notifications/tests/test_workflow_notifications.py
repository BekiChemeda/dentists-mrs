"""Workflow notifications: low stock, prescriptions waiting, daily reminders. Synthetic data only."""
import datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.clinical.models import Encounter
from apps.inventory.models import Batch, Item
from apps.notifications.models import Notification
from apps.scheduling.models import Appointment

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json() if r.content else None


def _receive(staff, code, batch, days, qty):
    item = Item.objects.get(code=code)
    sup = ok(staff.inventory_manager.post("/api/v1/inventory/suppliers/", {"name": f"Supplier {batch}"}, format="json"), 201)
    today = timezone.localdate()
    ok(staff.inventory_manager.post("/api/v1/inventory/purchases/", {
        "supplier_id": sup["id"], "purchase_date": today.isoformat(), "supplier_invoice_no": f"SI-{batch}",
        "lines": [{"item_id": str(item.pk), "batch_number": batch, "expiry_date": str(today + datetime.timedelta(days=days)),
                   "quantity": qty, "unit_cost": "1"}]}, format="json"), 201)
    return item


def _notes(user, kind):
    return list(Notification.objects.filter(user=user, kind=kind))


def test_low_stock_notice_is_sent_once(staff, django_capture_on_commit_callbacks):
    item = Item.objects.get(code="PCM500")
    Item.objects.filter(pk=item.pk).update(reorder_level=10)
    _receive(staff, "PCM500", "LOW-1", 400, "12")
    batch = Batch.objects.get(batch_number="LOW-1")
    assert sum(m.quantity for m in item.movements.all()) == 12  # the starter catalogue holds no stock
    for qty in ("-5", "-1"):
        with django_capture_on_commit_callbacks(execute=True):
            ok(staff.inventory_manager.post("/api/v1/inventory/movements/", {
                "batch_id": str(batch.pk), "quantity": qty, "kind": "adjustment", "reason": "Count correction"}, format="json"), 201)
    notes = _notes(staff.users.inventory_manager, "low_stock")
    assert len(notes) == 1 and "Paracetamol" in notes[0].title


def test_prescription_notifies_pharmacy(staff, django_capture_on_commit_callbacks):
    rc, dr = staff.receptionist, staff.doctor
    p = ok(rc.post("/api/v1/patients/", {"first_name": "Rx", "last_name": "Synthetic", "sex": "male", "age_years": 30,
                                         "city": "Adama", "confirm_not_duplicate": True}, format="json"), 201)
    v = ok(rc.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    enc = ok(dr.post(f"/api/v1/visits/{v['id']}/encounters/"), 201)
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": "R50.9"}, format="json"), 201)
    with django_capture_on_commit_callbacks(execute=True):
        ok(dr.post(f"/api/v1/encounters/{enc['id']}/prescriptions/", {"items": [
            {"item_id": str(Item.objects.get(code="PCM500").pk), "dose": "1 g", "frequency": "TID", "quantity": "9"}]},
            format="json"), 201)
    notes = _notes(staff.users.pharmacist, "prescription")
    assert len(notes) == 1 and notes[0].title == "Prescription waiting: Rx Synthetic"


def test_daily_reminders_expiry_appointments_follow_up(staff):
    _receive(staff, "AMOX500", "SOON-1", 30, "20")
    rc, dr = staff.receptionist, staff.doctor
    today = timezone.localdate()
    tomorrow = today + datetime.timedelta(days=1)
    p = ok(rc.post("/api/v1/patients/", {"first_name": "Appt", "last_name": "Synthetic", "sex": "female", "age_years": 40,
                                         "city": "Adama", "confirm_not_duplicate": True}, format="json"), 201)
    when = timezone.make_aware(datetime.datetime.combine(tomorrow, datetime.time(10, 0)))
    ok(rc.post("/api/v1/appointments/", {"patient_id": p["id"], "doctor_id": str(staff.users.doctor.pk),
                                         "scheduled_at": when.isoformat(), "reason": "Review"}, format="json"), 201)
    # A signed note asking for a follow-up tomorrow, with nothing booked.
    q = ok(rc.post("/api/v1/patients/", {"first_name": "Follow", "last_name": "Synthetic", "sex": "male", "age_years": 50,
                                         "city": "Adama", "confirm_not_duplicate": True}, format="json"), 201)
    v = ok(rc.post("/api/v1/visits/", {"patient_id": q["id"]}, format="json"), 201)
    enc = ok(dr.post(f"/api/v1/visits/{v['id']}/encounters/"), 201)
    ok(dr.patch(f"/api/v1/encounters/{enc['id']}/", {"version": enc["version"], "chief_complaint": "Cough",
                                                     "plan": "Review tomorrow", "follow_up_date": tomorrow.isoformat()},
                format="json"))
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": "J06.9"}, format="json"), 201)
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/sign/"))
    assert Encounter.objects.get(pk=enc["id"]).follow_up_date == tomorrow

    for _ in range(2):  # running twice must not repeat unread reminders
        call_command("send_daily_reminders", stdout=StringIO())
    expiry = _notes(staff.users.inventory_manager, "expiry")
    assert len(expiry) == 1 and "Amoxicillin" in expiry[0].title
    reception = _notes(staff.users.receptionist, "appointment_reminder")
    assert [n.title for n in reception] == ["1 appointment(s) tomorrow"] and "not yet confirmed" in reception[0].body
    doctor = [n for n in _notes(staff.users.doctor, "appointment_reminder") if n.title.startswith("Your appointments")]
    assert len(doctor) == 1 and "Appt Synthetic" in doctor[0].body
    follow = _notes(staff.users.receptionist, "follow_up")
    assert len(follow) == 1 and follow[0].title == "Follow-up due tomorrow: Follow Synthetic"
    assert Appointment.objects.count() == 1
