from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response

from apps.core.api import PermissionedView, validated

from . import services
from .models import Allergy, EmergencyContact, Patient
from apps.core.concurrency import bump_version, guarded_edit


def age_of(birth_date) -> int:
    today = timezone.localdate()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


class EmergencyContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmergencyContact
        fields = ["id", "name", "relationship", "phone"]


class AllergySerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.CharField(source="recorded_by.full_name", read_only=True)

    class Meta:
        model = Allergy
        fields = ["id", "substance", "reaction", "severity", "is_active", "inactive_reason", "created_at",
                  "recorded_by_name"]


class PatientListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    age = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = ["id", "mrn", "full_name", "first_name", "middle_name", "last_name", "sex", "birth_date",
                  "birth_date_estimated", "age", "phone", "city", "created_at", "is_active", "inactive_kind",
                  "date_of_death"]

    def get_age(self, obj) -> int:
        return age_of(obj.birth_date)


class PatientDetailSerializer(PatientListSerializer):
    emergency_contacts = EmergencyContactSerializer(many=True, read_only=True)
    allergies = AllergySerializer(many=True, read_only=True)

    class Meta(PatientListSerializer.Meta):
        fields = PatientListSerializer.Meta.fields + [
            "alt_phone", "region", "subcity_woreda", "kebele", "house_number", "national_id", "blood_group",
            "known_conditions", "past_history", "current_medications", "emergency_contacts", "allergies",
            "updated_at", "row_version", "is_active", "merged_into", "merged_at", "merge_reason", "merged_records",
            "inactive_note", "inactivated_at", "inactivated_by_name",
        ]

    inactivated_by_name = serializers.SerializerMethodField()

    def get_inactivated_by_name(self, obj) -> str | None:
        return obj.inactivated_by.full_name if obj.inactivated_by_id else None

    merged_into = serializers.SerializerMethodField()
    merged_records = serializers.SerializerMethodField()

    def get_merged_into(self, obj):
        p = obj.merged_into
        return {"id": str(p.pk), "mrn": p.mrn, "full_name": p.full_name} if p else None

    def get_merged_records(self, obj) -> list[dict]:
        return [{"id": str(p.pk), "mrn": p.mrn, "full_name": p.full_name, "merged_at": p.merged_at}
                for p in obj.merged_records.all()]


class ContactInput(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    relationship = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=20)


class AllergyInput(serializers.Serializer):
    substance = serializers.CharField(max_length=120)
    reaction = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    severity = serializers.ChoiceField(choices=Allergy.Severity.choices, default=Allergy.Severity.MODERATE)


class PatientInput(serializers.Serializer):
    first_name = serializers.CharField(max_length=60)
    middle_name = serializers.CharField(max_length=60, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=60, required=False, allow_blank=True)
    sex = serializers.ChoiceField(choices=Patient.Sex.choices)
    birth_date = serializers.DateField(required=False, allow_null=True)
    age_years = serializers.IntegerField(required=False, min_value=0, max_value=130)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    alt_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    region = serializers.CharField(max_length=60, required=False, allow_blank=True)
    city = serializers.CharField(max_length=60, required=False, allow_blank=True)
    subcity_woreda = serializers.CharField(max_length=60, required=False, allow_blank=True)
    kebele = serializers.CharField(max_length=30, required=False, allow_blank=True)
    house_number = serializers.CharField(max_length=30, required=False, allow_blank=True)
    national_id = serializers.CharField(max_length=30, required=False, allow_blank=True)
    blood_group = serializers.ChoiceField(choices=Patient.BloodGroup.choices, required=False, allow_blank=True)
    known_conditions = serializers.CharField(required=False, allow_blank=True)
    past_history = serializers.CharField(required=False, allow_blank=True)
    current_medications = serializers.CharField(required=False, allow_blank=True)


class RegisterInput(PatientInput):
    emergency_contacts = ContactInput(many=True, required=False, default=list)
    allergies = AllergyInput(many=True, required=False, default=list)
    confirm_not_duplicate = serializers.BooleanField(default=False)


def _patient_qs():
    return Patient.objects.select_related("inactivated_by", "merged_into").prefetch_related(
        "emergency_contacts", "allergies__recorded_by")


class PatientListCreateView(PermissionedView):
    required_permissions = {"GET": ("patients.view",), "POST": ("patients.create",)}

    def get(self, request):
        include_inactive = self.param_bool("include_inactive") or False
        return self.paginate(services.search_patients(request.query_params.get("q", ""), include_inactive=include_inactive),
                             PatientListSerializer)

    def post(self, request):
        data = validated(RegisterInput, request.data)
        contacts = data.pop("emergency_contacts")
        allergies = data.pop("allergies")
        confirm = data.pop("confirm_not_duplicate")
        if data.get("birth_date") is None:
            data.pop("birth_date", None)
        patient = services.register_patient(self.ctx(), data, emergency_contacts=contacts, allergies=allergies,
                                            confirm_not_duplicate=confirm)
        return Response(PatientDetailSerializer(_patient_qs().get(pk=patient.pk)).data, status=status.HTTP_201_CREATED)


class PatientDuplicateCheckView(PermissionedView):
    required_permissions = {"POST": ("patients.create",)}

    def post(self, request):
        data = validated(PatientInput, request.data)
        birth = data.get("birth_date") or (
            services.birth_date_from_age(data["age_years"]) if data.get("age_years") is not None else None)
        phone = services.normalize_phone(data.get("phone", ""))
        dupes = services.find_possible_duplicates(
            first_name=data["first_name"], middle_name=data.get("middle_name", ""),
            last_name=data.get("last_name", ""), birth_date=birth, phone=phone,
            alt_phone=services.normalize_phone(data.get("alt_phone", "")), national_id=data.get("national_id", ""),
            sex=data.get("sex", ""), birth_date_estimated=data.get("birth_date") is None)
        rows = PatientListSerializer(dupes, many=True).data
        for row, p in zip(rows, dupes):
            row["reason"] = getattr(p, "match_reason", "")
        return Response(rows)


class PatientDetailView(PermissionedView):
    required_permissions = {"GET": ("patients.view",), "PATCH": ("patients.update",)}

    def get(self, request, pk):
        patient = get_object_or_404(_patient_qs(), pk=pk)
        services.record_view(self.ctx(), patient)
        return Response(PatientDetailSerializer(patient).data)

    def patch(self, request, pk):
        data = validated(PatientInput, request.data, partial=True)
        if "birth_date" in data and data["birth_date"] is None:
            data.pop("birth_date")
        with guarded_edit(Patient, pk, request, object_type="patient", label="patient record") as patient:
            services.update_patient(self.ctx(), patient, data)
        return Response(PatientDetailSerializer(_patient_qs().get(pk=pk)).data)


class EmergencyContactsView(PermissionedView):
    required_permissions = {"PUT": ("patients.update",)}

    def put(self, request, pk):
        contacts = validated(ContactInput, request.data.get("contacts", []), many=True)
        # Emergency contacts are part of the patient record, so they share its version.
        with guarded_edit(Patient, pk, request, object_type="patient", label="patient record") as patient:
            services.set_emergency_contacts(self.ctx(), patient, contacts)
            bump_version(patient)
        resp = Response(EmergencyContactSerializer(patient.emergency_contacts.all(), many=True).data)
        resp["ETag"] = f'"{patient.row_version}"'
        return resp


class AllergyCreateView(PermissionedView):
    # Clinicians and reception can record allergies; they are safety-critical information.
    required_permissions = {"POST": ("patients.update",)}

    def post(self, request, pk):
        patient = get_object_or_404(Patient, pk=pk)
        data = validated(AllergyInput, request.data)
        allergy = services.add_allergy(self.ctx(), patient, **data)
        return Response(AllergySerializer(allergy).data, status=status.HTTP_201_CREATED)


class AllergyInactivateView(PermissionedView):
    required_permissions = {"POST": ("patients.update",)}

    def post(self, request, pk, allergy_id):
        allergy = get_object_or_404(Allergy, pk=allergy_id, patient_id=pk)
        services.inactivate_allergy(self.ctx(), allergy, str(request.data.get("reason", "")))
        return Response(AllergySerializer(allergy).data)


class PatientChangeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    field = serializers.CharField()
    old_value = serializers.CharField()
    new_value = serializers.CharField()
    changed_at = serializers.DateTimeField()
    changed_by = serializers.CharField(source="changed_by.full_name")


class MergeInput(serializers.Serializer):
    duplicate_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=255)


class PatientMergeView(PermissionedView):
    """POST patients/<keep>/merge/ {duplicate_id, reason}: move the duplicate's records here and retire it."""

    required_permissions = {"POST": ("patients.merge",)}

    def post(self, request, pk):
        data = validated(MergeInput, request.data)
        keep = get_object_or_404(Patient, pk=pk)
        duplicate = get_object_or_404(Patient, pk=data["duplicate_id"])
        details = services.merge_patients(self.ctx(), keep, duplicate, reason=data["reason"])
        keep.refresh_from_db()
        return Response({"patient": PatientDetailSerializer(keep).data, "details": details})


class DeactivateInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Patient.InactiveKind.choices)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    date_of_death = serializers.DateField(required=False, allow_null=True, default=None)


class PatientDeactivateView(PermissionedView):
    """POST patients/<id>/deactivate/ {kind: moved|deceased|other, note, date_of_death}."""

    required_permissions = {"POST": ("patients.status",)}

    def post(self, request, pk):
        data = validated(DeactivateInput, request.data)
        with guarded_edit(Patient, pk, request, object_type="patient", label="patient record") as patient:
            services.deactivate_patient(self.ctx(), patient, **data)
        return Response(PatientDetailSerializer(_patient_qs().get(pk=pk)).data)


class PatientReactivateView(PermissionedView):
    """POST patients/<id>/reactivate/ {reason}."""

    required_permissions = {"POST": ("patients.status",)}

    def post(self, request, pk):
        reason = str(request.data.get("reason", ""))
        with guarded_edit(Patient, pk, request, object_type="patient", label="patient record") as patient:
            services.reactivate_patient(self.ctx(), patient, reason=reason)
        return Response(PatientDetailSerializer(_patient_qs().get(pk=pk)).data)


class PatientHistoryView(PermissionedView):
    required_permissions = {"GET": ("patients.view",)}

    def get(self, request, pk):
        patient = get_object_or_404(Patient, pk=pk)
        changes = patient.changes.select_related("changed_by")[:200]
        return Response(PatientChangeSerializer(changes, many=True).data)


class PatientCardQrView(PermissionedView):
    """QR code printed on the patient card. It holds only "MRSPATIENT:<MRN>": the phone app scans it to
    open the record, and a lost card reveals nothing but the number already printed beside it."""

    required_permissions = {"GET": ("patients.view",)}

    def get(self, request, pk):
        import io

        import segno
        from django.http import HttpResponse

        patient = get_object_or_404(Patient, pk=pk)
        out = io.BytesIO()  # a complete SVG file (with its namespace), so browsers show it as an image
        segno.make(f"MRSPATIENT:{patient.mrn}", error="m").save(out, kind="svg", scale=4, border=1, dark="#111111")
        resp = HttpResponse(out.getvalue(), content_type="image/svg+xml")
        resp["Cache-Control"] = "private, max-age=86400"
        resp["X-Content-Type-Options"] = "nosniff"
        return resp
