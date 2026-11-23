"""Triage assessment and vital-sign interpretation. Synthetic data only."""

import datetime

import pytest

from apps.clinical.vitals_reference import interpret
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 21)


def born(years=0, months=0):
    return datetime.date(TODAY.year - years - (1 if months > TODAY.month - 1 else 0),
                         (TODAY.month - months - 1) % 12 + 1, 1)


def test_adult_news2_bands_and_total():
    adult = datetime.date(1980, 1, 1)
    normal = interpret({"respiratory_rate": 16, "spo2": 98, "systolic": 125, "heart_rate": 72,
                        "temperature_c": "36.8", "consciousness": "alert", "on_oxygen": False},
                       birth_date=adult, on=TODAY)
    assert normal["worst"] == "normal" and normal["news2"] == {"total": 0, "complete": True, "risk": "low"}

    sick = interpret({"respiratory_rate": 26, "spo2": 93, "systolic": 98, "heart_rate": 118,
                      "temperature_c": "39.4", "consciousness": "alert", "on_oxygen": False},
                     birth_date=adult, on=TODAY)
    # RR 3 + SpO2 2 + SBP 2 + HR 2 + Temp 2 = 11 -> high risk
    assert sick["news2"]["total"] == 11 and sick["news2"]["risk"] == "high" and sick["worst"] == "critical"
    assert sick["flags"]["respiratory_rate"]["level"] == "critical"
    assert sick["flags"]["temperature_c"]["level"] == "abnormal"

    partial = interpret({"temperature_c": "38.5"}, birth_date=adult, on=TODAY)
    assert partial["news2"]["complete"] is False and partial["news2"]["risk"] is None
    assert partial["flags"]["temperature_c"]["text"] == "Fever"


def test_adult_blood_pressure_definition():
    adult = datetime.date(1970, 5, 5)
    assert interpret({"systolic": 150, "diastolic": 85}, birth_date=adult, on=TODAY)["flags"]["systolic"]["level"] == "abnormal"
    assert interpret({"systolic": 130, "diastolic": 95}, birth_date=adult, on=TODAY)["flags"]["diastolic"]["level"] == "abnormal"
    assert interpret({"systolic": 185, "diastolic": 100}, birth_date=adult, on=TODAY)["flags"]["systolic"]["level"] == "critical"


def test_child_imci_fast_breathing_by_age():
    one_month = TODAY - datetime.timedelta(days=30)
    six_months = TODAY - datetime.timedelta(days=183)
    three_years = TODAY - datetime.timedelta(days=3 * 365)
    # 55/min: normal under 2 months (threshold 60), fast at 6 months (50), fast at 3 years (40).
    assert "respiratory_rate" not in interpret({"respiratory_rate": 55}, birth_date=one_month, on=TODAY)["flags"]
    assert interpret({"respiratory_rate": 55}, birth_date=six_months, on=TODAY)["flags"]["respiratory_rate"]["level"] == "abnormal"
    assert interpret({"respiratory_rate": 42}, birth_date=three_years, on=TODAY)["flags"]["respiratory_rate"]["level"] == "abnormal"
    assert interpret({"respiratory_rate": 38}, birth_date=three_years, on=TODAY)["flags"] == {}
    fever = interpret({"temperature_c": "37.6", "spo2": 88}, birth_date=three_years, on=TODAY)
    assert fever["flags"]["temperature_c"]["level"] == "abnormal" and fever["flags"]["spo2"]["level"] == "critical"
    # Adult heart-rate thresholds are never applied to young children.
    assert "heart_rate" not in interpret({"heart_rate": 140}, birth_date=one_month, on=TODAY)["flags"]


def test_school_age_child_only_oxygen_flagged():
    ten = TODAY - datetime.timedelta(days=10 * 365)
    r = interpret({"heart_rate": 120, "respiratory_rate": 30, "spo2": 95}, birth_date=ten, on=TODAY)
    assert r["flags"] == {} and r["worst"] == "normal"


def test_triage_assessment_saved_and_critical_alert(staff):
    rc, nurse = staff.receptionist, staff.nurse
    p = rc.post("/api/v1/patients/", {"first_name": "Gete", "sex": "male", "birth_date": "1960-02-02",
                                      "confirm_not_duplicate": True}, format="json").json()
    visit = rc.post("/api/v1/visits/", {"patient_id": p["id"], "doctor_id": str(staff.users.doctor.pk)},
                    format="json").json()
    preview = nurse.post(f"/api/v1/visits/{visit['id']}/vitals/preview/", {"spo2": 89, "heart_rate": 135},
                         format="json").json()
    assert preview["worst"] == "critical"
    r = nurse.post(f"/api/v1/visits/{visit['id']}/vitals/", {
        "spo2": 89, "heart_rate": 135, "respiratory_rate": 28, "temperature_c": "38.9", "systolic": 95,
        "consciousness": "alert", "on_oxygen": False,
        "chief_complaint": "Shortness of breath", "symptoms": "Cough 5 days, fever", "allergies_confirmed": True,
        "current_medications": "Salbutamol inhaler", "observations": "Using accessory muscles",
        "priority": "emergency"}, format="json")
    assert r.status_code == 201, r.content
    saved = r.json()
    assert saved["chief_complaint"] == "Shortness of breath" and saved["allergies_confirmed"] is True
    assert saved["interpretation"]["news2"]["risk"] == "high"
    assert Notification.objects.filter(user=staff.users.doctor, kind="critical_vitals").exists()

    # Abnormal but possible values are accepted; impossible ones are not.
    assert nurse.post(f"/api/v1/visits/{visit['id']}/vitals/", {"heart_rate": 999}, format="json").status_code == 400
    ok = nurse.post(f"/api/v1/visits/{visit['id']}/vitals/", {"heart_rate": 32}, format="json")
    assert ok.status_code == 201
    # Previous measurements are kept.
    assert staff.doctor.get(f"/api/v1/visits/{visit['id']}/vitals/").json()["count"] == 2
