"""QA run 4: the receipt shows the cash received, the change given and the balance at the time. Synthetic data."""

from decimal import Decimal

import pytest

from apps.core.exceptions import _flatten_fields

from .test_billing_rules import ok
from .test_discount_after_payment import _issued

pytestmark = pytest.mark.django_db


def _pay(staff, inv, body):
    return staff.cashier.post(f"/api/v1/billing/invoices/{inv['id']}/payments/", body, format="json")


def test_cash_received_and_balance_at_the_time_are_kept_with_the_payment(staff):
    inv = _issued(staff)
    total = Decimal(inv["total"])
    part = (total / 2).quantize(Decimal("0.01"))
    first = ok(_pay(staff, inv, {"amount": str(part), "method": "cash",
                                 "amount_tendered": str(part + 300)}), 201)["new_payment"]
    assert Decimal(first["amount_tendered"]) == part + 300
    assert Decimal(first["change_given"]) == 300
    assert Decimal(first["balance_after"]) == total - part
    second = ok(_pay(staff, inv, {"amount": str(total - part), "method": "telebirr", "reference": "TX1"}),
                201)["new_payment"]
    assert second["amount_tendered"] is None and second["change_given"] is None
    assert Decimal(second["balance_after"]) == 0
    # The first receipt still shows what was owed when it was printed, not today's balance.
    payments = ok(staff.cashier.get(f"/api/v1/billing/invoices/{inv['id']}/"))["payments"]
    again = next(p for p in payments if p["id"] == first["id"])
    assert Decimal(again["balance_after"]) == total - part


def test_cash_received_must_cover_the_payment_and_is_for_cash_only(staff):
    inv = _issued(staff)
    total = Decimal(inv["total"])
    r = _pay(staff, inv, {"amount": str(total), "method": "cash", "amount_tendered": str(total - 1)})
    assert r.status_code == 400 and "amount_tendered" in r.json()["error"]["fields"]
    r = _pay(staff, inv, {"amount": str(total), "method": "telebirr", "reference": "TX2",
                          "amount_tendered": str(total)})
    assert r.status_code == 400 and "amount_tendered" in r.json()["error"]["fields"]


def test_errors_on_rows_say_which_line():
    out = _flatten_fields({"items": [{}, {"drug_name": ["This field may not be blank."]}]})
    assert out == {"items": ["line 2, drug_name: This field may not be blank."]}
    assert _flatten_fields({"amount": ["Required."]}) == {"amount": ["Required."]}
