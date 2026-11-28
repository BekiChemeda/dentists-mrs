"""One-person clinic: the owner may approve their own refund only when the clinic says so and nobody else could.
Synthetic data."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.billing.tests.test_billing_rules import _invoice, _visit_with_lab, ok
from apps.core.models import ClinicSettings
from conftest import PASSWORD

pytestmark = pytest.mark.django_db


def _client(user):
    c = APIClient()
    assert c.post("/api/v1/auth/login/", {"username": user.username, "password": PASSWORD},
                  format="json").status_code == 200
    return c


def _refund_request(staff, owner):
    p, v, _ = _visit_with_lab(staff)
    inv = ok(staff.receptionist.post(f"/api/v1/billing/invoices/{_invoice(staff, p, v)['id']}/issue/"))
    inv = ok(owner.post(f"/api/v1/billing/invoices/{inv['id']}/payments/",
                        {"amount": inv["total"], "method": "cash"}, format="json"), 201)
    pay = inv["payments"][0]
    req = ok(owner.post(f"/api/v1/billing/payments/{pay['id']}/request-refund/",
                        {"amount": "50", "reason": "Test not done"}, format="json"), 201)
    return pay, req


def test_owner_approves_own_refund_only_when_alone_and_with_a_reason(staff, make_user):
    owner_user = make_user("clinic_director", "receptionist", "cashier", username="owner.dentist")
    owner = _client(owner_user)
    pay, req = _refund_request(staff, owner)
    approve = f"/api/v1/approvals/{req['id']}/approve/"

    # Off by default: a second person is needed.
    assert owner.post(approve, {"note": "x"}, format="json").status_code == 409
    row = next(r for r in ok(owner.get("/api/v1/approvals/?status=pending"))["results"] if r["id"] == req["id"])
    assert row["can_decide"] is False and row["self_approval"] is False

    # Switched on, but the clinic administrator could still approve: still refused.
    s = ClinicSettings.get()
    s.solo_approvals = True
    s.save()
    assert owner.post(approve, {"note": "x"}, format="json").status_code == 409

    # Nobody else can approve any more: allowed, with a written reason.
    staff.users.clinic_admin.is_active = False
    staff.users.clinic_admin.save()
    row = next(r for r in ok(owner.get("/api/v1/approvals/?status=pending"))["results"] if r["id"] == req["id"])
    assert row["can_decide"] is True and row["self_approval"] is True
    assert owner.post(approve, {"note": " "}, format="json").status_code == 400
    ok(owner.post(approve, {"note": "Only person working today; test was not done"}, format="json"))
    inv = ok(owner.post(f"/api/v1/billing/payments/{pay['id']}/refund/",
                        {"approval_id": req["id"], "method": "cash"}, format="json"), 201)
    assert Decimal(inv["refunds"][0]["amount"]) == 50
    event = AuditEvent.objects.filter(action="approval.approve", object_id=str(req["id"])).get()
    assert event.details["self_approved"] is True and "test was not done" in event.details["note"]


def test_a_second_approver_ends_self_approval(staff, make_user):
    owner = _client(make_user("clinic_director", "cashier", username="owner.two"))
    staff.users.clinic_admin.is_active = False
    staff.users.clinic_admin.save()
    s = ClinicSettings.get()
    s.solo_approvals = True
    s.save()
    _, req = _refund_request(staff, owner)
    make_user("clinic_admin", username="new.manager")  # the clinic hires a manager
    assert owner.post(f"/api/v1/approvals/{req['id']}/approve/", {"note": "x"}, format="json").status_code == 409
