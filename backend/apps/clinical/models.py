from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimestampedModel, UUIDModel
from apps.inventory.models import Item
from apps.patients.models import Patient
from apps.scheduling.models import Visit


GENERAL_APPEARANCE = [
    ("acute_sick", "Acute sick looking"),
    ("chronic_sick", "Chronic sick looking"),
    ("acute_on_chronic", "Acute on chronic sick looking"),
]

# The departments seeded as triage destinations on first install (accounts migration 0005).
# After that, clinic administrators manage destinations as Departments.
TRIAGE_DESTINATIONS = [
    ("adult_eopd", "Adult EOPD"),
    ("pediatric_eopd", "Pediatric EOPD"),
    ("opd1", "OPD 1"),
    ("opd2", "OPD 2"),
    ("labour_ward", "Labour ward"),
]

# Prescription frequencies, written the way clinicians write them.
FREQUENCIES = ["Daily", "BID", "TID", "QID", "STAT", "PRN", "Nocte", "Weekly"]


class VitalSigns(UUIDModel):
    """One triage assessment: measurements plus what the nurse observed. Never edited; re-measure instead."""

    class Consciousness(models.TextChoices):
        # ACVPU, as used by NEWS2.
        ALERT = "alert", "Alert"
        CONFUSION = "confusion", "New confusion"
        VOICE = "voice", "Responds to voice"
        PAIN = "pain", "Responds to pain"
        UNRESPONSIVE = "unresponsive", "Unresponsive"

    visit = models.ForeignKey(Visit, on_delete=models.PROTECT, related_name="vital_signs")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="vital_signs")
    recorded_at = models.DateTimeField(auto_now_add=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    systolic = models.PositiveSmallIntegerField("systolic BP (mmHg)", null=True, blank=True)
    diastolic = models.PositiveSmallIntegerField("diastolic BP (mmHg)", null=True, blank=True)
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    heart_rate = models.PositiveSmallIntegerField("heart rate (bpm)", null=True, blank=True)
    respiratory_rate = models.PositiveSmallIntegerField("respiratory rate (/min)", null=True, blank=True)
    spo2 = models.PositiveSmallIntegerField("SpO₂ (%)", null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    bmi = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True, editable=False)
    pain_score = models.PositiveSmallIntegerField(null=True, blank=True)
    consciousness = models.CharField(max_length=12, choices=Consciousness.choices, blank=True)
    on_oxygen = models.BooleanField(null=True, blank=True)
    # Triage assessment
    chief_complaint = models.CharField("main complaint at triage", max_length=255, blank=True)
    complaint_duration = models.CharField(max_length=60, blank=True)
    general_appearance = models.CharField(max_length=20, choices=GENERAL_APPEARANCE, blank=True)
    # Code of a Department with receives_triage; kept as text so history survives renamed departments.
    triage_to = models.CharField("sent to", max_length=30, blank=True)
    symptoms = models.TextField(blank=True)
    allergies_confirmed = models.BooleanField("allergies checked with the patient", null=True, blank=True)
    current_medications = models.TextField(blank=True)
    observations = models.TextField("clinical observations", blank=True)
    notes = models.CharField("triage notes", max_length=255, blank=True)

    class Meta:
        db_table = "clinical_vital_signs"
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["patient", "-recorded_at"], name="vitals_patient_idx")]
        constraints = [
            # Physiologically plausible ranges: catch typing errors such as 1200 instead of 120.
            models.CheckConstraint(condition=Q(systolic__isnull=True) | Q(systolic__range=(40, 300)), name="vitals_sys"),
            models.CheckConstraint(condition=Q(diastolic__isnull=True) | Q(diastolic__range=(20, 200)), name="vitals_dia"),
            models.CheckConstraint(condition=Q(temperature_c__isnull=True) | Q(temperature_c__range=(25, 45)),
                                   name="vitals_temp"),
            models.CheckConstraint(condition=Q(heart_rate__isnull=True) | Q(heart_rate__range=(20, 300)), name="vitals_hr"),
            models.CheckConstraint(condition=Q(respiratory_rate__isnull=True) | Q(respiratory_rate__range=(2, 120)),
                                   name="vitals_rr"),
            models.CheckConstraint(condition=Q(spo2__isnull=True) | Q(spo2__range=(30, 100)), name="vitals_spo2"),
            models.CheckConstraint(condition=Q(weight_kg__isnull=True) | Q(weight_kg__range=(0.3, 400)),
                                   name="vitals_weight"),
            models.CheckConstraint(condition=Q(height_cm__isnull=True) | Q(height_cm__range=(20, 250)),
                                   name="vitals_height"),
            models.CheckConstraint(condition=Q(pain_score__isnull=True) | Q(pain_score__range=(0, 10)), name="vitals_pain"),
        ]


class Encounter(TimestampedModel):
    """A doctor's consultation note. Once signed it never changes; corrections are amendments."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SIGNED = "signed", "Signed"

    NOTE_FIELDS = (
        "chief_complaint", "complaint_duration", "history_present_illness", "past_medical_history",
        "surgical_history", "family_history", "medication_history", "allergy_notes", "general_appearance",
        "physical_examination", "systems_examination", "assessment", "differential_diagnosis", "plan",
        "non_drug_treatment", "follow_up_instructions",
        "exam_heent", "exam_lgs", "exam_resp", "exam_cvs", "exam_abd", "exam_gus", "exam_cns",
    )
    # Fields kept only so notes written before the evaluation-note layout still display:
    # physical_examination, systems_examination, assessment, surgical_history.

    visit = models.ForeignKey(Visit, on_delete=models.PROTECT, related_name="encounters")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="encounters")
    doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="encounters")
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.DRAFT)
    version = models.PositiveIntegerField(default=1)
    chief_complaint = models.TextField("presenting complaint", blank=True)
    complaint_duration = models.CharField(max_length=60, blank=True)
    history_present_illness = models.TextField(blank=True)
    past_medical_history = models.TextField(blank=True)
    surgical_history = models.TextField("previous operations", blank=True)
    family_history = models.TextField(blank=True)
    medication_history = models.TextField(blank=True)
    allergy_notes = models.TextField(blank=True)
    general_appearance = models.TextField(blank=True)
    physical_examination = models.TextField("examination findings", blank=True)
    systems_examination = models.TextField("system-specific findings", blank=True)
    assessment = models.TextField("clinical assessment", blank=True)
    differential_diagnosis = models.TextField(blank=True)
    plan = models.TextField("treatment plan", blank=True)
    non_drug_treatment = models.TextField("advice and non-drug treatment", blank=True)
    follow_up_instructions = models.TextField(blank=True)
    # System-specific examination
    exam_heent = models.TextField("HEENT", blank=True)
    exam_lgs = models.TextField("LGS (lymph glandular system)", blank=True)
    exam_resp = models.TextField("respiratory system", blank=True)
    exam_cvs = models.TextField("cardiovascular system", blank=True)
    exam_abd = models.TextField("abdomen", blank=True)
    exam_gus = models.TextField("genitourinary system", blank=True)
    exam_cns = models.TextField("central nervous system", blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "clinical_encounter"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"], name="encounter_patient_idx"),
                   models.Index(fields=["doctor", "status"], name="encounter_doctor_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(status="draft", signed_at__isnull=True)
                                   | Q(status="signed", signed_at__isnull=False), name="encounter_signed_consistent"),
            models.UniqueConstraint(fields=["visit", "doctor"], condition=Q(status="draft"),
                                    name="encounter_one_draft_per_visit_doctor"),
        ]


class NoteAmendment(UUIDModel):
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name="amendments")
    field_name = models.CharField(max_length=40)
    original_text = models.TextField(blank=True)
    amended_text = models.TextField()
    reason = models.CharField(max_length=255)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "clinical_note_amendment"
        ordering = ["created_at"]


class IcdCode(models.Model):
    code = models.CharField(max_length=10, primary_key=True)
    title = models.CharField(max_length=255)
    is_common = models.BooleanField(default=False)

    class Meta:
        db_table = "clinical_icd_code"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} {self.title}"


class Diagnosis(UUIDModel):
    class Kind(models.TextChoices):
        PRIMARY = "primary", "Primary"
        SECONDARY = "secondary", "Secondary"

    class Certainty(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        PROVISIONAL = "provisional", "Provisional"

    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name="diagnoses")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="diagnoses")
    icd = models.ForeignKey(IcdCode, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    description = models.CharField(max_length=255)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PRIMARY)
    certainty = models.CharField(max_length=12, choices=Certainty.choices, default=Certainty.CONFIRMED)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    is_removed = models.BooleanField(default=False)  # only possible while the encounter is a draft

    class Meta:
        db_table = "clinical_diagnosis"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["icd"], name="diagnosis_icd_idx")]


class Prescription(TimestampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Awaiting dispensing"
        PARTIAL = "partial", "Partially dispensed"
        DISPENSED = "dispensed", "Dispensed"
        NOT_COLLECTED = "not_collected", "Not collected"
        CANCELLED = "cancelled", "Cancelled"
        # The clinic has no pharmacy module: the patient takes the printed prescription elsewhere.
        EXTERNAL = "external", "Printed for an outside pharmacy"

    OPEN = (Status.ACTIVE, Status.PARTIAL)

    # Printed on the prescription, e.g. RX-2026-00042. Unique when set (see migration 0010).
    number = models.CharField(max_length=20, blank=True)
    # Written in a medical consultation or in a dental examination (exactly one; ADR 0009). The visit is always set,
    # so pharmacy, billing and visit completion work the same for both.
    visit = models.ForeignKey(Visit, on_delete=models.PROTECT, related_name="prescriptions")
    encounter = models.ForeignKey(Encounter, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="prescriptions")
    dental_encounter = models.ForeignKey("dental.DentalEncounter", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="prescriptions")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="prescriptions")
    prescriber = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="prescriptions")
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.ACTIVE)
    notes = models.CharField(max_length=255, blank=True)
    # Controlled medicines (EFDA Directive 1121/2025): the paper special prescription remains the legal
    # document; its serial number and the patient's weight are recorded here.
    controlled_class = models.CharField(max_length=12, blank=True)
    special_form_serial = models.CharField(max_length=40, blank=True)
    patient_weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "clinical_prescription"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"], name="rx_status_idx")]
        constraints = [
            models.UniqueConstraint(fields=["number"], condition=~Q(number=""), name="prescription_number_unique"),
            models.CheckConstraint(condition=Q(encounter__isnull=False, dental_encounter__isnull=True)
                                   | Q(encounter__isnull=True, dental_encounter__isnull=False),
                                   name="prescription_one_encounter"),
        ]


class PrescriptionItem(UUIDModel):
    prescription = models.ForeignKey(Prescription, on_delete=models.PROTECT, related_name="items")
    item = models.ForeignKey(Item, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    drug_name = models.CharField(max_length=150)
    strength = models.CharField(max_length=50, blank=True)
    dosage_form = models.CharField(max_length=50, blank=True)
    dose = models.CharField(max_length=50)
    route = models.CharField(max_length=30, default="oral")
    frequency = models.CharField(max_length=50)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    quantity_dispensed = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    instructions = models.CharField(max_length=255, blank=True)
    warnings = models.CharField(max_length=255, blank=True)
    allergy_override_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "clinical_prescription_item"
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="rx_item_qty_positive"),
            models.CheckConstraint(condition=Q(quantity_dispensed__gte=0) & Q(quantity_dispensed__lte=models.F("quantity")),
                                   name="rx_item_dispensed_within_qty"),
        ]


class Referral(TimestampedModel):
    """A referral to another facility or service. Printed as a referral letter."""

    class Urgency(models.TextChoices):
        ROUTINE = "routine", "Routine"
        URGENT = "urgent", "Urgent"
        EMERGENCY = "emergency", "Emergency"

    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=20, unique=True)
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name="referrals")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="referrals")
    to_facility = models.CharField(max_length=150)
    to_department = models.CharField(max_length=100, blank=True)
    urgency = models.CharField(max_length=10, choices=Urgency.choices, default=Urgency.ROUTINE)
    reason = models.TextField()
    clinical_summary = models.TextField(blank=True)
    treatment_given = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ISSUED)
    cancel_reason = models.CharField(max_length=255, blank=True)
    referred_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "clinical_referral"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"], name="referral_patient_idx")]


class MedicalCertificate(TimestampedModel):
    """Sick leave, fitness or attendance certificate. Never edited; cancelled and reissued instead."""

    class Kind(models.TextChoices):
        SICK_LEAVE = "sick_leave", "Sick leave"
        FITNESS = "fitness", "Fitness to work or study"
        ATTENDANCE = "attendance", "Attendance"

    number = models.CharField(max_length=20, unique=True)
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name="certificates")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="certificates")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    # A diagnosis is personal health data: only printed when the patient agrees.
    include_diagnosis = models.BooleanField(default=False)
    diagnosis_text = models.CharField(max_length=255, blank=True)
    remarks = models.TextField(blank=True)
    is_cancelled = models.BooleanField(default=False)
    cancel_reason = models.CharField(max_length=255, blank=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "clinical_certificate"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(start_date__isnull=True) | Q(end_date__isnull=True)
                                   | Q(end_date__gte=models.F("start_date")), name="certificate_dates_ordered"),
            models.CheckConstraint(condition=~Q(kind="sick_leave") | Q(start_date__isnull=False, end_date__isnull=False),
                                   name="certificate_sick_leave_has_dates"),
        ]

    @property
    def days(self) -> int | None:
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return None


class InternalReferral(TimestampedModel):
    """
    A doctor sends the patient to another department of this clinic during the same visit (e.g. OPD to the
    dental clinic). The visit moves to that department's waiting list; the receiving doctor's consultation
    is linked when it starts. External referrals to other facilities are `Referral`.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting to be seen"
        SEEN = "seen", "Seen"
        CANCELLED = "cancelled", "Cancelled"

    class Urgency(models.TextChoices):
        ROUTINE = "routine", "Routine"
        URGENT = "urgent", "Urgent"
        EMERGENCY = "emergency", "Emergency"

    visit = models.ForeignKey(Visit, on_delete=models.PROTECT, related_name="internal_referrals")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="internal_referrals")
    from_encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name="internal_referrals_out")
    from_department = models.CharField(max_length=30, blank=True)
    to_department = models.CharField(max_length=30)
    to_doctor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+")
    urgency = models.CharField(max_length=10, choices=Urgency.choices, default=Urgency.ROUTINE)
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    referred_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    seen_encounter = models.ForeignKey(Encounter, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="internal_referrals_in")
    seen_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "clinical_internal_referral"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"], name="intref_patient_idx"),
                   models.Index(fields=["to_department", "status"], name="intref_dept_status_idx")]
        constraints = [
            models.CheckConstraint(condition=~Q(status="seen") | Q(seen_at__isnull=False), name="intref_seen_has_time"),
            models.UniqueConstraint(fields=["visit"], condition=Q(status="pending"), name="intref_one_pending_per_visit"),
        ]
