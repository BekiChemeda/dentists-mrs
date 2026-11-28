"""Dental API views. HTTP only: validate input, call a service, serialise. Every view declares its permissions."""

from __future__ import annotations

from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.models import Role, User
from apps.audit.services import record_event
from apps.core.api import PermissionedView, validated
from apps.core.concurrency import guarded_edit
from apps.core.permissions import AnyOf
from apps.patients.models import Patient
from apps.scheduling.models import Appointment, Visit

from .. import teeth
from ..models import (
    DentalDiagnosis, DentalDiagnosisTerm, DentalEncounter, DentalImage, DentalLabCase, DentalProcedure, FindingType,
    MedicalRiskReview, OrthoAssessment, OrthoCase, OrthoVisit, PeriodontalExam, ProcedureRecord, Recall, ToothFinding,
    TreatmentPlan, TreatmentPlanItem,
)
from ..services import catalog as catalog_svc
from ..services import chart, encounters, imaging, labcases, perio, plans, procedures, recalls
from ..starter_data import RISK_ANSWERS, RISK_QUESTIONS
from . import serializers as S

VIEW = ("dental.view",)
CATALOG_ADMIN = ("dental.catalog.manage",)


def _patient(pk) -> Patient:
    return get_object_or_404(Patient, pk=pk)


def _user(pk):
    return get_object_or_404(User, pk=pk, is_active=True) if pk else None


def _audit_view(view, action: str, object_type: str, object_id, patient_id) -> None:
    record_event(view.ctx(), action=action, object_type=object_type, object_id=object_id,
                 details={"patient": str(patient_id)})


# ===========================================================================
# Catalogues
# ===========================================================================
class CatalogView(PermissionedView):
    """Everything the dental screens need to draw choices. No patient data."""

    required_permissions = {"GET": AnyOf(("dental.view", "dental.catalog.manage", "dental.recall.manage",
                                          "dental.labcase.work", "dental.imaging.view", "appointments.view"))}

    def get(self, request):
        procs = DentalProcedure.objects.filter(is_active=True).prefetch_related("default_materials__item")
        return Response({
            "finding_types": S.FindingTypeSerializer(FindingType.objects.filter(is_active=True), many=True).data,
            "procedures": S.ProcedureSerializer(procs, many=True).data,
            "procedure_categories": DentalProcedure.Category.choices,
            "risk_questions": RISK_QUESTIONS, "risk_answers": RISK_ANSWERS,
            "surfaces": teeth.SURFACES, "regions": teeth.REGIONS, "scopes": teeth.SCOPES,
            "perio_sites": teeth.PERIO_SITES,
            "teeth": {"permanent": teeth.PERMANENT, "primary": teeth.PRIMARY},
            "image_kinds": DentalImage.Kind.choices, "recall_kinds": Recall.Kind.choices,
            "lab_case_types": DentalLabCase.CaseType.choices,
            "plan_item_priorities": TreatmentPlanItem.Priority.choices,
            "roles": list(Role.objects.filter(permissions__code="dental.procedure.record").distinct()
                          .order_by("name").values_list("code", "name")),
            "ortho": {
                "appliances": OrthoCase.Appliance.choices, "arches": OrthoCase.Arches.choices,
                "billing_modes": OrthoCase.Billing.choices, "retainers": OrthoCase.Retainer.choices,
                "visit_kinds": OrthoVisit.Kind.choices, "angle": OrthoAssessment.Angle.choices,
                "incisor": OrthoAssessment.Incisor.choices, "severity": OrthoAssessment.Severity.choices,
                "skeletal": OrthoAssessment.Skeletal.choices, "profile": OrthoAssessment.Profile.choices,
                "hygiene": OrthoAssessment.Hygiene.choices,
            },
        })


class FindingTypeListView(PermissionedView):
    required_permissions = {"GET": AnyOf(("dental.view", "dental.catalog.manage")), "POST": CATALOG_ADMIN}

    def get(self, request):
        return Response(S.FindingTypeSerializer(FindingType.objects.all(), many=True).data)

    def post(self, request):
        obj = catalog_svc.save_finding_type(self.ctx(), validated(S.FindingTypeSerializer, request.data))
        return Response(S.FindingTypeSerializer(obj).data, status=status.HTTP_201_CREATED)


class FindingTypeDetailView(PermissionedView):
    required_permissions = {"PATCH": CATALOG_ADMIN}

    def patch(self, request, pk):
        data = validated(S.FindingTypeSerializer, request.data, partial=True)
        data.pop("code", None)  # codes are permanent: findings refer to them in reports
        with guarded_edit(FindingType, pk, request, object_type="dental_finding_type", label="finding") as obj:
            catalog_svc.save_finding_type(self.ctx(), data, obj)
        return Response(S.FindingTypeSerializer(FindingType.objects.get(pk=pk)).data)


class DiagnosisTermListView(PermissionedView):
    required_permissions = {"GET": AnyOf(("dental.view", "dental.catalog.manage", "reports.clinical")),
                            "POST": CATALOG_ADMIN}

    def get(self, request):
        qs = DentalDiagnosisTerm.objects.all()
        if not self.param_bool("all"):
            qs = qs.filter(is_active=True)
        if q := request.query_params.get("q", "").strip():
            qs = qs.filter(Q(code__istartswith=q) | Q(term__icontains=q) | Q(category__icontains=q))
        return Response(S.DiagnosisTermSerializer(qs[:200], many=True).data)

    def post(self, request):
        obj = catalog_svc.save_diagnosis_term(self.ctx(), validated(S.DiagnosisTermSerializer, request.data))
        return Response(S.DiagnosisTermSerializer(obj).data, status=status.HTTP_201_CREATED)


class DiagnosisTermDetailView(PermissionedView):
    required_permissions = {"PATCH": CATALOG_ADMIN}

    def patch(self, request, pk):
        data = validated(S.DiagnosisTermSerializer, request.data, partial=True)
        data.pop("code", None)
        data.pop("code_system", None)
        with guarded_edit(DentalDiagnosisTerm, pk, request, object_type="dental_diagnosis_term",
                          label="diagnosis") as obj:
            catalog_svc.save_diagnosis_term(self.ctx(), data, obj)
        return Response(S.DiagnosisTermSerializer(DentalDiagnosisTerm.objects.get(pk=pk)).data)


class ProcedureListView(PermissionedView):
    required_permissions = {"GET": AnyOf(("dental.view", "dental.catalog.manage", "billing.view")),
                            "POST": CATALOG_ADMIN}

    def get(self, request):
        qs = DentalProcedure.objects.prefetch_related("default_materials__item")
        if not self.param_bool("all"):
            qs = qs.filter(is_active=True)
        return Response(S.ProcedureSerializer(qs, many=True).data)

    def post(self, request):
        obj = catalog_svc.save_procedure(self.ctx(), validated(S.ProcedureSerializer, request.data))
        return Response(S.ProcedureSerializer(obj).data, status=status.HTTP_201_CREATED)


class ProcedureDetailView(PermissionedView):
    required_permissions = {"PATCH": CATALOG_ADMIN}

    def patch(self, request, pk):
        data = validated(S.ProcedureSerializer, request.data, partial=True)
        data.pop("code", None)
        with guarded_edit(DentalProcedure, pk, request, object_type="dental_procedure_type",
                          label="procedure") as obj:
            catalog_svc.save_procedure(self.ctx(), data, obj)
        return Response(S.ProcedureSerializer(DentalProcedure.objects.get(pk=pk)).data)


class ProcedureMaterialsView(PermissionedView):
    required_permissions = {"PUT": CATALOG_ADMIN}

    def put(self, request, pk):
        rows = validated(S.MaterialInput, request.data.get("materials", []), many=True)
        obj = catalog_svc.set_default_materials(self.ctx(), get_object_or_404(DentalProcedure, pk=pk), rows)
        return Response(S.ProcedureSerializer(obj).data)


# ===========================================================================
# Patient-level dental record
# ===========================================================================
def _encounter_qs():
    return DentalEncounter.objects.select_related("dentist", "patient", "visit", "risk_review__reviewed_by").prefetch_related(
        Prefetch("diagnoses", queryset=DentalDiagnosis.objects.select_related("recorded_by")),
        Prefetch("findings", queryset=chart.findings_qs_all()),
        "amendments__author",
        Prefetch("procedures", queryset=ProcedureRecord.objects.select_related("procedure", "performed_by")),
        Prefetch("prescriptions", queryset=_rx_qs()),
    )


def _rx_qs():
    from apps.clinical.models import Prescription

    return Prescription.objects.select_related("prescriber", "patient", "encounter").prefetch_related("items__item")


class PatientSummaryView(PermissionedView):
    """The dental workspace header: alerts, history, examinations, plans, recalls."""

    required_permissions = {"GET": VIEW}

    def get(self, request, patient_id):
        patient = _patient(patient_id)
        _audit_view(self, "dental_record.view", "patient", patient.pk, patient.pk)
        profile = encounters.profile_for(patient)
        review = MedicalRiskReview.objects.filter(patient=patient).select_related("reviewed_by").first()
        encs = (DentalEncounter.objects.filter(patient=patient).select_related("dentist")
                .prefetch_related("diagnoses").order_by("-created_at")[:50])
        plan_rows = (TreatmentPlan.objects.filter(patient=patient).select_related("created_by")
                     .prefetch_related("items").order_by("-created_at"))
        allergies = [{"substance": a.substance, "severity": a.severity, "reaction": a.reaction}
                     for a in patient.allergies.filter(is_active=True)]
        return Response({
            "profile": S.ProfileSerializer(profile).data,
            "risk_review": S.RiskReviewSerializer(review).data if review else None,
            "shared_history": {"allergies": allergies, "known_conditions": patient.known_conditions,
                               "past_history": patient.past_history,
                               "current_medications": patient.current_medications},
            "encounters": S.EncounterListSerializer(encs, many=True).data,
            "plans": S.PlanListSerializer(plan_rows, many=True).data,
            "open_recalls": S.RecallSerializer(Recall.objects.filter(patient=patient, status__in=Recall.OPEN),
                                               many=True, context={"request": request}).data,
        })


class ProfileView(PermissionedView):
    required_permissions = {"GET": VIEW, "PATCH": ("dental.write",)}

    def get(self, request, patient_id):
        return Response(S.ProfileSerializer(encounters.profile_for(_patient(patient_id))).data)

    def patch(self, request, patient_id):
        from ..models import DentalProfile

        profile = encounters.profile_for(_patient(patient_id))
        data = validated(S.ProfileSerializer, request.data, partial=True)
        with guarded_edit(DentalProfile, profile.pk, request, object_type="patient", label="dental history") as locked:
            encounters.update_profile(self.ctx(), locked, data)
        return Response(S.ProfileSerializer(DentalProfile.objects.get(pk=profile.pk)).data)


class RiskReviewView(PermissionedView):
    required_permissions = {"GET": VIEW, "POST": ("dental.write",)}

    def get(self, request, patient_id):
        qs = MedicalRiskReview.objects.filter(patient_id=patient_id).select_related("reviewed_by")
        return self.paginate(qs, S.RiskReviewSerializer)

    def post(self, request, patient_id):
        data = validated(S.RiskReviewInput, request.data)
        enc = get_object_or_404(DentalEncounter, pk=data["encounter_id"]) if data.get("encounter_id") else None
        review = encounters.record_risk_review(self.ctx(), _patient(patient_id), answers=data["answers"],
                                               allergies_reviewed=data["allergies_reviewed"],
                                               medications_reviewed=data["medications_reviewed"], notes=data["notes"],
                                               encounter=enc)
        return Response(S.RiskReviewSerializer(review).data, status=status.HTTP_201_CREATED)


class ChartView(PermissionedView):
    """The chart as of now, as of a time (`as_of`) or as of an examination (`encounter`)."""

    required_permissions = {"GET": VIEW}

    def get(self, request, patient_id):
        patient = _patient(patient_id)
        enc = None
        if enc_id := self.param_uuid("encounter"):
            enc = get_object_or_404(DentalEncounter, pk=enc_id)
        at_raw = request.query_params.get("as_of")
        at = None
        if at_raw:
            from django.utils.dateparse import parse_datetime

            at = parse_datetime(at_raw)
            if at is None:
                raise serializers.ValidationError({"as_of": ["Use an ISO date and time."]})
        moment = chart.as_of_moment(patient, at=at, encounter=enc)
        _audit_view(self, "dental_chart.view", "patient", patient.pk, patient.pk)
        found = chart.chart_at(patient, moment)
        present = sorted({f.tooth for f in chart.findings_qs(patient).filter(tooth__isnull=False)})
        return Response({"as_of": moment, "findings": S.FindingSerializer(found, many=True).data,
                         "teeth_with_history": present,
                         "has_primary": any(teeth.dentition(t) == "primary" for t in present)})


class ChartHistoryView(PermissionedView):
    required_permissions = {"GET": VIEW}

    def get(self, request, patient_id):
        patient = _patient(patient_id)
        qs = chart.findings_qs(patient)
        if tooth := request.query_params.get("tooth"):
            qs = qs.filter(tooth=int(tooth)) if tooth.isdigit() else qs.none()
        _audit_view(self, "dental_chart.history_view", "patient", patient.pk, patient.pk)
        return Response(S.FindingSerializer(qs.order_by("-recorded_at")[:500], many=True).data)


class ChartCompareView(PermissionedView):
    required_permissions = {"GET": VIEW}

    def get(self, request, patient_id):
        patient = _patient(patient_id)
        a = get_object_or_404(DentalEncounter, pk=self.param_uuid("from"), patient=patient)
        b = get_object_or_404(DentalEncounter, pk=self.param_uuid("to"), patient=patient)
        diff = chart.compare(patient, chart.as_of_moment(patient, encounter=a), chart.as_of_moment(patient, encounter=b))
        _audit_view(self, "dental_chart.compare_view", "patient", patient.pk, patient.pk)
        return Response({k: S.FindingSerializer(v, many=True).data for k, v in diff.items()})


class PatientDiagnosesView(PermissionedView):
    required_permissions = {"GET": VIEW}

    def get(self, request, patient_id):
        qs = (DentalDiagnosis.objects.filter(patient_id=patient_id, is_removed=False)
              .select_related("recorded_by").order_by("-created_at"))
        if st := request.query_params.get("status"):
            qs = qs.filter(status=st)
        patient = _patient(patient_id)
        _audit_view(self, "dental_diagnoses.view", "patient", patient.pk, patient.pk)
        return Response(S.DiagnosisSerializer(qs[:300], many=True).data)


class PatientPerioView(PermissionedView):
    required_permissions = {"GET": VIEW}

    def get(self, request, patient_id):
        qs = (PeriodontalExam.objects.filter(patient_id=patient_id).select_related("examiner", "encounter")
              .prefetch_related("sites", "teeth").order_by("-created_at"))
        patient = _patient(patient_id)
        _audit_view(self, "dental_perio.view", "patient", patient.pk, patient.pk)
        return Response(S.PerioExamSerializer(qs[:30], many=True).data)


# ===========================================================================
# Examinations
# ===========================================================================
class StartEncounterView(PermissionedView):
    required_permissions = {"POST": ("dental.write",)}

    def post(self, request, visit_id):
        enc = encounters.start_encounter(self.ctx(), get_object_or_404(Visit, pk=visit_id))
        return Response(S.EncounterSerializer(_encounter_qs().get(pk=enc.pk)).data, status=status.HTTP_201_CREATED)


class EncounterListView(PermissionedView):
    required_permissions = {"GET": VIEW}

    def get(self, request):
        qs = DentalEncounter.objects.select_related("dentist", "patient").prefetch_related("diagnoses")
        if p := self.param_uuid("patient"):
            qs = qs.filter(patient_id=p)
        if v := self.param_uuid("visit"):
            qs = qs.filter(visit_id=v)
        if self.param_bool("mine"):
            qs = qs.filter(dentist=request.user)
        if st := request.query_params.get("status"):
            qs = qs.filter(status=st)
        return self.paginate(qs.order_by("-created_at"), S.EncounterListSerializer)


class EncounterDetailView(PermissionedView):
    required_permissions = {"GET": VIEW, "PATCH": ("dental.write",)}

    def get(self, request, pk):
        enc = get_object_or_404(_encounter_qs(), pk=pk)
        _audit_view(self, "dental_encounter.view", "dental_encounter", enc.pk, enc.patient_id)
        return Response(S.EncounterSerializer(enc).data)

    def patch(self, request, pk):
        data = validated(S.EncounterInput, request.data)
        version = data.pop("version")
        encounters.update_encounter(self.ctx(), get_object_or_404(DentalEncounter, pk=pk), data, version=version)
        return Response(S.EncounterSerializer(_encounter_qs().get(pk=pk)).data)


class SignEncounterView(PermissionedView):
    required_permissions = {"POST": ("dental.write",)}

    def post(self, request, pk):
        encounters.sign_encounter(self.ctx(), get_object_or_404(DentalEncounter, pk=pk))
        return Response(S.EncounterSerializer(_encounter_qs().get(pk=pk)).data)


class AmendEncounterView(PermissionedView):
    required_permissions = {"POST": ("dental.amend",)}

    def post(self, request, pk):
        data = validated(S.AmendInput, request.data)
        encounters.amend_encounter(self.ctx(), get_object_or_404(DentalEncounter, pk=pk), **data)
        return Response(S.EncounterSerializer(_encounter_qs().get(pk=pk)).data, status=status.HTTP_201_CREATED)


class EncounterDiagnosisView(PermissionedView):
    required_permissions = {"POST": ("dental.write",)}

    def post(self, request, pk):
        data = validated(S.DiagnosisInput, request.data)
        dx = encounters.add_diagnosis(self.ctx(), get_object_or_404(DentalEncounter, pk=pk), data)
        return Response(S.DiagnosisSerializer(dx).data, status=status.HTTP_201_CREATED)


class DiagnosisActionView(PermissionedView):
    required_permissions = {"POST": ("dental.write",)}

    def post(self, request, pk, action):
        dx = get_object_or_404(DentalDiagnosis, pk=pk)
        if action == "remove":
            encounters.remove_diagnosis(self.ctx(), dx)
            return Response(status=status.HTTP_204_NO_CONTENT)
        dx = encounters.resolve_diagnosis(self.ctx(), dx, str(request.data.get("note", "")))
        return Response(S.DiagnosisSerializer(dx).data)


class EncounterFindingsView(PermissionedView):
    required_permissions = {"POST": ("dental.chart.record",)}

    def post(self, request, pk):
        data = validated(S.FindingInput, request.data)
        finding = chart.record_finding(self.ctx(), get_object_or_404(DentalEncounter, pk=pk), data)
        return Response(S.FindingSerializer(chart.findings_qs_all().get(pk=finding.pk)).data,
                        status=status.HTTP_201_CREATED)


class FindingDetailView(PermissionedView):
    required_permissions = {"DELETE": ("dental.chart.record",)}

    def delete(self, request, pk):
        chart.remove_finding(self.ctx(), get_object_or_404(ToothFinding, pk=pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


class FindingActionView(PermissionedView):
    required_permissions = {"POST": AnyOf(("dental.chart.record", "dental.amend"))}

    def post(self, request, pk, action):
        finding = get_object_or_404(ToothFinding, pk=pk)
        if action == "resolve":
            if not request.user.has_permissions(["dental.chart.record"]):
                return Response({"error": {"code": "permission_denied", "message": "You cannot record chart changes."}},
                                status=403)
            enc = get_object_or_404(DentalEncounter, pk=request.data.get("encounter_id"))
            finding = chart.resolve_finding(self.ctx(), finding, enc, str(request.data.get("note", "")))
        else:
            if not request.user.has_permissions(["dental.amend"]):
                return Response({"error": {"code": "permission_denied",
                                           "message": "Only a dentist who may amend records can do this."}}, status=403)
            finding = chart.void_finding(self.ctx(), finding, str(request.data.get("reason", "")))
        return Response(S.FindingSerializer(chart.findings_qs_all().get(pk=finding.pk)).data)


class EncounterPerioView(PermissionedView):
    required_permissions = {"GET": VIEW, "PUT": ("dental.chart.record",)}

    def get(self, request, pk):
        exam = (PeriodontalExam.objects.filter(encounter_id=pk).select_related("examiner", "encounter")
                .prefetch_related("sites", "teeth").first())
        return Response(S.PerioExamSerializer(exam).data if exam else None)

    def put(self, request, pk):
        data = validated(S.PerioInput, request.data)
        version = data.pop("version", None)
        exam = perio.save_exam(self.ctx(), get_object_or_404(DentalEncounter, pk=pk), data, version=version)
        exam = PeriodontalExam.objects.prefetch_related("sites", "teeth").select_related("examiner", "encounter").get(pk=exam.pk)
        return Response(S.PerioExamSerializer(exam).data)


class PerioCompareView(PermissionedView):
    required_permissions = {"GET": VIEW}

    def get(self, request):
        a = get_object_or_404(PeriodontalExam, pk=self.param_uuid("a"))
        b = get_object_or_404(PeriodontalExam, pk=self.param_uuid("b"))
        if a.patient_id != b.patient_id:
            return Response({"error": {"code": "validation_error",
                                       "message": "Both periodontal charts must belong to the same patient."}},
                            status=400)
        if a.created_at > b.created_at:
            a, b = b, a
        _audit_view(self, "dental_perio.compare_view", "patient", a.patient_id, a.patient_id)
        return Response(perio.compare(a, b))


class EncounterPrescriptionView(PermissionedView):
    required_permissions = {"POST": ("prescriptions.create",)}

    def post(self, request, pk):
        from apps.clinical.api import PrescriptionSerializer, RxItemInput
        from apps.clinical.services import create_dental_prescription

        items = validated(RxItemInput, request.data.get("items", []), many=True)
        rx = create_dental_prescription(self.ctx(), get_object_or_404(DentalEncounter, pk=pk), items,
                                        notes=str(request.data.get("notes", ""))[:255])
        return Response(PrescriptionSerializer(_rx_qs().get(pk=rx.pk)).data, status=status.HTTP_201_CREATED)


# ===========================================================================
# Treatment plans
# ===========================================================================
def _plan_qs():
    return TreatmentPlan.objects.select_related("created_by", "patient").prefetch_related(
        "diagnoses",
        Prefetch("items", queryset=TreatmentPlanItem.objects.select_related("procedure", "diagnosis", "assigned_dentist")
                 .prefetch_related("appointments", "procedures").order_by("sequence", "created_at")))


class PatientPlansView(PermissionedView):
    required_permissions = {"GET": VIEW, "POST": ("dental.plan.manage",)}

    def get(self, request, patient_id):
        qs = _plan_qs().filter(patient_id=patient_id).order_by("-created_at")
        return Response(S.PlanSerializer(qs, many=True).data)

    def post(self, request, patient_id):
        data = validated(S.PlanInput, request.data)
        plan = plans.create_plan(self.ctx(), _patient(patient_id), data)
        return Response(S.PlanSerializer(_plan_qs().get(pk=plan.pk)).data, status=status.HTTP_201_CREATED)


class PlanDetailView(PermissionedView):
    required_permissions = {"GET": VIEW, "PATCH": ("dental.plan.manage",)}

    def get(self, request, pk):
        plan = get_object_or_404(_plan_qs(), pk=pk)
        _audit_view(self, "dental_plan.view", "treatment_plan", plan.pk, plan.patient_id)
        return Response(S.PlanSerializer(plan).data)

    def patch(self, request, pk):
        data = validated(S.PlanInput, request.data, partial=True)
        reason = data.pop("reason", "")
        with guarded_edit(TreatmentPlan, pk, request, object_type="treatment_plan", label="treatment plan") as plan:
            plans.update_plan(self.ctx(), plan, data, reason=reason)
        return Response(S.PlanSerializer(_plan_qs().get(pk=pk)).data)


class PlanActionView(PermissionedView):
    required_permissions = {"POST": ("dental.plan.manage",)}

    def post(self, request, pk, action):
        plan = get_object_or_404(TreatmentPlan, pk=pk)
        ctx = self.ctx()
        if action == "items":
            data = validated(S.PlanItemInput, request.data)
            data["assigned_dentist"] = _user(data.pop("assigned_dentist_id", None))
            plans.add_item(ctx, plan, data, reason=data.pop("reason", ""))
        elif action == "present":
            plans.present(ctx, plan)
        elif action == "decision":
            decisions = request.data.get("decisions")
            if not isinstance(decisions, dict):
                raise serializers.ValidationError({"decisions": ["Give a decision per item."]})
            plans.record_decision(ctx, plan, decisions, note=str(request.data.get("note", "")))
        elif action in ("cancel", "expire"):
            plans.close_plan(ctx, plan, status="cancelled" if action == "cancel" else "expired",
                             reason=str(request.data.get("reason", "")))
        else:
            return Response({"error": {"code": "not_found", "message": "Unknown action."}}, status=404)
        return Response(S.PlanSerializer(_plan_qs().get(pk=pk)).data,
                        status=status.HTTP_201_CREATED if action == "items" else status.HTTP_200_OK)


class PlanRevisionsView(PermissionedView):
    required_permissions = {"GET": VIEW}

    def get(self, request, pk):
        plan = get_object_or_404(TreatmentPlan, pk=pk)
        return Response(S.RevisionSerializer(plan.revisions.select_related("created_by"), many=True).data)


class PlanItemView(PermissionedView):
    required_permissions = {"PATCH": ("dental.plan.manage",), "POST": ("dental.plan.manage",)}

    def patch(self, request, pk):
        item = get_object_or_404(TreatmentPlanItem, pk=pk)
        data = validated(S.PlanItemInput, request.data, partial=True)
        if "assigned_dentist_id" in data:
            data["assigned_dentist"] = _user(data.pop("assigned_dentist_id"))
        plans.update_item(self.ctx(), item, data, reason=data.pop("reason", ""))
        return Response(S.PlanSerializer(_plan_qs().get(pk=item.plan_id)).data)

    def post(self, request, pk, action=None):
        item = get_object_or_404(TreatmentPlanItem, pk=pk)
        ctx = self.ctx()
        if action == "remove":
            plans.remove_item(ctx, item, reason=str(request.data.get("reason", "")))
        elif action == "cancel":
            plans.cancel_item(ctx, item, reason=str(request.data.get("reason", "")))
        elif action == "appointments":
            appt = get_object_or_404(Appointment, pk=request.data.get("appointment_id"))
            plans.link_appointment(ctx, item, appt, unlink=bool(request.data.get("unlink")))
        else:
            return Response({"error": {"code": "not_found", "message": "Unknown action."}}, status=404)
        return Response(S.PlanSerializer(_plan_qs().get(pk=item.plan_id)).data)


# ===========================================================================
# Procedure records
# ===========================================================================
def _record_qs():
    return (ProcedureRecord.objects
            .select_related("procedure", "performed_by", "assisted_by", "signed_by", "created_by", "plan_item")
            .prefetch_related("materials__item", "amendments__author"))


class EncounterProceduresView(PermissionedView):
    required_permissions = {"POST": ("dental.procedure.record",)}

    def post(self, request, pk):
        data = validated(S.ProcedureRecordInput, request.data)
        rec = procedures.create_record(self.ctx(), get_object_or_404(DentalEncounter, pk=pk), data)
        return Response(S.ProcedureRecordSerializer(_record_qs().get(pk=rec.pk)).data, status=status.HTTP_201_CREATED)


class ProcedureRecordListView(PermissionedView):
    required_permissions = {"GET": VIEW}

    def get(self, request):
        qs = ProcedureRecord.objects.select_related("procedure", "performed_by")
        for name in ("patient", "visit", "encounter"):
            if v := self.param_uuid(name):
                qs = qs.filter(**{f"{name}_id": v})
        if st := request.query_params.get("status"):
            qs = qs.filter(status=st)
        if self.param_bool("mine"):
            qs = qs.filter(performed_by=request.user)
        return self.paginate(qs.order_by("-created_at"), S.ProcedureRecordListSerializer)


class ProcedureRecordDetailView(PermissionedView):
    required_permissions = {"GET": VIEW, "PATCH": ("dental.procedure.record",)}

    def get(self, request, pk):
        rec = get_object_or_404(_record_qs(), pk=pk)
        _audit_view(self, "dental_procedure.view", "dental_procedure", rec.pk, rec.patient_id)
        return Response(S.ProcedureRecordSerializer(rec).data)

    def patch(self, request, pk):
        data = validated(S.ProcedureUpdateInput, request.data, partial=True)
        if "version" not in data:
            raise serializers.ValidationError({"version": ["Required."]})
        version = data.pop("version")
        procedures.update_record(self.ctx(), get_object_or_404(ProcedureRecord, pk=pk), data, version=version)
        return Response(S.ProcedureRecordSerializer(_record_qs().get(pk=pk)).data)


class ProcedureRecordActionView(PermissionedView):
    required_permissions = {"POST": AnyOf(("dental.procedure.record", "dental.procedure.sign", "dental.amend")),
                            "PUT": ("dental.procedure.record",)}

    def put(self, request, pk, action):
        if action != "materials":
            return Response({"error": {"code": "not_found", "message": "Unknown action."}}, status=404)
        rows = validated(S.MaterialInput, request.data.get("materials", []), many=True)
        procedures.set_materials(self.ctx(), get_object_or_404(ProcedureRecord, pk=pk), rows)
        return Response(S.ProcedureRecordSerializer(_record_qs().get(pk=pk)).data)

    def post(self, request, pk, action):
        rec = get_object_or_404(ProcedureRecord, pk=pk)
        need = {"sign": "dental.procedure.sign", "discard": "dental.procedure.record", "amendments": "dental.amend"}
        if action not in need:
            return Response({"error": {"code": "not_found", "message": "Unknown action."}}, status=404)
        if not request.user.has_permissions([need[action]]):
            return Response({"error": {"code": "permission_denied", "message": "You cannot do this."}}, status=403)
        ctx = self.ctx()
        if action == "sign":
            data = validated(S.SignProcedureInput, request.data)
            procedures.sign_record(ctx, rec, outcome=data["outcome"], reason=data["reason"],
                                   create_recall=data["create_recall"], confirm_charge=data["confirm_charge"])
        elif action == "discard":
            procedures.discard_record(ctx, rec, str(request.data.get("reason", "")))
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            procedures.amend_record(ctx, rec, **validated(S.ProcedureAmendInput, request.data))
        return Response(S.ProcedureRecordSerializer(_record_qs().get(pk=pk)).data)


# ===========================================================================
# Imaging
# ===========================================================================
class PatientImagesView(PermissionedView):
    parser_classes = [MultiPartParser, JSONParser]
    required_permissions = {"GET": ("dental.imaging.view",), "POST": ("dental.imaging.upload",)}

    def get(self, request, patient_id):
        qs = DentalImage.objects.filter(patient_id=patient_id).select_related("uploaded_by", "referring_dentist",
                                                                               "withdrawn_by").prefetch_related(
            "changes__changed_by")
        if not self.param_bool("include_withdrawn"):
            qs = qs.filter(status=DentalImage.Status.ACTIVE)
        if tooth := request.query_params.get("tooth"):
            qs = qs.filter(teeth__contains=[int(tooth)]) if tooth.isdigit() else qs.none()
        return Response(S.ImageSerializer(qs[:300], many=True).data)

    def post(self, request, patient_id):
        patient = _patient(patient_id)
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": ["Choose an image."]})
        from django.conf import settings

        if upload.size > settings.DENTAL_IMAGE_MAX_BYTES:
            raise serializers.ValidationError({"file": ["The file is too large."]})
        raw = dict(request.data.items())
        raw.pop("file", None)
        if isinstance(raw.get("teeth"), str):
            raw["teeth"] = [t for t in raw["teeth"].replace(",", " ").split() if t]
        data = validated(S.ImageMetaInput, raw)
        data["referring_dentist"] = _user(data.pop("referring_dentist_id", None))
        image = imaging.upload(self.ctx(), patient, upload.read(), upload.name, data)
        return Response(S.ImageSerializer(image).data, status=status.HTTP_201_CREATED)


class ImageDetailView(PermissionedView):
    required_permissions = {"GET": ("dental.imaging.view",), "PATCH": ("dental.imaging.manage",)}

    def get(self, request, pk):
        return Response(S.ImageSerializer(get_object_or_404(DentalImage, pk=pk)).data)

    def patch(self, request, pk):
        data = validated(S.ImageMetaInput, request.data, partial=True)
        reason = data.pop("reason", "")
        for k in ("encounter_id", "replaces_id"):
            data.pop(k, None)
        if "referring_dentist_id" in data:
            data["referring_dentist"] = _user(data.pop("referring_dentist_id"))
        image = imaging.update_metadata(self.ctx(), get_object_or_404(DentalImage, pk=pk), data, reason)
        return Response(S.ImageSerializer(image).data)


class ImageFileView(PermissionedView):
    """The image bytes, after the permission check. Never a public path. Every view is audited."""

    required_permissions = {"GET": ("dental.imaging.view",)}

    def get(self, request, pk):
        image = get_object_or_404(DentalImage, pk=pk)
        withdrawn = image.status != DentalImage.Status.ACTIVE
        # A withdrawn image stays out of the clinical record, but whoever manages images can still open it
        # (for example to check what was withdrawn, or for a complaint or legal review).
        if withdrawn and not request.user.has_permissions(["dental.imaging.manage"]):
            raise Http404
        preview = request.query_params.get("preview") == "1"
        fh = imaging.open_file(image, preview=preview)
        record_event(self.ctx(), action="dental_image.view", object_type="patient", object_id=image.patient_id,
                     details={"image": str(image.pk), "preview": preview, **({"withdrawn": True} if withdrawn else {})})
        ctype = "image/jpeg" if preview else image.content_type
        resp = FileResponse(fh, content_type=ctype)
        download = request.query_params.get("download") == "1" or (not preview and image.content_type == "image/tiff")
        name = image.original_name if not preview else f"preview-{image.pk}.jpg"
        resp["Content-Disposition"] = f'{"attachment" if download else "inline"}; filename="{name}"'
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
        resp["Cache-Control"] = "no-store"
        return resp


class ImageWithdrawView(PermissionedView):
    required_permissions = {"POST": ("dental.imaging.manage",)}

    def post(self, request, pk):
        image = imaging.withdraw(self.ctx(), get_object_or_404(DentalImage, pk=pk), str(request.data.get("reason", "")))
        return Response(S.ImageSerializer(image).data)


# ===========================================================================
# Recalls
# ===========================================================================
RECALL_READ = AnyOf(("dental.recall.manage", "dental.view"))


class RecallListView(PermissionedView):
    """The recall worklist (due soon, overdue, booked)."""

    required_permissions = {"GET": RECALL_READ}

    def get(self, request):
        from apps.core.modules import is_enabled

        if not is_enabled("recalls"):
            return Response({"error": {"code": "permission_denied",
                                       "message": "The Recalls and follow-ups module is switched off for this clinic."}},
                            status=403)
        recalls.sync_booked(self.ctx())
        qs = Recall.objects.select_related("patient", "appointment").prefetch_related("contacts__contacted_by")
        st = request.query_params.get("status")
        qs = qs.filter(status=st) if st else qs.filter(status__in=Recall.OPEN)
        if before := self.param_date("due_before"):
            qs = qs.filter(due_date__lte=before)
        if kind := request.query_params.get("kind"):
            qs = qs.filter(kind=kind)
        return self.paginate(qs.order_by("due_date"), S.RecallSerializer)


class PatientRecallsView(PermissionedView):
    required_permissions = {"GET": RECALL_READ, "POST": AnyOf(("dental.recall.manage", "dental.write"))}

    def get(self, request, patient_id):
        qs = Recall.objects.filter(patient_id=patient_id).select_related("patient", "appointment")
        return Response(S.RecallSerializer(qs.order_by("-due_date"), many=True, context={"request": request}).data)

    def post(self, request, patient_id):
        data = validated(S.RecallInput, request.data)
        enc = get_object_or_404(DentalEncounter, pk=data["encounter_id"]) if data.get("encounter_id") else None
        recall = recalls.create_recall(self.ctx(), _patient(patient_id), kind=data["kind"], due_date=data["due_date"],
                                       note=data["note"], source_encounter=enc)
        if recall is None:
            return Response({"error": {"code": "conflict", "message": "The recalls module is switched off."}},
                            status=409)
        return Response(S.RecallSerializer(recall, context={"request": request}).data, status=status.HTTP_201_CREATED)


class RecallActionView(PermissionedView):
    required_permissions = {"POST": ("dental.recall.manage",)}

    def post(self, request, pk, action):
        recall = get_object_or_404(Recall, pk=pk)
        ctx = self.ctx()
        if action == "book":
            recalls.book(ctx, recall, get_object_or_404(Appointment, pk=request.data.get("appointment_id")))
        elif action == "contact":
            recalls.log_contact(ctx, recall, outcome=str(request.data.get("outcome", "")),
                                note=str(request.data.get("note", "")))
        elif action == "status":
            due = None
            if request.data.get("due_date"):
                due = serializers.DateField().to_internal_value(request.data["due_date"])
            recalls.close(ctx, recall, status=str(request.data.get("status", "")),
                          reason=str(request.data.get("reason", "")), new_due_date=due)
        else:
            return Response({"error": {"code": "not_found", "message": "Unknown action."}}, status=404)
        recall = Recall.objects.select_related("patient", "appointment").get(pk=pk)
        return Response(S.RecallSerializer(recall, context={"request": request}).data)


# ===========================================================================
# Dental laboratory cases
# ===========================================================================
LAB_READ = AnyOf(("dental.labcase.manage", "dental.labcase.work"))


def _lab_scope(request, qs):
    """A technician without dental.labcase.manage sees only cases assigned to them."""
    if request.user.has_permissions(["dental.labcase.manage"]):
        return qs
    return qs.filter(technician=request.user)


class LabCaseListView(PermissionedView):
    required_permissions = {"GET": LAB_READ}

    def get(self, request):
        qs = _lab_scope(request, DentalLabCase.objects.select_related("patient", "technician", "requested_by"))
        st = request.query_params.get("status")
        qs = qs.filter(status=st) if st else qs.filter(status__in=DentalLabCase.OPEN)
        if p := self.param_uuid("patient"):
            qs = qs.filter(patient_id=p)
        return self.paginate(qs.prefetch_related("events__actor").order_by("due_date", "-created_at"),
                             S.LabCaseSerializer)


class PatientLabCasesView(PermissionedView):
    required_permissions = {"POST": ("dental.labcase.manage",)}

    def post(self, request, patient_id):
        data = validated(S.LabCaseInput, request.data)
        case = labcases.create_case(self.ctx(), _patient(patient_id), data)
        return Response(S.LabCaseSerializer(case).data, status=status.HTTP_201_CREATED)


class LabCaseDetailView(PermissionedView):
    required_permissions = {"GET": LAB_READ, "POST": LAB_READ}

    def get(self, request, pk):
        case = get_object_or_404(_lab_scope(request, DentalLabCase.objects.all()), pk=pk)
        return Response(S.LabCaseSerializer(case).data)

    def post(self, request, pk, action):
        case = get_object_or_404(_lab_scope(request, DentalLabCase.objects.all()), pk=pk)
        if action == "move":
            labcases.move(self.ctx(), case, status=str(request.data.get("status", "")),
                          note=str(request.data.get("note", "")))
        elif action == "assign":
            if not request.user.has_permissions(["dental.labcase.manage"]):
                return Response({"error": {"code": "permission_denied", "message": "You cannot assign cases."}},
                                status=403)
            labcases.assign(self.ctx(), case, request.data.get("technician_id"))
        else:
            return Response({"error": {"code": "not_found", "message": "Unknown action."}}, status=404)
        return Response(S.LabCaseSerializer(DentalLabCase.objects.get(pk=pk)).data)


class TechnicianListView(PermissionedView):
    required_permissions = {"GET": ("dental.labcase.manage",)}

    def get(self, request):
        from apps.scheduling.api import UserBrief

        users = (User.objects.filter(is_active=True, roles__permissions__code="dental.labcase.work").distinct()
                 .order_by("first_name"))
        return Response(UserBrief(users, many=True).data)


class ClinicianListView(PermissionedView):
    """People who can perform and sign procedures (dentists, hygienists), and dental assistants."""

    required_permissions = {"GET": AnyOf(("dental.view", "dental.plan.manage"))}

    def get(self, request):
        from apps.scheduling.api import UserBrief

        signers = User.objects.filter(is_active=True, roles__permissions__code="dental.procedure.sign").distinct()
        assistants = (User.objects.filter(is_active=True, roles__permissions__code="dental.procedure.record")
                      .exclude(pk__in=signers).distinct())
        return Response({"clinicians": UserBrief(signers.order_by("first_name"), many=True).data,
                         "assistants": UserBrief(assistants.order_by("first_name"), many=True).data})
