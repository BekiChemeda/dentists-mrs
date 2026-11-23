"""Unused accounts are switched off automatically. Synthetic accounts."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import SystemSettings
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


def test_dormant_accounts_switched_off_and_admins_told(make_user, sysadmin):
    SystemSettings.get()
    old = make_user("nurse", username="left.long.ago")
    User.objects.filter(pk=old.pk).update(last_login=timezone.now() - timedelta(days=120))
    never = make_user("cashier", username="never.used")
    User.objects.filter(pk=never.pk).update(created_at=timezone.now() - timedelta(days=100))
    recent = make_user("doctor", username="active.doc")
    User.objects.filter(pk=recent.pk).update(last_login=timezone.now() - timedelta(days=3))
    User.objects.filter(pk=sysadmin.pk).update(last_login=timezone.now())
    call_command("review_accounts")
    assert not User.objects.get(pk=old.pk).is_active
    assert not User.objects.get(pk=never.pk).is_active
    assert User.objects.get(pk=recent.pk).is_active
    assert Notification.objects.filter(user=sysadmin, kind="accounts_dormant").exists()


def test_last_admin_is_never_switched_off(make_user):
    SystemSettings.get()
    admin = make_user("system_admin", username="only.admin")
    User.objects.filter(pk=admin.pk).update(last_login=timezone.now() - timedelta(days=400))
    call_command("review_accounts")
    assert User.objects.get(pk=admin.pk).is_active


def test_zero_days_turns_review_off(make_user):
    SystemSettings.get()
    SystemSettings.objects.filter(pk=1).update(dormant_account_days=0)
    u = make_user("nurse")
    User.objects.filter(pk=u.pk).update(last_login=timezone.now() - timedelta(days=999))
    call_command("review_accounts")
    assert User.objects.get(pk=u.pk).is_active
