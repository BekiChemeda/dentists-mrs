"""
Treatment plans (docs/dental/clinical-workflows.md#treatment-plan).

A plan belongs to the patient and spans visits. Once presented, every change needs a reason and writes a full
snapshot (TreatmentPlanRevision), so what was originally proposed is never lost. An item is completed only by a
signed procedure record, never by an appointment or an invoice.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.core.numbering import next_number
from apps.patients.models import Patient
from apps.scheduling.models import Appointment

from ..models import (
    DentalDiagnosis, DentalEncounter, DentalProcedure, TreatmentPlan, TreatmentPlanItem, TreatmentPlanRevision,
)
from .common import location, same_patient

P, I = TreatmentPlan.Status, TreatmentPlanItem.Status
ITEM_EDITABLE = ("sequence", "priority", "notes", "estimated_fee", "sessions_planned", "estimated_minutes")


def _money(value) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001 - any unparsable input is a validation error
        raise BusinessValidationError("Enter an amount in birr.", fields={"estimated_fee": ["Invalid."]}) from None
    if amount < 0:
        raise BusinessValidationError("The estimate cannot be negative.", fields={"estimated_fee": [">= 0."]})
    return amount


def snapshot(plan: TreatmentPlan) -> dict:
    items = plan.items.select_related("procedure", "diagnosis", "assigned_dentist").order_by("sequence", "created_at")
    return {
        "number": plan.number, "title": plan.title, "clinical_reason": plan.clinical_reason, "status": plan.status,
        "review_date": plan.review_date.isoformat() if plan.review_date else None, "notes": plan.notes,
        "diagnoses": [f"{d.code} {d.term_text} ({d.location_label})" for d in plan.diagnoses.all()],
        "estimated_total": str(estimated_total(plan)),
        "items": [{"id": str(i.pk), "sequence": i.sequence, "procedure": i.procedure.code,
                   "procedure_name": i.procedure.name, "where": i.location_label, "status": i.status,
                   "priority": i.priority, "sessions_planned": i.sessions_planned,
                   "estimated_fee": str(i.estimated_fee), "notes": i.notes,
                   "diagnosis": f"{i.diagnosis.code} {i.diagnosis.term_text}" if i.diagnosis else None,
                   "assigned_dentist": i.assigned_dentist.full_name if i.assigned_dentist else None}
                  for i in items],
    }


def estimated_total(plan: TreatmentPlan) -> Decimal:
    """Estimate of what the patient agreed to (accepted, in progress or completed items) — or of everything
    proposed while no decision is recorded. Never an invoice."""
    items = [i for i in plan.items.all() if i.status != I.CANCELLED]
    agreed = [i for i in items if i.status in (I.ACCEPTED, I.IN_PROGRESS, I.COMPLETED)]
    chosen = agreed if agreed else [i for i in items if i.status == I.PROPOSED]
    return sum((i.estimated_fee for i in chosen), Decimal("0.00"))


def _revise(ctx, plan: TreatmentPlan, reason: str) -> None:
    """After presentation, every change is a new revision with a reason and a full snapshot."""
    if plan.revision == 0:
        return
    if not (reason or "").strip():
        raise BusinessValidationError("This plan was already presented. Give the reason for the change.",
                                      fields={"reason": ["Required."]})
    plan.revision += 1
    TreatmentPlan.objects.filter(pk=plan.pk).update(revision=plan.revision)
    TreatmentPlanRevision.objects.create(plan=plan, revision=plan.revision, reason=reason.strip()[:255],
                                         snapshot=snapshot(plan), created_by=ctx.user)


def derive_status(plan: TreatmentPlan) -> str:
    """The plan's status follows its items, except draft, cancelled and expired, which are set explicitly."""
    if plan.status in (P.DRAFT, P.CANCELLED, P.EXPIRED):
        return plan.status
    items = [i.status for i in plan.items.all() if i.status != I.CANCELLED]
    if not items:
        return plan.status
    started = any(s in (I.IN_PROGRESS, I.COMPLETED) for s in items)
    if started:
        # A deferred item is still outstanding: the patient may come back for it, and a completed plan can no
        # longer change. The plan stays in progress until it is done, cancelled or declined.
        open_work = any(s in (I.ACCEPTED, I.IN_PROGRESS, I.PROPOSED, I.DEFERRED) for s in items)
        return P.IN_PROGRESS if open_work else P.COMPLETED
    if any(s == I.PROPOSED for s in items):
        return P.PRESENTED
    accepted = sum(1 for s in items if s == I.ACCEPTED)
    if accepted == len(items):
        return P.ACCEPTED
    if accepted:
        return P.PARTIALLY_ACCEPTED
    if any(s == I.DEFERRED for s in items):
        return P.DEFERRED
    return P.DECLINED


def refresh_status(ctx, plan: TreatmentPlan) -> TreatmentPlan:
    new = derive_status(plan)
    if new != plan.status:
        old = plan.status
        plan.status = new
        plan.save(update_fields=["status", "updated_at"])
        record_event(ctx, action="dental_plan.status", object_type="treatment_plan", object_id=plan.pk,
                     details={"from": old, "to": new})
    return plan


def _lock(plan: TreatmentPlan) -> TreatmentPlan:
    return TreatmentPlan.objects.select_for_update().get(pk=plan.pk)


def lock_item(item_id) -> tuple[TreatmentPlanItem, TreatmentPlan]:
    """
    Lock a plan item and its plan. Always the plan first, then the item: every path that locks both must use this
    order, or two people working on the same plan can deadlock each other.
    """
    plan_id = TreatmentPlanItem.objects.values_list("plan_id", flat=True).get(pk=item_id)
    plan = TreatmentPlan.objects.select_for_update().get(pk=plan_id)
    # of=self: lock the item row only, never the procedure catalogue row every other signing also reads.
    item = (TreatmentPlanItem.objects.select_for_update(of=("self",)).select_related("plan", "procedure")
            .get(pk=item_id))
    return item, plan


def _has_unsigned_record(item: TreatmentPlanItem) -> bool:
    return item.procedures.filter(status="draft").exists()


def _require_open(plan: TreatmentPlan) -> None:
    if plan.status in (P.COMPLETED, P.CANCELLED, P.EXPIRED):
        raise ConflictError(f"This plan is {plan.get_status_display().lower()}. Start a new plan for further "
                            "treatment.")


def _diagnoses(ids, patient_id) -> list[DentalDiagnosis]:
    rows = list(DentalDiagnosis.objects.filter(pk__in=ids or [], is_removed=False))
    if len(rows) != len(set(ids or [])):
        raise BusinessValidationError("Unknown diagnosis.", fields={"diagnosis_ids": ["Not found."]})
    for d in rows:
        same_patient(d, patient_id, "diagnosis_ids")
    return rows


# ---------------------------------------------------------------------------
@transaction.atomic
def create_plan(ctx: ActorContext, patient: Patient, data: dict) -> TreatmentPlan:
    from apps.patients.services import require_active

    require_active(patient)
    title = (data.get("title") or "").strip()
    if not title:
        raise BusinessValidationError("Give the plan a short title.", fields={"title": ["Required."]})
    encounter = None
    if data.get("encounter_id"):
        encounter = DentalEncounter.objects.filter(pk=data["encounter_id"]).first()
        if encounter is None:
            raise BusinessValidationError("Unknown examination.", fields={"encounter_id": ["Not found."]})
        same_patient(encounter, patient.pk, "encounter_id")
    diagnoses = _diagnoses(data.get("diagnosis_ids"), patient.pk)
    year = timezone.localdate().year
    plan = TreatmentPlan.objects.create(
        number=f"TP-{year}-{next_number('dental_plan', str(year)):05d}", patient=patient, created_by=ctx.user,
        encounter=encounter, title=title[:150], clinical_reason=(data.get("clinical_reason") or "").strip(),
        review_date=data.get("review_date"), notes=(data.get("notes") or "").strip())
    plan.diagnoses.set(diagnoses)
    record_event(ctx, action="dental_plan.create", object_type="treatment_plan", object_id=plan.pk,
                 details={"patient": str(patient.pk), "number": plan.number})
    return plan


@transaction.atomic
def update_plan(ctx: ActorContext, plan: TreatmentPlan, data: dict, *, reason: str = "") -> TreatmentPlan:
    """Called inside guarded_edit (version check, lock)."""
    _require_open(plan)
    changed = []
    for key in ("title", "clinical_reason", "notes"):
        if key in data and getattr(plan, key) != (data[key] or "").strip():
            setattr(plan, key, (data[key] or "").strip())
            changed.append(key)
    if "review_date" in data and plan.review_date != data["review_date"]:
        plan.review_date = data["review_date"]
        changed.append("review_date")
    if not plan.title:
        raise BusinessValidationError("Give the plan a short title.", fields={"title": ["Required."]})
    if "diagnosis_ids" in data:
        new = _diagnoses(data["diagnosis_ids"], plan.patient_id)
        if {d.pk for d in new} != set(plan.diagnoses.values_list("pk", flat=True)):
            plan.diagnoses.set(new)
            changed.append("diagnoses")
    if changed:
        plan.save()
        clinical = {"clinical_reason", "diagnoses"} & set(changed)
        if clinical:
            _revise(ctx, plan, reason)
        record_event(ctx, action="dental_plan.update", object_type="treatment_plan", object_id=plan.pk,
                     details={"fields": changed, **({"reason": reason.strip()} if reason.strip() else {})})
    return plan


def _clean_item_location(procedure: DentalProcedure, data: dict) -> dict:
    req = procedure.tooth_requirement
    if req == DentalProcedure.ToothRequirement.REQUIRED:
        scopes = ("tooth", "surfaces") if procedure.surfaces_allowed else ("tooth",)
        return location(data, tooth_required=True, allowed_scopes=scopes)
    if req == DentalProcedure.ToothRequirement.NONE:
        return location(data, allowed_scopes=("region", "mouth"))
    scopes = ("tooth", "surfaces", "region", "mouth") if procedure.surfaces_allowed else ("tooth", "region", "mouth")
    return location(data, allowed_scopes=scopes)


@transaction.atomic
def add_item(ctx: ActorContext, plan: TreatmentPlan, data: dict, *, reason: str = "") -> TreatmentPlanItem:
    plan = _lock(plan)
    _require_open(plan)
    procedure = DentalProcedure.objects.filter(pk=data.get("procedure_id"), is_active=True).first()
    if procedure is None:
        raise BusinessValidationError("Choose a procedure from the catalogue.", fields={"procedure_id": ["Required."]})
    where = _clean_item_location(procedure, data)
    diagnosis = None
    if data.get("diagnosis_id"):
        diagnosis = DentalDiagnosis.objects.filter(pk=data["diagnosis_id"], is_removed=False).first()
        if diagnosis is None:
            raise BusinessValidationError("Unknown diagnosis.", fields={"diagnosis_id": ["Not found."]})
        same_patient(diagnosis, plan.patient_id, "diagnosis_id")
    sessions = data.get("sessions_planned") or procedure.typical_sessions
    if data.get("estimated_fee") in (None, ""):
        # A per-session procedure is charged for every session, so the default estimate covers all of them.
        per_session = procedure.billing_mode == DentalProcedure.BillingMode.PER_SESSION
        fee = procedure.price * sessions if per_session else procedure.price
    else:
        fee = _money(data["estimated_fee"])
    sequence = data.get("sequence") or (max((i.sequence for i in plan.items.all()), default=0) + 1)
    item = TreatmentPlanItem.objects.create(
        plan=plan, sequence=sequence, procedure=procedure, diagnosis=diagnosis,
        priority=data.get("priority") or TreatmentPlanItem.Priority.ROUTINE,
        sessions_planned=sessions,
        estimated_minutes=data.get("estimated_minutes") or procedure.default_minutes, estimated_fee=fee,
        assigned_dentist=data.get("assigned_dentist"), notes=(data.get("notes") or "").strip()[:255], **where)
    _revise(ctx, plan, reason)
    record_event(ctx, action="dental_plan.item_add", object_type="treatment_plan", object_id=plan.pk,
                 details={"item": str(item.pk), "procedure": procedure.code, "where": item.location_label,
                          "fee": str(fee)})
    refresh_status(ctx, plan)
    return item


@transaction.atomic
def update_item(ctx: ActorContext, item: TreatmentPlanItem, data: dict, *, reason: str = "") -> TreatmentPlanItem:
    item, plan = lock_item(item.pk)
    _require_open(plan)
    if item.status in (I.COMPLETED, I.CANCELLED):
        raise ConflictError("This item is finished and cannot be changed.")
    changed = {}
    for key in ITEM_EDITABLE:
        if key not in data or data[key] is None:
            continue
        value = _money(data[key]) if key == "estimated_fee" else data[key]
        if key == "notes":
            value = (value or "").strip()[:255]
        if getattr(item, key) != value:
            changed[key] = [str(getattr(item, key)), str(value)]
            setattr(item, key, value)
    if "assigned_dentist" in data and item.assigned_dentist != data["assigned_dentist"]:
        changed["assigned_dentist"] = [str(item.assigned_dentist_id), str(getattr(data["assigned_dentist"], "pk", ""))]
        item.assigned_dentist = data["assigned_dentist"]
    if any(k in data for k in ("scope", "tooth", "surfaces", "region")):
        if item.procedures.exists():
            raise ConflictError("Work was already recorded against this item; its tooth cannot change.")
        where = _clean_item_location(item.procedure, {**{"scope": item.scope, "tooth": item.tooth,
                                                         "surfaces": item.surfaces, "region": item.region}, **data})
        for k, v in where.items():
            if getattr(item, k) != v:
                changed[k] = [str(getattr(item, k)), str(v)]
                setattr(item, k, v)
    if not changed:
        return item
    item.save()
    _revise(ctx, plan, reason)
    record_event(ctx, action="dental_plan.item_update", object_type="treatment_plan", object_id=plan.pk,
                 details={"item": str(item.pk), "changes": changed,
                          **({"reason": reason.strip()} if reason.strip() else {})})
    return item


@transaction.atomic
def remove_item(ctx: ActorContext, item: TreatmentPlanItem, *, reason: str = "") -> None:
    """Draft plan: the item is deleted. Presented plan: the item is cancelled (kept, with the reason)."""
    item, plan = lock_item(item.pk)
    _require_open(plan)
    if item.procedures.exists() or item.status in (I.IN_PROGRESS, I.COMPLETED):
        raise ConflictError("Work was already recorded against this item. Cancel the remaining sessions instead.")
    if plan.status == P.DRAFT and plan.revision == 0:
        record_event(ctx, action="dental_plan.item_remove", object_type="treatment_plan", object_id=plan.pk,
                     details={"item": str(item.pk), "procedure": item.procedure.code})
        item.appointments.clear()
        item.delete()
        return
    cancel_item(ctx, item, reason=reason)


@transaction.atomic
def cancel_item(ctx: ActorContext, item: TreatmentPlanItem, *, reason: str) -> TreatmentPlanItem:
    item, plan = lock_item(item.pk)
    _require_open(plan)
    if item.status in (I.COMPLETED, I.CANCELLED):
        raise ConflictError("This item is already finished.")
    if _has_unsigned_record(item):
        raise ConflictError(f"An unsigned procedure record is open for {item.procedure.name}. Sign it or discard "
                            "it before cancelling the item.")
    if not reason.strip():
        raise BusinessValidationError("Give the reason.", fields={"reason": ["Required."]})
    item.status, item.cancel_reason = I.CANCELLED, reason.strip()[:255]
    item.save(update_fields=["status", "cancel_reason", "updated_at"])
    _revise(ctx, plan, reason)
    record_event(ctx, action="dental_plan.item_cancel", object_type="treatment_plan", object_id=plan.pk,
                 details={"item": str(item.pk), "reason": item.cancel_reason})
    refresh_status(ctx, plan)
    return item


@transaction.atomic
def present(ctx: ActorContext, plan: TreatmentPlan) -> TreatmentPlan:
    plan = _lock(plan)
    if plan.status not in (P.DRAFT, P.PRESENTED, P.DEFERRED, P.DECLINED):
        raise ConflictError("Only a draft, deferred or declined plan is presented (again). Add items to an accepted "
                            "plan and record the patient's decision for them.")
    if not plan.items.exclude(status=I.CANCELLED).exists():
        raise BusinessValidationError("Add at least one item before presenting the plan.", fields={"items": ["Empty."]})
    plan.items.filter(status__in=[I.DEFERRED, I.DECLINED]).update(status=I.PROPOSED, decision_at=None)
    plan.status, plan.presented_at = P.PRESENTED, timezone.now()
    plan.revision += 1
    plan.save()
    TreatmentPlanRevision.objects.create(plan=plan, revision=plan.revision,
                                         reason="Presented to the patient" if plan.revision == 1 else "Presented again",
                                         snapshot=snapshot(plan), created_by=ctx.user)
    record_event(ctx, action="dental_plan.present", object_type="treatment_plan", object_id=plan.pk,
                 details={"revision": plan.revision, "estimated_total": str(estimated_total(plan))})
    return plan


@transaction.atomic
def record_decision(ctx: ActorContext, plan: TreatmentPlan, decisions: dict, *, note: str = "") -> TreatmentPlan:
    """
    The patient's decision on each proposed item: accepted, declined or deferred. This records the discussion; it
    is not a consent form (review R-07).
    """
    plan = _lock(plan)
    if plan.status in (P.DRAFT,):
        raise ConflictError("Present the plan to the patient first.")
    _require_open(plan)
    if not decisions:
        raise BusinessValidationError("Record a decision for at least one item.", fields={"decisions": ["Required."]})
    items = {str(i.pk): i for i in plan.items.select_for_update()}
    allowed = {I.ACCEPTED, I.DECLINED, I.DEFERRED}
    now = timezone.now()
    for item_id, decision in decisions.items():
        item = items.get(str(item_id))
        if item is None:
            raise BusinessValidationError("Unknown item.", fields={"decisions": [f"{item_id} is not on this plan."]})
        if decision not in allowed:
            raise BusinessValidationError("Accepted, declined or deferred.", fields={"decisions": [str(decision)]})
        if item.status not in (I.PROPOSED, I.DEFERRED, I.DECLINED, I.ACCEPTED):
            raise ConflictError(f"{item.procedure.name} is already {item.get_status_display().lower()}.")
        if decision != item.status and decision != I.ACCEPTED and _has_unsigned_record(item):
            raise ConflictError(f"An unsigned procedure record is open for {item.procedure.name}. Sign it or "
                                "discard it before recording that the patient declined or deferred it.")
        item.status, item.decision_at = decision, now
        item.save(update_fields=["status", "decision_at", "updated_at"])
    plan.decision_at, plan.decision_recorded_by = now, ctx.user
    if note.strip():
        plan.decision_note = (plan.decision_note + "\n" if plan.decision_note else "") + note.strip()
    plan.save()
    record_event(ctx, action="dental_plan.decision", object_type="treatment_plan", object_id=plan.pk,
                 details={"decisions": {k: v for k, v in decisions.items()}})
    refresh_status(ctx, plan)
    return plan


@transaction.atomic
def close_plan(ctx: ActorContext, plan: TreatmentPlan, *, status: str, reason: str) -> TreatmentPlan:
    """Cancel (any open plan) or mark expired (a presented or deferred plan the patient never decided on)."""
    plan = _lock(plan)
    _require_open(plan)
    if not reason.strip():
        raise BusinessValidationError("Give the reason.", fields={"reason": ["Required."]})
    if status == P.EXPIRED and plan.status not in (P.PRESENTED, P.DEFERRED):
        raise ConflictError("Only a presented or deferred plan can expire.")
    if status not in (P.CANCELLED, P.EXPIRED):
        raise BusinessValidationError("Cancel or expire.")
    if plan.items.filter(procedures__status="draft").exists():
        raise ConflictError("A procedure record for this plan is still unsigned. Sign or discard it first.")
    plan.items.filter(status__in=[I.PROPOSED, I.ACCEPTED, I.DEFERRED, I.IN_PROGRESS]).update(
        status=I.CANCELLED, cancel_reason=f"Plan {status}: {reason.strip()}"[:255])
    plan.status, plan.cancel_reason = status, reason.strip()[:255]
    plan.save()
    if plan.revision:
        plan.revision += 1
        TreatmentPlan.objects.filter(pk=plan.pk).update(revision=plan.revision)
        TreatmentPlanRevision.objects.create(plan=plan, revision=plan.revision, reason=f"{status}: {reason.strip()}"[:255],
                                             snapshot=snapshot(plan), created_by=ctx.user)
    record_event(ctx, action=f"dental_plan.{status}", object_type="treatment_plan", object_id=plan.pk,
                 details={"reason": plan.cancel_reason})
    return plan


@transaction.atomic
def link_appointment(ctx: ActorContext, item: TreatmentPlanItem, appointment: Appointment, *,
                     unlink: bool = False) -> TreatmentPlanItem:
    """Plan an item for a booked appointment. Booking never changes the item's status."""
    item, _plan = lock_item(item.pk)
    if appointment.patient_id != item.plan.patient_id:
        raise BusinessValidationError("The appointment is for another patient.", fields={"appointment_id": ["Wrong patient."]})
    if unlink:
        item.appointments.remove(appointment)
    else:
        _require_open(item.plan)
        if item.status in (I.COMPLETED, I.CANCELLED, I.DECLINED):
            raise ConflictError("This item is not waiting to be done.")
        item.appointments.add(appointment)
    record_event(ctx, action="dental_plan.item_unlink" if unlink else "dental_plan.item_link",
                 object_type="treatment_plan", object_id=item.plan_id,
                 details={"item": str(item.pk), "appointment": str(appointment.pk)})
    return item


def on_procedure_signed(ctx, item: TreatmentPlanItem, record_status: str) -> None:
    """Called by procedures.sign_record inside its transaction (which already holds the plan and item locks)."""
    item, plan = lock_item(item.pk)
    if record_status == "completed":
        item.status = I.COMPLETED
    elif record_status == "session_completed" and item.status != I.COMPLETED:
        item.status = I.IN_PROGRESS
    else:
        return
    item.save(update_fields=["status", "updated_at"])
    refresh_status(ctx, plan)
