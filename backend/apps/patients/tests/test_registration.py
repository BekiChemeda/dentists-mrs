"""Registration details, duplicate detection and demographic history. Synthetic data only."""

import pytest

pytestmark = pytest.mark.django_db


def test_duplicate_detection_reasons(staff):
    rc = staff.receptionist
    base = {"first_name": "Mulu", "middle_name": "Kebede", "last_name": "Ayana", "sex": "female",
            "birth_date": "1985-06-01", "phone": "0911000111", "national_id": "FAYDA-0001"}
    first = rc.post("/api/v1/patients/", base, format="json")
    assert first.status_code == 201
    pid = first.json()["id"]

    # Same national ID, different name and phone: still caught.
    r = rc.post("/api/v1/patients/", {"first_name": "Other", "sex": "male", "birth_date": "1990-01-01",
                                      "national_id": "fayda-0001"}, format="json")
    assert r.status_code == 409 and r.json()["error"]["candidates"][0]["reason"] == "Same national ID"

    # Phone given as the second number of the new patient.
    r = rc.post("/api/v1/patients/", {"first_name": "Abel", "sex": "male", "birth_date": "2000-01-01",
                                      "alt_phone": "+251911000111"}, format="json")
    assert r.status_code == 409 and r.json()["error"]["candidates"][0]["reason"] == "Same phone number"

    # Similar name but the other sex: not a duplicate.
    r = rc.post("/api/v1/patients/", {**base, "sex": "male", "phone": "", "national_id": ""}, format="json")
    assert r.status_code == 201

    # Estimated age widens the birth-year window to three years.
    r = rc.post("/api/v1/patients/", {"first_name": "Mulu", "middle_name": "Kebede", "last_name": "Ayana",
                                      "sex": "female", "age_years": 2026 - 1983}, format="json")
    assert r.status_code == 409 and r.json()["error"]["candidates"][0]["id"] == pid


def test_medical_background_and_change_history(staff):
    rc = staff.receptionist
    p = rc.post("/api/v1/patients/", {"first_name": "Selam", "sex": "female", "age_years": 40,
                                      "known_conditions": "Hypertension", "past_history": "Appendectomy 2010",
                                      "current_medications": "Amlodipine 5 mg daily",
                                      "confirm_not_duplicate": True}, format="json").json()
    assert p["birth_date_estimated"] is True and p["current_medications"] == "Amlodipine 5 mg daily"
    rc.patch(f"/api/v1/patients/{p['id']}/", {"phone": "0922333444", "city": "Bishoftu"}, format="json")
    rc.put(f"/api/v1/patients/{p['id']}/emergency-contacts/",
           [{"name": "Kebede", "relationship": "Brother", "phone": "0911222333"}], format="json")
    history = rc.get(f"/api/v1/patients/{p['id']}/history/").json()
    fields = {h["field"] for h in history}
    assert {"phone", "city"} <= fields
    assert all(h["changed_by"] for h in history)
