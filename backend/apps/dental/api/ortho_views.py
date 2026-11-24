"""Orthodontics API. HTTP only: validate, call services/ortho.py, serialise. Every view declares its permissions."""

from __future__ import annotations

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response

from apps.core.api import PermissionedView
from apps.core.concurrency import expected_version
from apps.core.exceptions import ConflictError
from apps.core.modules import is_enabled
from apps.core.permissions import AnyOf
from apps.patients.models import Patient

from ..models import DentalEncounter, OrthoAssessment, OrthoCase, OrthoInstalment, OrthoVisit
from ..services import ortho
from . import ortho_serializers as OS
from .views import _audit_view

VIEW = ("dental.view",)
MANAGE = ("dental.ortho.manage",)


def _on() -> None:
    if not is_enabled("orthodontics"):
        raise ConflictError("Orthodontics is switched off for this clinic.")


def _cases():
    return (OrthoCase.objects.select_related("patient", "orthodontist", "created_by", "assessment__recorded_by",
                                             "assessment__encounter", "plan")
            .prefetch_related(Prefetch("visits", OrthoVisit.objects.select_related("visit", "performed_by",
                                                                                   "voided_by")),
                              "instalments", "events__actor"))


def _case_out(case_id) -> dict:
    return OS.OrthoCaseSerializer(_cases().get(pk=case_id)).data


class EncounterOrthoAssessmentView(PermissionedView):
    required_permissions = {"GET": VIEW, "PUT": MANAGE}

    def get(self, request, pk):
        _on()
        assessment = (OrthoAssessment.objects.select_related("recorded_by", "encounter")
                      .filter(encounter_id=pk).first())
        return Response(OS.OrthoAssessmentSerializer(assessment).data if assessment else None)

    def put(self, request, pk):
        data = dict(request.data)
        data.pop("row_version", None)
        assessment = ortho.save_assessment(self.ctx(), get_object_or_404(DentalEncounter, pk=pk), data,
                                           expected_version(request))
        return Response(OS.OrthoAssessmentSerializer(
            OrthoAssessment.objects.select_related("recorded_by", "encounter").get(pk=assessment.pk)).data)


class PatientOrthoView(PermissionedView):
    """The patient's orthodontic cases and assessments. Reading is audited like other dental records."""

    required_permissions = {"GET": VIEW}

    def get(self, request, patient_id):
        _on()
        patient = get_object_or_404(Patient, pk=patient_id)
        _audit_view(self, "dental_ortho.view", "patient", patient.pk, patient.pk)
        cases = _cases().filter(patient=patient)
        assessments = (OrthoAssessment.objects.filter(patient=patient).select_related("recorded_by", "encounter")
                       .order_by("-created_at"))
        return Response({"cases": OS.OrthoCaseSerializer(cases, many=True).data,
                         "assessments": OS.OrthoAssessmentSerializer(assessments, many=True).data})


class PatientOrthoCasesView(PermissionedView):
    required_permissions = {"POST": MANAGE}

    def post(self, request, patient_id):
        case = ortho.create_case(self.ctx(), get_object_or_404(Patient, pk=patient_id), dict(request.data))
        return Response(_case_out(case.pk), status=status.HTTP_201_CREATED)


class OrthoCaseListView(PermissionedView):
    """Orthodontic patients: open cases by default, with the last visit."""

    required_permissions = {"GET": VIEW}

    def get(self, request):
        _on()
        qs = OrthoCase.objects.select_related("patient", "orthodontist").prefetch_related(
            Prefetch("visits", OrthoVisit.objects.select_related("visit")))
        st = request.query_params.get("status")
        qs = qs.filter(status=st) if st else qs.filter(status__in=OrthoCase.OPEN)
        if self.param_bool("mine"):
            qs = qs.filter(orthodontist=request.user)
        return self.paginate(qs.order_by("patient__last_name", "patient__first_name"), OS.OrthoCaseBriefSerializer)


class OrthoCaseDetailView(PermissionedView):
    required_permissions = {"GET": VIEW, "PATCH": MANAGE, "POST": MANAGE}

    def get(self, request, pk):
        _on()
        case = get_object_or_404(OrthoCase, pk=pk)
        _audit_view(self, "dental_ortho.view", "ortho_case", case.pk, case.patient_id)
        return Response(_case_out(pk))

    def patch(self, request, pk):
        case = get_object_or_404(OrthoCase, pk=pk)
        data = dict(request.data)
        data.pop("row_version", None)
        ortho.update_case(self.ctx(), case, data, expected_version(request))
        return Response(_case_out(pk))

    def post(self, request, pk, action):
        case = get_object_or_404(OrthoCase, pk=pk)
        data = dict(request.data)
        if action == "visits":
            ov = ortho.record_visit(self.ctx(), case, data)
            return Response({"visit": OS.OrthoVisitSerializer(
                OrthoVisit.objects.select_related("visit", "performed_by").get(pk=ov.pk)).data,
                "case": _case_out(pk)}, status=status.HTTP_201_CREATED)
        if action == "billing":
            data["version"] = expected_version(request)
            ortho.change_billing(self.ctx(), case, data)
        elif action in ("start", "retention", "complete", "discontinue"):
            ortho.change_status(self.ctx(), case, action, reason=str(data.get("reason") or ""),
                                on_date=ortho.parse_past_date(data.get("on_date"), "on_date") if action == "retention"
                                else None)
        else:
            return Response({"error": {"code": "not_found", "message": "Unknown action."}}, status=404)
        return Response(_case_out(pk))


class OrthoVisitVoidView(PermissionedView):
    required_permissions = {"POST": AnyOf(("dental.ortho.manage", "dental.amend"))}

    def post(self, request, pk):
        ov = ortho.void_visit(self.ctx(), get_object_or_404(OrthoVisit, pk=pk), str(request.data.get("reason") or ""))
        return Response(_case_out(ov.case_id))


class OrthoInstalmentForwardView(PermissionedView):
    """Bring an instalment forward to today so the cashier can take it early (dentist or cashier)."""

    required_permissions = {"POST": AnyOf(("dental.ortho.manage", "billing.invoice"))}

    def post(self, request, pk):
        inst = ortho.bring_forward(self.ctx(), get_object_or_404(OrthoInstalment, pk=pk),
                                   str(request.data.get("reason") or ""))
        if request.user.has_permissions(["dental.view"]):
            return Response(_case_out(inst.case_id))
        return Response({"id": str(inst.pk), "due_date": inst.due_date})
