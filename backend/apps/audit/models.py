import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditEvent(models.Model):
    """
    Append-only record of an important action.

    A PostgreSQL trigger (migration 0002) rejects UPDATE and DELETE on this table, so even
    application code with a bug, or someone with the application's database credentials,
    cannot silently rewrite history. Only a database superuser can disable the trigger,
    and doing so is itself visible in PostgreSQL logs.
    """

    class Outcome(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILURE = "failure", "Failure"
        DENIED = "denied", "Denied"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    occurred_at = models.DateTimeField(default=timezone.now, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    # Snapshot of the username at the time, so the record stays readable if the account changes.
    actor_username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    outcome = models.CharField(max_length=10, choices=Outcome.choices, default=Outcome.SUCCESS)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    details = models.JSONField(default=dict, blank=True)
    # Tamper evidence: each event carries a SHA-256 over its own content and the previous event's
    # hash, in an unbroken sequence. Editing, inserting or removing a row breaks the chain, which
    # `manage.py verify_audit_chain` detects. (Events written before this was added have no hash.)
    chain_seq = models.BigIntegerField(null=True, blank=True, unique=True, editable=False)
    chain_hash = models.CharField(max_length=64, blank=True, editable=False)

    class Meta:
        db_table = "audit_event"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["-occurred_at"], name="audit_occurred_idx"),
            models.Index(fields=["actor", "-occurred_at"], name="audit_actor_idx"),
            models.Index(fields=["object_type", "object_id"], name="audit_object_idx"),
            models.Index(fields=["action", "-occurred_at"], name="audit_action_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(outcome__in=["success", "failure", "denied"]),
                name="audit_outcome_valid",
            )
        ]

    def __str__(self) -> str:
        return f"{self.occurred_at:%Y-%m-%d %H:%M:%S} {self.actor_username or 'system'} {self.action}"


def chain_digest(prev_hash: str, event: "AuditEvent") -> str:
    import hashlib
    import json

    body = json.dumps({
        "seq": event.chain_seq, "id": str(event.id), "at": event.occurred_at.isoformat(),
        "actor": str(event.actor_id or ""), "user": event.actor_username, "action": event.action,
        "type": event.object_type, "obj": event.object_id, "outcome": event.outcome,
        "ip": event.ip_address or "", "agent": event.user_agent, "req": event.request_id, "details": event.details,
    }, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256(f"{prev_hash}|{body}".encode()).hexdigest()
