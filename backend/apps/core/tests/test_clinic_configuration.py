"""Rooms, opening hours, queue settings, set-up checklist, prescription numbers. Synthetic data only."""

import datetime

import pytest
from django.utils import timezone

from apps.core.models import ClinicSettings
from apps.scheduling.models import Visit

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json() if r.content else None


def _patient(rc, first="Meron"):
    return ok(rc.post("/api/v1/patients/", {"first_name": first, "last_name": "Synthetic", "sex": "female", "age_years": 28,
                                            "confirm_not_duplicate": True}, format="json"), 201)


def test_rooms_and_called_room(staff):
    room = ok(staff.clinic_admin.post("/api/v1/rooms/", {"name": "Room 3"}, format="json"), 201)
    assert staff.receptionist.post("/api/v1/rooms/", {"name": "X"}, format="json").status_code == 403
    assert any(r["name"] == "Room 3" for r in ok(staff.doctor.get("/api/v1/rooms/")))
    ok(staff.doctor.patch("/api/v1/auth/me/room/", {"room_id": room["id"]}, format="json"))
    assert ok(staff.doctor.get("/api/v1/auth/me/"))["room"]["name"] == "Room 3"
    assert staff.doctor.patch("/api/v1/auth/me/room/", {"room_id": "nope"}, format="json").status_code == 400
    p = _patient(staff.receptionist)
    v = ok(staff.receptionist.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    ok(staff.nurse.post(f"/api/v1/visits/{v['id']}/vitals/", {"chief_complaint": "Cough", "complaint_duration": "3 days",
                                                             "triage_to": "opd1"}, format="json"), 201)
    called = ok(staff.doctor.post(f"/api/v1/visits/{v['id']}/call/", {}, format="json"))
    assert called["called_room"] == "Room 3"


def test_opening_hours_limit_booking(staff):
    hours = {d: {"open": "08:00", "close": "17:00"} for d in ("mon", "tue", "wed", "thu", "fri")}
    hours.update({"sat": {"open": "08:00", "close": "12:00"}, "sun": None})
    ok(staff.clinic_admin.patch("/api/v1/settings/clinic/", {"opening_hours": hours}, format="json"))
    assert staff.clinic_admin.patch("/api/v1/settings/clinic/", {"opening_hours": {"mon": {"open": "18:00", "close": "08:00"}}},
                                    format="json").status_code == 400
    p = _patient(staff.receptionist)
    day = timezone.localdate() + datetime.timedelta(days=1)
    while day.weekday() != 6:  # next Sunday: closed
        day += datetime.timedelta(days=1)
    tz = timezone.get_current_timezone()
    sunday = datetime.datetime.combine(day, datetime.time(10, 0), tzinfo=tz)
    body = {"patient_id": p["id"], "doctor_id": str(staff.users.doctor.pk)}
    r = staff.receptionist.post("/api/v1/appointments/", {**body, "scheduled_at": sunday.isoformat()}, format="json")
    assert r.status_code == 400 and "closed on Sundays" in r.json()["error"]["message"]
    evening = datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time(17, 50), tzinfo=tz)
    assert staff.receptionist.post("/api/v1/appointments/", {**body, "scheduled_at": evening.isoformat()},
                                   format="json").status_code == 400
    morning = datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time(9, 0), tzinfo=tz)
    ok(staff.receptionist.post("/api/v1/appointments/", {**body, "scheduled_at": morning.isoformat()}, format="json"), 201)


def test_triage_can_be_required(staff):
    p = _patient(staff.receptionist)
    v = ok(staff.receptionist.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    ok(staff.clinic_admin.patch("/api/v1/settings/clinic/", {"allow_skip_triage": False}, format="json"))
    r = staff.receptionist.patch(f"/api/v1/visits/{v['id']}/", {"status": "waiting_doctor"}, format="json")
    assert r.status_code == 409
    # A doctor can still take an emergency straight in.
    ok(staff.doctor.post(f"/api/v1/visits/{v['id']}/encounters/", {}, format="json"), 201)
    assert Visit.objects.get(pk=v["id"]).status == "in_consultation"


def test_setup_checklist(staff):
    body = ok(staff.clinic_admin.get("/api/v1/settings/setup-checklist/"))
    assert body["total"] == len(body["items"]) and {i["key"] for i in body["items"]} >= {"clinic", "staff", "hours"}
    assert staff.receptionist.get("/api/v1/settings/setup-checklist/").status_code == 403
    ok(staff.clinic_admin.patch("/api/v1/settings/clinic/", {"setup_checklist_hidden": True}, format="json"))
    assert ClinicSettings.get().setup_checklist_hidden is True


def test_document_notes(staff):
    ok(staff.clinic_admin.patch("/api/v1/settings/clinic/", {"note_prescription": "Open Mon–Sat 8–17. Bring this paper."},
                                format="json"))
    assert ok(staff.receptionist.get("/api/v1/settings/clinic/"))["note_prescription"].startswith("Open")
    assert staff.clinic_admin.patch("/api/v1/settings/clinic/", {"note_prescription": "x" * 301},
                                    format="json").status_code == 400
