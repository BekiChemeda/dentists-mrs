from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.clinical.models import Encounter
from apps.core.models import TimestampedModel, UUIDModel
from apps.patients.models import Patient
from apps.scheduling.models import Visit
from apps.core.concurrency import Versioned


class LabTest(Versioned, TimestampedModel):
    class ResultType(models.TextChoices):
        NUMERIC = "numeric", "Number"
        QUALITATIVE = "qualitative", "Positive / negative"
        CHOICE = "choice", "One of a list (categorical)"
        TEXT = "text", "Free text"

    QUALITATIVE_CHOICES = ("Negative", "Positive", "Indeterminate")

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    category = models.CharField("department", max_length=50, blank=True)  # Haematology, Chemistry, Parasitology...
    specimen_type = models.CharField(max_length=50, blank=True)
    result_type = models.CharField(max_length=12, choices=ResultType.choices, default=ResultType.NUMERIC)
    unit = models.CharField(max_length=30, blank=True)
    ref_low = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    ref_high = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    ref_text = models.CharField("reference range text", max_length=120, blank=True)
    choices = models.CharField(max_length=255, blank=True, help_text="Comma-separated, for choice results")
    normal_choice = models.CharField(max_length=60, blank=True)
    # Results at or beyond these limits are critical: phoned to the clinician and acknowledged.
    critical_low = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    critical_high = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    critical_choices = models.CharField(max_length=255, blank=True, help_text="Comma-separated critical answers")
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "laboratory_test"
        ordering = ["category", "name"]
        constraints = [
            models.CheckConstraint(condition=Q(ref_low__isnull=True) | Q(ref_high__isnull=True)
                                   | Q(ref_low__lte=models.F("ref_high")), name="labtest_range_ordered"),
            models.CheckConstraint(condition=Q(price__gte=0), name="labtest_price_nonneg"),
        ]

    def choice_list(self) -> list[str]:
        listed = [c.strip() for c in self.choices.split(",") if c.strip()]
        if self.result_type == self.ResultType.QUALITATIVE and not listed:
            return list(self.QUALITATIVE_CHOICES)
        return listed

    def normal_answer(self) -> str:
        if self.normal_choice:
            return self.normal_choice
        return "Negative" if self.result_type == self.ResultType.QUALITATIVE else ""

    def critical_answers(self) -> set[str]:
        return {c.strip() for c in self.critical_choices.split(",") if c.strip()}


class LabReferenceRange(models.Model):
    """
    A reference range that applies to some patients only (by sex and/or age). The most specific
    matching row is copied onto the order item at request time; otherwise the test's default range.
    """

    id = models.BigAutoField(primary_key=True)
    test = models.ForeignKey(LabTest, on_delete=models.CASCADE, related_name="ranges")
    sex = models.CharField(max_length=6, blank=True, choices=[("", "Any"), ("female", "Female"), ("male", "Male")])
    age_min_days = models.PositiveIntegerField(default=0)
    age_max_days = models.PositiveIntegerField(null=True, blank=True)  # exclusive; empty = no upper limit
    ref_low = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    ref_high = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    ref_text = models.CharField(max_length=120, blank=True)
    critical_low = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    critical_high = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)

    class Meta:
        db_table = "laboratory_reference_range"
        ordering = ["test", "sex", "age_min_days"]
        constraints = [
            models.CheckConstraint(condition=Q(age_max_days__isnull=True) | Q(age_max_days__gt=models.F("age_min_days")),
                                   name="labrange_age_ordered"),
        ]


class LabOrder(TimestampedModel):
    class Priority(models.TextChoices):
        ROUTINE = "routine", "Routine"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        ORDERED = "ordered", "Ordered"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    accession_number = models.CharField(max_length=20, unique=True)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="lab_orders")
    visit = models.ForeignKey(Visit, on_delete=models.PROTECT, related_name="lab_orders")
    encounter = models.ForeignKey(Encounter, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="lab_orders")
    ordered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="lab_orders")
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.ROUTINE)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ORDERED)
    clinical_notes = models.CharField(max_length=255, blank=True)
    # Laboratory-only visits: the paper request from a clinician elsewhere.
    external_requester = models.CharField("requesting clinician", max_length=120, blank=True)
    external_facility = models.CharField("requesting facility", max_length=150, blank=True)

    class Meta:
        db_table = "laboratory_order"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"], name="laborder_status_idx"),
                   models.Index(fields=["patient", "-created_at"], name="laborder_patient_idx")]
        constraints = [
            # Every request has a clinician behind it: a consultation here, or a named outside requester.
            models.CheckConstraint(condition=Q(encounter__isnull=False) | ~Q(external_requester=""),
                                   name="laborder_has_requester"),
        ]


class LabOrderItem(UUIDModel):
    class Status(models.TextChoices):
        ORDERED = "ordered", "Awaiting specimen"
        COLLECTED = "collected", "Specimen collected"
        RESULTED = "resulted", "Result entered"
        VERIFIED = "verified", "Verified"
        CANCELLED = "cancelled", "Cancelled"

    class Flag(models.TextChoices):
        NONE = "", "—"
        NORMAL = "N", "Normal"
        LOW = "L", "Low"
        HIGH = "H", "High"
        ABNORMAL = "A", "Abnormal"
        CRITICAL_LOW = "LL", "Critically low"
        CRITICAL_HIGH = "HH", "Critically high"
        CRITICAL = "AA", "Critical"

    CRITICAL_FLAGS = (Flag.CRITICAL_LOW, Flag.CRITICAL_HIGH, Flag.CRITICAL)
    ABNORMAL_FLAGS = (Flag.LOW, Flag.HIGH, Flag.ABNORMAL) + CRITICAL_FLAGS

    order = models.ForeignKey(LabOrder, on_delete=models.PROTECT, related_name="items")
    test = models.ForeignKey(LabTest, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ORDERED)
    price = models.DecimalField(max_digits=12, decimal_places=2)  # snapshot at order time
    repeat_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="repeats")
    repeat_reason = models.CharField(max_length=255, blank=True)
    is_chargeable = models.BooleanField(default=True)  # repeats caused by the laboratory are not charged
    specimen_type = models.CharField(max_length=50, blank=True)
    specimen_label = models.CharField(max_length=30, blank=True)
    collected_at = models.DateTimeField(null=True, blank=True)
    collected_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    result_numeric = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    result_text = models.CharField(max_length=500, blank=True)
    unit = models.CharField(max_length=30, blank=True)
    ref_low = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    ref_high = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    ref_text = models.CharField(max_length=120, blank=True)
    critical_low = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    critical_high = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    flag = models.CharField(max_length=2, choices=Flag.choices, blank=True)
    result_comment = models.CharField(max_length=255, blank=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    entered_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    # Critical results: who in the laboratory told which clinician, when; and the clinician's acknowledgement.
    critical_reported_to = models.CharField(max_length=150, blank=True)
    critical_reported_at = models.DateTimeField(null=True, blank=True)
    critical_reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                             related_name="+")
    critical_acknowledged_at = models.DateTimeField(null=True, blank=True)
    critical_acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                                 on_delete=models.PROTECT, related_name="+")

    @property
    def is_critical(self) -> bool:
        return self.flag in self.CRITICAL_FLAGS

    def display_value(self) -> str:
        if self.result_numeric is not None:
            return f"{self.result_numeric.normalize():f}"
        return self.result_text

    class Meta:
        db_table = "laboratory_order_item"
        ordering = ["order", "test__name"]
        indexes = [models.Index(fields=["status"], name="labitem_status_idx")]
        constraints = [
            models.CheckConstraint(condition=~Q(status="verified") | Q(verified_by__isnull=False, entered_by__isnull=False),
                                   name="labitem_verified_has_people"),
            models.CheckConstraint(
                condition=~(Q(status="verified") & Q(flag__in=["LL", "HH", "AA"])) | ~Q(critical_reported_to=""),
                name="labitem_critical_reported"),
        ]


class LabResultAmendment(UUIDModel):
    """Correction of a verified result. The previous value is kept here permanently."""

    item = models.ForeignKey(LabOrderItem, on_delete=models.PROTECT, related_name="amendments")
    previous_numeric = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    previous_text = models.CharField(max_length=500, blank=True)
    previous_flag = models.CharField(max_length=2, blank=True)
    reason = models.CharField(max_length=255)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "laboratory_result_amendment"
        ordering = ["created_at"]
