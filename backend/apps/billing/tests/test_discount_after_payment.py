"""Manager QA: discounts on invoices that were paid in full, and the audit trail of price edits. Synthetic data."""

from decimal import Decimal

import pytest

from apps.approvals.models import ApprovalRequest
from apps.audit.models import AuditEvent
from apps.billing.models import ServicePrice

from .test_billing_rules import _invoice, _visit_with_lab, ok

pytestmark = pytest.mark.django_db


def _issued(staff):
    p, v, _ = _visit_with_lab(staff)
    inv = _invoice(staff, p, v)
    return ok(staff.receptionist.post(f"/api/v1/billing/invoices/{inv['id']}/issue/"))


def _pay(staff, inv, amount):
    return staff.cashier.post(f"/api/v1/billing/invoices/{inv['id']}/payments/",
                              {"amount": str(amount), "method": "cash"}, format="json")


def _ask(staff, inv, amount):
    return staff.receptionist.post(f"/api/v1/billing/invoices/{inv['id']}/request-discount/",
                                   {"amount": str(amount), "reason": "Hardship"}, format="json")


def test_payment_cannot_swallow_a_waiting_discount(staff):
    inv = _issued(staff)
    total = Decimal(inv["total"])
    ok(_ask(staff, inv, 20), 201)
    # Taking the full undiscounted balance would leave the patient overpaid once the discount is approved.
    r = _pay(staff, inv, total)
    assert r.status_code == 409 and "not settled" in r.json()["error"]["message"]
    ok(_pay(staff, inv, total - 20), 201)


def test_discount_cannot_be_approved_or_applied_on_a_paid_invoice(staff):
    inv = _issued(staff)
    req = ok(_ask(staff, inv, 20), 201)
    # Simulate an invoice that was paid in full before these rules existed (the QA case INV-2026-000002).
    ApprovalRequest.objects.filter(pk=req["id"]).update(amount=Decimal("0.00"))
    ok(_pay(staff, inv, Decimal(inv["total"])), 201)
    ApprovalRequest.objects.filter(pk=req["id"]).update(amount=Decimal("20.00"))

    listed = ok(staff.clinic_admin.get(f"/api/v1/approvals/?object_id={inv['id']}"))["results"][0]
    assert "already paid in full" in listed["problem"]
    r = staff.clinic_admin.post(f"/api/v1/approvals/{req['id']}/approve/")
    assert r.status_code == 409 and "already paid in full" in r.json()["error"]["message"]
    # Rejecting still works, and nothing about the invoice changes.
    ok(staff.clinic_admin.post(f"/api/v1/approvals/{req['id']}/reject/", {"note": "Already paid"}, format="json"))
    after = ok(staff.cashier.get(f"/api/v1/billing/invoices/{inv['id']}/"))
    assert after["status"] == "paid" and Decimal(after["discount_amount"]) == 0
    # And no new discount can be asked for on a paid invoice.
    assert _ask(staff, inv, 10).status_code == 409


def test_approved_but_unapplied_discount_on_a_paid_invoice_is_flagged_and_can_be_closed(staff):
    inv = _issued(staff)
    req = ok(_ask(staff, inv, 20), 201)
    ok(staff.clinic_admin.post(f"/api/v1/approvals/{req['id']}/approve/"))
    # Old data: approved, then paid in full without applying it (the QA case INV-2026-000007).
    ApprovalRequest.objects.filter(pk=req["id"]).update(amount=Decimal("0.00"))
    ok(_pay(staff, inv, Decimal(inv["total"])), 201)
    ApprovalRequest.objects.filter(pk=req["id"]).update(amount=Decimal("20.00"))

    r = staff.receptionist.post(f"/api/v1/billing/invoices/{inv['id']}/apply-discount/",
                                {"approval_id": req["id"]}, format="json")
    assert r.status_code == 409 and "refund" in r.json()["error"]["message"]
    listed = ok(staff.cashier.get(f"/api/v1/approvals/?object_id={inv['id']}"))
    assert all(a["id"] != req["id"] for a in listed["results"]) or listed["results"][0]["problem"]
    # The approver may close it so it stops hanging on the invoice; the refund route stays separate.
    closed = ok(staff.clinic_admin.post(f"/api/v1/approvals/{req['id']}/withdraw/"))
    assert closed["status"] == "cancelled"


def test_approver_cannot_close_a_request_that_still_works(staff):
    inv = _issued(staff)
    req = ok(_ask(staff, inv, 20), 201)
    assert staff.clinic_admin.post(f"/api/v1/approvals/{req['id']}/withdraw/").status_code == 409


def test_price_edits_record_before_and_after(staff):
    svc = ok(staff.clinic_admin.post("/api/v1/billing/services/", {"code": "FLU", "name": "Fluoride", "category":
                                                                  "procedure", "price": "500"}, format="json"), 201)
    ok(staff.clinic_admin.patch(f"/api/v1/billing/services/{svc['id']}/", {"price": "501"}, format="json"))
    ev = AuditEvent.objects.filter(action="price.update").latest("occurred_at")
    assert ev.details["changes"]["price"] == {"from": "500.00", "to": "501.00"}
    assert ev.details["name"] == "Fluoride"
    assert ServicePrice.objects.get(pk=svc["id"]).price == Decimal("501")


def test_staff_manager_sees_staff_creation_in_audit_but_not_sign_ins(staff):
    from apps.accounts.models import Role

    role = Role.objects.get(code="receptionist")
    ok(staff.clinic_admin.post("/api/v1/users/", {"username": "new.assistant", "first_name": "New",
                                                 "last_name": "Assistant", "role_ids": [str(role.pk)]},
                               format="json"), 201)
    actions = [e["action"] for e in ok(staff.clinic_admin.get("/api/v1/audit-events/?page_size=200"))["results"]]
    assert "user.create" in actions
    assert not any(a.startswith("auth.") for a in actions)


def test_second_discount_request_counts_the_one_already_waiting(staff):
    inv = _issued(staff)
    subtotal = Decimal(inv["subtotal"])
    req = ok(_ask(staff, inv, 20), 201)
    ok(staff.clinic_admin.post(f"/api/v1/approvals/{req['id']}/approve/"))  # approved, not applied yet
    # Together with the approved 20 ETB this would discount more than the charges and block every payment.
    r = _ask(staff, inv, subtotal)
    assert r.status_code == 409 and "already waiting" in r.json()["error"]["message"]
    ok(_ask(staff, inv, subtotal - 20), 201)
