"""
Email for Clinic MRS: settings, the outbox, and what gets emailed.

Rules:
- Email is off until a system administrator sets it up (System › Email).
- Emails never contain patient information. Patient-related notifications are emailed as a generic
  "something is waiting for you" with a link; only system and security notices carry their text.
  Email providers may store messages outside Ethiopia, and health data is sensitive personal data
  under Proclamation 1321/2024.
- Messages go through the outbox and are retried, so an internet outage only delays them.
"""

from __future__ import annotations

import logging
import smtplib
import socket
import ssl
from datetime import timedelta

from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import transaction
from django.utils import timezone

from apps.core.secretbox import seal, unseal

from .models import EmailSettings, OutboundEmail

logger = logging.getLogger(__name__)
PURPOSE = "email-password"

PRESETS = {
    "brevo": {"host": "smtp-relay.brevo.com", "port": 587, "security": "starttls"},
    "cpanel": {"host": "", "port": 465, "security": "ssl"},
    "custom": {"host": "", "port": 587, "security": "starttls"},
}

# Notifications whose title and text contain no patient information, so they can be emailed as they are.
SAFE_KINDS = {"accounts_dormant", "audit_chain_broken", "mfa_enabled", "mfa_recovery_used", "offsite_overdue",
              "system_health", "low_stock", "expiry", "expired", "security", "test"}
# Emailed to people who chose "Important only".
IMPORTANT_KINDS = SAFE_KINDS - {"low_stock", "expiry", "expired"} | {
    "critical_result", "critical_vitals", "emergency", "approval"}
# Generic wording for everything else (no names, no results).
GENERIC = {
    "critical_result": "A critical laboratory result needs your attention",
    "critical_vitals": "Critical vital signs were recorded for a patient",
    "emergency": "An emergency patient has arrived",
    "approval": "An approval is waiting for you",
    "lab_result": "Laboratory results are ready",
    "prescription": "A prescription is waiting",
    "dispense": "A pharmacy item needs attention",
    "appointment": "An appointment was booked or changed",
    "appointment_reminder": "You have appointments tomorrow",
    "arrival": "A patient has arrived",
    "walk_in": "A walk-in patient was added",
    "follow_up": "A follow-up needs booking",
}
MAX_ATTEMPTS = 8
BACKOFF_MINUTES = [1, 5, 15, 30, 60, 120, 240, 480]
KEEP_DAYS = 90


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
def connection_for(cfg: EmailSettings, password: str | None = None, timeout: int = 20):
    password = password if password is not None else unseal(cfg.password_sealed, PURPOSE)
    return get_connection(
        "django.core.mail.backends.smtp.EmailBackend", host=cfg.host, port=cfg.port, username=cfg.username,
        password=password or "", use_ssl=cfg.security == "ssl", use_tls=cfg.security == "starttls",
        timeout=timeout, fail_silently=False)


def _message(cfg: EmailSettings, to: str, subject: str, body: str, connection) -> EmailMultiAlternatives:
    sender = f"{cfg.from_name} <{cfg.from_email}>" if cfg.from_name else cfg.from_email
    msg = EmailMultiAlternatives(subject=subject, body=body, from_email=sender, to=[to], connection=connection,
                                 reply_to=[cfg.reply_to] if cfg.reply_to else None,
                                 headers={"Auto-Submitted": "auto-generated"})
    return msg


def explain_error(exc: Exception) -> str:
    """A short, plain explanation of a sending failure. Never includes the password."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "The server refused the username or password."
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "The server refused the From address. Use an address that belongs to this account or is verified."
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "The server refused the recipient address."
    if isinstance(exc, (socket.gaierror,)):
        return "The server name could not be found. Check the server name and the internet connection."
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "The server did not answer in time. Check the port and the internet connection."
    if isinstance(exc, ConnectionRefusedError):
        return "The connection was refused. Check the port and security setting."
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return ("The server closed the connection. Check the username and password, "
                "then the security setting (SSL/TLS on 465, STARTTLS on 587).")
    if isinstance(exc, ssl.SSLError):
        return "The secure connection failed. Try the other security setting (SSL/TLS on 465, STARTTLS on 587)."
    if isinstance(exc, smtplib.SMTPException):
        return f"The email server refused the message ({type(exc).__name__})."
    if isinstance(exc, OSError):
        return "Could not reach the email server. Check the internet connection."
    return f"Sending failed ({type(exc).__name__})."


def send_test(cfg: EmailSettings, to: str, password: str | None = None) -> tuple[bool, str]:
    body = ("This is a test message from Clinic MRS.\n\n"
            "If you can read this, email is set up correctly and staff can receive alerts.\n")
    try:
        conn = connection_for(cfg, password=password)
        _message(cfg, to, "Clinic MRS: test email", _with_footer(cfg, body), conn).send()
        return True, "Test email sent. Check the inbox (and the spam folder)."
    except Exception as exc:  # noqa: BLE001 - reported to the administrator in plain words
        logger.info("Test email failed: %s", type(exc).__name__)
        return False, explain_error(exc)


def _with_footer(cfg: EmailSettings, body: str, *, add_link: bool = True) -> str:
    link = f"\n{cfg.site_url.rstrip('/')}/" if (cfg.site_url and add_link) else ""
    return (f"{body}{link}\n\n--\nSent automatically by Clinic MRS. Do not reply with patient information.\n"
            "To change which emails you get: your name menu › Security and alerts.\n")


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------
def email_ready() -> EmailSettings | None:
    cfg = EmailSettings.get()
    return cfg if cfg.enabled and cfg.configured else None


def queue(user, *, kind: str, subject: str, body: str, link: str = "") -> OutboundEmail | None:
    cfg = email_ready()
    if cfg is None or user is None or not user.email or not user.is_active:
        return None
    url = f"{cfg.site_url.rstrip('/')}{link}" if (cfg.site_url and link) else ""
    text = f"Hello {user.first_name or user.username},\n\n{body}\n" + (f"\nOpen: {url}\n" if url else "")
    email = OutboundEmail(to_email=user.email, user=user, kind=kind[:40], subject=f"Clinic MRS: {subject}"[:200],
                          body_text=_with_footer(cfg, text, add_link=not url))
    # Saved with the surrounding transaction: if the action rolls back, no email is sent.
    email.save()
    return email


def for_notification(user, *, kind: str, title: str, body: str, link: str) -> None:
    """Called for every in-app notification; emails it if the person asked for this kind."""
    choice = getattr(user, "email_alerts", "important")
    if choice == "off" or (choice == "important" and kind not in IMPORTANT_KINDS):
        return
    if kind in SAFE_KINDS:
        queue(user, kind=kind, subject=title, body=body or title, link=link)
    else:
        generic = GENERIC.get(kind, "Something new is waiting for you")
        queue(user, kind=kind, subject=generic,
              body=f"{generic}. Sign in to Clinic MRS to see the details (they are not included in emails).",
              link=link)


def security_notice(user, title: str, body: str) -> None:
    """Notices about a person's own account: always emailed when email is set up."""
    queue(user, kind="security", subject=title,
          body=f"{body}\n\nIf this was not you, tell your system administrator at once.", link="/account/security")


# ---------------------------------------------------------------------------
# Sending the outbox
# ---------------------------------------------------------------------------
def send_outbox(limit: int = 50) -> dict:
    cfg = email_ready()
    if cfg is None:
        return {"sent": 0, "failed": 0, "skipped": "email is off or not set up"}
    now = timezone.now()
    due = list(OutboundEmail.objects.filter(status=OutboundEmail.Status.QUEUED, next_attempt_at__lte=now)
               .order_by("created_at")[:limit])
    sent = failed = 0
    if due:
        try:
            conn = connection_for(cfg)
            conn.open()
        except Exception as exc:  # noqa: BLE001 - whole batch postponed
            reason = explain_error(exc)
            for e in due:
                _postpone(e, reason, now)
            return {"sent": 0, "failed": len(due), "error": reason}
        try:
            for e in due:
                try:
                    _message(cfg, e.to_email, e.subject, e.body_text, conn).send()
                    OutboundEmail.objects.filter(pk=e.pk).update(status=OutboundEmail.Status.SENT, sent_at=timezone.now(),
                                                                 attempts=e.attempts + 1, last_error="")
                    sent += 1
                except Exception as exc:  # noqa: BLE001
                    _postpone(e, explain_error(exc), now)
                    failed += 1
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    OutboundEmail.objects.filter(created_at__lt=now - timedelta(days=KEEP_DAYS)).exclude(
        status=OutboundEmail.Status.QUEUED).delete()
    return {"sent": sent, "failed": failed}


def _postpone(e: OutboundEmail, reason: str, now) -> None:
    attempts = e.attempts + 1
    if attempts >= MAX_ATTEMPTS:
        OutboundEmail.objects.filter(pk=e.pk).update(status=OutboundEmail.Status.FAILED, attempts=attempts,
                                                     last_error=reason[:255])
        return
    delay = BACKOFF_MINUTES[min(attempts - 1, len(BACKOFF_MINUTES) - 1)]
    OutboundEmail.objects.filter(pk=e.pk).update(attempts=attempts, last_error=reason[:255],
                                                 next_attempt_at=now + timedelta(minutes=delay))


def save_settings(data: dict) -> tuple[EmailSettings, dict]:
    """Apply changes; returns the settings and a description of what changed (no password)."""
    with transaction.atomic():
        EmailSettings.get()
        cfg = EmailSettings.objects.select_for_update().get(pk=1)
        changes = {}
        password = data.pop("password", None)
        for key, value in data.items():
            if isinstance(value, str):
                value = value.strip()
            if getattr(cfg, key) != value:
                changes[key] = {"from": getattr(cfg, key), "to": value}
                setattr(cfg, key, value)
        if password:
            cfg.password_sealed = seal(password, PURPOSE)
            changes["password"] = "changed"
        if changes:
            cfg.save()
    return cfg, changes
