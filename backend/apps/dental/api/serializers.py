"""Response shapes and input validation for the dental API. HTTP only: no business rules here."""

from __future__ import annotations

from rest_framework import serializers

from apps.scheduling.api import UserBrief

from .. import teeth
from ..models import (
    DentalDiagnosis, DentalDiagnosisTerm, DentalEncounter, DentalEncounterAmendment, DentalImage, DentalLabCase,
    DentalProcedure, DentalProfile, FindingType, MedicalRiskReview, PeriodontalExam, ProcedureAmendment,
    ProcedureRecord, Recall, ToothFinding, TreatmentPlan, TreatmentPlanItem, TreatmentPlanRevision,
)


class PatientMini(serializers.Serializer):
    """Name and MRN only: what a dental technician or a recall list may see."""

    id = serializers.UUIDField()
    mrn = serializers.CharField()
    full_name = serializers.CharField()


class LocationFields(serializers.Serializer):
    scope = serializers.ChoiceField(choices=list(teeth.SCOPES), required=False, allow_blank=True, default="")
    tooth = serializers.IntegerField(required=False, allow_null=True, default=None)
    surfaces = serializers.CharField(max_length=6, required=False, allow_blank=True, default="")
    region = serializers.CharField(max_length=12, required=False, allow_blank=True, default="")


def location_out(obj) -> dict:
    return {"scope": obj.scope, "tooth": obj.tooth, "surfaces": obj.surfaces, "region": obj.region,
            "label": obj.location_label}


# ---------------------------------------------------------------------------
# Catalogues
# ---------------------------------------------------------------------------
class FindingTypeSerializer(serializers.ModelSerializer):
    code = serializers.SlugField(max_length=40)

    class Meta:
        model = FindingType
        fields = ["id", "code", "name", "kind", "applies_to", "symbol", "color", "description", "is_active",
                  "sort_order", "review_status", "row_version"]
        read_only_fields = ["row_version"]

    def validate_color(self, value):
        import re

        if value and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise serializers.ValidationError("Use #rrggbb or leave empty.")
        return value


class DiagnosisTermSerializer(serializers.ModelSerializer):
    class Meta:
        model = DentalDiagnosisTerm
        fields = ["id", "code_system", "code", "term", "category", "source_version", "is_active", "review_status",
                  "row_version"]
        read_only_fields = ["row_version"]
        validators = []  # uniqueness is checked by the service with a clear message


class ProcedureSerializer(serializers.ModelSerializer):
    default_materials = serializers.SerializerMethodField()
    code = serializers.CharField(max_length=30)

    class Meta:
        model = DentalProcedure
        fields = ["id", "code", "name", "category", "description", "default_minutes", "price", "tax_rate", "is_active",
                  "tooth_requirement", "surfaces_allowed", "consumes_stock", "typical_sessions", "billing_mode",
                  "follow_up_kind", "follow_up_days", "performer_roles", "review_status", "default_materials",
                  "row_version"]
        read_only_fields = ["row_version"]

    def get_default_materials(self, obj):
        return [{"item_id": str(m.item_id), "item": str(m.item), "unit": m.item.unit, "quantity": str(m.quantity)}
                for m in obj.default_materials.all()]

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Cannot be negative.")
        return value

    def validate_performer_roles(self, value):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise serializers.ValidationError("A list of role codes.")
        return value


# ---------------------------------------------------------------------------
# Patient level
# ---------------------------------------------------------------------------
class ProfileSerializer(serializers.ModelSerializer):
    updated_by = UserBrief(read_only=True)

    class Meta:
        model = DentalProfile
        fields = ["id", *DentalProfile.FIELDS, "updated_by", "updated_at", "row_version"]
        read_only_fields = ["id", "updated_by", "updated_at", "row_version"]


class RiskReviewSerializer(serializers.ModelSerializer):
    reviewed_by = UserBrief(read_only=True)

    class Meta:
        model = MedicalRiskReview
        fields = ["id", "encounter", "reviewed_by", "reviewed_at", "answers", "allergies_reviewed",
                  "medications_reviewed", "notes", "changed_since_previous"]


class RiskReviewInput(serializers.Serializer):
    answers = serializers.DictField()
    allergies_reviewed = serializers.BooleanField(default=False)
    medications_reviewed = serializers.BooleanField(default=False)
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    encounter_id = serializers.UUIDField(required=False, allow_null=True)


# ---------------------------------------------------------------------------
# Examination
# ---------------------------------------------------------------------------
class DiagnosisSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()
    recorded_by = UserBrief(read_only=True)

    class Meta:
        model = DentalDiagnosis
        fields = ["id", "encounter", "term", "code_system", "code", "term_text", "source_version", "certainty", "status",
                  "notes", "location", "recorded_by", "created_at", "resolved_at", "resolution_note"]

    def get_location(self, obj):
        return location_out(obj)


class DiagnosisInput(LocationFields):
    term_id = serializers.UUIDField()
    certainty = serializers.ChoiceField(choices=DentalDiagnosis.Certainty.choices, default="confirmed")
    status = serializers.ChoiceField(choices=[("active", "Active"), ("historical", "Historical")], default="active")
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class FindingSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()
    finding_type = serializers.SerializerMethodField()
    recorded_by = UserBrief(read_only=True)
    resolved_by = UserBrief(read_only=True)
    voided_by = UserBrief(read_only=True)
    encounter_signed_at = serializers.DateTimeField(source="encounter.signed_at", read_only=True)
    diagnosis = serializers.SerializerMethodField()

    class Meta:
        model = ToothFinding
        fields = ["id", "encounter", "encounter_signed_at", "location", "finding_type", "is_existing_work", "note",
                  "diagnosis", "procedure", "recorded_by", "recorded_at", "resolved_at", "resolved_in", "resolved_by",
                  "resolution_note", "voided_at", "voided_by", "void_reason"]

    def get_location(self, obj):
        return location_out(obj)

    def get_finding_type(self, obj):
        t = obj.finding_type
        return {"id": str(t.pk), "code": t.code, "name": t.name, "kind": t.kind, "symbol": t.symbol, "color": t.color}

    def get_diagnosis(self, obj):
        d = obj.diagnosis
        return {"id": str(d.pk), "code": d.code, "term": d.term_text} if d else None


class FindingInput(LocationFields):
    finding_type_id = serializers.UUIDField()
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    diagnosis_id = serializers.UUIDField(required=False, allow_null=True)


class AmendmentSerializer(serializers.ModelSerializer):
    author = UserBrief(read_only=True)

    class Meta:
        model = DentalEncounterAmendment
        fields = ["id", "field_name", "original_text", "amended_text", "reason", "author", "created_at"]


class EncounterListSerializer(serializers.ModelSerializer):
    dentist = UserBrief(read_only=True)
    diagnoses = serializers.SerializerMethodField()

    class Meta:
        model = DentalEncounter
        fields = ["id", "visit", "patient", "dentist", "status", "chief_complaint", "signed_at", "created_at",
                  "diagnoses"]

    def get_diagnoses(self, obj):
        return [f"{d.code} {d.term_text} ({d.location_label})" for d in obj.diagnoses.all() if not d.is_removed]


class EncounterSerializer(serializers.ModelSerializer):
    dentist = UserBrief(read_only=True)
    patient = serializers.SerializerMethodField()
    diagnoses = serializers.SerializerMethodField()
    amendments = AmendmentSerializer(many=True, read_only=True)
    findings = serializers.SerializerMethodField()
    risk_review = RiskReviewSerializer(read_only=True)
    visit_status = serializers.CharField(source="visit.status", read_only=True)
    procedures = serializers.SerializerMethodField()
    prescriptions = serializers.SerializerMethodField()
    has_periodontal = serializers.SerializerMethodField()

    class Meta:
        model = DentalEncounter
        fields = ["id", "visit", "visit_status", "patient", "dentist", "status", "version", *DentalEncounter.NOTE_FIELDS,
                  *DentalEncounter.STRUCTURED_FIELDS, "signed_at", "created_at", "updated_at", "risk_review",
                  "diagnoses", "findings", "amendments", "procedures", "prescriptions", "has_periodontal"]

    def get_patient(self, obj):
        from apps.scheduling.api import PatientBrief

        return PatientBrief(obj.patient).data

    def get_diagnoses(self, obj):
        return DiagnosisSerializer([d for d in obj.diagnoses.all() if not d.is_removed], many=True).data

    def get_findings(self, obj):
        return FindingSerializer(obj.findings.all(), many=True).data

    def get_procedures(self, obj):
        return ProcedureRecordListSerializer(obj.procedures.all(), many=True).data

    def get_prescriptions(self, obj):
        from apps.clinical.api import PrescriptionSerializer

        return PrescriptionSerializer(obj.prescriptions.all(), many=True).data

    def get_has_periodontal(self, obj):
        return obj.periodontal_exams.exists()


class EncounterInput(serializers.Serializer):
    version = serializers.IntegerField()
    pain_present = serializers.BooleanField(required=False, allow_null=True)
    pain_teeth = serializers.ListField(child=serializers.IntegerField(), required=False)
    pain_severity = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=10)
    pain_pattern = serializers.ChoiceField(choices=DentalEncounter.PainPattern.choices, required=False, allow_blank=True)
    pain_sensitivity = serializers.ListField(child=serializers.CharField(max_length=8), required=False)
    mouth_opening_mm = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=90)
    follow_up_date = serializers.DateField(required=False, allow_null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in DentalEncounter.NOTE_FIELDS:
            limit = DentalEncounter._meta.get_field(name).max_length or 20000
            self.fields[name] = serializers.CharField(required=False, allow_blank=True, max_length=limit)


class AmendInput(serializers.Serializer):
    field_name = serializers.ChoiceField(choices=DentalEncounter.NOTE_FIELDS)
    text = serializers.CharField(max_length=20000)
    reason = serializers.CharField(max_length=255)


# ---------------------------------------------------------------------------
# Periodontal
# ---------------------------------------------------------------------------
class PerioExamSerializer(serializers.ModelSerializer):
    examiner = UserBrief(read_only=True)
    teeth = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    encounter_status = serializers.CharField(source="encounter.status", read_only=True)

    class Meta:
        model = PeriodontalExam
        fields = ["id", "patient", "encounter", "encounter_status", "examiner", "protocol", "notes", "version",
                  "created_at", "updated_at", "teeth", "summary"]

    def get_teeth(self, obj):
        from ..services.perio import cal

        sites: dict[int, dict] = {}
        for s in obj.sites.all():
            sites.setdefault(s.tooth, {})[s.site] = {
                "probing_depth_mm": s.probing_depth_mm, "gingival_margin_mm": s.gingival_margin_mm,
                "cal_mm": cal(s), "bleeding": s.bleeding, "plaque": s.plaque, "suppuration": s.suppuration,
                "not_measured": s.not_measured, "not_measured_reason": s.not_measured_reason}
        return [{"tooth": t.tooth, "missing": t.missing, "excluded": t.excluded, "exclusion_reason": t.exclusion_reason,
                 "implant": t.implant, "mobility": t.mobility, "furcation": t.furcation, "notes": t.notes,
                 "furcation_applies": teeth.can_have_furcation(t.tooth), "sites": sites.get(t.tooth, {})}
                for t in obj.teeth.all()]

    def get_summary(self, obj):
        from ..services.perio import summary

        return summary(obj)


class PerioInput(serializers.Serializer):
    version = serializers.IntegerField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    teeth = serializers.ListField(child=serializers.DictField(), required=False, default=list)


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------
class PlanItemSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()
    procedure = serializers.SerializerMethodField()
    diagnosis = serializers.SerializerMethodField()
    assigned_dentist = UserBrief(read_only=True)
    appointments = serializers.SerializerMethodField()
    sessions_done = serializers.SerializerMethodField()

    class Meta:
        model = TreatmentPlanItem
        fields = ["id", "sequence", "procedure", "location", "diagnosis", "priority", "sessions_planned",
                  "sessions_done", "estimated_minutes", "estimated_fee", "assigned_dentist", "notes", "status",
                  "decision_at", "cancel_reason", "appointments"]

    def get_location(self, obj):
        return location_out(obj)

    def get_procedure(self, obj):
        p = obj.procedure
        return {"id": str(p.pk), "code": p.code, "name": p.name, "category": p.category}

    def get_diagnosis(self, obj):
        d = obj.diagnosis
        return {"id": str(d.pk), "code": d.code, "term": d.term_text} if d else None

    def get_appointments(self, obj):
        return [{"id": str(a.pk), "scheduled_at": a.scheduled_at, "status": a.status} for a in obj.appointments.all()]

    def get_sessions_done(self, obj):
        return sum(1 for r in obj.procedures.all() if r.status in ("completed", "session_completed"))


class PlanSerializer(serializers.ModelSerializer):
    created_by = UserBrief(read_only=True)
    items = PlanItemSerializer(many=True, read_only=True)
    diagnoses = serializers.SerializerMethodField()
    estimated_total = serializers.SerializerMethodField()
    patient = serializers.SerializerMethodField()

    class Meta:
        model = TreatmentPlan
        fields = ["id", "number", "patient", "created_by", "encounter", "title", "clinical_reason", "diagnoses",
                  "status", "revision", "review_date", "presented_at", "decision_at", "decision_note", "cancel_reason",
                  "notes", "created_at", "updated_at", "estimated_total", "items", "row_version"]

    def get_patient(self, obj):
        from apps.scheduling.api import PatientBrief

        return PatientBrief(obj.patient).data

    def get_diagnoses(self, obj):
        return [{"id": str(d.pk), "code": d.code, "term": d.term_text, "location": d.location_label}
                for d in obj.diagnoses.all()]

    def get_estimated_total(self, obj):
        from ..services.plans import estimated_total

        return str(estimated_total(obj))


class PlanListSerializer(serializers.ModelSerializer):
    created_by = UserBrief(read_only=True)
    estimated_total = serializers.SerializerMethodField()
    item_counts = serializers.SerializerMethodField()

    class Meta:
        model = TreatmentPlan
        fields = ["id", "number", "title", "status", "created_by", "created_at", "presented_at", "review_date",
                  "estimated_total", "item_counts"]

    def get_estimated_total(self, obj):
        from ..services.plans import estimated_total

        return str(estimated_total(obj))

    def get_item_counts(self, obj):
        counts: dict[str, int] = {}
        for i in obj.items.all():
            counts[i.status] = counts.get(i.status, 0) + 1
        return counts


class PlanInput(serializers.Serializer):
    title = serializers.CharField(max_length=150)
    clinical_reason = serializers.CharField(max_length=5000, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=5000, required=False, allow_blank=True, default="")
    review_date = serializers.DateField(required=False, allow_null=True)
    encounter_id = serializers.UUIDField(required=False, allow_null=True)
    diagnosis_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class PlanItemInput(LocationFields):
    procedure_id = serializers.UUIDField(required=False)
    diagnosis_id = serializers.UUIDField(required=False, allow_null=True)
    priority = serializers.ChoiceField(choices=TreatmentPlanItem.Priority.choices, required=False)
    sequence = serializers.IntegerField(required=False, min_value=1, max_value=999)
    sessions_planned = serializers.IntegerField(required=False, min_value=1, max_value=20)
    estimated_minutes = serializers.IntegerField(required=False, min_value=5, max_value=480)
    estimated_fee = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True,
                                             min_value=0)
    assigned_dentist_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class RevisionSerializer(serializers.ModelSerializer):
    created_by = UserBrief(read_only=True)

    class Meta:
        model = TreatmentPlanRevision
        fields = ["id", "revision", "reason", "snapshot", "created_by", "created_at"]


# ---------------------------------------------------------------------------
# Procedures
# ---------------------------------------------------------------------------
class ProcedureRecordListSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()
    procedure = serializers.SerializerMethodField()
    performed_by = UserBrief(read_only=True)

    class Meta:
        model = ProcedureRecord
        fields = ["id", "number", "patient", "visit", "encounter", "plan_item", "procedure", "location", "performed_by",
                  "session_number", "status", "signed_at", "price", "created_at"]

    def get_location(self, obj):
        return location_out(obj)

    def get_procedure(self, obj):
        p = obj.procedure
        return {"id": str(p.pk), "code": p.code, "name": p.name, "category": p.category,
                "billing_mode": p.billing_mode}


class ProcedureAmendmentSerializer(serializers.ModelSerializer):
    author = UserBrief(read_only=True)

    class Meta:
        model = ProcedureAmendment
        fields = ["id", "field_name", "original_text", "amended_text", "reason", "author", "created_at"]


class ProcedureRecordSerializer(ProcedureRecordListSerializer):
    assisted_by = UserBrief(read_only=True)
    signed_by = UserBrief(read_only=True)
    created_by = UserBrief(read_only=True)
    materials = serializers.SerializerMethodField()
    amendments = ProcedureAmendmentSerializer(many=True, read_only=True)
    billed = serializers.SerializerMethodField()

    class Meta(ProcedureRecordListSerializer.Meta):
        fields = ProcedureRecordListSerializer.Meta.fields + [
            "assisted_by", "started_at", "completed_at", *ProcedureRecord.TEXT_FIELDS, "follow_up_days",
            "not_performed_reason", "signed_by", "tax_rate", "version", "created_by", "materials", "amendments",
            "billed"]

    def get_materials(self, obj):
        return [{"id": str(m.pk), "item_id": str(m.item_id), "item": str(m.item), "unit": m.item.unit,
                 "quantity": str(m.quantity), "note": m.note} for m in obj.materials.all()]

    def get_billed(self, obj):
        from apps.billing.models import InvoiceLine

        line = (InvoiceLine.objects.filter(source_type="dental_procedure", source_id=str(obj.pk), is_void=False)
                .select_related("invoice").first())
        return {"invoice_id": str(line.invoice_id), "invoice_number": line.invoice.number,
                "status": line.invoice.status} if line else None


class ProcedureRecordInput(LocationFields):
    procedure_id = serializers.UUIDField(required=False, allow_null=True)
    plan_item_id = serializers.UUIDField(required=False, allow_null=True)
    performed_by_id = serializers.UUIDField(required=False, allow_null=True)
    assisted_by_id = serializers.UUIDField(required=False, allow_null=True)
    started_at = serializers.DateTimeField(required=False, allow_null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ProcedureRecord.TEXT_FIELDS:
            limit = ProcedureRecord._meta.get_field(name).max_length or 20000
            self.fields[name] = serializers.CharField(required=False, allow_blank=True, max_length=limit)


class ProcedureUpdateInput(ProcedureRecordInput):
    version = serializers.IntegerField()
    follow_up_days = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=730)


class MaterialInput(serializers.Serializer):
    item_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=3)
    note = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")


class SignProcedureInput(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=[c for c in ProcedureRecord.Status.choices if c[0] != "draft"])
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    create_recall = serializers.BooleanField(default=True)


class ProcedureAmendInput(serializers.Serializer):
    field_name = serializers.ChoiceField(choices=ProcedureRecord.TEXT_FIELDS)
    text = serializers.CharField(max_length=20000)
    reason = serializers.CharField(max_length=255)


# ---------------------------------------------------------------------------
# Imaging, recalls, laboratory cases
# ---------------------------------------------------------------------------
class ImageSerializer(serializers.ModelSerializer):
    uploaded_by = UserBrief(read_only=True)
    referring_dentist = UserBrief(read_only=True)
    withdrawn_by = UserBrief(read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    changes = serializers.SerializerMethodField()

    class Meta:
        model = DentalImage
        fields = ["id", "patient", "visit", "encounter", "kind", "kind_label", "captured_at", "uploaded_at",
                  "uploaded_by", "referring_dentist", "teeth", "region", "description", "original_name",
                  "content_type", "size_bytes", "sha256", "width", "height", "status", "withdrawn_at", "withdrawn_by",
                  "withdrawn_reason", "replaces", "changes"]

    def get_changes(self, obj):
        return [{"field": c.field_name, "old": c.old_value, "new": c.new_value, "reason": c.reason,
                 "by": c.changed_by.full_name, "at": c.changed_at} for c in obj.changes.all()]


class ImageMetaInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=DentalImage.Kind.choices, required=False)
    captured_at = serializers.DateTimeField(required=False, allow_null=True)
    teeth = serializers.ListField(child=serializers.IntegerField(), required=False)
    region = serializers.CharField(max_length=12, required=False, allow_blank=True)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    referring_dentist_id = serializers.UUIDField(required=False, allow_null=True)
    encounter_id = serializers.UUIDField(required=False, allow_null=True)
    replaces_id = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class RecallSerializer(serializers.ModelSerializer):
    patient = PatientMini(read_only=True)
    phone = serializers.CharField(source="patient.phone", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    appointment = serializers.SerializerMethodField()
    contacts = serializers.SerializerMethodField()
    note = serializers.SerializerMethodField()

    class Meta:
        model = Recall
        fields = ["id", "patient", "phone", "kind", "kind_label", "due_date", "note", "status", "appointment",
                  "closed_reason", "contacts", "created_at"]

    def get_note(self, obj):
        # The free-text note may hold clinical detail: only for people who can read dental records.
        user = self.context.get("request").user if self.context.get("request") else None
        return obj.note if user is not None and user.has_permissions(["dental.view"]) else ""

    def get_appointment(self, obj):
        a = obj.appointment
        return {"id": str(a.pk), "scheduled_at": a.scheduled_at, "status": a.status} if a else None

    def get_contacts(self, obj):
        return [{"outcome": c.outcome, "note": c.note, "by": c.contacted_by.full_name, "at": c.contacted_at}
                for c in obj.contacts.all()]


class RecallInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Recall.Kind.choices)
    due_date = serializers.DateField()
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    encounter_id = serializers.UUIDField(required=False, allow_null=True)


class LabCaseSerializer(serializers.ModelSerializer):
    patient = PatientMini(read_only=True)
    technician = UserBrief(read_only=True)
    requested_by = UserBrief(read_only=True)
    case_type_label = serializers.CharField(source="get_case_type_display", read_only=True)
    events = serializers.SerializerMethodField()

    class Meta:
        model = DentalLabCase
        fields = ["id", "number", "patient", "plan_item", "case_type", "case_type_label", "teeth", "shade",
                  "instructions", "technician", "due_date", "status", "requested_by", "delivered_at", "created_at",
                  "events"]

    def get_events(self, obj):
        return [{"status": e.status, "note": e.note, "by": e.actor.full_name, "at": e.created_at}
                for e in obj.events.all()]


class LabCaseInput(serializers.Serializer):
    case_type = serializers.ChoiceField(choices=DentalLabCase.CaseType.choices)
    teeth = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    shade = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    instructions = serializers.CharField(max_length=5000)
    technician_id = serializers.UUIDField(required=False, allow_null=True)
    due_date = serializers.DateField(required=False, allow_null=True)
    plan_item_id = serializers.UUIDField(required=False, allow_null=True)
