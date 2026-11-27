"""
Regressions from the code review of November 2026: plan decisions against open procedure records, prices at
signing, per-session estimates, audit of chart reads, perio comparison across patients, amendment authorship.
Synthetic data only.
"""

from decimal import Decimal

import pytest

from apps.audit.models import AuditEvent
from apps.dental.models import ProcedureRecord, TreatmentPlanItem

from .conftest import ok, procedure
from .test_plans_and_procedures import _plan, _price, _record, _sign, _sign_exam

pytestmark = pytest.mark.django_db


def _accepted_item(dental, exam, catalog_data, code="RS-COMP2", where=None):
    p, v, enc = exam()
    plan = _plan(dental, p["id"], [(code, where or {"scope": "surfaces", "tooth": 36, "surfaces": "MO"})],
                 catalog_data, enc)
    ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/present/"))
    item = plan["items"][0]
    ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/decision/", {"decisions": {item["id"]: "accepted"}},
                           format="json"))
    return p, v, enc, plan, item


# --------------------------------------------------------------------------- declined items are never completed
def test_patient_cannot_decline_an_item_while_its_record_is_open(dental, exam, catalog_data):
    _price(dental, catalog_data, "RS-COMP2", "1500.00")
    _, _, enc, plan, item = _accepted_item(dental, exam, catalog_data)
    rec = ok(_record(dental, enc, item), 201)
    for decision in ("declined", "deferred"):
        r = dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/decision/", {"decisions": {item["id"]: decision}},
                                format="json")
        assert r.status_code == 409 and "unsigned procedure record" in r.json()["error"]["message"]
    r = dental.dentist.post(f"/api/v1/dental/plan-items/{item['id']}/cancel/", {"reason": "Changed mind"},
                            format="json")
    assert r.status_code == 409 and "unsigned procedure record" in r.json()["error"]["message"]
    # Once the draft is discarded, the decision can be recorded.
    ok(dental.dentist.post(f"/api/v1/dental/procedure-records/{rec['id']}/discard/", {"reason": "Patient declined"},
                           format="json"), 204)
    ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/decision/", {"decisions": {item["id"]: "declined"}},
                           format="json"))


def test_signing_refuses_an_item_that_is_no_longer_accepted(dental, exam, catalog_data):
    _price(dental, catalog_data, "RS-COMP2", "1500.00")
    _, _, enc, plan, item = _accepted_item(dental, exam, catalog_data)
    rec = ok(_record(dental, enc, item), 201)
    # However the item came to be declined (an older version, a direct data fix), signing must not complete it.
    TreatmentPlanItem.objects.filter(pk=item["id"]).update(status="declined")
    r = _sign(dental, rec)
    assert r.status_code == 409 and "declined" in r.json()["error"]["message"]
    assert TreatmentPlanItem.objects.get(pk=item["id"]).status == "declined"
    assert ProcedureRecord.objects.get(pk=rec["id"]).status == "draft"
    # It can still be recorded as not performed.
    ok(_sign(dental, rec, "not_performed", reason="Patient declined at the chair"))


# --------------------------------------------------------------------------- prices at signing
def test_signing_at_price_zero_needs_confirmation(dental, exam, catalog_data):
    p, v, enc = exam()
    code = procedure(catalog_data, "OS-EXT")["id"]  # the starter catalogue ships at 0 ETB
    rec = ok(_record(dental, enc, code=code, scope="tooth", tooth=38), 201)
    detail = ok(dental.dentist.get(f"/api/v1/dental/procedure-records/{rec['id']}/"))
    assert detail["charge"]["warning"] == "no_price"
    r = _sign(dental, rec)
    assert r.status_code == 409 and r.json()["error"]["charge"]["warning"] == "no_price"
    assert ProcedureRecord.objects.get(pk=rec["id"]).status == "draft"
    rec = ok(_sign(dental, rec, confirm_charge=True))
    assert rec["status"] == "completed" and rec["price"] == "0.00" and rec["charge"] is None
    event = AuditEvent.objects.get(action="dental_procedure.sign", object_id=rec["id"])
    assert event.details["charge_confirmed"] == "no_price"


def test_not_performed_and_unbilled_sessions_need_no_price_confirmation(dental, exam, catalog_data):
    p, v, enc = exam()
    rec = ok(_record(dental, enc, code=procedure(catalog_data, "OS-EXT")["id"], scope="tooth", tooth=38), 201)
    ok(_sign(dental, rec, "not_performed", reason="Referred"))


def test_price_different_from_the_accepted_estimate_needs_confirmation(dental, exam, catalog_data):
    _price(dental, catalog_data, "RS-COMP2", "1500.00")
    _, _, enc, plan, item = _accepted_item(dental, exam, catalog_data)
    assert Decimal(item["estimated_fee"]) == Decimal("1500.00")
    _price(dental, catalog_data, "RS-COMP2", "2200.00")  # the price list changed after the patient agreed
    rec = ok(_record(dental, enc, item), 201)
    charge = ok(dental.dentist.get(f"/api/v1/dental/procedure-records/{rec['id']}/"))["charge"]
    assert charge == {"price": "2200.00", "estimate": "1500.00", "expected_total": "2200.00",
                      "billing_mode": "on_completion", "warning": "differs_from_estimate"}
    r = _sign(dental, rec)
    assert r.status_code == 409 and "1500.00" in r.json()["error"]["message"]
    rec = ok(_sign(dental, rec, confirm_charge=True))
    assert rec["price"] == "2200.00"


def test_matching_price_signs_without_confirmation(dental, exam, catalog_data):
    _price(dental, catalog_data, "RS-COMP2", "1500.00")
    _, _, enc, _, item = _accepted_item(dental, exam, catalog_data)
    rec = ok(_record(dental, enc, item), 201)
    assert ok(dental.dentist.get(f"/api/v1/dental/procedure-records/{rec['id']}/"))["charge"]["warning"] is None
    ok(_sign(dental, rec))


def test_per_session_estimate_covers_every_session(dental, exam, catalog_data):
    _price(dental, catalog_data, "EN-RCT", "1200.00")
    p, _, enc = exam()
    plan = _plan(dental, p["id"], [("EN-RCT", {"scope": "tooth", "tooth": 46})], catalog_data, enc)
    item = plan["items"][0]
    assert item["sessions_planned"] == 3 and Decimal(item["estimated_fee"]) == Decimal("3600.00")


# --------------------------------------------------------------------------- audit of sensitive reads
def test_chart_history_and_comparisons_are_audited(dental, exam):
    p, _, enc = exam()
    ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/chart/history/"))
    ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/diagnoses/"))
    ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/perio/"))
    actions = set(AuditEvent.objects.filter(details__patient=p["id"]).values_list("action", flat=True))
    assert {"dental_chart.history_view", "dental_diagnoses.view", "dental_perio.view"} <= actions


def test_perio_comparison_refuses_two_patients(dental, exam):
    charts = []
    for name in ("Abebe", "Tigist"):
        p, _, enc = exam()
        ok(dental.dentist.put(f"/api/v1/dental/encounters/{enc['id']}/perio/", {"teeth": [
            {"tooth": 36, "sites": {"MB": {"probing_depth_mm": 4, "gingival_margin_mm": 1}}}]}, format="json"))
        charts.append(ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/perio/"))[0])
    r = dental.dentist.get(f"/api/v1/dental/perio/compare/?a={charts[0]['id']}&b={charts[1]['id']}")
    assert r.status_code == 400


# --------------------------------------------------------------------------- amendments by the author
def test_only_the_author_amends_a_signed_examination(dental, exam):
    _, _, enc = exam()
    _sign_exam(dental, enc)
    url = f"/api/v1/dental/encounters/{enc['id']}/amendments/"
    body = {"field_name": "assessment", "text": "Corrected", "reason": "Typo"}
    assert dental.dentist2.post(url, body, format="json").status_code == 403
    ok(dental.dentist.post(url, body, format="json"), 201)
    # The author has left the clinic: another dentist may now correct it.
    dental.users.dentist.is_active = False
    dental.users.dentist.save(update_fields=["is_active"])
    ok(dental.dentist2.post(url, {**body, "text": "Corrected again"}, format="json"), 201)


def test_only_the_signer_amends_a_procedure_record(dental, exam, catalog_data):
    _price(dental, catalog_data, "OS-EXT", "800.00")
    _, _, enc = exam()
    rec = ok(_record(dental, enc, code=procedure(catalog_data, "OS-EXT")["id"], scope="tooth", tooth=38), 201)
    ok(_sign(dental, rec))
    url = f"/api/v1/dental/procedure-records/{rec['id']}/amendments/"
    body = {"field_name": "notes", "text": "Sutures placed", "reason": "Omitted"}
    assert dental.dentist2.post(url, body, format="json").status_code == 403
    ok(dental.dentist.post(url, body, format="json"))
