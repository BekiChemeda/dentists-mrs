"""Abstract base models shared by every module."""

import uuid

from django.db import models
from .concurrency import Versioned


class UUIDModel(models.Model):
    """UUID primary key: safe to expose in URLs and to merge across future branches."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimestampedModel(UUIDModel):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Counter(models.Model):
    """
    Human-readable running numbers (MRN, queue number, invoice and receipt numbers).
    Incremented with a single atomic UPSERT, so concurrent requests never get the same value.
    """

    name = models.CharField(max_length=50)
    period = models.CharField(max_length=20, blank=True)
    value = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "core_counter"
        constraints = [models.UniqueConstraint(fields=["name", "period"], name="core_counter_unique")]


class ClinicSettings(Versioned, models.Model):
    """
    One row: the facility's identity (printed on receipts, referrals and certificates) and the
    billing policy. Editable by holders of settings.manage; every change is audited.
    """

    class FacilityLevel(models.TextChoices):
        # EFDA Directive 1121/2025 Art. 27: medium clinics may handle psychotropic, not narcotic, prescriptions.
        MEDIUM_CLINIC = "medium_clinic", "Medium clinic"
        SPECIALTY_CLINIC = "specialty_clinic", "Specialty clinic"
        SPECIALTY_CENTER = "specialty_center", "Specialty center"
        HOSPITAL = "hospital", "Hospital"
        OTHER = "other", "Other"

    class LabBillingPoint(models.TextChoices):
        ORDERED = "ordered", "When the test is requested"
        COLLECTED = "collected", "When the specimen is collected"
        VERIFIED = "verified", "When the result is verified"

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    facility_name = models.CharField(max_length=150, default="Clinic")
    facility_level = models.CharField(max_length=20, choices=FacilityLevel.choices, default=FacilityLevel.MEDIUM_CLINIC)
    license_number = models.CharField(max_length=50, blank=True)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    tin = models.CharField("TIN", max_length=20, blank=True)
    lab_billing_point = models.CharField(max_length=10, choices=LabBillingPoint.choices,
                                         default=LabBillingPoint.COLLECTED)
    show_ethiopian_calendar = models.BooleanField(default=True)
    # Document templates: a short text the clinic chooses, printed at the foot of each kind of document
    # (e.g. opening hours, "Bring this card to every visit", pharmacy advice). Plain text, no layout code.
    note_patient_card = models.CharField(max_length=300, blank=True)
    note_prescription = models.CharField(max_length=300, blank=True)
    note_consultation = models.CharField(max_length=300, blank=True)
    note_referral = models.CharField(max_length=300, blank=True)
    note_lab_report = models.CharField(max_length=300, blank=True)
    note_certificate = models.CharField(max_length=300, blank=True)
    # Opening hours by weekday ("mon".."sun"): {"open": "08:00", "close": "17:00"}, or null when closed.
    # Appointments can be booked only inside them. Empty = no limit (the default until the clinic sets them).
    opening_hours = models.JSONField(default=dict, blank=True)
    # Waiting list: highlight patients waiting longer than this; whether reception may send a patient
    # straight to the doctor without triage.
    wait_alert_minutes = models.PositiveSmallIntegerField(default=60)
    allow_skip_triage = models.BooleanField(default=True)
    # Close a visit automatically this many minutes after the consultation was signed, once nothing is
    # outstanding (no unverified tests, undispensed medicines or unpaid charges). 0 = staff close visits.
    auto_complete_minutes = models.PositiveSmallIntegerField(default=0)
    # Dental visits are billed by procedure (examinations are procedures in the dental catalogue). When on, the
    # clinic's consultation fee is also charged for a visit with a dental examination.
    bill_consultation_for_dental = models.BooleanField(default=False)
    # The first-run checklist on the clinic administrator's dashboard, until they close it.
    setup_checklist_hidden = models.BooleanField(default=False)
    # Clinic logo, shown on screens and printed documents. Kept in the database (not on disk) so the
    # normal database backup carries it. Always stored as a PNG the server re-encoded itself
    # (apps/core/branding.py), never the uploaded bytes.
    logo_png = models.BinaryField(null=True, blank=True, editable=False)
    logo_updated_at = models.DateTimeField(null=True, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_clinic_settings"
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="clinic_settings_singleton")]

    @classmethod
    def get(cls) -> "ClinicSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SystemSettings(Versioned, models.Model):
    """
    One row: security policy and maintenance mode, changed by holders of system.security.manage.
    Environment variables give the floor (e.g. PASSWORD_MIN_LENGTH); these values can only be stricter
    for passwords, and stay within safe limits for the rest. Every change is audited.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    password_min_length = models.PositiveSmallIntegerField(default=10)
    login_max_failures = models.PositiveSmallIntegerField(default=5)
    login_lockout_minutes = models.PositiveSmallIntegerField(default=15)
    session_idle_minutes = models.PositiveSmallIntegerField(default=30)
    # Modules this clinic does not use (apps/core/modules.py). Empty = everything on.
    disabled_modules = models.JSONField(default=list, blank=True)
    class MfaPolicy(models.TextChoices):
        OFF = "off", "Nobody (optional for everyone)"
        ADMINS = "admins", "Administrators and the clinic director"
        ALL = "all", "Everyone"

    # Accounts nobody has signed in to for this many days are switched off automatically (0 = never).
    dormant_account_days = models.PositiveSmallIntegerField(default=90)
    mfa_required_for = models.CharField(max_length=10, choices=MfaPolicy.choices, default=MfaPolicy.ADMINS)
    maintenance_mode = models.BooleanField(default=False)
    maintenance_message = models.CharField(max_length=255, blank=True)
    # Off-site backup. The schedule is switched here; where the copies go and the encryption
    # key live only in the server's .env, never in the database (deploy/scripts/offsite-backup.sh).
    offsite_enabled = models.BooleanField(default=False)
    offsite_interval_hours = models.PositiveSmallIntegerField(default=24)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_system_settings"
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="system_settings_singleton")]

    @classmethod
    def get(cls) -> "SystemSettings":
        from django.conf import settings

        obj, _ = cls.objects.get_or_create(pk=1, defaults={
            "password_min_length": settings.PASSWORD_MIN_LENGTH,
            "login_max_failures": settings.LOGIN_MAX_FAILURES,
            "login_lockout_minutes": settings.LOGIN_LOCKOUT_MINUTES,
            "session_idle_minutes": settings.SESSION_IDLE_TIMEOUT_MINUTES,
            "mfa_required_for": settings.MFA_DEFAULT_POLICY,
        })
        return obj


class ErrorEvent(models.Model):
    """An unexpected server error. Holds the request ID and exception type, never request bodies or patient data."""

    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    request_id = models.CharField(max_length=64, blank=True)
    method = models.CharField(max_length=10, blank=True)
    path = models.CharField(max_length=255, blank=True)
    exception_type = models.CharField(max_length=150)
    message = models.CharField(max_length=255, blank=True)
    user_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "core_error_event"
        ordering = ["-occurred_at"]


class OffsiteBackupRun(models.Model):
    """One attempt by deploy/scripts/offsite-backup.sh to send an encrypted copy off site."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Uploaded"
        FAILURE = "failure", "Failed"

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(auto_now_add=True, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    snapshot_id = models.CharField(max_length=64, blank=True)
    bytes_added = models.BigIntegerField(null=True, blank=True)
    dump_file = models.CharField(max_length=120, blank=True)
    target = models.CharField(max_length=255, blank=True, help_text="Where the copy went, without credentials.")
    message = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "core_offsite_backup_run"
        ordering = ["-finished_at"]


class HealthSample(models.Model):
    """One reading per day of disk and storage use, for the trend charts on the System page.
    Written by the daily health job and whenever the health page is opened (the same day is updated)."""

    day = models.DateField(unique=True)
    disk_percent_used = models.DecimalField(max_digits=5, decimal_places=1, null=True)
    disk_free_bytes = models.BigIntegerField(null=True)
    database_bytes = models.BigIntegerField(null=True)
    newest_backup_bytes = models.BigIntegerField(null=True)
    recorded_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_health_sample"
        ordering = ["day"]
