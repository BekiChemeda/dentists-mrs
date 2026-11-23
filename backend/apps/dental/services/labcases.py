"""Dental laboratory cases: crowns, bridges, dentures sent to the technician. The technician sees name and MRN only."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError, PermissionDeniedError
from apps.core.numbering import next_number
from apps.notifications.services import notify_user
from apps.patients.models import Patient

from ..models import DentalLabCase, DentalLabCaseEvent, TreatmentPlanItem
from .common import check_teeth_list, same_patient

L = DentalLabCase.Status
# Who may move a case where: the technician works on it; the dentist side requests, delivers and cancels.
TECH_MOVES = {L.REQUESTED: {L.IN_PROGRESS}, L.IN_PROGRESS: {L.READY}}
DENTIST_MOVES = {L.READY: {L.DELIVERED, L.IN_PROGRESS}, L.REQUESTED: {L.CANCELLED}, L.IN_PROGRESS: {L.CANCELLED},
                 }


def _technician(pk):
    if not pk:
        return None
    user = User.objects.filter(pk=pk, is_active=True).first()
    if user is None or not user.has_permissions(["dental.labcase.work"]):
        raise BusinessValidationError("Choose a dental technician.", fields={"technician_id": ["Not a technician."]})
    return user


@transaction.atomic
def create_case(ctx: ActorContext, patient: Patient, data: dict) -> DentalLabCase:
    if data.get("case_type") not in DentalLabCase.CaseType.values:
        raise BusinessValidationError("Choose the type of work.", fields={"case_type": ["Required."]})
    instructions = (data.get("instructions") or "").strip()
    if not instructions:
        raise BusinessValidationError("Write the instructions for the technician.", fields={"instructions": ["Required."]})
    plan_item = None
    if data.get("plan_item_id"):
        plan_item = TreatmentPlanItem.objects.select_related("plan").filter(pk=data["plan_item_id"]).first()
        if plan_item is None:
            raise BusinessValidationError("Unknown plan item.", fields={"plan_item_id": ["Not found."]})
        same_patient(plan_item.plan, patient.pk, "plan_item_id")
    technician = _technician(data.get("technician_id"))
    year = timezone.localdate().year
    case = DentalLabCase.objects.create(
        number=f"LC-{year}-{next_number('dental_labcase', str(year)):05d}", patient=patient, plan_item=plan_item,
        case_type=data["case_type"], teeth=check_teeth_list(data.get("teeth")), shade=(data.get("shade") or "")[:30],
        instructions=instructions, technician=technician, due_date=data.get("due_date"), requested_by=ctx.user)
    DentalLabCaseEvent.objects.create(case=case, status=L.REQUESTED, note="Requested", actor=ctx.user)
    record_event(ctx, action="dental_labcase.create", object_type="dental_labcase", object_id=case.pk,
                 details={"number": case.number, "type": case.case_type,
                          "technician": technician.username if technician else None})
    if technician:
        # No patient details in the notification: the technician opens the case to see name and MRN.
        notify_user(technician, kind="lab_case", title=f"New laboratory case {case.number}",
                    body=case.get_case_type_display(), link=f"/dental/lab-cases?case={case.pk}")
    return case


@transaction.atomic
def move(ctx: ActorContext, case: DentalLabCase, *, status: str, note: str = "") -> DentalLabCase:
    case = DentalLabCase.objects.select_for_update().get(pk=case.pk)
    user = ctx.user
    is_tech = user.has_permissions(["dental.labcase.work"]) and case.technician_id == user.pk
    is_dentist = user.has_permissions(["dental.labcase.manage"])
    allowed = (TECH_MOVES.get(case.status, set()) if is_tech else set()) | \
              (DENTIST_MOVES.get(case.status, set()) if is_dentist else set())
    if status not in allowed:
        if not (is_tech or is_dentist):
            raise PermissionDeniedError("This case is not assigned to you.")
        raise ConflictError(f"A case that is {case.get_status_display().lower()} cannot move to "
                            f"{DentalLabCase.Status(status).label.lower() if status in L.values else status}.")
    if status in (L.CANCELLED,) and not note.strip():
        raise BusinessValidationError("Give the reason.", fields={"note": ["Required."]})
    old = case.status
    case.status = status
    if status == L.DELIVERED:
        case.delivered_at = timezone.now()
    case.save()
    DentalLabCaseEvent.objects.create(case=case, status=status, note=note.strip()[:255], actor=user)
    record_event(ctx, action="dental_labcase.status", object_type="dental_labcase", object_id=case.pk,
                 details={"from": old, "to": status})
    if status == L.READY:
        notify_user(case.requested_by, kind="lab_case", title=f"Laboratory case {case.number} is ready",
                    body=case.get_case_type_display(), link=f"/dental/lab-cases?case={case.pk}")
    return case


@transaction.atomic
def assign(ctx: ActorContext, case: DentalLabCase, technician_id) -> DentalLabCase:
    case = DentalLabCase.objects.select_for_update().get(pk=case.pk)
    if case.status not in DentalLabCase.OPEN:
        raise ConflictError("This case is closed.")
    case.technician = _technician(technician_id)
    case.save(update_fields=["technician", "updated_at"])
    record_event(ctx, action="dental_labcase.assign", object_type="dental_labcase", object_id=case.pk,
                 details={"technician": case.technician.username if case.technician else None})
    return case
