"""Closing finished visits automatically (Clinic settings: auto_complete_minutes). Synthetic data only."""
import datetime

from django.core.management import call_command
from django.utils import timezone

from apps.core.models import ClinicSettings, SystemSettings
from apps.laboratory.models import LabTest
from apps.scheduling.completion import close_finished_visits
from apps.scheduling.models import Visit


def ok(response, code=200):
    assert response.status_code == code, response.content
    return response.json()


def _signed_visit(staff, *, lab=False):
    rc, nurse, dr = staff.receptionist, staff.nurse, staff.doctor
    patient = ok(rc.post("/api/v1/patients/", {"first_name": "Auto", "last_name": f"Close{timezone.now().microsecond}",
                                               "sex": "female", "birth_date": "1991-02-03"}, format="json"), 201)
    visit = ok(rc.post("/api/v1/visits/", {"patient_id": patient["id"]}, format="json"), 201)
    ok(nurse.post(f"/api/v1/visits/{visit['id']}/vitals/", {"systolic": 120, "diastolic": 80}, format="json"), 201)
    enc = ok(dr.post(f"/api/v1/visits/{visit['id']}/encounters/"), 201)
    enc = ok(dr.patch(f"/api/v1/encounters/{enc['id']}/", {"version": enc["version"], "chief_complaint": "Sore throat",
                                                            "plan": "Rest and fluids"}, format="json"))
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": "J06.9", "certainty": "confirmed"},
               format="json"), 201)
    if lab:
        ok(dr.post(f"/api/v1/encounters/{enc['id']}/lab-orders/", {"test_ids": [str(LabTest.objects.first().pk)]},
                   format="json"), 201)
    ok(dr.post(f"/api/v1/encounters/{enc['id']}/sign/"))
    return Visit.objects.get(pk=visit["id"])


def _billing_off():
    s = SystemSettings.objects.get(pk=1)
    s.disabled_modules = ["billing"]
    s.save()


def _setting(minutes):
    c = ClinicSettings.get()
    c.auto_complete_minutes = minutes
    c.save()


def test_off_by_default_staff_close_visits(staff):
    _billing_off()
    visit = _signed_visit(staff)
    assert close_finished_visits(now=timezone.now() + datetime.timedelta(days=1)) == []
    visit.refresh_from_db()
    assert visit.status == Visit.Status.AFTER_CONSULTATION


def test_closes_a_finished_visit_after_the_waiting_time(staff):
    _billing_off()
    _setting(30)
    visit = _signed_visit(staff)
    assert close_finished_visits(now=timezone.now() + datetime.timedelta(minutes=10)) == []  # doctor may still add
    assert close_finished_visits(now=timezone.now() + datetime.timedelta(minutes=31)) == [str(visit.pk)]
    visit.refresh_from_db()
    assert visit.status == Visit.Status.COMPLETED and visit.outcome == Visit.Outcome.COMPLETED
    assert visit.completed_by is None and "automatically" in visit.completion_note
    events = ok(staff.receptionist.get(f"/api/v1/visits/{visit.pk}/"))
    assert events["status"] == "completed"


def test_visits_with_open_work_are_left_for_staff(staff):
    _billing_off()
    _setting(15)
    visit = _signed_visit(staff, lab=True)  # test requested, not yet done
    assert close_finished_visits(now=timezone.now() + datetime.timedelta(hours=3)) == []
    visit.refresh_from_db()
    assert visit.status == Visit.Status.AFTER_CONSULTATION


def test_unpaid_charges_keep_the_visit_open_when_billing_is_on(staff):
    _setting(15)
    visit = _signed_visit(staff)
    from apps.scheduling.completion import outstanding_for

    assert outstanding_for(visit).unbilled  # the consultation fee is still to be invoiced and paid
    assert close_finished_visits(now=timezone.now() + datetime.timedelta(hours=3)) == []


def test_command_runs_quietly_when_switched_off(staff):
    call_command("close_finished_visits", verbosity=0)


def test_setting_is_saved_and_validated(staff):
    admin = staff.clinic_admin
    current = ok(admin.get("/api/v1/settings/clinic/"))
    assert current["auto_complete_minutes"] == 0
    saved = ok(admin.patch("/api/v1/settings/clinic/", {"auto_complete_minutes": 45}, format="json",
                           HTTP_IF_MATCH=f'"{current["row_version"]}"'))
    assert saved["auto_complete_minutes"] == 45
    bad = admin.patch("/api/v1/settings/clinic/", {"auto_complete_minutes": 1000}, format="json")
    assert bad.status_code == 400
