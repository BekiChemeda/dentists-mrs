from decimal import Decimal

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response

from apps.audit.services import record_event
from apps.core.api import PermissionedView, validated
from apps.core.permissions import AnyOf
from apps.scheduling.api import PatientBrief, UserBrief
from apps.scheduling.models import Visit

from . import services
from .models import (
    FREQUENCIES, GENERAL_APPEARANCE, Diagnosis, Encounter, IcdCode, InternalReferral, MedicalCertificate, NoteAmendment,
    Prescription, PrescriptionItem, Referral, VitalSigns,
)


class VitalSignsSerializer(serializers.ModelSerializer):
    recorded_by = UserBrief(read_only=True)
    interpretation = serializers.SerializerMethodField()

    class Meta:
        model = VitalSigns
        fields = ["id", "visit", "recorded_at", "recorded_by", "systolic", "diastolic", "temperature_c", "heart_rate",
                  "respiratory_rate", "spo2", "weight_kg", "height_cm", "bmi", "pain_score", "consciousness",
                  "on_oxygen", "chief_complaint", "complaint_duration", "general_appearance", "triage_to", "symptoms", "allergies_confirmed", "current_medications",
                  "observations", "notes", "interpretation"]

    def get_interpretation(self, obj):
        from django.utils import timezone

        from .vitals_reference import interpret

        values = {f: getattr(obj, f) for f in services.VITAL_FIELDS + ("consciousness", "on_oxygen")}
        return interpret(values, birth_date=obj.patient.birth_date, on=timezone.localtime(obj.recorded_at).date())


class VitalSignsInput(serializers.Serializer):
    systolic = serializers.IntegerField(required=False, allow_null=True, min_value=40, max_value=300)
    diastolic = serializers.IntegerField(required=False, allow_null=True, min_value=20, max_value=200)
    temperature_c = serializers.DecimalField(max_digits=4, decimal_places=1, required=False, allow_null=True,
                                             min_value=25, max_value=45)
    heart_rate = serializers.IntegerField(required=False, allow_null=True, min_value=20, max_value=300)
    respiratory_rate = serializers.IntegerField(required=False, allow_null=True, min_value=2, max_value=120)
    spo2 = serializers.IntegerField(required=False, allow_null=True, min_value=30, max_value=100)
    weight_kg = serializers.DecimalField(max_digits=5, decimal_places=1, required=False, allow_null=True,
                                         min_value=Decimal("0.3"), max_value=400)
    height_cm = serializers.DecimalField(max_digits=5, decimal_places=1, required=False, allow_null=True,
                                         min_value=20, max_value=250)
    pain_score = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=10)
    consciousness = serializers.ChoiceField(choices=VitalSigns.Consciousness.choices, required=False, allow_blank=True,
                                            default="")
    on_oxygen = serializers.BooleanField(required=False, allow_null=True, default=None)
    chief_complaint = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    complaint_duration = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    general_appearance = serializers.ChoiceField(choices=GENERAL_APPEARANCE, required=False, allow_blank=True, default="")
    triage_to = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    symptoms = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    allergies_confirmed = serializers.BooleanField(required=False, allow_null=True, default=None)
    current_medications = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    observations = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    priority = serializers.ChoiceField(choices=Visit.Priority.choices, required=False)


class IcdSerializer(serializers.ModelSerializer):
    class Meta:
        model = IcdCode
        fields = ["code", "title", "is_common"]


class DiagnosisSerializer(serializers.ModelSerializer):
    icd = IcdSerializer(read_only=True)

    class Meta:
        model = Diagnosis
        fields = ["id", "icd", "description", "kind", "certainty", "created_at"]


class AmendmentSerializer(serializers.ModelSerializer):
    author = UserBrief(read_only=True)

    class Meta:
        model = NoteAmendment
        fields = ["id", "field_name", "original_text", "amended_text", "reason", "author", "created_at"]


class PrescriptionItemSerializer(serializers.ModelSerializer):
    remaining = serializers.SerializerMethodField()
    unit = serializers.CharField(source="item.unit", read_only=True, default="")

    class Meta:
        model = PrescriptionItem
        fields = ["id", "item", "drug_name", "strength", "dosage_form", "dose", "route", "frequency", "duration_days",
                  "quantity", "quantity_dispensed", "remaining", "instructions", "warnings", "allergy_override_reason",
                  "unit"]

    def get_remaining(self, obj):
        return str(obj.quantity - obj.quantity_dispensed)


class ClinicianBrief(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    job_title = serializers.CharField()
    registration_number = serializers.CharField()


class PrescriptionSerializer(serializers.ModelSerializer):
    items = PrescriptionItemSerializer(many=True, read_only=True)
    prescriber = UserBrief(read_only=True)
    patient = PatientBrief(read_only=True)
    visit_id = serializers.UUIDField(source="encounter.visit_id", read_only=True)
    prescriber_details = ClinicianBrief(source="prescriber", read_only=True)

    class Meta:
        model = Prescription
        fields = ["id", "number", "encounter", "visit_id", "patient", "prescriber", "prescriber_details", "status",
                  "notes", "cancel_reason",
                  "controlled_class", "special_form_serial", "patient_weight_kg", "created_at", "items"]


class EncounterSerializer(serializers.ModelSerializer):
    doctor = UserBrief(read_only=True)
    doctor_details = ClinicianBrief(source="doctor", read_only=True)
    patient = PatientBrief(read_only=True)
    diagnoses = serializers.SerializerMethodField()
    amendments = AmendmentSerializer(many=True, read_only=True)
    prescriptions = PrescriptionSerializer(many=True, read_only=True)

    class Meta:
        model = Encounter
        fields = ["id", "visit", "patient", "doctor", "doctor_details", "status", "version", *Encounter.NOTE_FIELDS,
                  "follow_up_date",
                  "signed_at", "created_at", "updated_at", "diagnoses", "amendments", "prescriptions"]

    def get_diagnoses(self, obj):
        return DiagnosisSerializer([d for d in obj.diagnoses.all() if not d.is_removed], many=True).data


class EncounterListSerializer(serializers.ModelSerializer):
    doctor = UserBrief(read_only=True)
    diagnoses = serializers.SerializerMethodField()

    class Meta:
        model = Encounter
        fields = ["id", "visit", "doctor", "status", "chief_complaint", "signed_at", "created_at", "diagnoses"]

    def get_diagnoses(self, obj):
        return [d.description for d in obj.diagnoses.all() if not d.is_removed]


def _encounter_qs():
    return Encounter.objects.select_related("doctor", "patient").prefetch_related(
        Prefetch("diagnoses", queryset=Diagnosis.objects.select_related("icd")),
        Prefetch("amendments", queryset=NoteAmendment.objects.select_related("author")),
        Prefetch("prescriptions", queryset=Prescription.objects.select_related("prescriber", "patient", "encounter")
                 .prefetch_related("items__item")),
    )


# ---------------------------------------------------------------------------
class VitalsPreviewView(PermissionedView):
    """Interpret measurements before saving, so the nurse sees abnormal values while typing."""

    required_permissions = {"POST": ("triage.record",)}

    def post(self, request, visit_id):
        from django.utils import timezone

        from .vitals_reference import interpret

        visit = get_object_or_404(Visit.objects.select_related("patient"), pk=visit_id)
        data = validated(VitalSignsInput, request.data)
        return Response(interpret(data, birth_date=visit.patient.birth_date, on=timezone.localdate()))


class VitalsView(PermissionedView):
    required_permissions = {"GET": AnyOf(("clinical.view", "triage.record")), "POST": ("triage.record",)}

    def get(self, request, visit_id=None):
        qs = VitalSigns.objects.select_related("recorded_by", "patient")
        if visit_id:
            qs = qs.filter(visit_id=visit_id)
        elif patient := self.param_uuid("patient"):
            qs = qs.filter(patient_id=patient)
        else:
            return Response({"error": {"code": "validation_error", "message": "Give a visit or patient."}}, status=400)
        return self.paginate(qs, VitalSignsSerializer)

    def post(self, request, visit_id=None):
        visit = get_object_or_404(Visit, pk=visit_id)
        data = validated(VitalSignsInput, request.data)
        priority = data.pop("priority", None)
        vitals = services.record_vitals(self.ctx(), visit, data, priority=priority)
        return Response(VitalSignsSerializer(vitals).data, status=status.HTTP_201_CREATED)


class StartEncounterView(PermissionedView):
    required_permissions = {"POST": ("clinical.write",)}

    def post(self, request, visit_id):
        encounter = services.start_encounter(self.ctx(), get_object_or_404(Visit, pk=visit_id))
        return Response(EncounterSerializer(_encounter_qs().get(pk=encounter.pk)).data, status=status.HTTP_201_CREATED)


class EncounterListView(PermissionedView):
    required_permissions = {"GET": ("clinical.view",)}

    def get(self, request):
        qs = Encounter.objects.select_related("doctor").prefetch_related("diagnoses")
        if patient := self.param_uuid("patient"):
            qs = qs.filter(patient_id=patient)
        if visit := self.param_uuid("visit"):
            qs = qs.filter(visit_id=visit)
        if self.param_bool("mine"):
            qs = qs.filter(doctor=request.user)
        if st := request.query_params.get("status"):
            qs = qs.filter(status=st)
        return self.paginate(qs.order_by("-created_at"), EncounterListSerializer)


class EncounterInput(serializers.Serializer):
    version = serializers.IntegerField()
    follow_up_date = serializers.DateField(required=False, allow_null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in Encounter.NOTE_FIELDS:
            limit = Encounter._meta.get_field(name).max_length or 20000
            self.fields[name] = serializers.CharField(required=False, allow_blank=True, max_length=limit)
        self.fields["general_appearance"] = serializers.ChoiceField(choices=GENERAL_APPEARANCE, required=False,
                                                                    allow_blank=True)


class EncounterDetailView(PermissionedView):
    required_permissions = {"GET": ("clinical.view",), "PATCH": ("clinical.write",)}

    def get(self, request, pk):
        encounter = get_object_or_404(_encounter_qs(), pk=pk)
        record_event(self.ctx(), action="encounter.view", object_type="encounter", object_id=encounter.pk,
                     details={"patient": str(encounter.patient_id)})
        return Response(EncounterSerializer(encounter).data)

    def patch(self, request, pk):
        data = validated(EncounterInput, request.data)
        version = data.pop("version")
        services.update_encounter(self.ctx(), get_object_or_404(Encounter, pk=pk), data, version=version)
        return Response(EncounterSerializer(_encounter_qs().get(pk=pk)).data)


class SignEncounterView(PermissionedView):
    required_permissions = {"POST": ("clinical.write",)}

    def post(self, request, pk):
        services.sign_encounter(self.ctx(), get_object_or_404(Encounter, pk=pk))
        return Response(EncounterSerializer(_encounter_qs().get(pk=pk)).data)


class AmendInput(serializers.Serializer):
    field_name = serializers.ChoiceField(choices=Encounter.NOTE_FIELDS)
    text = serializers.CharField(max_length=20000)
    reason = serializers.CharField(max_length=255)


class AmendEncounterView(PermissionedView):
    required_permissions = {"POST": ("clinical.amend",)}

    def post(self, request, pk):
        data = validated(AmendInput, request.data)
        services.amend_encounter(self.ctx(), get_object_or_404(Encounter, pk=pk), **data)
        return Response(EncounterSerializer(_encounter_qs().get(pk=pk)).data, status=status.HTTP_201_CREATED)


class DiagnosisInput(serializers.Serializer):
    icd_code = serializers.CharField(max_length=10, required=False, allow_blank=True, default="")
    description = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    kind = serializers.ChoiceField(choices=Diagnosis.Kind.choices, default=Diagnosis.Kind.PRIMARY)
    certainty = serializers.ChoiceField(choices=Diagnosis.Certainty.choices, default=Diagnosis.Certainty.CONFIRMED)


class DiagnosisCreateView(PermissionedView):
    required_permissions = {"POST": ("clinical.write",)}

    def post(self, request, pk):
        data = validated(DiagnosisInput, request.data)
        dx = services.add_diagnosis(self.ctx(), get_object_or_404(Encounter, pk=pk), **data)
        return Response(DiagnosisSerializer(dx).data, status=status.HTTP_201_CREATED)


class DiagnosisRemoveView(PermissionedView):
    required_permissions = {"POST": ("clinical.write",)}

    def post(self, request, pk):
        services.remove_diagnosis(self.ctx(), get_object_or_404(Diagnosis, pk=pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


class IcdSearchView(PermissionedView):
    required_permissions = {"GET": AnyOf(("clinical.view", "reports.clinical"))}

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        qs = IcdCode.objects.all()
        if q:
            qs = qs.filter(Q(code__istartswith=q) | Q(title__icontains=q))
        else:
            qs = qs.filter(is_common=True)
        return Response(IcdSerializer(qs.order_by("-is_common", "code")[:30], many=True).data)


class RxItemInput(serializers.Serializer):
    item_id = serializers.UUIDField(required=False, allow_null=True)
    drug_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    dose = serializers.CharField(max_length=50)
    route = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    frequency = serializers.ChoiceField(choices=[(f, f) for f in FREQUENCIES])
    duration_days = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=365)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=3, min_value=Decimal("0.001"))
    instructions = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    allergy_override_reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class RxInput(serializers.Serializer):
    items = RxItemInput(many=True)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    special_form_serial = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    patient_weight_kg = serializers.DecimalField(max_digits=5, decimal_places=1, required=False, allow_null=True,
                                                 default=None, min_value=Decimal("0.3"), max_value=400)


class PrescriptionCreateView(PermissionedView):
    required_permissions = {"POST": ("prescriptions.create",)}

    def post(self, request, pk):
        data = validated(RxInput, request.data)
        rx = services.create_prescription(self.ctx(), get_object_or_404(Encounter, pk=pk), data["items"],
                                          data["notes"], special_form_serial=data["special_form_serial"],
                                          patient_weight_kg=data["patient_weight_kg"])
        rx = Prescription.objects.select_related("prescriber", "patient", "encounter").prefetch_related(
            "items__item").get(pk=rx.pk)
        return Response(PrescriptionSerializer(rx).data, status=status.HTTP_201_CREATED)


class PrescriptionListView(PermissionedView):
    required_permissions = {"GET": AnyOf(("pharmacy.view", "clinical.view"))}

    def get(self, request):
        qs = Prescription.objects.select_related("prescriber", "patient", "encounter").prefetch_related("items__item")
        if patient := self.param_uuid("patient"):
            qs = qs.filter(patient_id=patient)
        if st := request.query_params.get("status"):
            qs = qs.filter(status__in=st.split(","))
        return self.paginate(qs.order_by("-created_at"), PrescriptionSerializer)


class PrescriptionCancelView(PermissionedView):
    required_permissions = {"POST": ("prescriptions.create",)}

    def post(self, request, pk):
        rx = services.cancel_prescription(self.ctx(), get_object_or_404(Prescription, pk=pk),
                                          str(request.data.get("reason", "")))
        rx = Prescription.objects.select_related("prescriber", "patient", "encounter").prefetch_related(
            "items__item").get(pk=rx.pk)
        return Response(PrescriptionSerializer(rx).data)



# ---------------------------------------------------------------------------
# Referrals and certificates
# ---------------------------------------------------------------------------
class ReferralSerializer(serializers.ModelSerializer):
    referred_by = ClinicianBrief(read_only=True)
    patient = PatientBrief(read_only=True)
    visit_date = serializers.DateField(source="encounter.visit.visit_date", read_only=True)

    class Meta:
        model = Referral
        fields = ["id", "number", "encounter", "patient", "to_facility", "to_department", "urgency", "reason",
                  "clinical_summary", "treatment_given", "status", "cancel_reason", "referred_by", "created_at",
                  "visit_date"]


class ReferralInput(serializers.Serializer):
    to_facility = serializers.CharField(max_length=150)
    to_department = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    urgency = serializers.ChoiceField(choices=Referral.Urgency.choices, default=Referral.Urgency.ROUTINE)
    reason = serializers.CharField(max_length=5000)
    clinical_summary = serializers.CharField(max_length=10000, required=False, allow_blank=True, default="")
    treatment_given = serializers.CharField(max_length=5000, required=False, allow_blank=True, default="")


class CertificateSerializer(serializers.ModelSerializer):
    issued_by = ClinicianBrief(read_only=True)
    patient = PatientBrief(read_only=True)
    days = serializers.IntegerField(read_only=True)

    class Meta:
        model = MedicalCertificate
        fields = ["id", "number", "encounter", "patient", "kind", "start_date", "end_date", "days",
                  "include_diagnosis", "diagnosis_text", "remarks", "is_cancelled", "cancel_reason", "issued_by",
                  "created_at"]


class CertificateInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=MedicalCertificate.Kind.choices)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    include_diagnosis = serializers.BooleanField(default=False)
    diagnosis_text = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    remarks = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class EncounterReferralsView(PermissionedView):
    required_permissions = {"GET": ("clinical.view",), "POST": ("clinical.write",)}

    def get(self, request, pk):
        rows = Referral.objects.filter(encounter_id=pk).select_related("referred_by", "patient", "encounter__visit")
        return Response(ReferralSerializer(rows, many=True).data)

    def post(self, request, pk):
        data = validated(ReferralInput, request.data)
        ref = services.create_referral(self.ctx(), get_object_or_404(Encounter, pk=pk), **data)
        return Response(ReferralSerializer(ref).data, status=status.HTTP_201_CREATED)


class EncounterCertificatesView(PermissionedView):
    required_permissions = {"GET": ("clinical.view",), "POST": ("clinical.write",)}

    def get(self, request, pk):
        rows = MedicalCertificate.objects.filter(encounter_id=pk).select_related("issued_by", "patient")
        return Response(CertificateSerializer(rows, many=True).data)

    def post(self, request, pk):
        data = validated(CertificateInput, request.data)
        cert = services.issue_certificate(self.ctx(), get_object_or_404(Encounter, pk=pk), **data)
        return Response(CertificateSerializer(cert).data, status=status.HTTP_201_CREATED)


class InternalReferralSerializer(serializers.ModelSerializer):
    referred_by = serializers.CharField(source="referred_by.full_name", read_only=True)
    to_doctor = serializers.SerializerMethodField()
    from_department_name = serializers.SerializerMethodField()
    to_department_name = serializers.SerializerMethodField()
    seen_by = serializers.SerializerMethodField()

    class Meta:
        model = InternalReferral
        fields = ["id", "visit", "patient", "from_encounter", "from_department", "from_department_name",
                  "to_department", "to_department_name", "to_doctor", "urgency", "reason", "status", "referred_by",
                  "seen_by", "seen_at", "cancel_reason", "created_at"]

    def _dept(self, code):
        from apps.accounts.models import Department

        cache = self.context.setdefault("_depts", {d.code: d.name for d in Department.objects.all()})
        return cache.get(code, code)

    def get_from_department_name(self, obj):
        return self._dept(obj.from_department) if obj.from_department else ""

    def get_to_department_name(self, obj):
        return self._dept(obj.to_department)

    def get_to_doctor(self, obj):
        return {"id": str(obj.to_doctor_id), "full_name": obj.to_doctor.full_name} if obj.to_doctor_id else None

    def get_seen_by(self, obj):
        return obj.seen_encounter.doctor.full_name if obj.seen_encounter_id else None


class InternalReferralInput(serializers.Serializer):
    to_department = serializers.CharField(max_length=30)
    to_doctor_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    urgency = serializers.ChoiceField(choices=InternalReferral.Urgency.choices, default="routine")
    reason = serializers.CharField(max_length=2000)


def _internal_qs():
    return InternalReferral.objects.select_related("referred_by", "to_doctor", "seen_encounter__doctor")


class EncounterInternalReferralsView(PermissionedView):
    """GET/POST encounters/<id>/internal-referrals/: refer the patient to another department of this clinic."""

    required_permissions = {"GET": ("clinical.view",), "POST": ("clinical.write",)}

    def get(self, request, pk):
        return Response(InternalReferralSerializer(_internal_qs().filter(from_encounter_id=pk), many=True).data)

    def post(self, request, pk):
        data = validated(InternalReferralInput, request.data)
        ref = services.create_internal_referral(self.ctx(), get_object_or_404(Encounter, pk=pk), **data)
        return Response(InternalReferralSerializer(_internal_qs().get(pk=ref.pk)).data, status=status.HTTP_201_CREATED)


class InternalReferralCancelView(PermissionedView):
    required_permissions = {"POST": ("clinical.write",)}

    def post(self, request, pk):
        ref = services.cancel_internal_referral(self.ctx(), get_object_or_404(InternalReferral, pk=pk),
                                                str(request.data.get("reason", "")))
        return Response(InternalReferralSerializer(_internal_qs().get(pk=ref.pk)).data)


class VisitInternalReferralView(PermissionedView):
    """The waiting internal referral of a visit, for the receiving doctor and the waiting list."""

    required_permissions = {"GET": AnyOf(("clinical.view", "queue.manage"))}

    def get(self, request, visit_id):
        rows = _internal_qs().filter(visit_id=visit_id)
        return Response(InternalReferralSerializer(rows, many=True).data)


class PatientDocumentsView(PermissionedView):
    """Referrals and certificates for a patient, for the chart."""

    required_permissions = {"GET": ("clinical.view",)}

    def get(self, request, patient_id):
        refs = Referral.objects.filter(patient_id=patient_id).select_related("referred_by", "patient", "encounter__visit")
        certs = MedicalCertificate.objects.filter(patient_id=patient_id).select_related("issued_by", "patient")
        internal = _internal_qs().filter(patient_id=patient_id)
        return Response({"referrals": ReferralSerializer(refs, many=True).data,
                         "certificates": CertificateSerializer(certs, many=True).data,
                         "internal_referrals": InternalReferralSerializer(internal, many=True).data})


class PatientDiagnosesView(PermissionedView):
    """Every diagnosis recorded for the patient, newest first (removed draft entries excluded)."""

    required_permissions = {"GET": ("clinical.view",)}

    def get(self, request, patient_id):
        rows = (Diagnosis.objects.filter(patient_id=patient_id, is_removed=False)
                .select_related("icd", "created_by", "encounter").order_by("-created_at")[:500])
        return Response([{
            "id": str(d.pk), "date": d.created_at, "code": d.icd_id or "", "description": d.description,
            "kind": d.kind, "certainty": d.certainty, "doctor": d.created_by.full_name,
            "encounter": str(d.encounter_id), "signed": d.encounter.status == Encounter.Status.SIGNED,
        } for d in rows])


class DocumentCancelView(PermissionedView):
    required_permissions = {"POST": ("clinical.write",)}

    def post(self, request, kind, pk):
        reason = str(request.data.get("reason", ""))
        if kind == "referrals":
            obj = services.cancel_referral(self.ctx(), get_object_or_404(Referral, pk=pk), reason)
            return Response(ReferralSerializer(obj).data)
        obj = services.cancel_certificate(self.ctx(), get_object_or_404(MedicalCertificate, pk=pk), reason)
        return Response(CertificateSerializer(obj).data)


class PatientClinicalSummaryView(PermissionedView):
    """What a doctor needs beside the note: history, current medicines, recent diagnoses and results."""

    required_permissions = {"GET": ("clinical.view",)}

    def get(self, request, patient_id):
        from apps.laboratory.models import LabOrderItem
        from apps.patients.models import Patient

        patient = get_object_or_404(Patient, pk=patient_id)
        diagnoses, seen = [], set()
        for d in (Diagnosis.objects.filter(patient=patient, is_removed=False, encounter__status="signed")
                  .select_related("icd", "encounter").order_by("-created_at")[:40]):
            key = d.icd_id or d.description.lower()
            if key in seen:
                continue
            seen.add(key)
            diagnoses.append({"code": d.icd_id or "", "description": d.description, "certainty": d.certainty,
                              "date": d.encounter.signed_at or d.created_at})
            if len(diagnoses) == 10:
                break
        results = [{"test": i.test.name, "result": i.result_text or (f"{i.result_numeric.normalize():f}" if i.result_numeric is not None else ""),
                    "unit": i.unit, "flag": i.flag, "date": i.verified_at}
                   for i in (LabOrderItem.objects.filter(order__patient=patient, status="verified")
                             .select_related("test").order_by("-verified_at")[:12])]
        recent_rx = []
        for line in (PrescriptionItem.objects.filter(prescription__patient=patient)
                     .exclude(prescription__status="cancelled").select_related("prescription")
                     .order_by("-prescription__created_at")[:10]):
            recent_rx.append({"drug": line.drug_name, "dose": line.dose, "frequency": line.frequency,
                              "days": line.duration_days, "date": line.prescription.created_at,
                              "status": line.prescription.status})
        visits = patient.visits.exclude(status="cancelled")
        last = visits.order_by("-visit_date").first()
        return Response({
            "known_conditions": patient.known_conditions, "past_history": patient.past_history,
            "current_medications": patient.current_medications,
            "allergies": [{"substance": a.substance, "severity": a.severity, "reaction": a.reaction}
                          for a in patient.allergies.filter(is_active=True)],
            "diagnoses": diagnoses, "results": results, "recent_prescriptions": recent_rx,
            "visit_count": visits.count(), "last_visit": last.visit_date if last else None,
        })
