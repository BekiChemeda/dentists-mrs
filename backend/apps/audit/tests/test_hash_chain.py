"""Tamper evidence for the audit log. Synthetic events only."""

import pytest
from django.core.management import call_command
from django.db import connection

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.core.context import ActorContext

pytestmark = pytest.mark.django_db


def _events(n=5):
    for i in range(n):
        record_event(ActorContext.system(), action="test.event", object_type="x", object_id=str(i),
                     details={"n": i, "note": "synthetic", "amount": "10.50"})


def _verify(*extra):
    try:
        call_command("verify_audit_chain", "--quiet", *extra)
    except SystemExit as exc:
        return exc.code
    return 0


def _raw(sql, params=()):
    with connection.cursor() as c:
        c.execute("SET CONSTRAINTS ALL IMMEDIATE")
        c.execute("ALTER TABLE audit_event DISABLE TRIGGER USER")
        try:
            c.execute(sql, params)
        finally:
            c.execute("ALTER TABLE audit_event ENABLE TRIGGER USER")


def test_chain_is_contiguous_and_verifies():
    _events()
    seqs = list(AuditEvent.objects.order_by("chain_seq").values_list("chain_seq", flat=True))
    assert seqs == list(range(seqs[0], seqs[0] + 5))
    assert _verify() == 0


def test_edit_is_detected():
    _events()
    target = AuditEvent.objects.filter(action="test.event").order_by("chain_seq")[2]
    _raw("UPDATE audit_event SET action = 'test.innocent' WHERE id = %s", [target.pk])
    assert _verify() == 1


def test_deleted_row_is_detected():
    _events()
    target = AuditEvent.objects.filter(action="test.event").order_by("chain_seq")[1]
    _raw("DELETE FROM audit_event WHERE id = %s", [target.pk])
    assert _verify() == 1


def test_rewritten_tail_is_caught_by_anchor():
    _events()
    last = AuditEvent.objects.order_by("-chain_seq").first()
    anchor = f"{last.chain_seq}:{last.chain_hash}"
    _raw("DELETE FROM audit_event WHERE id = %s", [last.pk])
    assert _verify() == 0  # a removed last row leaves a valid shorter chain...
    assert _verify("--expect", anchor) == 1  # ...but not one matching yesterday's anchor


def test_trigger_still_blocks_ordinary_updates():
    _events(1)
    from django.db import DatabaseError

    from django.db import transaction

    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as c:
        c.execute("UPDATE audit_event SET action = 'x'")
