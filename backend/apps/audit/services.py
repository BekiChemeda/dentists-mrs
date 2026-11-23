"""
The only way to write audit events.

Call `record_event` inside the same `transaction.atomic()` block as the change it
describes: if the audit insert fails, the change is rolled back too.
"""

from typing import Any

from apps.core.context import ActorContext

from django.db import connection, transaction

from .models import AuditEvent, chain_digest

# Any constant; serialises audit inserts so the hash chain has no forks.
_CHAIN_LOCK_KEY = 784_221_901

# Keys that must never be written into audit details.
_FORBIDDEN_DETAIL_KEYS = {"password", "new_password", "old_password", "temporary_password", "token", "secret"}


def record_event(
    ctx: ActorContext,
    *,
    action: str,
    object_type: str = "",
    object_id: Any = "",
    outcome: str = AuditEvent.Outcome.SUCCESS,
    details: dict | None = None,
    actor=None,
) -> AuditEvent:
    """`actor` overrides ctx.user, e.g. for a login where the request is still anonymous."""
    details = dict(details or {})
    leaked = _FORBIDDEN_DETAIL_KEYS.intersection(details)
    if leaked:
        raise ValueError(f"Refusing to write secret fields to the audit log: {sorted(leaked)}")

    who = actor if actor is not None else ctx.user
    event = AuditEvent(
        actor=who,
        actor_username=getattr(who, "username", "") or "",
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id else "",
        outcome=outcome,
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
        request_id=ctx.request_id,
        details=details,
    )
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_CHAIN_LOCK_KEY])
        last = (AuditEvent.objects.filter(chain_seq__isnull=False).order_by("-chain_seq")
                .values("chain_seq", "chain_hash").first())
        event.chain_seq = (last["chain_seq"] + 1) if last else 1
        # Round-trip the details through JSON so the stored value hashes the same when re-read.
        import json

        event.details = json.loads(json.dumps(details, default=str))
        event.chain_hash = chain_digest(last["chain_hash"] if last else "", event)
        event.save(force_insert=True)
    return event
