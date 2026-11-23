"""Appointments, queue handling and visit completion. Synthetic data only."""

import datetime

import pytest
from django.utils import timezone

from apps.notifications.models import Notification
from apps.scheduling.models import Visit, VisitEvent

pytestmark = pytest.mark.django_db


def ok(response, code=200):
    assert response.status_code == code, response.content
    return response.json()


def _patient(client, first="Hana", phone=""):
    return ok(client.post("/api/v1/patients/", {"first_name": first, "middle_name": "Lemma", "last_name": "Girma",
                                                "sex": "female", "age_years": 30, "phone": phone,
                                                "confirm_not_duplicate": True}, format="json"), 201)


def _soon(minutes=60):
    return (timezone.localtime() + datetime.timedelta(minutes=minutes)).isoformat()


@pytest.fixture
def mid_morning(monkeypatch):
    """Run as if it were 10:00 today. The test books appointments up to three hours ahead; late in the
    evening those would fall on tomorrow and could not be checked in today."""
    real_now = timezone.now
    start = real_now()
    if timezone.localtime(start).hour < 18:
        return  # three hours ahead is still today; moving the clock forward would make sessions look idle
    morning = timezone.localtime(start).replace(hour=10, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(timezone, "now", lambda: morning + (real_now() - start))


def test_appointment_confirm_reschedule_and_arrival(staff, mid_morning):
    rc, doctor = staff.receptionist, staff.users.doctor
    p = _patient(rc)
    appt = ok(rc.post("/api/v1/appointments/", {"patient_id": p["id"], "doctor_id": str(doctor.pk),
                                                 "scheduled_at": _soon(60), "reason": "Review",
                                                 "notes": "Bring previous results"}, format="json"), 201)
    assert appt["status"] == "scheduled" and appt["notes"] == "Bring previous results"
    assert Notification.objects.filter(user=doctor, kind="appointment").exists()

    appt = ok(rc.post(f"/api/v1/appointments/{appt['id']}/confirm/"))
    assert appt["status"] == "confirmed" and appt["confirmed_at"]
    assert rc.post(f"/api/v1/appointments/{appt['id']}/confirm/").status_code == 409

    moved = ok(rc.post(f"/api/v1/appointments/{appt['id']}/reschedule/",
                       {"scheduled_at": _soon(120), "reason": "Patient asked"}, format="json"))
    assert moved["status"] == "scheduled" and moved["reschedule_count"] == 1  # needs confirming again

    # A no-show cannot be recorded before the appointment time.
    assert rc.post(f"/api/v1/appointments/{appt['id']}/no-show/").status_code == 409

    visit = ok(rc.post(f"/api/v1/appointments/{appt['id']}/check-in/"), 201)
    assert visit["kind"] == "appointment" and visit["assigned_doctor"]["id"] == str(doctor.pk)
    assert Notification.objects.filter(user=doctor, kind="arrival").exists()
    assert rc.post(f"/api/v1/appointments/{appt['id']}/reschedule/", {"scheduled_at": _soon(200)},
                   format="json").status_code == 409


def test_queue_order_call_skip_and_return(staff):
    rc, nurse = staff.receptionist, staff.nurse
    a = ok(rc.post("/api/v1/visits/", {"patient_id": _patient(rc, "Abebe")["id"]}, format="json"), 201)
    b = ok(rc.post("/api/v1/visits/", {"patient_id": _patient(rc, "Bontu")["id"], "priority": "urgent"},
                   format="json"), 201)
    c = ok(rc.post("/api/v1/visits/", {"patient_id": _patient(rc, "Chaltu")["id"], "priority": "emergency"},
                   format="json"), 201)
    assert Notification.objects.filter(kind="emergency", user=staff.users.nurse).exists()

    order = [v["id"] for v in ok(rc.get("/api/v1/visits/?open=1"))]
    assert order == [c["id"], b["id"], a["id"]]  # emergency, urgent, routine

    called = ok(nurse.post("/api/v1/visits/call-next/", {"stage": "triage"}, format="json"))["visit"]
    assert called["id"] == c["id"] and called["called_by"]["id"] == str(staff.users.nurse.pk)

    assert nurse.post(f"/api/v1/visits/{b['id']}/skip/", {"reason": ""}, format="json").status_code == 400
    skipped = ok(nurse.post(f"/api/v1/visits/{b['id']}/skip/", {"reason": "Gone to the toilet"}, format="json"))
    assert skipped["skip_reason"] == "Gone to the toilet"
    order = [v["id"] for v in ok(rc.get("/api/v1/visits/?open=1"))]
    assert order[-1] == b["id"]  # skipped patients go to the end
    ok(nurse.post(f"/api/v1/visits/{b['id']}/return/"))
    order = [v["id"] for v in ok(rc.get("/api/v1/visits/?open=1"))]
    assert order.index(b["id"]) < order.index(a["id"])

    # Queue handling never changes clinical data, and every step is on the timeline.
    kinds = list(VisitEvent.objects.filter(visit_id=b["id"]).values_list("kind", flat=True))
    assert kinds == ["arrived", "queue.skip", "queue.return"]

    # Reassigning a doctor notifies them.
    ok(rc.patch(f"/api/v1/visits/{a['id']}/", {"doctor_id": str(staff.users.doctor.pk)}, format="json"))
    assert Notification.objects.filter(user=staff.users.doctor, kind="arrival").exists()

    # Staff without queue permissions cannot call patients.
    assert staff.cashier.post("/api/v1/visits/call-next/", {"stage": "triage"}, format="json").status_code == 403


def _consulted_visit(staff, *, with_lab=False):
    rc, dr = staff.receptionist, staff.doctor
    visit = ok(rc.post("/api/v1/visits/", {"patient_id": _patient(rc, "Dawit")["id"]}, format="json"), 201)
    ok(staff.nurse.post(f"/api/v1/visits/{visit['id']}/vitals/", {"temperature_c": "37.0"}, format="json"), 201)
    enc = ok(dr.post(f"/api/v1/visits/{visit['id']}/encounters/"), 201)
    ok(dr.patch(f"/api/v1/encounters/{enc['id']}/", {"chief_complaint": "Cough", "plan": "Fluids and rest",
                                                     "version": enc["version"]}, format="json"))
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": "J06.9"}, format="json"), 201)
    if with_lab:
        from apps.laboratory.models import LabTest

        ok(dr.post(f"/api/v1/encounters/{enc['id']}/lab-orders/",
                   {"test_ids": [str(LabTest.objects.get(code='HGB').pk)]}, format="json"), 201)
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/sign/"))
    return visit, enc


def test_signing_keeps_visit_open_until_completed(staff):
    visit, _ = _consulted_visit(staff, with_lab=True)
    rc = staff.receptionist
    assert ok(rc.get(f"/api/v1/visits/{visit['id']}/"))["status"] == "after_consult"

    # Lab still pending: completion needs an explicit acknowledgement and a note.
    r = rc.post(f"/api/v1/visits/{visit['id']}/complete/", {"outcome": "left_early"}, format="json")
    assert r.status_code == 400  # left early needs a note
    r = rc.post(f"/api/v1/visits/{visit['id']}/complete/", {"outcome": "left_early", "note": "Will return"},
                format="json")
    assert r.status_code == 409 and r.json()["error"]["outstanding"]["lab_pending"]
    done = ok(rc.post(f"/api/v1/visits/{visit['id']}/complete/",
                      {"outcome": "left_early", "note": "Patient left; will return for results",
                       "acknowledge_outstanding": True}, format="json"))
    assert done["status"] == "completed" and done["outcome"] == "left_early"
    # The lab request survives: results can still be entered and reach the chart.
    from apps.laboratory.models import LabOrderItem
    assert LabOrderItem.objects.filter(order__visit_id=visit["id"], status="ordered").count() == 1

    # Reopen (same day, with reason) and run a review consultation on the same visit.
    assert rc.post(f"/api/v1/visits/{visit['id']}/reopen/", {"reason": ""}, format="json").status_code == 400
    reopened = ok(rc.post(f"/api/v1/visits/{visit['id']}/reopen/", {"reason": "Came back with results"},
                          format="json"))
    assert reopened["status"] == "after_consult" and reopened["outcome"] == ""
    review = ok(staff.doctor.post(f"/api/v1/visits/{visit['id']}/encounters/"), 201)
    assert Visit.objects.get(pk=visit["id"]).encounters.count() == 2
    # An unsigned note blocks completion even when acknowledged.
    r = rc.post(f"/api/v1/visits/{visit['id']}/complete/", {"outcome": "completed", "note": "x",
                                                            "acknowledge_outstanding": True}, format="json")
    assert r.status_code == 409
    ok(staff.doctor.patch(f"/api/v1/encounters/{review['id']}/", {"chief_complaint": "Results review",
                                                                 "plan": "Normal haemoglobin; no treatment",
                                                                 "version": review["version"]}, format="json"))
    ok(staff.doctor.post(f"/api/v1/encounters/{review['id']}/diagnoses/", {"icd_code": "J06.9"}, format="json"), 201)
    ok(staff.doctor.post(f"/api/v1/encounters/{review['id']}/sign/"))
    assert ok(rc.get(f"/api/v1/visits/{visit['id']}/"))["status"] == "after_consult"


def test_undispensed_medicines_closed_as_not_collected(staff):
    from apps.inventory.models import Item

    rc, dr = staff.receptionist, staff.doctor
    visit = ok(rc.post("/api/v1/visits/", {"patient_id": _patient(rc, "Eleni")["id"]}, format="json"), 201)
    enc = ok(dr.post(f"/api/v1/visits/{visit['id']}/encounters/"), 201)
    ok(dr.patch(f"/api/v1/encounters/{enc['id']}/", {"chief_complaint": "Pain", "version": enc["version"],
                                                     "plan": "Analgesia"}, format="json"))
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": "M79.1"}, format="json"), 201)
    item = Item.objects.filter(category="medicine").first()
    rx = ok(dr.post(f"/api/v1/encounters/{enc['id']}/prescriptions/", {"items": [
        {"item_id": str(item.pk), "dose": "1 tab", "frequency": "TID", "quantity": "9"}]}, format="json"), 201)
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/sign/"))
    ok(rc.post(f"/api/v1/visits/{visit['id']}/complete/", {"outcome": "completed", "acknowledge_outstanding": True,
                                                         "note": "Patient will buy outside"}, format="json"))
    from apps.clinical.models import Prescription
    assert Prescription.objects.get(pk=rx["id"]).status == "not_collected"
    line = rx["items"][0]["id"]
    assert staff.pharmacist.post(f"/api/v1/prescription-items/{line}/dispense/", {"quantity": "1"},
                                 format="json").status_code == 409


def test_cannot_complete_before_consultation_or_twice(staff):
    rc = staff.receptionist
    visit = ok(rc.post("/api/v1/visits/", {"patient_id": _patient(rc, "Fikru")["id"]}, format="json"), 201)
    assert rc.post(f"/api/v1/visits/{visit['id']}/complete/", {"outcome": "completed"},
                   format="json").status_code == 409
    visit, _ = _consulted_visit(staff)
    # The consultation fee has not been billed yet: that is outstanding too.
    r = rc.post(f"/api/v1/visits/{visit['id']}/complete/", {"outcome": "completed"}, format="json")
    assert r.status_code == 409 and r.json()["error"]["outstanding"]["unbilled"] == ["General consultation"]
    ok(rc.post(f"/api/v1/visits/{visit['id']}/complete/", {"outcome": "completed", "acknowledge_outstanding": True,
                                                         "note": "Free follow-up visit"}, format="json"))
    assert rc.post(f"/api/v1/visits/{visit['id']}/complete/", {"outcome": "completed"},
                   format="json").status_code == 409
    # Cashier and lab staff cannot complete visits.
    assert staff.cashier.post(f"/api/v1/visits/{visit['id']}/reopen/", {"reason": "x"},
                              format="json").status_code == 403
