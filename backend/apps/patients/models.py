from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.core.models import TimestampedModel, UUIDModel
from apps.core.concurrency import Versioned


class Patient(Versioned, TimestampedModel):
    """
    Demographics only. Clinical information lives in the clinical, laboratory and pharmacy
    modules and is linked by patient ID. Ethiopian naming: given name, father's name,
    grandfather's name.
    """

    class Sex(models.TextChoices):
        FEMALE = "female", "Female"
        MALE = "male", "Male"

    class BloodGroup(models.TextChoices):
        UNKNOWN = "", "Unknown"
        A_POS = "A+", "A+"
        A_NEG = "A-", "A-"
        B_POS = "B+", "B+"
        B_NEG = "B-", "B-"
        AB_POS = "AB+", "AB+"
        AB_NEG = "AB-", "AB-"
        O_POS = "O+", "O+"
        O_NEG = "O-", "O-"

    mrn = models.CharField("medical record number", max_length=30, unique=True)
    first_name = models.CharField(max_length=60)
    middle_name = models.CharField("father's name", max_length=60, blank=True)
    last_name = models.CharField("grandfather's name", max_length=60, blank=True)
    sex = models.CharField(max_length=6, choices=Sex.choices)
    birth_date = models.DateField()
    birth_date_estimated = models.BooleanField(default=False)
    phone = models.CharField(max_length=15, blank=True)
    alt_phone = models.CharField(max_length=15, blank=True)
    region = models.CharField(max_length=60, blank=True)
    city = models.CharField(max_length=60, blank=True)
    subcity_woreda = models.CharField(max_length=60, blank=True)
    kebele = models.CharField(max_length=30, blank=True)
    house_number = models.CharField(max_length=30, blank=True)
    national_id = models.CharField(max_length=30, blank=True)
    blood_group = models.CharField(max_length=3, choices=BloodGroup.choices, blank=True)
    known_conditions = models.TextField("existing medical conditions", blank=True)
    past_history = models.TextField("previous illnesses and operations", blank=True)
    current_medications = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class InactiveKind(models.TextChoices):
        MOVED = "moved", "Moved away or transferred care"
        DECEASED = "deceased", "Deceased"
        OTHER = "other", "Other reason"

    # Why an unmerged record is inactive. Inactive records are kept in full and hidden from everyday search.
    inactive_kind = models.CharField(max_length=10, choices=InactiveKind.choices, blank=True)
    inactive_note = models.CharField(max_length=255, blank=True)
    date_of_death = models.DateField(null=True, blank=True)
    inactivated_at = models.DateTimeField(null=True, blank=True)
    inactivated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    # A duplicate record merged into another keeps its MRN (paper files may cite it) and points to the survivor.
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="merged_records")
    merged_at = models.DateTimeField(null=True, blank=True)
    merged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    merge_reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "patients_patient"
        ordering = ["first_name", "middle_name"]
        indexes = [
            GinIndex(fields=["first_name"], opclasses=["gin_trgm_ops"], name="patient_first_trgm"),
            GinIndex(fields=["middle_name"], opclasses=["gin_trgm_ops"], name="patient_middle_trgm"),
            GinIndex(fields=["last_name"], opclasses=["gin_trgm_ops"], name="patient_last_trgm"),
            models.Index(fields=["phone"], name="patient_phone_idx"),
            models.Index(fields=["birth_date"], name="patient_birth_idx"),
            models.Index(fields=["-created_at"], name="patient_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(sex__in=["female", "male"]), name="patient_sex_valid"),
            models.CheckConstraint(condition=models.Q(merged_into__isnull=True) | models.Q(is_active=False),
                                   name="patient_merged_is_inactive"),
            models.CheckConstraint(condition=~models.Q(inactive_kind="deceased") | models.Q(date_of_death__isnull=False),
                                   name="patient_deceased_has_date"),
            models.CheckConstraint(condition=models.Q(inactive_kind="") | models.Q(is_active=False),
                                   name="patient_inactive_kind_only_when_inactive"),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.mrn})"

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.middle_name, self.last_name) if p)


class EmergencyContact(UUIDModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="emergency_contacts")
    name = models.CharField(max_length=120)
    relationship = models.CharField(max_length=40, blank=True)
    phone = models.CharField(max_length=15)

    class Meta:
        db_table = "patients_emergency_contact"


class Allergy(TimestampedModel):
    class Severity(models.TextChoices):
        MILD = "mild", "Mild"
        MODERATE = "moderate", "Moderate"
        SEVERE = "severe", "Severe"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="allergies")
    substance = models.CharField(max_length=120)
    reaction = models.CharField(max_length=255, blank=True)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MODERATE)
    is_active = models.BooleanField(default=True)
    inactive_reason = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "patients_allergy"
        ordering = ["-is_active", "substance"]


class PatientChange(models.Model):
    """Readable history of demographic changes, shown in the chart. The audit log keeps the same facts."""

    id = models.BigAutoField(primary_key=True)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="changes")
    field = models.CharField(max_length=40)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "patients_change"
        ordering = ["-changed_at", "-id"]
        indexes = [models.Index(fields=["patient", "-changed_at"], name="patient_change_idx")]


class PatientAttachment(UUIDModel):
    """
    A scanned paper or photo kept with the patient's record: a referral letter from another facility, an
    outside laboratory or imaging report, a signed consent form. Stored in the database so the normal
    backup carries it. Never deleted (records must be kept); a wrong file is marked removed with a reason
    and is then no longer shown or downloadable.
    """

    class Kind(models.TextChoices):
        REFERRAL = "referral", "Referral letter from another facility"
        OUTSIDE_LAB = "outside_lab", "Outside laboratory result"
        IMAGING = "imaging", "X-ray, ultrasound or other imaging report"
        CONSENT = "consent", "Signed consent form"
        OTHER_CLINICAL = "other_clinical", "Other clinical document"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="attachments")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=120)
    document_date = models.DateField(null=True, blank=True)
    file_name = models.CharField(max_length=120)
    content_type = models.CharField(max_length=40)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    data = models.BinaryField(editable=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    removed_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "patients_attachment"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"], name="attachment_patient_idx")]
        constraints = [
            models.CheckConstraint(condition=models.Q(removed_at__isnull=True) | ~models.Q(removed_reason=""),
                                   name="attachment_removed_has_reason"),
        ]
