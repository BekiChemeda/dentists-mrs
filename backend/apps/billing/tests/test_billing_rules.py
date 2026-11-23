"""Billing policy, tax, refunds and net revenue. Synthetic data only."""

from decimal import Decimal

import pytest

from apps.billing.models import ServicePrice
from apps.core.models import ClinicSettings
from apps.laboratory.models import LabTest

pytestmark = pytest.mark.django_db


def ok(r, code=200):
    assert r.status_code == code, r.content
    return r.json()


def _visit_with_lab(staff):
    rc = staff.receptionist
    p = ok(rc.post("/api/v1/patients/", {"first_name": "Bill", "sex": "male", "age_years": 30,
                                         "confirm_not_duplicate": True}, format="json"), 201)
    v = ok(rc.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    enc = ok(staff.doctor.post(f"/api/v1/visits/{v['id']}/encounters/"), 201)
    order = ok(staff.doctor.post(f"/api/v1/encounters/{enc['id']}/lab-orders/",
                                 {"test_ids": [str(LabTest.objects.get(code="RBS").pk)]}, format="json"), 201)
    return p, v, order["items"][0]


def _invoice(staff, p, v):
    return ok(staff.receptionist.post("/api/v1/billing/invoices/", {"patient_id": p["id"], "visit_id": v["id"]},
                                      format="json"), 201)


def test_lab_billed_according_to_policy(staff):
    p, v, item = _visit_with_lab(staff)
    # Default policy: bill when the specimen is collected. Requested-only tests are not charged.
    inv = _invoice(staff, p, v)
    assert sorted(l["kind"] for l in inv["lines"]) == ["consultation"]
    ok(staff.lab_technician.post(f"/api/v1/lab/items/{item['id']}/collect/"))
    inv = ok(staff.receptionist.post(f"/api/v1/billing/invoices/{inv['id']}/pull-charges/"))
    assert sorted(l["kind"] for l in inv["lines"]) == ["consultation", "lab"]


def test_policy_ordered_and_verified(staff):
    s = ClinicSettings.get()
    s.lab_billing_point = "ordered"
    s.save()
    p, v, _ = _visit_with_lab(staff)
    assert "lab" in [l["kind"] for l in _invoice(staff, p, v)["lines"]]
    s.lab_billing_point = "verified"
    s.save()
    p, v, _ = _visit_with_lab(staff)
    assert "lab" not in [l["kind"] for l in _invoice(staff, p, v)["lines"]]


def test_tax_on_discounted_total(staff):
    svc = ServicePrice.objects.create(code="COSM", name="Cosmetic procedure", category="procedure",
                                      price=Decimal("1000"), tax_rate=Decimal("15"))
    p, v, _ = _visit_with_lab(staff)
    inv = _invoice(staff, p, v)
    inv = ok(staff.receptionist.post(f"/api/v1/billing/invoices/{inv['id']}/lines/", {"service_id": str(svc.pk)},
                                     format="json"))
    consult = Decimal([l for l in inv["lines"] if l["kind"] == "consultation"][0]["line_total"])
    assert Decimal(inv["tax_amount"]) == Decimal("150.00")
    assert Decimal(inv["total"]) == consult + Decimal("1000") + Decimal("150")
    # Discount reduces the tax base proportionally.
    req = ok(staff.receptionist.post(f"/api/v1/billing/invoices/{inv['id']}/request-discount/",
                                     {"amount": str(consult + Decimal("1000")), "reason": "Staff family"}, format="json"), 201)
    ok(staff.clinic_admin.post(f"/api/v1/approvals/{req['id']}/approve/"))
    inv = ok(staff.receptionist.post(f"/api/v1/billing/invoices/{inv['id']}/apply-discount/", {"approval_id": req["id"]},
                                     format="json"))
    assert Decimal(inv["tax_amount"]) == 0 and Decimal(inv["total"]) == 0


def test_refund_needs_approval_and_reduces_revenue(staff):
    p, v, _ = _visit_with_lab(staff)
    inv = _invoice(staff, p, v)
    inv = ok(staff.receptionist.post(f"/api/v1/billing/invoices/{inv['id']}/issue/"))
    total = Decimal(inv["total"])
    inv = ok(staff.cashier.post(f"/api/v1/billing/invoices/{inv['id']}/payments/", {"amount": str(total), "method": "cash"},
                                format="json"), 201)
    pay = inv["payments"][0]
    assert staff.cashier.post(f"/api/v1/billing/payments/{pay['id']}/request-refund/",
                              {"amount": str(total + 1), "reason": "x"}, format="json").status_code == 400
    req = ok(staff.cashier.post(f"/api/v1/billing/payments/{pay['id']}/request-refund/",
                                {"amount": "50", "reason": "Test not done"}, format="json"), 201)
    # Without approval the refund cannot be paid out.
    assert staff.cashier.post(f"/api/v1/billing/payments/{pay['id']}/refund/",
                              {"approval_id": req["id"], "method": "cash"}, format="json").status_code == 409
    ok(staff.clinic_admin.post(f"/api/v1/approvals/{req['id']}/approve/"))
    inv = ok(staff.cashier.post(f"/api/v1/billing/payments/{pay['id']}/refund/",
                                {"approval_id": req["id"], "method": "cash"}, format="json"), 201)
    assert inv["status"] == "partial" and Decimal(inv["balance"]) == Decimal("50")
    assert inv["refunds"][0]["number"].startswith("RFD-") and inv["payments"][0]["refundable"] == str(total - 50)
    summary = ok(staff.cashier.get("/api/v1/billing/daily-summary/"))
    assert Decimal(str(summary["collected_total"])) == total - 50 and Decimal(str(summary["refunded_total"])) == 50
    rev = ok(staff.clinic_admin.get("/api/v1/reports/revenue/"))["rows"][-1]
    assert Decimal(rev["total"]) == total - 50 and Decimal(rev["refunded"]) == 50
    # A paid invoice cannot be voided until the payment is refunded.
    assert staff.receptionist.post(f"/api/v1/billing/invoices/{inv['id']}/request-void/", {"reason": "x"},
                                   format="json").status_code == 409
