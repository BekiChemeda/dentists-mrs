"""
Off-site backup: schedule decisions and run records.

The upload itself is done on the host by deploy/scripts/offsite-backup.sh (pg_dump + restic, which
encrypts on this server before anything leaves). The script asks `manage.py offsite check` whether a
run is due, and reports each attempt with `manage.py offsite record`. Turning the feature off in the
System page stops all uploads at the next check; nothing already sent is deleted.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import OffsiteBackupRun, SystemSettings

INTERVAL_CHOICES = (1, 2, 3, 6, 12, 24)
# How often the host timer asks; a run counts as due slightly early so a 1-hour schedule
# is not pushed to 1 h 15 min by timer drift.
CHECK_SLACK = timedelta(minutes=10)


def last_success():
    return OffsiteBackupRun.objects.filter(status=OffsiteBackupRun.Status.SUCCESS).order_by("-finished_at").first()


def status(now=None) -> dict:
    now = now or timezone.now()
    cfg = SystemSettings.get()
    ok = last_success()
    last = OffsiteBackupRun.objects.order_by("-finished_at").first()
    interval = timedelta(hours=cfg.offsite_interval_hours)
    next_due = (ok.finished_at + interval) if ok else now
    # Overdue: two intervals plus an hour without a successful upload (allows one missed run,
    # e.g. a short internet outage, before anyone is warned).
    overdue = bool(cfg.offsite_enabled and (ok is None or now - ok.finished_at > 2 * interval + timedelta(hours=1)))
    return {
        "enabled": cfg.offsite_enabled,
        "interval_hours": cfg.offsite_interval_hours,
        "last_success_at": ok.finished_at if ok else None,
        "last_attempt_at": last.finished_at if last else None,
        "last_status": last.status if last else None,
        "last_message": last.message if last else "",
        "target": (ok or last).target if (ok or last) else "",
        "next_due_at": next_due if cfg.offsite_enabled else None,
        "overdue": overdue,
    }


def is_due(now=None) -> bool:
    now = now or timezone.now()
    cfg = SystemSettings.get()
    if not cfg.offsite_enabled:
        return False
    ok = last_success()
    return ok is None or now - ok.finished_at >= timedelta(hours=cfg.offsite_interval_hours) - CHECK_SLACK


def warn_if_overdue() -> None:
    """Tell backup managers once (until they read it) that off-site copies have stopped arriving."""
    from apps.notifications.services import notify_permission_holders

    st = status()
    if st["overdue"]:
        when = st["last_success_at"]
        body = (f"Last successful upload {timezone.localtime(when):%d %b %Y %H:%M}." if when
                else "No off-site upload has succeeded yet.")
        notify_permission_holders("backups.manage", kind="offsite_overdue", title="Off-site backup is overdue",
                                  body=f"{body} Check the internet connection and the System page.",
                                  link="/admin/system?tab=offsite", once=True)
