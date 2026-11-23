from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimestampedModel
from apps.patients.models import Patient
from apps.core.concurrency import Versioned


class AppointmentType(Versioned, TimestampedModel):
    """
    What an appointment is for (new patient examination, root canal session, crown fitting...). Sets the
    default length and chair. Managed by the clinic; never hard-coded. Prices live in the procedure catalogue.
    """

    class Category(models.TextChoices):
        CONSULTATION = "consultation", "Consultation or examination"
        PROCEDURE = "procedure", "Planned procedure"
        REVIEW = "review", "Follow-up or review"
        IMAGING = "imaging", "Imaging"

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=12, choices=Category.choices)
    default_minutes = models.PositiveSmallIntegerField(default=30)
    default_room = models.ForeignKey("accounts.Room", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "scheduling_appointment_type"
        ordering = ["sort_order", "name"]
        constraints = [models.CheckConstraint(condition=Q(default_minutes__gte=5, default_minutes__lte=240),
                                              name="appt_type_minutes_range")]

    def __str__(self) -> str:
        return self.name


class Appointment(TimestampedModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CONFIRMED = "confirmed", "Confirmed"
        ARRIVED = "arrived", "Arrived"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        NO_SHOW = "no_show", "No-show"

    ACTIVE = (Status.SCHEDULED, Status.CONFIRMED, Status.ARRIVED)
    BOOKED = (Status.SCHEDULED, Status.CONFIRMED)  # not yet arrived

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="appointments")
    doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="appointments")
    scheduled_at = models.DateTimeField()
    scheduled_date = models.DateField(editable=False)  # local (EAT) date, for duplicate checks and day views
    duration_minutes = models.PositiveSmallIntegerField(default=15)
    reason = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    # The service the patient is booked for (consultation type). String reference avoids a circular import.
    service = models.ForeignKey("billing.ServicePrice", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    reschedule_count = models.PositiveSmallIntegerField(default=0)
    cancel_reason = models.CharField(max_length=255, blank=True)
    # Set when a doctor books this as a follow-up from a consultation.
    source_encounter = models.ForeignKey("clinical.Encounter", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="follow_up_appointments")
    appointment_type = models.ForeignKey(AppointmentType, null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="appointments")
    # The chair or treatment room booked. Two active appointments may not overlap on the same room.
    room = models.ForeignKey("accounts.Room", null=True, blank=True, on_delete=models.PROTECT,
                             related_name="appointments")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "scheduling_appointment"
        ordering = ["scheduled_at"]
        indexes = [
            models.Index(fields=["scheduled_date", "doctor"], name="appt_day_doctor_idx"),
            models.Index(fields=["patient", "-scheduled_at"], name="appt_patient_idx"),
            models.Index(fields=["scheduled_date", "room"], name="appt_day_room_idx"),
        ]
        constraints = [
            # One active appointment per patient per day: prevents accidental double booking.
            models.UniqueConstraint(fields=["patient", "scheduled_date"], condition=Q(status__in=["scheduled", "confirmed", "arrived"]),
                                    name="appt_one_active_per_patient_day"),
            models.CheckConstraint(condition=Q(duration_minutes__gte=5, duration_minutes__lte=240),
                                   name="appt_duration_range"),
        ]


class Visit(TimestampedModel):
    """One attendance at the clinic. Everything clinical and billable in a day hangs off a visit."""

    class Kind(models.TextChoices):
        WALK_IN = "walk_in", "Walk-in"
        APPOINTMENT = "appointment", "Appointment"
        # Came only for tests requested elsewhere: no triage, no consultation here.
        LAB_ONLY = "lab_only", "Laboratory only"

    class Status(models.TextChoices):
        WAITING_TRIAGE = "waiting_triage", "Waiting for triage"
        WAITING_DOCTOR = "waiting_doctor", "Waiting for doctor"
        IN_CONSULTATION = "in_consultation", "In consultation"
        # Consultation signed; laboratory, pharmacy and billing may still be in progress, in any order.
        AFTER_CONSULTATION = "after_consult", "After consultation"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class Outcome(models.TextChoices):
        COMPLETED = "completed", "Care completed"
        REFERRED = "referred", "Referred elsewhere"
        LEFT_EARLY = "left_early", "Left before completion"
        FOLLOW_UP = "follow_up", "Completed, follow-up booked"

    class Priority(models.TextChoices):
        ROUTINE = "routine", "Routine"
        URGENT = "urgent", "Urgent"
        EMERGENCY = "emergency", "Emergency"

    OPEN = (Status.WAITING_TRIAGE, Status.WAITING_DOCTOR, Status.IN_CONSULTATION, Status.AFTER_CONSULTATION)
    WAITING = (Status.WAITING_TRIAGE, Status.WAITING_DOCTOR)

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="visits")
    appointment = models.OneToOneField(Appointment, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="visit")
    visit_date = models.DateField()
    queue_number = models.PositiveIntegerField()
    kind = models.CharField(max_length=12, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.WAITING_TRIAGE)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.ROUTINE)
    # Where the patient is now waiting or being seen (a Department code): set by triage, changed by an
    # internal referral. The waiting list's department view uses it.
    department = models.CharField(max_length=30, blank=True)
    assigned_doctor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="assigned_visits")
    arrived_at = models.DateTimeField()
    consultation_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    outcome = models.CharField(max_length=12, choices=Outcome.choices, blank=True)
    completion_note = models.CharField(max_length=500, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    # Queue handling. These never touch the clinical record.
    called_at = models.DateTimeField(null=True, blank=True)
    called_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+")
    called_room = models.CharField(max_length=60, blank=True)  # the room the patient was called to
    skipped_at = models.DateTimeField(null=True, blank=True)
    skip_reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "scheduling_visit"
        ordering = ["visit_date", "queue_number"]
        indexes = [
            models.Index(fields=["visit_date", "status"], name="visit_day_status_idx"),
            models.Index(fields=["patient", "-visit_date"], name="visit_patient_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["visit_date", "queue_number"], name="visit_queue_number_unique"),
            models.UniqueConstraint(
                fields=["patient", "visit_date"],
                condition=Q(status__in=["waiting_triage", "waiting_doctor", "in_consultation", "after_consult"]),
                name="visit_one_open_per_patient_day",
            ),
            models.CheckConstraint(condition=~Q(status="completed") | ~Q(outcome=""), name="visit_completed_has_outcome"),
        ]


class VisitEvent(models.Model):
    """The visit timeline: what happened to this patient today, in plain words, in order."""

    id = models.BigAutoField(primary_key=True)
    visit = models.ForeignKey(Visit, on_delete=models.PROTECT, related_name="events")
    at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=30)
    summary = models.CharField(max_length=255)

    class Meta:
        db_table = "scheduling_visit_event"
        ordering = ["at", "id"]
        indexes = [models.Index(fields=["visit", "at"], name="visit_event_idx")]


class Holiday(Versioned, models.Model):
    """A holiday the clinic enters itself: Islamic holidays (set by moon sighting) and clinic-specific days.

    Holidays with a fixed rule (Proclamation 1334/2024) are computed, not stored; see scheduling/holidays.py."""

    class Kind(models.TextChoices):
        NATIONAL = "national", "National holiday"
        RELIGIOUS = "religious", "Religious holiday"
        MEMORIAL = "memorial", "Memorial day (offices open)"
        CLINIC = "clinic", "Clinic day (closure or reduced service)"

    date = models.DateField()
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.RELIGIOUS)
    tentative = models.BooleanField(default=False, help_text="Date not yet confirmed (moon sighting).")
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "scheduling_holiday"
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["date", "name"], name="holiday_unique_per_day")]
