"""Dental examinations and the odontogram. Synthetic data only."""

import pytest

from apps.audit.models import AuditEvent
from apps.dental import teeth

from .conftest import finding_type, ok, term

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- teeth
def test_fdi_numbering_and_surfaces():
    assert len(teeth.PERMANENT) == 32 and len(teeth.PRIMARY) == 20
    assert teeth.check_tooth("36") == 36 and teeth.check_tooth(75) == 75
    for bad in (10, 19, 49, 56, 86, 0, "x"):
        with pytest.raises(teeth.ToothError):
            teeth.check_tooth(bad)
    assert teeth.dentition(55) == "primary" and teeth.dentition(16) == "permanent"
    assert teeth.normalise_surfaces(36, "dom") == "MOD"
    assert teeth.normalise_surfaces(36, "od") == "DO" and teeth.normalise_surfaces(46, "bom") == "MOB"
    assert teeth.normalise_surfaces(11, ["b", "i"]) == "IB"
    with pytest.raises(teeth.ToothError):
        teeth.normalise_surfaces(11, "O")  # incisors have no occlusal surface
    with pytest.raises(teeth.ToothError):
        teeth.normalise_surfaces(46, "I")  # molars have no incisal edge
    with pytest.raises(teeth.ToothError):
        teeth.normalise_surfaces(46, "MM")
    assert teeth.can_have_furcation(36) and teeth.can_have_furcation(14) and not teeth.can_have_furcation(34)
    assert teeth.can_have_furcation(75) and not teeth.can_have_furcation(53)
    assert teeth.describe("surfaces", 36, "MOD") == "36 MOD"
    assert teeth.describe("region", region="q1") == "Upper right quadrant"


# --------------------------------------------------------------------------- examination
def test_start_sign_and_visit_flow(dental, exam):
    p, v, enc = exam()
    assert enc["status"] == "draft" and enc["visit_status"] == "in_consultation"
    # Starting again returns the same draft.
    again = ok(dental.dentist.post(f"/api/v1/dental/visits/{v['id']}/encounters/"), 201)
    assert again["id"] == enc["id"]
    # Incomplete: refused with field messages.
    r = dental.dentist.post(f"/api/v1/dental/encounters/{enc['id']}/sign/")
    assert r.status_code == 400 and {"chief_complaint", "diagnoses"} <= set(r.json()["error"]["fields"])
    enc = ok(dental.dentist.patch(f"/api/v1/dental/encounters/{enc['id']}/", {
        "version": enc["version"], "chief_complaint": "Pain lower left when chewing", "pain_present": True,
        "pain_teeth": [36], "pain_severity": 7, "pain_sensitivity": ["cold", "biting"], "pain_pattern": "intermittent",
        "intraoral_gingiva": "Healthy", "assessment": "Deep caries 36"}, format="json"))
    assert enc["pain_teeth"] == [36] and enc["pain_sensitivity"] == ["cold", "biting"]
    # A stale version is refused.
    r = dental.dentist.patch(f"/api/v1/dental/encounters/{enc['id']}/", {"version": 1, "assessment": "x"}, format="json")
    assert r.status_code == 409
    enc = ok(dental.dentist.post(f"/api/v1/dental/encounters/{enc['id']}/sign/"))
    assert enc["status"] == "signed" and enc["visit_status"] == "after_consult"
    # Signed: no more edits, only amendments with a reason.
    r = dental.dentist.patch(f"/api/v1/dental/encounters/{enc['id']}/", {"version": enc["version"], "assessment": "y"},
                             format="json")
    assert r.status_code == 409
    r = dental.dentist.post(f"/api/v1/dental/encounters/{enc['id']}/amendments/",
                            {"field_name": "assessment", "text": "Deep caries 36 DO", "reason": ""}, format="json")
    assert r.status_code == 400
    enc = ok(dental.dentist.post(f"/api/v1/dental/encounters/{enc['id']}/amendments/",
                                 {"field_name": "assessment", "text": "Deep caries 36 DO",
                                  "reason": "Surfaces were missing"}, format="json"), 201)
    assert enc["assessment"] == "Deep caries 36" and enc["amendments"][0]["original_text"] == "Deep caries 36"
    assert AuditEvent.objects.filter(action="dental_encounter.amend").exists()


def test_bad_tooth_and_sensitivity_refused(dental, exam):
    _, _, enc = exam()
    r = dental.dentist.patch(f"/api/v1/dental/encounters/{enc['id']}/", {"version": 1, "pain_teeth": [19]},
                             format="json")
    assert r.status_code == 400 and "pain_teeth" in r.json()["error"]["fields"]
    r = dental.dentist.patch(f"/api/v1/dental/encounters/{enc['id']}/", {"version": 1, "pain_sensitivity": ["loud"]},
                             format="json")
    assert r.status_code == 400


def test_only_author_edits_and_signs(dental, exam):
    _, _, enc = exam()
    r = dental.dentist2.patch(f"/api/v1/dental/encounters/{enc['id']}/", {"version": 1, "assessment": "x"},
                              format="json")
    assert r.status_code == 403
    assert dental.dentist2.post(f"/api/v1/dental/encounters/{enc['id']}/sign/").status_code == 403


def test_access_boundaries(dental, exam):
    p, v, enc = exam()
    # Reception, cashier, director: no dental clinical data.
    for who in (dental.receptionist, dental.cashier, dental.clinic_director, dental.dental_technician):
        assert who.get(f"/api/v1/dental/encounters/{enc['id']}/").status_code == 403
        assert who.get(f"/api/v1/dental/patients/{p['id']}/chart/").status_code == 403
        assert who.get(f"/api/v1/dental/patients/{p['id']}/summary/").status_code == 403
    # The assistant can read and chart but not write notes, diagnose or sign.
    ok(dental.dental_assistant.get(f"/api/v1/dental/encounters/{enc['id']}/"))
    assert dental.dental_assistant.patch(f"/api/v1/dental/encounters/{enc['id']}/", {"version": 1},
                                         format="json").status_code == 403
    assert dental.dental_assistant.post(f"/api/v1/dental/encounters/{enc['id']}/sign/").status_code == 403
    assert dental.dental_assistant.post(f"/api/v1/dental/encounters/{enc['id']}/diagnoses/", {},
                                        format="json").status_code == 403
    # Reading the record is audited.
    assert AuditEvent.objects.filter(action="dental_encounter.view", object_id=enc["id"]).exists()
    # The system administrator has no dental access.


def test_sysadmin_has_no_dental_access(dental, exam, sysadmin, login):
    from rest_framework.test import APIClient

    p, _, enc = exam()
    admin = login(sysadmin, client=APIClient())
    assert admin.get(f"/api/v1/dental/encounters/{enc['id']}/").status_code == 403


def test_diagnosis_snapshot_and_location(dental, exam):
    _, _, enc = exam()
    k021 = term(dental, "K02.1")
    dx = ok(dental.dentist.post(f"/api/v1/dental/encounters/{enc['id']}/diagnoses/", {
        "term_id": k021["id"], "scope": "surfaces", "tooth": 36, "surfaces": "do"}, format="json"), 201)
    assert dx["code"] == "K02.1" and dx["code_system"] == "ICD-10" and dx["location"]["label"] == "36 DO"
    assert "ICD-10" in dx["source_version"]
    # Renaming the catalogue term never changes the past record.
    ok(dental.clinic_admin.patch(f"/api/v1/dental/diagnosis-terms/{k021['id']}/", {"term": "Renamed"}, format="json"))
    detail = ok(dental.dentist.get(f"/api/v1/dental/encounters/{enc['id']}/"))
    assert detail["diagnoses"][0]["term_text"] == "Caries of dentine"
    r = dental.dentist.post(f"/api/v1/dental/encounters/{enc['id']}/diagnoses/", {
        "term_id": k021["id"], "scope": "surfaces", "tooth": 11, "surfaces": "O"}, format="json")
    assert r.status_code == 400 and "surfaces" in r.json()["error"]["fields"]


# --------------------------------------------------------------------------- odontogram
def _finding(client, enc_id, ftype, **where):
    return client.post(f"/api/v1/dental/encounters/{enc_id}/findings/", {"finding_type_id": ftype["id"], **where},
                       format="json")


def test_findings_history_and_reconstruction(dental, exam, catalog_data):
    caries, comp, missing = (finding_type(catalog_data, c) for c in ("caries", "restoration_composite", "missing"))
    p, v, enc1 = exam()
    # Several findings on one tooth, by the assistant at the chair.
    f1 = ok(_finding(dental.dental_assistant, enc1["id"], caries, scope="surfaces", tooth=36, surfaces="DO"), 201)
    ok(_finding(dental.dentist, enc1["id"], comp, scope="surfaces", tooth=36, surfaces="M"), 201)
    ok(_finding(dental.dentist, enc1["id"], missing, scope="tooth", tooth=48), 201)
    assert f1["recorded_by"]["username"] == "dental.assistant"
    # Wrong scope for the finding type is refused (missing applies to a whole tooth).
    assert _finding(dental.dentist, enc1["id"], missing, scope="surfaces", tooth=47, surfaces="O").status_code == 400
    ok(dental.dentist.patch(f"/api/v1/dental/encounters/{enc1['id']}/", {
        "version": 1, "chief_complaint": "Check-up", "assessment": "Caries 36"}, format="json"))
    enc1 = ok(dental.dentist.post(f"/api/v1/dental/encounters/{enc1['id']}/sign/"))
    # Signed: findings are frozen.
    assert dental.dentist.delete(f"/api/v1/dental/findings/{f1['id']}/").status_code == 409
    assert _finding(dental.dentist, enc1["id"], caries, scope="tooth", tooth=37).status_code == 409

    # A later visit: caries restored. The old finding is resolved, the new restoration recorded.
    ok(dental.receptionist.post(f"/api/v1/visits/{v['id']}/complete/", {"outcome": "completed"}, format="json"))
    from apps.scheduling.models import Visit

    Visit.objects.filter(pk=v["id"]).update(visit_date="2020-01-01")
    v2 = ok(dental.receptionist.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    enc2 = ok(dental.dentist.post(f"/api/v1/dental/visits/{v2['id']}/encounters/"), 201)
    r = dental.dentist.post(f"/api/v1/dental/findings/{f1['id']}/resolve/", {"encounter_id": enc2["id"], "note": ""},
                            format="json")
    assert r.status_code == 400
    ok(dental.dentist.post(f"/api/v1/dental/findings/{f1['id']}/resolve/",
                           {"encounter_id": enc2["id"], "note": "Restored with composite"}, format="json"))
    ok(_finding(dental.dentist, enc2["id"], comp, scope="surfaces", tooth=36, surfaces="DO"), 201)

    now = ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/chart/"))
    on36 = sorted((f["finding_type"]["code"], f["location"]["surfaces"]) for f in now["findings"] if f["location"]["tooth"] == 36)
    assert on36 == [("restoration_composite", "DO"), ("restoration_composite", "M")]
    then = ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/chart/?encounter={enc1['id']}"))
    on36_then = sorted((f["finding_type"]["code"], f["location"]["surfaces"]) for f in then["findings"]
                       if f["location"]["tooth"] == 36)
    assert on36_then == [("caries", "DO"), ("restoration_composite", "M")]
    history = ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/chart/history/?tooth=36"))
    assert len(history) == 3 and any(h["resolution_note"] == "Restored with composite" for h in history)
    diff = ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/chart/compare/?from={enc1['id']}&to={enc2['id']}"))
    assert [f["finding_type"]["code"] for f in diff["no_longer_present"]] == ["caries"]
    assert [f["finding_type"]["code"] for f in diff["added"]] == ["restoration_composite"]


def test_void_needs_amend_permission_and_reason(dental, exam, catalog_data):
    caries = finding_type(catalog_data, "caries")
    p, v, enc = exam()
    f = ok(_finding(dental.dentist, enc["id"], caries, scope="tooth", tooth=21), 201)
    # While the draft is open: remove, not void.
    assert dental.dentist.post(f"/api/v1/dental/findings/{f['id']}/void/", {"reason": "x"}, format="json").status_code == 409
    ok(dental.dentist.delete(f"/api/v1/dental/findings/{f['id']}/"), 204)
    f = ok(_finding(dental.dentist, enc["id"], caries, scope="tooth", tooth=22), 201)
    ok(dental.dentist.patch(f"/api/v1/dental/encounters/{enc['id']}/", {"version": 1, "chief_complaint": "x",
                                                                        "assessment": "y"}, format="json"))
    ok(dental.dentist.post(f"/api/v1/dental/encounters/{enc['id']}/sign/"))
    assert dental.dental_assistant.post(f"/api/v1/dental/findings/{f['id']}/void/", {"reason": "Wrong tooth"},
                                        format="json").status_code == 403
    assert dental.dentist.post(f"/api/v1/dental/findings/{f['id']}/void/", {"reason": ""}, format="json").status_code == 400
    voided = ok(dental.dentist.post(f"/api/v1/dental/findings/{f['id']}/void/", {"reason": "Wrong tooth"}, format="json"))
    assert voided["voided_at"] and voided["void_reason"] == "Wrong tooth"
    chart_now = ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/chart/"))
    assert not [x for x in chart_now["findings"] if x["location"]["tooth"] == 22]
    hist = ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/chart/history/?tooth=22"))
    assert hist[0]["voided_at"]  # still in the history


def test_primary_and_mixed_dentition(dental, exam, patient, catalog_data):
    child = patient("Hana", age=8, sex="female")
    _, _, enc = exam(child)
    caries, unerupted = finding_type(catalog_data, "caries"), finding_type(catalog_data, "unerupted")
    ok(_finding(dental.dentist, enc["id"], caries, scope="surfaces", tooth=75, surfaces="O"), 201)
    ok(_finding(dental.dentist, enc["id"], unerupted, scope="tooth", tooth=45), 201)
    assert _finding(dental.dentist, enc["id"], caries, scope="tooth", tooth=56).status_code == 400
    chart_now = ok(dental.dentist.get(f"/api/v1/dental/patients/{child['id']}/chart/"))
    assert chart_now["has_primary"] and sorted(chart_now["teeth_with_history"]) == [45, 75]


def test_concurrent_note_edits_conflict(dental, exam):
    _, _, enc = exam()
    first = ok(dental.dentist.patch(f"/api/v1/dental/encounters/{enc['id']}/", {"version": 1, "assessment": "A"},
                                    format="json"))
    r = dental.dentist.patch(f"/api/v1/dental/encounters/{enc['id']}/", {"version": 1, "assessment": "B"}, format="json")
    assert r.status_code == 409 and first["version"] == 2


def test_risk_review_and_profile(dental, exam):
    p, _, enc = exam()
    answers = {k: {"answer": "no"} for k in ("cardiovascular", "diabetes", "bleeding", "immune", "pregnancy",
                                              "anaesthesia_reaction", "surgery_hospital", "other")}
    answers["pregnancy"] = {"answer": "not_applicable"}
    r = dental.dentist.post(f"/api/v1/dental/patients/{p['id']}/risk-reviews/",
                            {"answers": {**answers, "bleeding": {"answer": "yes"}}, "encounter_id": enc["id"]},
                            format="json")
    assert r.status_code == 400 and "bleeding" in r.json()["error"]["fields"]  # yes needs the detail
    first = ok(dental.dentist.post(f"/api/v1/dental/patients/{p['id']}/risk-reviews/",
                                   {"answers": answers, "allergies_reviewed": True, "medications_reviewed": True,
                                    "encounter_id": enc["id"]}, format="json"), 201)
    assert first["changed_since_previous"] is None
    answers["bleeding"] = {"answer": "yes", "detail": "Takes warfarin"}
    second = ok(dental.dentist.post(f"/api/v1/dental/patients/{p['id']}/risk-reviews/", {"answers": answers},
                                    format="json"), 201)
    assert second["changed_since_previous"] is True
    detail = ok(dental.dentist.get(f"/api/v1/dental/encounters/{enc['id']}/"))
    assert detail["risk_review"]["id"] == first["id"]
    # Profile: versioned, every change kept.
    prof = ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/profile/"))
    prof = ok(dental.dentist.patch(f"/api/v1/dental/patients/{p['id']}/profile/",
                                   {"row_version": prof["row_version"], "tobacco_use": "former",
                                    "anxiety_notes": "Nervous about injections"}, format="json"))
    r = dental.dentist.patch(f"/api/v1/dental/patients/{p['id']}/profile/",
                             {"row_version": 1, "anxiety_notes": "x"}, format="json")
    assert r.status_code == 409
    from apps.dental.models import DentalProfileChange

    assert DentalProfileChange.objects.filter(profile_id=prof["id"]).count() == 2
    assert dental.dental_assistant.patch(f"/api/v1/dental/patients/{p['id']}/profile/", {"anxiety_notes": "x"},
                                         format="json").status_code == 403
    summary = ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/summary/"))
    assert summary["risk_review"]["id"] == second["id"] and summary["profile"]["tobacco_use"] == "former"


def test_queue_shows_dentists_and_dental_encounters(dental, exam):
    docs = ok(dental.receptionist.get("/api/v1/doctors/"))
    assert {"dentist", "dentist.two"} <= {d["username"] for d in docs}
    _, v, enc = exam()
    visits = ok(dental.dentist.get("/api/v1/visits/"))
    row = next(x for x in visits if x["id"] == v["id"])
    assert row["dental_encounters"][0]["id"] == enc["id"]
