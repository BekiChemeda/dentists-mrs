"""
Check the audit log's hash chain. Exit code 0 = intact, 1 = broken.

Run daily (deploy/systemd/mrs-reminders.service does). The last line printed (sequence number and hash)
is an anchor: it lands in the server's system log, outside the database, so even someone able to
rewrite the whole table and recompute every hash would not match yesterday's anchor.
"""

from django.core.management.base import BaseCommand

from apps.audit.models import AuditEvent, chain_digest


class Command(BaseCommand):
    help = "Verify the tamper-evident hash chain of the audit log."

    def add_arguments(self, parser):
        parser.add_argument("--expect", help="Anchor from an earlier run, as SEQ:HASH; must still be present.")
        parser.add_argument("--quiet", action="store_true", help="Do not notify anyone on failure.")

    def handle(self, *args, expect=None, quiet=False, **opts):
        prev_hash, expected_seq, checked = "", None, 0
        problem = None
        qs = AuditEvent.objects.filter(chain_seq__isnull=False).order_by("chain_seq")
        for event in qs.iterator(chunk_size=2000):
            if expected_seq is not None and event.chain_seq != expected_seq:
                problem = f"events missing before sequence {event.chain_seq} (expected {expected_seq})"
                break
            if chain_digest(prev_hash, event) != event.chain_hash:
                problem = f"event {event.chain_seq} ({event.action}, {event.occurred_at:%Y-%m-%d %H:%M}) was changed"
                break
            prev_hash, expected_seq, checked = event.chain_hash, event.chain_seq + 1, checked + 1
        if problem is None and expect:
            seq, _, digest = expect.partition(":")
            row = AuditEvent.objects.filter(chain_seq=int(seq)).values_list("chain_hash", flat=True).first()
            if row != digest:
                problem = f"anchor {seq} no longer matches: the log was rewritten after it was taken"
        if problem:
            self.stderr.write(f"AUDIT CHAIN BROKEN: {problem}")
            if not quiet:
                from apps.notifications.services import notify_permission_holders

                for perm in ("audit.view", "users.manage"):
                    notify_permission_holders(perm, kind="audit_chain_broken", title="Audit log tampering detected",
                                              body=problem[:255], link="/admin/audit", once=True)
            raise SystemExit(1)
        self.stdout.write(f"audit chain intact: {checked} events; anchor {expected_seq - 1 if expected_seq else 0}:{prev_hash}")
