from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import UUIDModel
from apps.core.concurrency import Versioned


class Notification(UUIDModel):
    """In-app notice to one staff member (e.g. lab results ready, approval needed). Contains no clinical detail."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="notifications")
    kind = models.CharField(max_length=30)
    title = models.CharField(max_length=150)
    body = models.CharField(max_length=255, blank=True)
    link = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications_notification"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at", "-created_at"], name="notification_user_idx")]


class Announcement(Versioned, UUIDModel):
    """
    A notice from clinic management shown on staff dashboards (e.g. "Lab closed Saturday afternoon").
    Targets everyone, or only the listed roles / department. Never contains patient information.
    """

    class Level(models.TextChoices):
        INFO = "info", "Information"
        IMPORTANT = "important", "Important"

    title = models.CharField(max_length=150)
    body = models.TextField(max_length=2000, blank=True)
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    roles = models.ManyToManyField("accounts.Role", blank=True, related_name="+")
    department = models.ForeignKey("accounts.Department", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notifications_announcement"
        ordering = ["-starts_on", "-created_at"]
        constraints = [models.CheckConstraint(
            condition=models.Q(ends_on__isnull=True) | models.Q(ends_on__gte=models.F("starts_on")),
            name="announcement_dates_ordered")]


class EmailSettings(Versioned, models.Model):
    """
    One row: how this clinic sends email. Set in System › Email; off until switched on.
    The password is stored encrypted (apps/core/secretbox.py) and is never sent back to the browser.
    """

    class Provider(models.TextChoices):
        CPANEL = "cpanel", "Clinic email from the web host (cPanel)"
        BREVO = "brevo", "Brevo"
        CUSTOM = "custom", "Other email server"

    class Security(models.TextChoices):
        SSL = "ssl", "SSL/TLS (usually port 465)"
        STARTTLS = "starttls", "STARTTLS (usually port 587)"

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)
    provider = models.CharField(max_length=10, choices=Provider.choices, default=Provider.CPANEL)
    host = models.CharField(max_length=255, blank=True)
    port = models.PositiveIntegerField(default=465)
    security = models.CharField(max_length=10, choices=Security.choices, default=Security.SSL)
    username = models.CharField(max_length=255, blank=True)
    password_sealed = models.TextField(blank=True)
    from_email = models.EmailField(blank=True)
    from_name = models.CharField(max_length=100, blank=True)
    reply_to = models.EmailField(blank=True)
    site_url = models.URLField(blank=True, help_text="Address staff use to open the system; used for links in emails.")
    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notifications_email_settings"
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="email_settings_singleton")]

    @classmethod
    def get(cls) -> "EmailSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def configured(self) -> bool:
        return bool(self.host and self.port and self.from_email and self.username and self.password_sealed)


class OutboundEmail(models.Model):
    """
    The outbox. Emails are queued here and sent by `send_email_outbox` (every minute), with retries, so
    an internet outage only delays them. Bodies never contain patient information (see email.py).
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "Waiting"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    to_email = models.EmailField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=40)
    subject = models.CharField(max_length=200)
    body_text = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_error = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications_outbound_email"
        ordering = ["-created_at"]
