"""Reference ranges by age and sex, critical results, qualitative tests and repeats. Synthetic data only."""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.laboratory.models import LabOrderItem, LabTest
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json()


def _encounter(staff, *, sex="female", birth="1990-01-01"):
    rc = staff.receptionist
    p = ok(rc.post("/api/v1/patients/", {"first_name": "Lab", "middle_name": sex, "sex": sex, "birth_date": birth,
                                         "confirm_not_duplicate": True}, format="json"), 201)
    v = ok(rc.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    return ok(staff.doctor.post(f"/api/v1/visits/{v['id']}/encounters/"), 201)


def _order(staff, enc, *codes):
    ids = [str(LabTest.objects.get(code=c).pk) for c in codes]
    order = ok(staff.doctor.post(f"/api/v1/encounters/{enc['id']}/lab-orders/", {"test_ids": ids}, format="json"), 201)
    return {i["test"]["code"]: i for i in order["items"]}


def _result(staff, item, value, **extra):
    lab = staff.lab_technician
    if item["status"] == "ordered":
        ok(lab.post(f"/api/v1/lab/items/{item['id']}/collect/"))
    ok(lab.post(f"/api/v1/lab/items/{item['id']}/result/", {"value": value}, format="json"))
    return lab.post(f"/api/v1/lab/items/{item['id']}/verify/", extra, format="json")


def test_haemoglobin_range_depends_on_sex_and_age(staff):
    woman = _order(staff, _encounter(staff, sex="female"), "HGB")["HGB"]
    man = _order(staff, _encounter(staff, sex="male"), "HGB")["HGB"]
    child = _order(staff, _encounter(staff, sex="male", birth=(timezone.localdate() - datetime.timedelta(days=3 * 365))
                                     .isoformat()), "HGB")["HGB"]
    assert Decimal(woman["ref_low"]) == Decimal("12") and Decimal(man["ref_low"]) == Decimal("13")
    assert Decimal(child["ref_low"]) == Decimal("11")
    # 12.5 is normal for a woman and low for a man.
    ok(_result(staff, woman, "12.5"))
    ok(_result(staff, man, "12.5"))
    flags = {i.test.code + i.order.patient.sex: i.flag for i in LabOrderItem.objects.filter(status="verified")}
    assert flags == {"HGBfemale": "N", "HGBmale": "L"}


def test_critical_result_requires_report_and_acknowledgement(staff):
    hgb = LabTest.objects.get(code="HGB")
    hgb.critical_low = Decimal("7")
    hgb.save()
    enc = _encounter(staff)
    item = _order(staff, enc, "HGB")["HGB"]
    r = _result(staff, item, "6.1")
    assert r.status_code == 400 and "critical_reported_to" in r.json()["error"]["fields"]
    order = ok(staff.lab_technician.post(f"/api/v1/lab/items/{item['id']}/verify/",
                                         {"critical_reported_to": "Dr. Dawit Haile by phone"}, format="json"))
    row = order["items"][0]
    assert row["flag"] == "LL" and row["critical_reported_to"] == "Dr. Dawit Haile by phone"
    assert Notification.objects.filter(user=staff.users.doctor, kind="critical_result").exists()
    pending = ok(staff.doctor.get("/api/v1/lab/critical/?mine=1"))
    assert [p["id"] for p in pending] == [item["id"]]
    assert staff.lab_technician.post(f"/api/v1/lab/items/{item['id']}/acknowledge/").status_code == 403
    ok(staff.doctor.post(f"/api/v1/lab/items/{item['id']}/acknowledge/"))
    assert ok(staff.doctor.get("/api/v1/lab/critical/?mine=1")) == []
    report = ok(staff.clinic_admin.get("/api/v1/reports/lab_results/"))
    assert report["rows"][0]["critical"] == 1 and report["rows"][0]["unacknowledged"] == 0


def test_qualitative_and_critical_answer(staff):
    t = LabTest.objects.create(code="RDTM", name="Malaria RDT", category="Parasitology", result_type="qualitative",
                               price=Decimal("50"), critical_choices="")
    enc = _encounter(staff)
    item = _order(staff, enc, "RDTM")["RDTM"]
    assert item["test"]["answers"] == ["Negative", "Positive", "Indeterminate"]
    lab = staff.lab_technician
    ok(lab.post(f"/api/v1/lab/items/{item['id']}/collect/", {"specimen_type": "Capillary blood"}, format="json"))
    assert lab.post(f"/api/v1/lab/items/{item['id']}/result/", {"value": "maybe"}, format="json").status_code == 400
    ok(lab.post(f"/api/v1/lab/items/{item['id']}/result/", {"value": "Positive"}, format="json"))
    row = ok(lab.post(f"/api/v1/lab/items/{item['id']}/verify/"))["items"][0]
    assert row["flag"] == "A" and row["specimen_type"] == "Capillary blood"
    t.critical_choices = "P. falciparum"
    t.save()


def test_repeat_after_rejected_specimen_is_not_charged(staff):
    enc = _encounter(staff)
    item = _order(staff, enc, "RBS")["RBS"]
    lab = staff.lab_technician
    assert lab.post(f"/api/v1/lab/items/{item['id']}/repeat/", {"reason": "x"}, format="json").status_code == 409
    ok(lab.post(f"/api/v1/lab/items/{item['id']}/collect/"))
    order = ok(lab.post(f"/api/v1/lab/items/{item['id']}/repeat/", {"reason": "Haemolysed specimen",
                                                                   "chargeable": True}, format="json"))
    rows = {r["id"]: r for r in order["items"]}
    original = rows[item["id"]]
    repeat = next(r for r in order["items"] if r["repeat_of"] == item["id"])
    assert original["status"] == "cancelled" and repeat["status"] == "ordered"
    assert repeat["is_chargeable"] is False  # the laboratory cannot make its own repeat chargeable
    # Collection time cannot be in the future.
    future = (timezone.now() + datetime.timedelta(hours=1)).isoformat()
    assert lab.post(f"/api/v1/lab/items/{repeat['id']}/collect/", {"collected_at": future},
                    format="json").status_code == 400
    ok(lab.post(f"/api/v1/lab/items/{repeat['id']}/collect/"))
    # Billing: the repeat is not charged, the cancelled original is not charged.
    from apps.billing.services import unbilled_charges
    from apps.scheduling.models import Visit
    visit = Visit.objects.get(pk=LabOrderItem.objects.get(pk=item["id"]).order.visit_id)
    assert [c["description"] for c in unbilled_charges(visit) if c["kind"] == "lab"] == []
