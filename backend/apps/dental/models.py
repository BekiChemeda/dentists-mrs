"""
Dental clinical records. See docs/dental/data-model.md.

Shared identity, visits, billing, stock and audit come from the shared apps; this module owns only what is
specific to dentistry. Signed records are never edited in place: corrections are separate rows.
"""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from apps.core.concurrency import Versioned
from apps.core.models import TimestampedModel, UUIDModel
from apps.inventory.models import Item
from apps.patients.models import Patient
from apps.scheduling.models import Appointment, Visit

from . import teeth

User = settings.AUTH_USER_MODEL

TEETH_LIST = sorted(teeth.ALL_TEETH)


class ReviewStatus(models.TextChoices):
    PENDING = "pending", "Starter list — pending clinical review"
    APPROVED = "approved", "Reviewed by the clinic"


class Scope(models.TextChoices):
    TOOTH = "tooth", "Whole tooth"
    SURFACES = "surfaces", "Tooth surfaces"
    REGION = "region", "Region"
    MOUTH = "mouth", "Whole mouth"


class Location(models.Model):
    """Where something applies: a tooth, some of its surfaces, a region or the whole mouth (apps/dental/teeth.py)."""

    scope = models.CharField(max_length=8, choices=Scope.choices)
    tooth = models.PositiveSmallIntegerField(null=True, blank=True)
    surfaces = models.CharField(max_length=6, blank=True)  # letters in fixed order, e.g. "MOD"
    region = models.CharField(max_length=12, blank=True)

    class Meta:
        abstract = True

    @property
    def location_label(self) -> str:
        return teeth.describe(self.scope, self.tooth, self.surfaces, self.region)


def location_constraints(prefix: str) -> list:
    return [
        models.CheckConstraint(
            condition=(Q(scope="tooth", tooth__isnull=False, surfaces="", region="")
                       | (Q(scope="surfaces", tooth__isnull=False, region="") & ~Q(surfaces=""))
                       | (Q(scope="region", tooth__isnull=True, surfaces="") & ~Q(region=""))
                       | Q(scope="mouth", tooth__isnull=True, surfaces="", region="")),
            name=f"{prefix}_location_consistent"),
        models.CheckConstraint(condition=Q(tooth__isnull=True) | Q(tooth__in=TEETH_LIST), name=f"{prefix}_fdi_tooth"),
    ]


# ===========================================================================
# Catalogues (configurable; starter content is pending clinical review)
# ===========================================================================
class FindingType(Versioned, TimestampedModel):
    """A kind of chart finding: caries, restoration, missing... with the short symbol printed on the chart."""

    class Kind(models.TextChoices):
        STATE = "state", "Tooth state (missing, unerupted...)"
        CONDITION = "condition", "Current condition"
        EXISTING = "existing", "Existing treatment"

    class AppliesTo(models.TextChoices):
        TOOTH = "tooth", "Whole tooth only"
        SURFACE = "surface", "Surfaces only"
        EITHER = "either", "Whole tooth or surfaces"
        AREA = "area", "Region or whole mouth"

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80, unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    applies_to = models.CharField(max_length=8, choices=AppliesTo.choices, default=AppliesTo.EITHER)
    symbol = models.CharField(max_length=6)  # printed on the chart; never colour alone
    color = models.CharField(max_length=7, blank=True)  # optional #rrggbb, a secondary cue
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    review_status = models.CharField(max_length=8, choices=ReviewStatus.choices, default=ReviewStatus.PENDING)

    class Meta:
        db_table = "dental_finding_type"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class DentalDiagnosisTerm(Versioned, TimestampedModel):
    """A diagnosis the clinic uses, with its code system. Seeded from WHO ICD-10 chapter XI (ADR 0008)."""

    code_system = models.CharField(max_length=20, default="ICD-10")
    code = models.CharField(max_length=20)
    term = models.CharField(max_length=200)
    category = models.CharField(max_length=60, blank=True)
    source_version = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    review_status = models.CharField(max_length=8, choices=ReviewStatus.choices, default=ReviewStatus.PENDING)

    class Meta:
        db_table = "dental_diagnosis_term"
        ordering = ["code_system", "code"]
        constraints = [models.UniqueConstraint(fields=["code_system", "code"], name="dental_dx_term_unique")]

    def __str__(self) -> str:
        return f"{self.code} {self.term}"


class DentalProcedure(Versioned, TimestampedModel):
    """A service the clinic offers, with its price. Clinics enable only what they actually provide."""

    class Category(models.TextChoices):
        CONSULTATION = "consultation", "Consultation and diagnostics"
        PREVENTIVE = "preventive", "Preventive dentistry"
        RESTORATIVE = "restorative", "Restorative dentistry"
        ENDODONTICS = "endodontics", "Endodontics"
        ORAL_SURGERY = "oral_surgery", "Oral surgery"
        PERIODONTICS = "periodontics", "Periodontics"
        PROSTHODONTICS = "prosthodontics", "Prosthodontics"
        ORTHODONTICS = "orthodontics", "Orthodontics"
        IMPLANTS = "implants", "Implant dentistry"
        COSMETIC = "cosmetic", "Cosmetic dentistry"
        IMAGING = "imaging", "Imaging"

    class ToothRequirement(models.TextChoices):
        REQUIRED = "required", "A tooth must be chosen"
        OPTIONAL = "optional", "Tooth optional"
        NONE = "none", "Not tooth-specific"

    class BillingMode(models.TextChoices):
        ON_COMPLETION = "on_completion", "Charged once, when completed"
        PER_SESSION = "per_session", "Charged for every session"

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=16, choices=Category.choices)
    description = models.CharField(max_length=255, blank=True)
    default_minutes = models.PositiveSmallIntegerField(default=30)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    tooth_requirement = models.CharField(max_length=8, choices=ToothRequirement.choices,
                                         default=ToothRequirement.OPTIONAL)
    surfaces_allowed = models.BooleanField(default=False)
    consumes_stock = models.BooleanField(default=False)
    typical_sessions = models.PositiveSmallIntegerField(default=1)
    billing_mode = models.CharField(max_length=14, choices=BillingMode.choices, default=BillingMode.ON_COMPLETION)
    follow_up_kind = models.CharField(max_length=20, blank=True)  # a Recall.Kind, or empty
    follow_up_days = models.PositiveSmallIntegerField(null=True, blank=True)
    # Role codes allowed to perform it under clinic policy; empty = anyone with dental.procedure.sign.
    performer_roles = models.JSONField(default=list, blank=True)
    review_status = models.CharField(max_length=8, choices=ReviewStatus.choices, default=ReviewStatus.PENDING)

    class Meta:
        db_table = "dental_procedure"
        ordering = ["category", "name"]
        constraints = [
            models.CheckConstraint(condition=Q(price__gte=0), name="dental_procedure_price_nonneg"),
            models.CheckConstraint(condition=Q(default_minutes__gte=5, default_minutes__lte=480),
                                   name="dental_procedure_minutes"),
            models.CheckConstraint(condition=Q(typical_sessions__gte=1, typical_sessions__lte=20),
                                   name="dental_procedure_sessions"),
        ]

    def __str__(self) -> str:
        return self.name


class ProcedureDefaultMaterial(UUIDModel):
    """Materials usually used; offered when recording the procedure, always editable."""

    procedure = models.ForeignKey(DentalProcedure, on_delete=models.PROTECT, related_name="default_materials")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=10, decimal_places=3)

    class Meta:
        db_table = "dental_procedure_default_material"
        constraints = [models.UniqueConstraint(fields=["procedure", "item"], name="dental_default_material_once"),
                       models.CheckConstraint(condition=Q(quantity__gt=0), name="dental_default_material_qty")]


# ===========================================================================
# Patient level
# ===========================================================================
class DentalProfile(Versioned, TimestampedModel):
    """The patient's dental history. Examination findings never overwrite it; every change is kept."""

    class Tobacco(models.TextChoices):
        UNKNOWN = "", "Not asked"
        NEVER = "never", "Never"
        FORMER = "former", "Former"
        CURRENT = "current", "Current"

    TEXT_FIELDS = ("previous_treatment", "extraction_history", "root_canal_history", "orthodontic_history",
                   "prosthesis_history", "oral_hygiene", "tobacco_notes", "other_habits", "anxiety_notes",
                   "communication_notes")
    FIELDS = TEXT_FIELDS + ("tobacco_use",)

    patient = models.OneToOneField(Patient, on_delete=models.PROTECT, related_name="dental_profile")
    previous_treatment = models.TextField("previous dental treatment", blank=True)
    extraction_history = models.TextField(blank=True)
    root_canal_history = models.TextField(blank=True)
    orthodontic_history = models.TextField(blank=True)
    prosthesis_history = models.TextField("dentures, crowns, bridges, implants", blank=True)
    oral_hygiene = models.TextField("oral hygiene habits", blank=True)
    tobacco_use = models.CharField(max_length=8, choices=Tobacco.choices, blank=True)
    tobacco_notes = models.CharField(max_length=255, blank=True)
    other_habits = models.TextField("other relevant habits (e.g. khat chewing, bruxism)", blank=True)
    anxiety_notes = models.TextField("dental anxiety", blank=True)
    communication_notes = models.TextField("communication needs", blank=True)
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "dental_profile"


class DentalProfileChange(models.Model):
    id = models.BigAutoField(primary_key=True)
    profile = models.ForeignKey(DentalProfile, on_delete=models.PROTECT, related_name="changes")
    field_name = models.CharField(max_length=40)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    changed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dental_profile_change"
        ordering = ["-changed_at", "-id"]


class MedicalRiskReview(UUIDModel):
    """
    The dentist's structured review of medical history before treatment. Never edited: a new review is recorded.
    Answers: {question_key: {"answer": "yes"|"no"|"unknown", "detail": "..."}}; questions in starter_data.
    """

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="dental_risk_reviews")
    encounter = models.ForeignKey("DentalEncounter", null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="risk_reviews")
    reviewed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    reviewed_at = models.DateTimeField(auto_now_add=True)
    answers = models.JSONField(default=dict)
    allergies_reviewed = models.BooleanField(default=False)
    medications_reviewed = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    previous = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    changed_since_previous = models.BooleanField(null=True)

    class Meta:
        db_table = "dental_risk_review"
        ordering = ["-reviewed_at"]
        indexes = [models.Index(fields=["patient", "-reviewed_at"], name="dental_risk_patient_idx")]


# ===========================================================================
# Dental examination
# ===========================================================================
class DentalEncounter(TimestampedModel):
    """A dentist's clinical record of one consultation or treatment visit. Signed = frozen."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SIGNED = "signed", "Signed"

    class PainPattern(models.TextChoices):
        NONE = "", "Not recorded"
        CONTINUOUS = "continuous", "Continuous"
        INTERMITTENT = "intermittent", "Intermittent"

    SENSITIVITY = ("hot", "cold", "sweet", "biting")

    NOTE_FIELDS = (
        "chief_complaint", "history_of_complaint",
        "pain_location", "pain_onset", "pain_duration", "pain_triggers", "pain_relief", "swelling",
        "patient_description",
        "medical_history_review", "dental_history_review",
        "extraoral_symmetry", "extraoral_swelling", "extraoral_lymph_nodes", "extraoral_jaw_movement",
        "extraoral_tmj", "extraoral_other",
        "intraoral_mucosa", "intraoral_tongue", "intraoral_floor_of_mouth", "intraoral_palate", "intraoral_gingiva",
        "intraoral_saliva", "intraoral_occlusion", "intraoral_soft_tissue", "intraoral_other",
        "assessment", "proposed_treatment", "discussion_notes", "consent_notes", "follow_up_instructions",
    )
    STRUCTURED_FIELDS = ("pain_present", "pain_teeth", "pain_severity", "pain_pattern", "pain_sensitivity",
                         "mouth_opening_mm", "follow_up_date")

    visit = models.ForeignKey(Visit, on_delete=models.PROTECT, related_name="dental_encounters")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="dental_encounters")
    dentist = models.ForeignKey(User, on_delete=models.PROTECT, related_name="dental_encounters")
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.DRAFT)
    version = models.PositiveIntegerField(default=1)
    risk_review = models.ForeignKey(MedicalRiskReview, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    # Complaint and pain
    chief_complaint = models.TextField(blank=True)
    history_of_complaint = models.TextField("history of the present complaint", blank=True)
    pain_present = models.BooleanField(null=True, blank=True)
    pain_teeth = ArrayField(models.PositiveSmallIntegerField(), default=list, blank=True)
    pain_location = models.CharField("pain location or region", max_length=255, blank=True)
    pain_severity = models.PositiveSmallIntegerField(null=True, blank=True)  # 0-10
    pain_onset = models.CharField(max_length=120, blank=True)
    pain_duration = models.CharField(max_length=120, blank=True)
    pain_pattern = models.CharField(max_length=12, choices=PainPattern.choices, blank=True)
    pain_sensitivity = ArrayField(models.CharField(max_length=8), default=list, blank=True)
    pain_triggers = models.CharField(max_length=255, blank=True)
    pain_relief = models.CharField("relieving factors", max_length=255, blank=True)
    swelling = models.CharField("swelling or associated symptoms", max_length=255, blank=True)
    patient_description = models.TextField("in the patient's words", blank=True)
    # Histories reviewed today (the patient-level histories live in DentalProfile and MedicalRiskReview)
    medical_history_review = models.TextField(blank=True)
    dental_history_review = models.TextField(blank=True)
    # Extraoral examination
    extraoral_symmetry = models.CharField("facial symmetry", max_length=255, blank=True)
    extraoral_swelling = models.CharField("swelling", max_length=255, blank=True)
    extraoral_lymph_nodes = models.CharField("lymph nodes", max_length=255, blank=True)
    extraoral_jaw_movement = models.CharField("jaw movement", max_length=255, blank=True)
    extraoral_tmj = models.CharField("temporomandibular joint", max_length=255, blank=True)
    mouth_opening_mm = models.PositiveSmallIntegerField(null=True, blank=True)
    extraoral_other = models.TextField(blank=True)
    # Intraoral examination
    intraoral_mucosa = models.CharField("oral mucosa", max_length=255, blank=True)
    intraoral_tongue = models.CharField("tongue", max_length=255, blank=True)
    intraoral_floor_of_mouth = models.CharField("floor of mouth", max_length=255, blank=True)
    intraoral_palate = models.CharField("palate", max_length=255, blank=True)
    intraoral_gingiva = models.CharField("gingiva", max_length=255, blank=True)
    intraoral_saliva = models.CharField("saliva and dryness", max_length=255, blank=True)
    intraoral_occlusion = models.CharField("occlusion and bite", max_length=255, blank=True)
    intraoral_soft_tissue = models.TextField("soft tissue lesions", blank=True)
    intraoral_other = models.TextField(blank=True)
    # Assessment and plan
    assessment = models.TextField("diagnostic assessment", blank=True)
    proposed_treatment = models.TextField(blank=True)
    discussion_notes = models.TextField("discussion with the patient", blank=True)
    consent_notes = models.TextField(blank=True)
    follow_up_instructions = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "dental_encounter"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"], name="dental_enc_patient_idx"),
                   models.Index(fields=["dentist", "status"], name="dental_enc_dentist_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(status="draft", signed_at__isnull=True)
                                   | Q(status="signed", signed_at__isnull=False), name="dental_enc_signed_consistent"),
            models.UniqueConstraint(fields=["visit", "dentist"], condition=Q(status="draft"),
                                    name="dental_enc_one_draft_per_visit_dentist"),
            models.CheckConstraint(condition=Q(pain_severity__isnull=True) | Q(pain_severity__range=(0, 10)),
                                   name="dental_enc_pain_severity"),
            models.CheckConstraint(condition=Q(mouth_opening_mm__isnull=True) | Q(mouth_opening_mm__range=(0, 90)),
                                   name="dental_enc_mouth_opening"),
        ]


class DentalEncounterAmendment(UUIDModel):
    encounter = models.ForeignKey(DentalEncounter, on_delete=models.PROTECT, related_name="amendments")
    field_name = models.CharField(max_length=40)
    original_text = models.TextField(blank=True)
    amended_text = models.TextField()
    reason = models.CharField(max_length=255)
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dental_encounter_amendment"
        ordering = ["created_at"]


# ===========================================================================
# Diagnoses
# ===========================================================================
class DentalDiagnosis(UUIDModel, Location):
    class Certainty(models.TextChoices):
        SUSPECTED = "suspected", "Suspected"
        CONFIRMED = "confirmed", "Confirmed"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        HISTORICAL = "historical", "Historical"
        RESOLVED = "resolved", "Resolved"

    encounter = models.ForeignKey(DentalEncounter, on_delete=models.PROTECT, related_name="diagnoses")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="dental_diagnoses")
    term = models.ForeignKey(DentalDiagnosisTerm, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    # Copied at recording so later catalogue edits never change a past record.
    code_system = models.CharField(max_length=20)
    code = models.CharField(max_length=20)
    term_text = models.CharField(max_length=200)
    source_version = models.CharField(max_length=40, blank=True)
    certainty = models.CharField(max_length=10, choices=Certainty.choices, default=Certainty.CONFIRMED)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    is_removed = models.BooleanField(default=False)  # only while the examination is a draft
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    resolution_note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "dental_diagnosis"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"], name="dental_dx_patient_idx"),
                   models.Index(fields=["code"], name="dental_dx_code_idx")]
        constraints = location_constraints("dental_dx") + [
            models.CheckConstraint(condition=Q(resolved_at__isnull=True) | Q(status="resolved"),
                                   name="dental_dx_resolved_consistent"),
        ]


# ===========================================================================
# Odontogram: dated findings (ADR 0006)
# ===========================================================================
class ToothFinding(UUIDModel, Location):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="tooth_findings")
    encounter = models.ForeignKey(DentalEncounter, on_delete=models.PROTECT, related_name="findings")
    finding_type = models.ForeignKey(FindingType, on_delete=models.PROTECT, related_name="findings")
    is_existing_work = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)
    diagnosis = models.ForeignKey(DentalDiagnosis, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="findings")
    procedure = models.ForeignKey("ProcedureRecord", null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="findings")
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)
    # No longer true (set once, in a later examination).
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_in = models.ForeignKey(DentalEncounter, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="resolved_findings")
    resolved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    resolution_note = models.CharField(max_length=255, blank=True)
    # Entered in error (set once, with a reason).
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "dental_tooth_finding"
        ordering = ["recorded_at"]
        indexes = [models.Index(fields=["patient", "tooth", "recorded_at"], name="dental_finding_tooth_idx"),
                   models.Index(fields=["encounter"], name="dental_finding_enc_idx")]
        constraints = location_constraints("dental_finding") + [
            models.CheckConstraint(
                condition=Q(resolved_at__isnull=True, resolved_by__isnull=True, resolved_in__isnull=True)
                | (Q(resolved_at__isnull=False, resolved_by__isnull=False, resolved_in__isnull=False)
                   & ~Q(resolution_note="")),
                name="dental_finding_resolution_consistent"),
            models.CheckConstraint(
                condition=Q(voided_at__isnull=True, voided_by__isnull=True)
                | (Q(voided_at__isnull=False, voided_by__isnull=False) & ~Q(void_reason="")),
                name="dental_finding_void_consistent"),
        ]


# ===========================================================================
# Periodontal chart
# ===========================================================================
class PeriodontalExam(TimestampedModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="periodontal_exams")
    encounter = models.ForeignKey(DentalEncounter, on_delete=models.PROTECT, related_name="periodontal_exams")
    examiner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    protocol = models.CharField(max_length=12, default="six_site")
    notes = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "dental_perio_exam"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["encounter"], name="dental_perio_one_per_encounter")]


class PeriodontalTooth(UUIDModel):
    exam = models.ForeignKey(PeriodontalExam, on_delete=models.PROTECT, related_name="teeth")
    tooth = models.PositiveSmallIntegerField()
    missing = models.BooleanField(default=False)
    excluded = models.BooleanField(default=False)
    exclusion_reason = models.CharField(max_length=120, blank=True)
    implant = models.BooleanField(default=False)
    mobility = models.PositiveSmallIntegerField(null=True, blank=True)
    furcation = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "dental_perio_tooth"
        ordering = ["tooth"]
        constraints = [
            models.UniqueConstraint(fields=["exam", "tooth"], name="dental_perio_tooth_once"),
            models.CheckConstraint(condition=Q(tooth__in=TEETH_LIST), name="dental_perio_tooth_fdi"),
            models.CheckConstraint(condition=Q(mobility__isnull=True) | Q(mobility__lte=3), name="dental_perio_mobility"),
            models.CheckConstraint(condition=Q(furcation__isnull=True) | Q(furcation__lte=3),
                                   name="dental_perio_furcation"),
            models.CheckConstraint(condition=Q(excluded=False) | ~Q(exclusion_reason=""),
                                   name="dental_perio_excluded_reason"),
        ]


class PeriodontalSite(UUIDModel):
    exam = models.ForeignKey(PeriodontalExam, on_delete=models.PROTECT, related_name="sites")
    tooth = models.PositiveSmallIntegerField()
    site = models.CharField(max_length=2)
    probing_depth_mm = models.SmallIntegerField(null=True, blank=True)
    # From the CEJ to the gingival margin; positive = margin apical to the CEJ (recession). Pending review R-04.
    gingival_margin_mm = models.SmallIntegerField(null=True, blank=True)
    bleeding = models.BooleanField(null=True, blank=True)
    plaque = models.BooleanField(null=True, blank=True)
    suppuration = models.BooleanField(null=True, blank=True)
    not_measured = models.BooleanField(default=False)
    not_measured_reason = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = "dental_perio_site"
        ordering = ["tooth", "site"]
        constraints = [
            models.UniqueConstraint(fields=["exam", "tooth", "site"], name="dental_perio_site_once"),
            models.CheckConstraint(condition=Q(site__in=list(teeth.PERIO_SITES)), name="dental_perio_site_code"),
            models.CheckConstraint(condition=Q(tooth__in=TEETH_LIST), name="dental_perio_site_fdi"),
            models.CheckConstraint(condition=Q(probing_depth_mm__isnull=True) | Q(probing_depth_mm__range=(0, 15)),
                                   name="dental_perio_pd_range"),
            models.CheckConstraint(condition=Q(gingival_margin_mm__isnull=True)
                                   | Q(gingival_margin_mm__range=(-10, 15)), name="dental_perio_gm_range"),
            models.CheckConstraint(
                condition=Q(not_measured=False)
                | Q(probing_depth_mm__isnull=True, gingival_margin_mm__isnull=True, bleeding__isnull=True,
                    plaque__isnull=True, suppuration__isnull=True),
                name="dental_perio_not_measured_empty"),
        ]


# ===========================================================================
# Treatment plans
# ===========================================================================
class TreatmentPlan(Versioned, TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PRESENTED = "presented", "Presented to the patient"
        ACCEPTED = "accepted", "Accepted"
        PARTIALLY_ACCEPTED = "partially_accepted", "Partially accepted"
        DEFERRED = "deferred", "Deferred"
        DECLINED = "declined", "Declined"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    CLOSED = (Status.COMPLETED, Status.CANCELLED, Status.EXPIRED, Status.DECLINED)

    number = models.CharField(max_length=20, unique=True)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="treatment_plans")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    encounter = models.ForeignKey(DentalEncounter, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="treatment_plans")
    title = models.CharField(max_length=150)
    clinical_reason = models.TextField(blank=True)
    diagnoses = models.ManyToManyField(DentalDiagnosis, blank=True, related_name="treatment_plans",
                                       db_table="dental_plan_diagnosis")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    revision = models.PositiveIntegerField(default=0)  # 0 = never presented
    review_date = models.DateField(null=True, blank=True)
    presented_at = models.DateTimeField(null=True, blank=True)
    decision_at = models.DateTimeField(null=True, blank=True)
    decision_recorded_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    decision_note = models.TextField(blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "dental_treatment_plan"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "status"], name="dental_plan_patient_idx")]


class TreatmentPlanItem(TimestampedModel, Location):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        ACCEPTED = "accepted", "Accepted"
        DEFERRED = "deferred", "Deferred"
        DECLINED = "declined", "Declined"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class Priority(models.TextChoices):
        URGENT = "urgent", "Urgent"
        HIGH = "high", "High"
        ROUTINE = "routine", "Routine"
        ELECTIVE = "elective", "Elective"

    plan = models.ForeignKey(TreatmentPlan, on_delete=models.PROTECT, related_name="items")
    sequence = models.PositiveSmallIntegerField(default=1)
    procedure = models.ForeignKey(DentalProcedure, on_delete=models.PROTECT, related_name="plan_items")
    diagnosis = models.ForeignKey(DentalDiagnosis, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.ROUTINE)
    sessions_planned = models.PositiveSmallIntegerField(default=1)
    estimated_minutes = models.PositiveSmallIntegerField(default=30)
    estimated_fee = models.DecimalField(max_digits=12, decimal_places=2)
    assigned_dentist = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    notes = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PROPOSED)
    decision_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    appointments = models.ManyToManyField(Appointment, blank=True, related_name="dental_plan_items",
                                          db_table="dental_plan_item_appointment")

    class Meta:
        db_table = "dental_plan_item"
        ordering = ["plan", "sequence", "created_at"]
        constraints = location_constraints("dental_plan_item") + [
            models.CheckConstraint(condition=Q(estimated_fee__gte=0), name="dental_plan_item_fee_nonneg"),
            models.CheckConstraint(condition=Q(sessions_planned__gte=1, sessions_planned__lte=20),
                                   name="dental_plan_item_sessions"),
        ]


class TreatmentPlanRevision(UUIDModel):
    """The whole plan as it stood when presented or changed afterwards. Revision 1 is the original proposal."""

    plan = models.ForeignKey(TreatmentPlan, on_delete=models.PROTECT, related_name="revisions")
    revision = models.PositiveIntegerField()
    reason = models.CharField(max_length=255)
    snapshot = models.JSONField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dental_plan_revision"
        ordering = ["plan", "revision"]
        constraints = [models.UniqueConstraint(fields=["plan", "revision"], name="dental_plan_revision_once")]


# ===========================================================================
# Procedures performed
# ===========================================================================
class ProcedureRecord(TimestampedModel, Location):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        COMPLETED = "completed", "Completed"
        SESSION_COMPLETED = "session_completed", "Session done, more sessions needed"
        NOT_PERFORMED = "not_performed", "Not performed"

    SIGNED = (Status.COMPLETED, Status.SESSION_COMPLETED, Status.NOT_PERFORMED)
    TEXT_FIELDS = ("findings_before", "findings_after", "notes", "anaesthesia", "complications",
                   "post_op_instructions", "follow_up_recommendation")

    number = models.CharField(max_length=20, unique=True)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="dental_procedures")
    visit = models.ForeignKey(Visit, on_delete=models.PROTECT, related_name="dental_procedures")
    encounter = models.ForeignKey(DentalEncounter, on_delete=models.PROTECT, related_name="procedures")
    plan_item = models.ForeignKey(TreatmentPlanItem, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="procedures")
    procedure = models.ForeignKey(DentalProcedure, on_delete=models.PROTECT, related_name="records")
    performed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    assisted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    session_number = models.PositiveSmallIntegerField(default=1)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    findings_before = models.TextField(blank=True)
    findings_after = models.TextField(blank=True)
    notes = models.TextField("procedure notes", blank=True)
    anaesthesia = models.TextField("anaesthesia (as written by the clinician)", blank=True)
    complications = models.TextField("complications or unexpected events", blank=True)
    post_op_instructions = models.TextField("post-procedure instructions", blank=True)
    follow_up_recommendation = models.CharField(max_length=255, blank=True)
    follow_up_days = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=18, choices=Status.choices, default=Status.DRAFT)
    not_performed_reason = models.CharField(max_length=255, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    # Copied from the catalogue at signing; past records keep the price they were charged at.
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "dental_procedure_record"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"], name="dental_proc_patient_idx"),
                   models.Index(fields=["visit"], name="dental_proc_visit_idx"),
                   models.Index(fields=["status", "signed_at"], name="dental_proc_status_idx")]
        constraints = location_constraints("dental_proc") + [
            models.CheckConstraint(condition=Q(status="draft", signed_at__isnull=True)
                                   | (~Q(status="draft") & Q(signed_at__isnull=False, signed_by__isnull=False)),
                                   name="dental_proc_signed_consistent"),
            models.CheckConstraint(condition=~Q(status="not_performed") | ~Q(not_performed_reason=""),
                                   name="dental_proc_not_performed_reason"),
            # A plan item is completed by exactly one record (sessions before it are session_completed).
            models.UniqueConstraint(fields=["plan_item"], condition=Q(status="completed"),
                                    name="dental_proc_one_completion_per_item"),
            models.CheckConstraint(condition=Q(price__isnull=True) | Q(price__gte=0), name="dental_proc_price"),
        ]


class ProcedureMaterial(UUIDModel):
    """Material used. Stock is deducted (FEFO ledger) when the record is signed, never before."""

    record = models.ForeignKey(ProcedureRecord, on_delete=models.PROTECT, related_name="materials")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = "dental_procedure_material"
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="dental_material_qty_positive")]


class ProcedureAmendment(UUIDModel):
    record = models.ForeignKey(ProcedureRecord, on_delete=models.PROTECT, related_name="amendments")
    field_name = models.CharField(max_length=40)
    original_text = models.TextField(blank=True)
    amended_text = models.TextField()
    reason = models.CharField(max_length=255)
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dental_procedure_amendment"
        ordering = ["created_at"]


# ===========================================================================
# Imaging (ADR 0007): bytes on disk, metadata here
# ===========================================================================
class DentalImage(UUIDModel):
    class Kind(models.TextChoices):
        PERIAPICAL = "periapical", "Periapical radiograph"
        BITEWING = "bitewing", "Bitewing radiograph"
        PANORAMIC = "panoramic", "Panoramic radiograph (OPG)"
        CEPHALOMETRIC = "cephalometric", "Cephalometric image"
        INTRAORAL_PHOTO = "intraoral_photo", "Intraoral photograph"
        EXTRAORAL_PHOTO = "extraoral_photo", "Extraoral photograph"
        CBCT = "cbct", "CBCT export (picture only)"
        OTHER = "other", "Other clinical image"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        WITHDRAWN = "withdrawn", "Withdrawn"

    EDITABLE = ("kind", "captured_at", "teeth", "region", "description", "referring_dentist_id")

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="dental_images")
    visit = models.ForeignKey(Visit, null=True, blank=True, on_delete=models.PROTECT, related_name="dental_images")
    encounter = models.ForeignKey(DentalEncounter, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="images")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    captured_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    referring_dentist = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    teeth = ArrayField(models.PositiveSmallIntegerField(), default=list, blank=True)
    region = models.CharField(max_length=12, blank=True)
    description = models.CharField(max_length=255, blank=True)
    original_name = models.CharField(max_length=120)
    content_type = models.CharField(max_length=40)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    storage_key = models.CharField(max_length=80, unique=True)
    preview_key = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    withdrawn_reason = models.CharField(max_length=255, blank=True)
    replaces = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="replaced_by")

    class Meta:
        db_table = "dental_image"
        ordering = ["-uploaded_at"]
        indexes = [models.Index(fields=["patient", "-uploaded_at"], name="dental_image_patient_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(status="active", withdrawn_at__isnull=True)
                                   | (Q(status="withdrawn", withdrawn_at__isnull=False) & ~Q(withdrawn_reason="")),
                                   name="dental_image_withdrawn_consistent"),
        ]


class DentalImageChange(models.Model):
    id = models.BigAutoField(primary_key=True)
    image = models.ForeignKey(DentalImage, on_delete=models.PROTECT, related_name="changes")
    field_name = models.CharField(max_length=40)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    reason = models.CharField(max_length=255)
    changed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dental_image_change"
        ordering = ["-changed_at", "-id"]


# ===========================================================================
# Recalls and follow-ups
# ===========================================================================
class Recall(TimestampedModel):
    class Kind(models.TextChoices):
        POST_OP = "post_op", "Post-operative review"
        RCT_CONTINUATION = "rct_continuation", "Root canal treatment, next session"
        CROWN_BRIDGE = "crown_bridge", "Crown or bridge fitting"
        PERIO_REVIEW = "perio_review", "Periodontal review"
        ORTHO_ADJUSTMENT = "ortho_adjustment", "Orthodontic adjustment"
        PREVENTIVE = "preventive", "Preventive recall"
        OTHER = "other", "Other follow-up"

    class Status(models.TextChoices):
        DUE = "due", "Due"
        BOOKED = "booked", "Booked"
        COMPLETED = "completed", "Attended"
        POSTPONED = "postponed", "Postponed"
        DECLINED = "declined", "Declined by the patient"
        UNREACHABLE = "unreachable", "Could not be reached"
        CANCELLED = "cancelled", "Cancelled"

    OPEN = (Status.DUE, Status.BOOKED, Status.POSTPONED)

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="dental_recalls")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    due_date = models.DateField()
    note = models.CharField(max_length=255, blank=True)
    source_procedure = models.ForeignKey(ProcedureRecord, null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="recalls")
    source_encounter = models.ForeignKey(DentalEncounter, null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="recalls")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DUE)
    appointment = models.ForeignKey(Appointment, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="dental_recalls")
    closed_reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "dental_recall"
        ordering = ["due_date"]
        indexes = [models.Index(fields=["status", "due_date"], name="dental_recall_due_idx"),
                   models.Index(fields=["patient", "due_date"], name="dental_recall_patient_idx")]
        constraints = [models.CheckConstraint(condition=~Q(status="booked") | Q(appointment__isnull=False),
                                              name="dental_recall_booked_has_appointment")]


class RecallContact(models.Model):
    class Outcome(models.TextChoices):
        REACHED = "reached", "Spoke to the patient"
        NO_ANSWER = "no_answer", "No answer"
        WRONG_NUMBER = "wrong_number", "Wrong or unavailable number"
        MESSAGE_LEFT = "message_left", "Message left"

    id = models.BigAutoField(primary_key=True)
    recall = models.ForeignKey(Recall, on_delete=models.PROTECT, related_name="contacts")
    outcome = models.CharField(max_length=14, choices=Outcome.choices)
    note = models.CharField(max_length=255, blank=True)
    contacted_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    contacted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dental_recall_contact"
        ordering = ["-contacted_at", "-id"]


# ===========================================================================
# Dental laboratory cases
# ===========================================================================
class DentalLabCase(TimestampedModel):
    class CaseType(models.TextChoices):
        CROWN = "crown", "Crown"
        BRIDGE = "bridge", "Bridge"
        DENTURE = "denture", "Denture (complete or partial)"
        VENEER = "veneer", "Veneer"
        ORTHO_APPLIANCE = "ortho_appliance", "Orthodontic appliance"
        REPAIR = "repair", "Repair or reline"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        IN_PROGRESS = "in_progress", "In progress"
        READY = "ready", "Ready for fitting"
        DELIVERED = "delivered", "Delivered to the patient"
        CANCELLED = "cancelled", "Cancelled"

    OPEN = (Status.REQUESTED, Status.IN_PROGRESS, Status.READY)

    number = models.CharField(max_length=20, unique=True)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="dental_lab_cases")
    plan_item = models.ForeignKey(TreatmentPlanItem, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="lab_cases")
    case_type = models.CharField(max_length=16, choices=CaseType.choices)
    teeth = ArrayField(models.PositiveSmallIntegerField(), default=list, blank=True)
    shade = models.CharField(max_length=30, blank=True)
    instructions = models.TextField()
    technician = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="dental_lab_cases")
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED)
    requested_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "dental_lab_case"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["technician", "status"], name="dental_labcase_tech_idx")]


class DentalLabCaseEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    case = models.ForeignKey(DentalLabCase, on_delete=models.PROTECT, related_name="events")
    status = models.CharField(max_length=12, choices=DentalLabCase.Status.choices)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dental_lab_case_event"
        ordering = ["created_at", "id"]



# ===========================================================================
# Orthodontics (module "orthodontics"). Starter vocabulary pending clinical review (R-15).
# ===========================================================================
class OrthoAssessment(Versioned, TimestampedModel):
    """The orthodontic assessment recorded in a dental examination. Editable while that examination is a draft."""

    class Angle(models.TextChoices):
        CLASS_I = "class_i", "Class I"
        CLASS_II = "class_ii", "Class II"
        CLASS_III = "class_iii", "Class III"
        NOT_ASSESSABLE = "not_assessable", "Cannot be assessed"

    class Incisor(models.TextChoices):
        CLASS_I = "class_i", "Class I"
        CLASS_II_1 = "class_ii_div1", "Class II division 1"
        CLASS_II_2 = "class_ii_div2", "Class II division 2"
        CLASS_III = "class_iii", "Class III"
        NOT_ASSESSABLE = "not_assessable", "Cannot be assessed"

    class Severity(models.TextChoices):
        NONE = "none", "None"
        MILD = "mild", "Mild"
        MODERATE = "moderate", "Moderate"
        SEVERE = "severe", "Severe"

    class Skeletal(models.TextChoices):
        CLASS_I = "class_i", "Class I"
        CLASS_II = "class_ii", "Class II"
        CLASS_III = "class_iii", "Class III"
        NOT_ASSESSED = "not_assessed", "Not assessed"

    class Profile(models.TextChoices):
        STRAIGHT = "straight", "Straight"
        CONVEX = "convex", "Convex"
        CONCAVE = "concave", "Concave"
        NOT_ASSESSED = "not_assessed", "Not assessed"

    class Hygiene(models.TextChoices):
        GOOD = "good", "Good"
        FAIR = "fair", "Fair"
        POOR = "poor", "Poor"

    TEXT_FIELDS = ("midline_upper", "midline_lower", "crossbite", "other_findings", "habits", "tmj",
                   "problem_list", "objectives", "treatment_options", "extractions_planned", "notes")
    CHOICE_FIELDS = {"molar_right": Angle, "molar_left": Angle, "canine_right": Angle, "canine_left": Angle,
                     "incisor_relationship": Incisor, "crowding_upper": Severity, "crowding_lower": Severity,
                     "spacing_upper": Severity, "spacing_lower": Severity, "skeletal_pattern": Skeletal,
                     "facial_profile": Profile, "oral_hygiene": Hygiene}

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="ortho_assessments")
    encounter = models.OneToOneField(DentalEncounter, on_delete=models.PROTECT, related_name="ortho_assessment")
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    molar_right = models.CharField(max_length=16, choices=Angle.choices, blank=True)
    molar_left = models.CharField(max_length=16, choices=Angle.choices, blank=True)
    canine_right = models.CharField(max_length=16, choices=Angle.choices, blank=True)
    canine_left = models.CharField(max_length=16, choices=Angle.choices, blank=True)
    incisor_relationship = models.CharField(max_length=16, choices=Incisor.choices, blank=True)
    # Millimetres; a negative overbite is an open bite, a negative overjet a reverse overjet.
    overjet_mm = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    overbite_mm = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    crowding_upper = models.CharField(max_length=10, choices=Severity.choices, blank=True)
    crowding_lower = models.CharField(max_length=10, choices=Severity.choices, blank=True)
    spacing_upper = models.CharField(max_length=10, choices=Severity.choices, blank=True)
    spacing_lower = models.CharField(max_length=10, choices=Severity.choices, blank=True)
    midline_upper = models.CharField(max_length=80, blank=True)
    midline_lower = models.CharField(max_length=80, blank=True)
    crossbite = models.CharField(max_length=255, blank=True)
    other_findings = models.TextField(blank=True)  # impacted, missing, rotated teeth...
    skeletal_pattern = models.CharField(max_length=14, choices=Skeletal.choices, blank=True)
    facial_profile = models.CharField(max_length=14, choices=Profile.choices, blank=True)
    habits = models.CharField(max_length=255, blank=True)
    tmj = models.CharField(max_length=255, blank=True)
    oral_hygiene = models.CharField(max_length=6, choices=Hygiene.choices, blank=True)
    problem_list = models.TextField(blank=True)
    objectives = models.TextField(blank=True)
    treatment_options = models.TextField(blank=True)
    extractions_planned = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "dental_ortho_assessment"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(overjet_mm__isnull=True) | Q(overjet_mm__gte=-20, overjet_mm__lte=20),
                                   name="ortho_overjet_range"),
            models.CheckConstraint(condition=Q(overbite_mm__isnull=True) | Q(overbite_mm__gte=-20, overbite_mm__lte=20),
                                   name="ortho_overbite_range"),
        ]


class OrthoCase(Versioned, TimestampedModel):
    """A course of orthodontic treatment, from planning through active treatment and retention."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        ACTIVE = "active", "Active treatment"
        RETENTION = "retention", "Retention"
        COMPLETED = "completed", "Completed"
        DISCONTINUED = "discontinued", "Discontinued"

    class Appliance(models.TextChoices):
        FIXED_METAL = "fixed_metal", "Fixed braces, metal brackets"
        FIXED_CERAMIC = "fixed_ceramic", "Fixed braces, ceramic brackets"
        SELF_LIGATING = "self_ligating", "Fixed braces, self-ligating brackets"
        ALIGNERS = "aligners", "Clear aligners"
        REMOVABLE = "removable", "Removable appliance"
        FUNCTIONAL = "functional", "Functional appliance"
        OTHER = "other", "Other appliance"

    class Arches(models.TextChoices):
        BOTH = "both", "Upper and lower"
        UPPER = "upper", "Upper only"
        LOWER = "lower", "Lower only"

    class Billing(models.TextChoices):
        PACKAGE = "package", "Package price, paid in instalments"
        PER_VISIT = "per_visit", "Charged per visit"

    class Retainer(models.TextChoices):
        NONE = "none", "None"
        BONDED = "bonded", "Bonded (fixed) retainer"
        HAWLEY = "hawley", "Removable Hawley retainer"
        CLEAR = "clear", "Removable clear retainer"
        OTHER = "other", "Other retainer"

    OPEN = (Status.PLANNED, Status.ACTIVE, Status.RETENTION)
    EDITABLE = ("orthodontist_id", "appliance", "arches", "objectives", "expected_months", "retainer_upper",
                "retainer_lower", "retention_review_months", "notes")

    number = models.CharField(max_length=20, unique=True)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="ortho_cases")
    assessment = models.ForeignKey(OrthoAssessment, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="cases")
    plan = models.ForeignKey(TreatmentPlan, null=True, blank=True, on_delete=models.PROTECT, related_name="ortho_cases")
    orthodontist = models.ForeignKey(User, on_delete=models.PROTECT, related_name="ortho_cases")
    appliance = models.CharField(max_length=16, choices=Appliance.choices)
    arches = models.CharField(max_length=6, choices=Arches.choices, default=Arches.BOTH)
    objectives = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    expected_months = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PLANNED)
    started_on = models.DateField(null=True, blank=True)
    debonded_on = models.DateField(null=True, blank=True)
    closed_on = models.DateField(null=True, blank=True)
    closed_reason = models.CharField(max_length=255, blank=True)
    retainer_upper = models.CharField(max_length=8, choices=Retainer.choices, blank=True)
    retainer_lower = models.CharField(max_length=8, choices=Retainer.choices, blank=True)
    retention_review_months = models.PositiveSmallIntegerField(null=True, blank=True)
    billing_mode = models.CharField(max_length=10, choices=Billing.choices)
    package_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    deposit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    per_visit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "dental_ortho_case"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["patient"], condition=Q(status__in=["planned", "active", "retention"]),
                                    name="ortho_one_open_case_per_patient"),
            models.CheckConstraint(condition=(Q(billing_mode="package", package_price__isnull=False,
                                                package_price__gte=0, deposit__gte=0,
                                                deposit__lte=models.F("package_price"))
                                              | Q(billing_mode="per_visit", per_visit_price__isnull=False,
                                                  per_visit_price__gte=0)),
                                   name="ortho_case_billing_consistent"),
            models.CheckConstraint(condition=Q(expected_months__isnull=True)
                                   | Q(expected_months__gte=1, expected_months__lte=96),
                                   name="ortho_case_expected_months"),
            models.CheckConstraint(condition=~Q(status__in=["completed", "discontinued"]) | Q(closed_on__isnull=False),
                                   name="ortho_case_closed_has_date"),
        ]


class OrthoVisit(UUIDModel):
    """What was done at one orthodontic appointment: wires, elastics, aligner number, breakages, hygiene."""

    class Kind(models.TextChoices):
        RECORDS = "records", "Records (photos, X-rays, models)"
        BONDING = "bonding", "Braces or appliance fitted"
        ADJUSTMENT = "adjustment", "Adjustment"
        ALIGNER = "aligner", "Aligner check or change"
        EMERGENCY = "emergency", "Emergency (breakage, discomfort)"
        DEBOND = "debond", "Braces removed"
        RETAINER_FIT = "retainer_fit", "Retainer fitted"
        RETENTION_REVIEW = "retention_review", "Retention review"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        RECORDED = "recorded", "Recorded"
        ENTERED_IN_ERROR = "entered_in_error", "Entered in error"

    case = models.ForeignKey(OrthoCase, on_delete=models.PROTECT, related_name="visits")
    visit = models.ForeignKey(Visit, on_delete=models.PROTECT, related_name="ortho_visits")
    encounter = models.ForeignKey(DentalEncounter, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="ortho_visits")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    upper_wire = models.CharField(max_length=60, blank=True)
    lower_wire = models.CharField(max_length=60, blank=True)
    elastics = models.CharField(max_length=120, blank=True)
    aligner_number = models.PositiveSmallIntegerField(null=True, blank=True)
    breakages = models.CharField(max_length=255, blank=True)
    oral_hygiene = models.CharField(max_length=6, choices=OrthoAssessment.Hygiene.choices, blank=True)
    compliance = models.CharField(max_length=6, choices=OrthoAssessment.Hygiene.choices, blank=True)
    notes = models.TextField(blank=True)
    next_interval_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    performed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    # Per-visit billing: the case's per-visit price at the time, or null when this visit is not charged.
    charge = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    no_charge_reason = models.CharField(max_length=255, blank=True)
    # Either billing mode: an additional charge, e.g. a lost retainer or broken appliance.
    extra_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    extra_charge_reason = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECORDED)
    voided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "dental_ortho_visit"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["case", "-created_at"], name="dental_ortho_visit_case_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(charge__isnull=True) | Q(charge__gte=0), name="ortho_visit_charge"),
            models.CheckConstraint(condition=Q(extra_charge=0) | (Q(extra_charge__gt=0) & ~Q(extra_charge_reason="")),
                                   name="ortho_visit_extra_has_reason"),
            models.CheckConstraint(condition=Q(status="recorded")
                                   | (Q(status="entered_in_error", voided_at__isnull=False) & ~Q(void_reason="")),
                                   name="ortho_visit_void_consistent"),
            models.CheckConstraint(condition=Q(next_interval_weeks__isnull=True)
                                   | Q(next_interval_weeks__gte=1, next_interval_weeks__lte=52),
                                   name="ortho_visit_interval"),
        ]


class OrthoInstalment(TimestampedModel):
    """One scheduled payment of a package. Billing state comes from the invoice line that charged it."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CANCELLED = "cancelled", "Cancelled"

    case = models.ForeignKey(OrthoCase, on_delete=models.PROTECT, related_name="instalments")
    sequence = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=60)
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    cancelled_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "dental_ortho_instalment"
        ordering = ["case", "sequence"]
        indexes = [models.Index(fields=["status", "due_date"], name="dental_ortho_inst_due_idx")]
        constraints = [
            models.UniqueConstraint(fields=["case", "sequence"], name="ortho_instalment_sequence_unique"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="ortho_instalment_amount_positive"),
            models.CheckConstraint(condition=Q(status="scheduled") | ~Q(cancelled_reason=""),
                                   name="ortho_instalment_cancel_reason"),
        ]


class OrthoCaseEvent(models.Model):
    """Status changes and price revisions of a case, with who and why."""

    id = models.BigAutoField(primary_key=True)
    case = models.ForeignKey(OrthoCase, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=30)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dental_ortho_case_event"
        ordering = ["created_at", "id"]
