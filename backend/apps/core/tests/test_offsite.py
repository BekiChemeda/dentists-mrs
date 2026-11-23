"""Off-site backup switch, schedule and run log. The upload itself is tested by deploy/scripts/test-offsite-backup.sh."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.core import offsite
from apps.core.management.commands.offsite import clean_target
from apps.core.models import OffsiteBackupRun, SystemSettings
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


def _set(enabled, hours=6):
    SystemSettings.get()
    SystemSettings.objects.filter(pk=1).update(offsite_enabled=enabled, offsite_interval_hours=hours)


def _run(status="success", ago=timedelta(0)):
    run = OffsiteBackupRun.objects.create(started_at=timezone.now() - ago, status=status)
    OffsiteBackupRun.objects.filter(pk=run.pk).update(finished_at=timezone.now() - ago)


def _check():
    with pytest.raises(SystemExit) as exc:
        call_command("offsite", "check")
        raise SystemExit(0)
    return exc.value.code


def test_off_by_default_and_check_says_off():
    assert SystemSettings.get().offsite_enabled is False
    assert _check() == 3


def test_due_follows_interval():
    _set(True, hours=6)
    assert _check() == 0  # never uploaded
    _run(ago=timedelta(hours=2))
    assert _check() == 4
    OffsiteBackupRun.objects.all().delete()
    _run(ago=timedelta(hours=6))
    assert _check() == 0


def test_failures_do_not_reset_the_schedule():
    _set(True, hours=6)
    _run(ago=timedelta(hours=7))
    _run(status="failure", ago=timedelta(minutes=5))
    assert offsite.is_due()


def test_record_hides_credentials_and_is_audited():
    call_command("offsite", "record", "--status", "success", "--started", timezone.now().isoformat(),
                 "--snapshot", "abc123", "--bytes", "2048",
                 "--target", "rest:https://clinic:S3cret@backup.example.et/clinic-a/?token=x")
    run = OffsiteBackupRun.objects.get()
    assert run.target == "rest:https://backup.example.et/clinic-a/"
    assert AuditEvent.objects.filter(action="backup.offsite_success").exists()


def test_clean_target_variants():
    assert clean_target("s3:https://key:secret@s3.example.et/bucket") == "s3:https://s3.example.et/bucket"
    assert clean_target("/mnt/usb/repo") == "/mnt/usb/repo"


def test_overdue_warns_backup_managers_once(make_user):
    admin = make_user("system_admin")
    _set(True, hours=1)
    _run(ago=timedelta(hours=4))
    assert offsite.status()["overdue"]
    offsite.warn_if_overdue()
    offsite.warn_if_overdue()
    assert Notification.objects.filter(user=admin, kind="offsite_overdue").count() == 1


def test_not_overdue_when_switched_off(make_user):
    _set(False)
    _run(ago=timedelta(days=10))
    assert not offsite.status()["overdue"]


def test_switch_on_and_off_through_api(make_user, login):
    client = login(make_user("system_admin"), client=APIClient())
    r = client.patch("/api/v1/system/offsite/", {"enabled": True, "interval_hours": 6}, format="json")
    assert r.status_code == 200 and r.json()["enabled"] and r.json()["interval_hours"] == 6
    assert client.patch("/api/v1/system/offsite/", {"interval_hours": 5}, format="json").status_code == 400
    client.patch("/api/v1/system/offsite/", {"enabled": False}, format="json")
    assert AuditEvent.objects.filter(action="backup.offsite_on").exists()
    assert AuditEvent.objects.filter(action="backup.offsite_off").exists()


def test_only_backup_managers_can_switch(make_user, login):
    for role in ("clinic_admin", "clinic_director", "doctor"):
        client = login(make_user(role), client=APIClient())
        assert client.patch("/api/v1/system/offsite/", {"enabled": True}, format="json").status_code == 403
        assert client.get("/api/v1/system/offsite/").status_code == 403
