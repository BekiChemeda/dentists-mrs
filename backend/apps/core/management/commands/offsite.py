"""
Used by deploy/scripts/offsite-backup.sh; not meant to be run by hand (except `status`).

    manage.py offsite check      exit 0 when an upload is due, 3 when switched off, 4 when not yet due
    manage.py offsite record --status success|failure --started ISO [--snapshot ID] [--bytes N]
                             [--dump FILE] [--target URL] [--message TEXT]
    manage.py offsite status     print the current state (for technicians)
"""

import datetime
import json
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.models import OffsiteBackupRun
from apps.core.offsite import is_due, status, warn_if_overdue

EXIT_OFF = 3
EXIT_NOT_DUE = 4
KEEP_RUNS = 500
# user:password@ or ?key=secret parts must never reach the database or the screen.
_CREDENTIALS = re.compile(r"//[^/@\s]*@")


def clean_target(raw: str) -> str:
    target = _CREDENTIALS.sub("//", raw or "").split("?", 1)[0]
    return target[:255]


class Command(BaseCommand):
    help = "Off-site backup schedule and run log (called by deploy/scripts/offsite-backup.sh)."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)
        sub.add_parser("check")
        sub.add_parser("status")
        rec = sub.add_parser("record")
        rec.add_argument("--status", choices=["success", "failure"], required=True)
        rec.add_argument("--started", required=True, help="ISO 8601 start time")
        rec.add_argument("--snapshot", default="")
        rec.add_argument("--bytes", type=int, default=None)
        rec.add_argument("--dump", default="")
        rec.add_argument("--target", default="")
        rec.add_argument("--message", default="")

    def handle(self, *args, action, **opts):
        if action == "status":
            self.stdout.write(json.dumps(status(), default=str, indent=2))
            return
        if action == "check":
            warn_if_overdue()
            if not status()["enabled"]:
                self.stdout.write("off")
                raise SystemExit(EXIT_OFF)
            if not is_due():
                self.stdout.write("not-due")
                raise SystemExit(EXIT_NOT_DUE)
            self.stdout.write("due")
            return
        self._record(opts)

    def _record(self, opts):
        try:
            started = datetime.datetime.fromisoformat(opts["started"])
        except ValueError as exc:
            raise CommandError("--started must be an ISO 8601 time") from exc
        if timezone.is_naive(started):
            started = timezone.make_aware(started)
        with transaction.atomic():
            run = OffsiteBackupRun.objects.create(
                started_at=started, status=opts["status"], snapshot_id=opts["snapshot"][:64],
                bytes_added=opts["bytes"], dump_file=opts["dump"].rsplit("/", 1)[-1][:120],
                target=clean_target(opts["target"]), message=(opts["message"] or "").splitlines()[0][:255]
                if opts["message"] else "")
            record_event(ActorContext.system(), action=f"backup.offsite_{run.status}", object_type="offsite_backup",
                         object_id=run.pk, outcome="success" if run.status == "success" else "failure",
                         details={"snapshot": run.snapshot_id, "bytes_added": run.bytes_added,
                                  **({"message": run.message} if run.message else {})})
            stale = OffsiteBackupRun.objects.order_by("-finished_at").values_list("pk", flat=True)[KEEP_RUNS:]
            OffsiteBackupRun.objects.filter(pk__in=list(stale)).delete()
        if run.status == "failure":
            warn_if_overdue()
        self.stdout.write(f"recorded {run.status}")
