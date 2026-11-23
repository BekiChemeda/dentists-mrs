"""Built-in Accountant role: read-only financial oversight. Synthetic data only."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role

pytestmark = pytest.mark.django_db


def test_accountant_role_exists_with_read_only_finance(db):
    role = Role.objects.get(code="accountant")
    assert role.is_system
    codes = set(role.permissions.values_list("code", flat=True))
    assert {"billing.view", "reports.financial", "reports.export"} <= codes
    for forbidden in ("billing.payment", "billing.invoice", "billing.discount.approve", "billing.void.approve",
                      "clinical.view", "patients.update", "users.manage", "settings.manage"):
        assert forbidden not in codes


def test_accountant_can_read_finance_but_not_take_money_or_see_notes(make_user, login, catalog):
    client = login(make_user("accountant", username="accounts.one"), client=APIClient())
    assert client.get("/api/v1/billing/invoices/").status_code == 200
    assert client.get("/api/v1/billing/payments/").status_code == 200
    assert client.get("/api/v1/billing/daily-summary/").status_code == 200
    assert client.get("/api/v1/reports/revenue/").status_code == 200
    assert client.post("/api/v1/billing/invoices/", {}, format="json").status_code == 403
    assert client.get("/api/v1/patients/").status_code == 403
    assert client.get("/api/v1/users/").status_code == 403


def test_clinic_admin_can_assign_accountant(staff):
    role = Role.objects.get(code="accountant")
    body = {"username": "acc.two", "first_name": "Synthetic", "last_name": "Accountant", "role_ids": [str(role.pk)]}
    r = staff.clinic_admin.post("/api/v1/users/", body, format="json")
    assert r.status_code == 201, r.content
