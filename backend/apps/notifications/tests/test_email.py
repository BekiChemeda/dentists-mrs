"""Email set-up (cPanel / Brevo), outbox, and what may be emailed. Synthetic data; no real mail is sent."""

import smtplib
from datetime import timedelta

import pytest
from django.core import mail
from django.core.mail import get_connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.core.secretbox import unseal
from apps.notifications import email as email_mod
from apps.notifications.models import EmailSettings, OutboundEmail
from apps.notifications.services import notify_permission_holders, notify_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def fake_smtp(monkeypatch):
    """Messages go to django.core.mail.outbox instead of a real server."""
    monkeypatch.setattr(email_mod, "connection_for",
                        lambda cfg, password=None, timeout=20: get_connection("django.core.mail.backends.locmem.EmailBackend"))
    return mail.outbox


def _configure(**extra):
    EmailSettings.get()
    values = dict(enabled=True, provider="cpanel", host="mail.example-clinic.et", port=465, security="ssl",
                  username="mrs@example-clinic.et", from_email="mrs@example-clinic.et", from_name="Example Clinic",
                  site_url="https://mrs.example-clinic.et")
    values.update(extra)
    EmailSettings.objects.filter(pk=1).update(**values)
    cfg, _ = email_mod.save_settings({"password": "synthetic-smtp-pass"})
    return cfg


def test_off_by_default_nothing_queued(make_user):
    user = make_user("nurse", email="nurse@example.et")
    notify_user(user, kind="critical_result", title="x")
    assert OutboundEmail.objects.count() == 0


def test_password_stored_encrypted_and_never_returned(make_user, login):
    client = login(make_user("system_admin"), client=APIClient())
    r = client.patch("/api/v1/system/email/", {"provider": "brevo", "host": "smtp-relay.brevo.com", "port": 587,
                                              "security": "starttls", "username": "9a1b2c@smtp-brevo.com",
                                              "password": "xsmtpsib-synthetic-key", "from_email": "noreply@example.et"},
                     format="json")
    assert r.status_code == 200, r.content
    assert "xsmtpsib" not in r.content.decode() and r.json()["password_set"] is True
    stored = EmailSettings.get().password_sealed
    assert "xsmtpsib" not in stored and unseal(stored, email_mod.PURPOSE) == "xsmtpsib-synthetic-key"
    event = AuditEvent.objects.filter(action="email.settings_update").latest("occurred_at")
    assert "xsmtpsib" not in str(event.details)


def test_cannot_switch_on_before_set_up(make_user, login):
    client = login(make_user("system_admin"), client=APIClient())
    r = client.patch("/api/v1/system/email/", {"enabled": True}, format="json")
    assert r.status_code == 400 and EmailSettings.get().enabled is False


def test_host_must_be_a_plain_server_name(make_user, login):
    client = login(make_user("system_admin"), client=APIClient())
    r = client.patch("/api/v1/system/email/", {"host": "https://mail.example.et:465"}, format="json")
    assert r.status_code == 400


def test_only_system_admins_configure_email(make_user, login):
    for role in ("clinic_admin", "clinic_director", "doctor"):
        c = login(make_user(role), client=APIClient())
        assert c.patch("/api/v1/system/email/", {"host": "x.et"}, format="json").status_code == 403
        assert c.post("/api/v1/system/email/test/", {"to": "a@b.et"}, format="json").status_code == 403


def test_send_test_with_unsaved_form_values(make_user, login, fake_smtp):
    client = login(make_user("system_admin"), client=APIClient())
    r = client.post("/api/v1/system/email/test/", {
        "to": "admin@example.et", "host": "mail.example-clinic.et", "port": 465, "security": "ssl",
        "username": "mrs@example-clinic.et", "password": "synthetic", "from_email": "mrs@example-clinic.et",
        "from_name": "Example Clinic"}, format="json")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert fake_smtp[0].to == ["admin@example.et"] and "Example Clinic" in fake_smtp[0].from_email
    assert AuditEvent.objects.filter(action="email.test", outcome="success").exists()


def test_test_failure_is_explained_plainly(make_user, login, monkeypatch):
    def refuse(cfg, password=None, timeout=20):
        class Conn:
            def send_messages(self, msgs):
                raise smtplib.SMTPAuthenticationError(535, b"5.7.8 auth failed")

            def open(self):
                return None

            def close(self):
                return None
        return Conn()
    monkeypatch.setattr(email_mod, "connection_for", refuse)
    _configure()
    client = login(make_user("system_admin"), client=APIClient())
    r = client.post("/api/v1/system/email/test/", {"to": "admin@example.et"}, format="json")
    assert r.json() == {"ok": False, "message": "The server refused the username or password."}


def test_patient_related_notice_is_generic(make_user, fake_smtp):
    _configure()
    doctor = make_user("doctor", email="doctor@example.et")
    notify_user(doctor, kind="critical_result", title="Critical potassium for Abebe Kebede (MRN 00012)",
                body="K 7.1 mmol/L", link="/lab/orders/1")
    out = OutboundEmail.objects.get()
    assert "Abebe" not in out.subject + out.body_text and "7.1" not in out.body_text
    assert "https://mrs.example-clinic.et/lab/orders/1" in out.body_text
    email_mod.send_outbox()
    assert fake_smtp[0].subject == "Clinic MRS: A critical laboratory result needs your attention"


def test_preferences(make_user):
    _configure()
    off = make_user("nurse", email="off@example.et")
    off.email_alerts = "off"
    off.save()
    imp = make_user("nurse", email="imp@example.et")
    every = make_user("nurse", email="all@example.et")
    every.email_alerts = "all"
    every.save()
    for u in (off, imp, every):
        notify_user(u, kind="lab_result", title="Results ready")
        notify_user(u, kind="emergency", title="Emergency")
    sent = sorted(OutboundEmail.objects.values_list("to_email", "kind"))
    assert sent == [("all@example.et", "emergency"), ("all@example.et", "lab_result"), ("imp@example.et", "emergency")]


def test_system_alerts_reach_admins_with_their_text(make_user, fake_smtp):
    _configure()
    admin = make_user("system_admin", email="it@example.et")
    notify_permission_holders("system.health.view", kind="offsite_overdue", title="Off-site backup is overdue",
                              body="Last successful upload 20 Nov 2026 08:00.")
    email_mod.send_outbox()
    assert fake_smtp[0].to == ["it@example.et"] and "20 Nov 2026" in fake_smtp[0].body
    assert admin


def test_security_notice_on_password_change(make_user, login):
    _configure()
    user = make_user("nurse", email="me@example.et")
    client = login(user, client=APIClient())
    from conftest import PASSWORD

    client.post("/api/v1/auth/password/change/", {"current_password": PASSWORD,
                                                  "new_password": "Another-Synthetic-Pass-2026"}, format="json")
    out = OutboundEmail.objects.get(kind="security")
    assert out.subject == "Clinic MRS: Your password was changed" and "Another" not in out.body_text


def test_no_email_without_address(make_user):
    _configure()
    notify_user(make_user("nurse", email=""), kind="emergency", title="x")
    assert not OutboundEmail.objects.exists()


def test_outage_retries_then_gives_up(make_user, monkeypatch):
    _configure()
    notify_user(make_user("nurse", email="n@example.et"), kind="emergency", title="x")

    def down(cfg, password=None, timeout=20):
        raise OSError("network unreachable")
    monkeypatch.setattr(email_mod, "connection_for", down)
    result = email_mod.send_outbox()
    e = OutboundEmail.objects.get()
    assert result["failed"] == 1 and e.status == "queued" and e.attempts == 1 and e.next_attempt_at > timezone.now()
    assert "internet" in e.last_error
    OutboundEmail.objects.update(attempts=email_mod.MAX_ATTEMPTS - 1, next_attempt_at=timezone.now() - timedelta(seconds=1))
    email_mod.send_outbox()
    assert OutboundEmail.objects.get().status == "failed"


def test_queued_mail_sent_when_connection_returns(make_user, fake_smtp):
    _configure()
    notify_user(make_user("nurse", email="n@example.et"), kind="emergency", title="x")
    OutboundEmail.objects.update(attempts=2, next_attempt_at=timezone.now() - timedelta(seconds=1))
    assert email_mod.send_outbox()["sent"] == 1 and len(fake_smtp) == 1
    assert OutboundEmail.objects.get().status == "sent"


def test_email_follows_rolled_back_action(make_user):
    from django.db import transaction

    _configure()
    user = make_user("nurse", email="n@example.et")
    with pytest.raises(RuntimeError), transaction.atomic():
        notify_user(user, kind="emergency", title="x")
        raise RuntimeError("action failed")
    assert not OutboundEmail.objects.exists()


def test_personal_email_alert_setting(make_user, login):
    client = login(make_user("nurse"), client=APIClient())
    assert client.patch("/api/v1/auth/me/email-alerts/", {"email_alerts": "all"}, format="json").json() == {"email_alerts": "all"}
    assert client.get("/api/v1/auth/me/").json()["email_alerts"] == "all"
    assert client.patch("/api/v1/auth/me/email-alerts/", {"email_alerts": "loud"}, format="json").status_code == 400
