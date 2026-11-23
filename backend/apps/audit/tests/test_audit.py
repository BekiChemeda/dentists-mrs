import pytest
from django.db import DatabaseError, connection, transaction

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.core.context import ActorContext

pytestmark = pytest.mark.django_db


def _event():
    return record_event(ActorContext.system("test"), action="test.event", object_type="thing", object_id="1")


def test_audit_events_cannot_be_updated():
    event = _event()
    with pytest.raises(DatabaseError, match="append-only"):
        with transaction.atomic():
            AuditEvent.objects.filter(pk=event.pk).update(action="tampered")
    event.refresh_from_db()
    assert event.action == "test.event"


def test_audit_events_cannot_be_deleted():
    event = _event()
    with pytest.raises(DatabaseError, match="append-only"):
        with transaction.atomic():
            AuditEvent.objects.filter(pk=event.pk).delete()
    assert AuditEvent.objects.filter(pk=event.pk).exists()


def test_audit_table_cannot_be_truncated():
    with pytest.raises(DatabaseError, match="append-only"):
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("TRUNCATE audit_event")


def test_record_event_refuses_secret_fields():
    with pytest.raises(ValueError):
        record_event(ActorContext.system(), action="x", details={"password": "abc"})


def test_audit_rolls_back_with_failed_change(make_user):
    """An audit event written in a transaction that fails must not survive, and vice versa."""
    user = make_user()
    before = AuditEvent.objects.count()
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            user.job_title = "Changed"
            user.save()
            record_event(ActorContext.system(), action="user.update", object_type="user", object_id=user.pk)
            raise RuntimeError("simulated failure")
    user.refresh_from_db()
    assert user.job_title == ""
    assert AuditEvent.objects.count() == before


class TestAuditApi:
    def test_list_and_filter(self, api, make_user, login):
        admin = make_user("system_admin")
        login(admin)
        record_event(ActorContext.system(), action="user.create", object_type="user", object_id="42")
        record_event(ActorContext.system(), action="role.update", object_type="role", object_id="7")
        body = api.get("/api/v1/audit-events/?action=user.").json()
        assert body["count"] == 1
        assert body["results"][0]["object_id"] == "42"
        assert api.get(f"/api/v1/audit-events/?actor={admin.pk}").json()["results"][0]["action"] == "auth.login"

    def test_invalid_filter_rejected(self, api, make_user, login):
        login(make_user("clinic_admin"))
        response = api.get("/api/v1/audit-events/?date_from=2026-05-01&date_to=2026-04-01")
        assert response.status_code == 400

    def test_no_write_methods(self, api, make_user, login):
        login(make_user("system_admin"))
        assert api.post("/api/v1/audit-events/", {}, format="json").status_code in (403, 405)  # fails closed
        assert api.delete("/api/v1/audit-events/").status_code in (403, 405)  # fails closed
