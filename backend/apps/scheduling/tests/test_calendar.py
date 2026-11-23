"""Clinic calendar: holidays (Proclamation 1334/2024) and appointment load. Synthetic data only."""
import datetime

import pytest
from django.utils import timezone

from apps.core.ethiopian import from_ethiopian, to_ethiopian
from apps.scheduling.holidays import holidays_between, orthodox_easter

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json() if r.content else None


def test_ethiopian_conversion_round_trip():
    assert to_ethiopian(datetime.date(2026, 11, 21)) == (2019, 3, 12)
    d = datetime.date(2015, 1, 1)
    for i in range(365 * 12):
        x = d + datetime.timedelta(days=i)
        assert from_ethiopian(*to_ethiopian(x)) == x


def test_orthodox_easter_known_years():
    # Fasika: 5 May 2024, 20 April 2025, 12 April 2026, 2 May 2027
    assert [orthodox_easter(y) for y in (2024, 2025, 2026, 2027)] == [
        datetime.date(2024, 5, 5), datetime.date(2025, 4, 20), datetime.date(2026, 4, 12), datetime.date(2027, 5, 2)]


def test_holiday_rules_follow_proclamation_and_ethiopian_dates():
    hs = {h["name"]: h for h in holidays_between(datetime.date(2027, 1, 1), datetime.date(2027, 12, 31))}
    assert hs["Enkutatash (Ethiopian New Year)"]["date"] == datetime.date(2027, 9, 12)  # before a leap year
    assert hs["Meskel"]["date"] == datetime.date(2027, 9, 28)
    assert hs["Timket (Epiphany)"]["date"] == datetime.date(2027, 1, 19)
    assert hs["Siklet (Good Friday)"]["date"] == datetime.date(2027, 4, 30)
    assert hs["Martyrs' Day"]["offices_closed"] is False  # memorial day
    assert hs["Eid al-Fitr"]["tentative"] is True  # seeded, set by moon sighting
    assert not any("Derg" in name for name in hs)  # not a holiday under Proclamation 1334/2024
    hs26 = {h["name"]: h["date"] for h in holidays_between(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))}
    assert hs26["Enkutatash (Ethiopian New Year)"] == datetime.date(2026, 9, 11)


def test_calendar_endpoint_and_holiday_admin(staff):
    rc, admin = staff.receptionist, staff.clinic_admin
    p = ok(rc.post("/api/v1/patients/", {"first_name": "Cal", "last_name": "Synthetic", "sex": "male", "age_years": 30,
                                         "city": "Adama", "confirm_not_duplicate": True}, format="json"), 201)
    day = timezone.localdate() + datetime.timedelta(days=3)
    when = timezone.make_aware(datetime.datetime.combine(day, datetime.time(9, 0)))
    ok(rc.post("/api/v1/appointments/", {"patient_id": p["id"], "doctor_id": str(staff.users.doctor.pk),
                                         "scheduled_at": when.isoformat(), "reason": "Review"}, format="json"), 201)
    res = ok(rc.get(f"/api/v1/calendar/?date_from={day - datetime.timedelta(days=5)}&date_to={day + datetime.timedelta(days=5)}"))
    assert res["days"][day.isoformat()]["total"] == 1 and res["days"][day.isoformat()]["by_status"] == {"scheduled": 1}
    assert rc.get("/api/v1/calendar/?date_from=2026-01-01&date_to=2026-06-30").status_code == 400  # range too long

    body = {"date": day.isoformat(), "name": "Clinic staff training", "kind": "clinic", "note": "Reduced service"}
    assert rc.post("/api/v1/calendar/holidays/", body, format="json").status_code == 403
    h = ok(admin.post("/api/v1/calendar/holidays/", body, format="json"), 201)
    assert admin.post("/api/v1/calendar/holidays/", body, format="json").status_code == 409
    ok(admin.patch(f"/api/v1/calendar/holidays/{h['id']}/", {"name": "Staff training"}, format="json"))
    names = [x["name"] for x in ok(rc.get(f"/api/v1/calendar/?date_from={day}&date_to={day}"))["holidays"]]
    assert "Staff training" in names
    ok(admin.delete(f"/api/v1/calendar/holidays/{h['id']}/"), 204)
