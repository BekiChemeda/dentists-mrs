"""Daily storage readings for the System page trend charts."""

import datetime

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import HealthSample

pytestmark = pytest.mark.django_db


def test_opening_health_records_one_reading_per_day(sysadmin, login):
    client = login(sysadmin, client=APIClient())
    assert client.get("/api/v1/system/health/").status_code == 200
    assert client.get("/api/v1/system/health/").status_code == 200
    assert HealthSample.objects.count() == 1
    rows = client.get("/api/v1/system/health/history/").json()
    assert len(rows) == 1 and rows[0]["day"] == timezone.localdate().isoformat()
    assert rows[0]["disk_percent_used"] is not None


def test_history_range_and_permission(sysadmin, login, staff):
    today = timezone.localdate()
    for n in range(120):
        HealthSample.objects.create(day=today - datetime.timedelta(days=n), disk_percent_used=50)
    client = login(sysadmin, client=APIClient())
    assert len(client.get("/api/v1/system/health/history/").json()) == 90
    assert len(client.get("/api/v1/system/health/history/?days=30").json()) == 30
    assert staff.doctor.get("/api/v1/system/health/history/").status_code == 403


def test_daily_job_records_a_reading():
    from django.core.management import call_command

    call_command("health_alerts")
    assert HealthSample.objects.filter(day=timezone.localdate()).exists()
