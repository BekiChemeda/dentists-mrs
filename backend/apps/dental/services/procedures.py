"""
Procedure records: what was actually done, by whom, on which tooth, with which materials.

Planned (plan item), booked (appointment), performed (this record) and billed (invoice line) are separate records.
Signing a record copies the catalogue price, deducts materials from stock (FEFO ledger), updates the plan item and
creates the follow-up recall. A record that says "not performed" is never billed and uses no stock.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError, PermissionDeniedError
from apps.core.numbering import next_number
from apps.inventory.models import Item
from apps.inventory.services import InsufficientStock, allocate_fefo
from apps.scheduling.services import visit_event

from ..models import (
    DentalEncounter, DentalProcedure, ProcedureAmendment, ProcedureMaterial, ProcedureRecord, TreatmentPlanItem,
)
from .common import check_amend_author, open_encounter, same_patient
from .plans import _clean_item_location, lock_item, on_procedure_signed

S = ProcedureRecord.Status


def _performer(user_id) -> User:
    user = User.objects.filter(pk=user_id, is_active=True).first() if user_id else None
    if user is None or not user.has_permissions(["dental.procedure.sign"]):
        raise BusinessValidationError("Choose the clinician who performs the procedure.",
                                      fields={"performed_by_id": ["Must be able to sign procedure records."]})
    return user


def _check_role_policy(procedure: DentalProcedure, performer: User) -> None:
    allowed = set(procedure.performer_roles or [])
    if allowed and not allowed & set(performer.roles.values_list("code", flat=True)):
        raise PermissionDeniedError(f"Clinic policy: {procedure.name} is performed only by "
                                    f"{', '.join(sorted(allowed))}.")


def _lock_draft(record: ProcedureRecord) -> ProcedureRecord:
    record = ProcedureRecord.objects.select_for_update().select_related("procedure", "encounter").get(pk=record.pk)
    if record.status != S.DRAFT:
        raise ConflictError("This procedure record is signed. Corrections are made with an amendment.")
    return record


@transaction.atomic
def create_record(ctx: ActorContext, encounter: DentalEncounter, data: dict) -> ProcedureRecord:
    enc = open_encounter(encounter)
    plan_item = None
    if data.get("plan_item_id"):
        if not TreatmentPlanItem.objects.filter(pk=data["plan_item_id"]).exists():
            raise BusinessValidationError("Unknown plan item.", fields={"plan_item_id": ["Not found."]})
        plan_item, _plan = lock_item(data["plan_item_id"])
        same_patient(plan_item.plan, enc.patient_id, "plan_item_id")
        if plan_item.status not in (TreatmentPlanItem.Status.ACCEPTED, TreatmentPlanItem.Status.IN_PROGRESS):
            raise ConflictError("Only accepted plan items are carried out. Record the patient's decision first.")
        procedure = plan_item.procedure
        where = {"scope": plan_item.scope, "tooth": plan_item.tooth, "surfaces": plan_item.surfaces,
                 "region": plan_item.region}
    else:
        procedure = DentalProcedure.objects.filter(pk=data.get("procedure_id"), is_active=True).first()
        if procedure is None:
            raise BusinessValidationError("Choose the procedure.", fields={"procedure_id": ["Required."]})
        where = _clean_item_location(procedure, data)
    # An assistant preparing the record: the examining dentist performs it unless someone else is named.
    default = ctx.user.pk if ctx.user.has_permissions(["dental.procedure.sign"]) else enc.dentist_id
    performer = _performer(data.get("performed_by_id") or default)
    _check_role_policy(procedure, performer)
    assistant = None
    if data.get("assisted_by_id"):
        assistant = User.objects.filter(pk=data["assisted_by_id"], is_active=True).first()
        if assistant is None:
            raise BusinessValidationError("Unknown staff member.", fields={"assisted_by_id": ["Not found."]})
    session = 1
    if plan_item is not None:
        session = plan_item.procedures.filter(status__in=[S.COMPLETED, S.SESSION_COMPLETED]).count() + 1
        if plan_item.procedures.filter(status=S.DRAFT).exists():
            raise ConflictError("An unsigned record already exists for this plan item. Continue that one.")
    year = timezone.localdate().year
    record = ProcedureRecord.objects.create(
        number=f"PR-{year}-{next_number('dental_procedure', str(year)):05d}", patient=enc.patient, visit=enc.visit,
        encounter=enc, plan_item=plan_item, procedure=procedure, performed_by=performer, assisted_by=assistant,
        session_number=session, started_at=data.get("started_at") or timezone.now(), created_by=ctx.user,
        follow_up_days=procedure.follow_up_days, **where,
        **{k: (data.get(k) or "").strip() for k in ProcedureRecord.TEXT_FIELDS})
    for row in procedure.default_materials.select_related("item"):
        if row.item.is_active and row.item.category not in Item.REUSABLE:
            ProcedureMaterial.objects.create(record=record, item=row.item, quantity=row.quantity)
    record_event(ctx, action="dental_procedure.create", object_type="dental_procedure", object_id=record.pk,
                 details={"number": record.number, "procedure": procedure.code, "where": record.location_label,
                          "plan_item": str(plan_item.pk) if plan_item else None})
    return record


@transaction.atomic
def update_record(ctx: ActorContext, record: ProcedureRecord, data: dict, *, version: int) -> ProcedureRecord:
    record = _lock_draft(record)
    if version != record.version:
        raise ConflictError("This record was changed elsewhere. Reload before saving.",
                            extra={"current_version": record.version})
    changed = []
    for key in ProcedureRecord.TEXT_FIELDS:
        if key in data and getattr(record, key) != (data[key] or "").strip():
            setattr(record, key, (data[key] or "").strip())
            changed.append(key)
    for key in ("started_at", "follow_up_days"):
        if key in data and getattr(record, key) != data[key]:
            setattr(record, key, data[key])
            changed.append(key)
    if "assisted_by_id" in data:
        assistant = User.objects.filter(pk=data["assisted_by_id"], is_active=True).first() if data["assisted_by_id"] else None
        if record.assisted_by_id != getattr(assistant, "pk", None):
            record.assisted_by = assistant
            changed.append("assisted_by")
    if "performed_by_id" in data and str(data["performed_by_id"]) != str(record.performed_by_id):
        performer = _performer(data["performed_by_id"])
        _check_role_policy(record.procedure, performer)
        record.performed_by = performer
        changed.append("performed_by")
    if changed:
        record.version += 1
        record.save()
        record_event(ctx, action="dental_procedure.update", object_type="dental_procedure", object_id=record.pk,
                     details={"fields": changed, "version": record.version})
    return record


@transaction.atomic
def set_materials(ctx: ActorContext, record: ProcedureRecord, rows: list[dict]) -> ProcedureRecord:
    """Replace the list of materials on a draft. Nothing touches stock until the record is signed."""
    record = _lock_draft(record)
    clean = []
    for row in rows:
        item = Item.objects.filter(pk=row.get("item_id"), is_active=True).first()
        if item is None:
            raise BusinessValidationError("Unknown stock item.", fields={"materials": ["Item not found."]})
        if item.category in Item.REUSABLE:
            raise BusinessValidationError(f"{item.name} is a reusable instrument, not a consumable.",
                                          fields={"materials": ["Instruments are not consumed."]})
        try:
            quantity = Decimal(str(row.get("quantity")))
        except Exception:  # noqa: BLE001
            raise BusinessValidationError("Enter the quantity.", fields={"materials": ["Invalid quantity."]}) from None
        if quantity <= 0:
            raise BusinessValidationError("Quantities must be positive.", fields={"materials": ["Must be > 0."]})
        clean.append((item, quantity, (row.get("note") or "").strip()[:120]))
    record.materials.all().delete()
    ProcedureMaterial.objects.bulk_create([ProcedureMaterial(record=record, item=i, quantity=q, note=n)
                                           for i, q, n in clean])
    record.version += 1
    record.save(update_fields=["version", "updated_at"])
    record_event(ctx, action="dental_procedure.materials", object_type="dental_procedure", object_id=record.pk,
                 details={"materials": [{"item": i.code, "quantity": str(q)} for i, q, _ in clean]})
    return record


@transaction.atomic
def discard_record(ctx: ActorContext, record: ProcedureRecord, reason: str) -> None:
    record = _lock_draft(record)
    if not reason.strip():
        raise BusinessValidationError("Give the reason.", fields={"reason": ["Required."]})
    record_event(ctx, action="dental_procedure.discard", object_type="dental_procedure", object_id=record.pk,
                 details={"number": record.number, "procedure": record.procedure.code, "reason": reason.strip()})
    record.materials.all().delete()
    record.delete()


def _is_charged(procedure: DentalProcedure, outcome: str) -> bool:
    """Whether signing with this outcome puts a charge on the visit (see billable_procedures)."""
    return outcome == S.COMPLETED or (outcome == S.SESSION_COMPLETED
                                      and procedure.billing_mode == DentalProcedure.BillingMode.PER_SESSION)


def charge_check(record: ProcedureRecord) -> dict:
    """
    What signing this record will charge, compared with the estimate the patient accepted for the plan item.

    The bill always uses the catalogue price at signing (the estimate is separate from the invoice), so a price of 0
    or a price that differs from the accepted estimate must be confirmed by the clinician before signing.
    """
    procedure = record.procedure
    price = procedure.price
    estimate = expected = None
    if record.plan_item_id:
        item = record.plan_item
        estimate = item.estimated_fee
        sessions = item.sessions_planned if procedure.billing_mode == DentalProcedure.BillingMode.PER_SESSION else 1
        expected = price * sessions
    warning = None
    if price <= 0:
        warning = "no_price"
    elif estimate is not None and estimate != expected:
        warning = "differs_from_estimate"
    return {"price": str(price), "estimate": None if estimate is None else str(estimate),
            "expected_total": None if expected is None else str(expected), "billing_mode": procedure.billing_mode,
            "warning": warning}


def _require_charge_confirmed(record: ProcedureRecord, outcome: str, confirmed: bool) -> None:
    if not _is_charged(record.procedure, outcome):
        return
    check = charge_check(record)
    if check["warning"] is None or confirmed:
        return
    name = record.procedure.name
    if check["warning"] == "no_price":
        message = (f"{name} has no price in the procedure catalogue, so it would be billed at 0 ETB, and the price "
                   f"cannot be changed after signing. Ask the clinic administrator to set the price, or confirm "
                   f"that this procedure is free of charge.")
    else:
        message = (f"The patient accepted an estimate of {check['estimate']} ETB for {name}; the invoice will use "
                   f"the catalogue price ({check['expected_total']} ETB). Confirm the charge, or ask for the "
                   f"estimate or the catalogue price to be corrected first.")
    raise ConflictError(message, fields={"confirm_charge": ["Confirm the charge."]}, extra={"charge": check})


@transaction.atomic
def sign_record(ctx: ActorContext, record: ProcedureRecord, *, outcome: str, reason: str = "",
                create_recall: bool = True, confirm_charge: bool = False) -> ProcedureRecord:
    record = _lock_draft(record)
    if record.performed_by_id != ctx.user.pk:
        raise PermissionDeniedError("Only the clinician recorded as performing the procedure can sign it.")
    if outcome not in (S.COMPLETED, S.SESSION_COMPLETED, S.NOT_PERFORMED):
        raise BusinessValidationError("Completed, session completed or not performed.", fields={"outcome": ["Invalid."]})
    if outcome == S.NOT_PERFORMED and not reason.strip():
        raise BusinessValidationError("Say why it was not performed.", fields={"reason": ["Required."]})
    if record.plan_item_id:
        # Plan first, then item (plans.lock_item), so this cannot deadlock with a decision on the same plan.
        plan_item, _plan = lock_item(record.plan_item_id)
        record.plan_item = plan_item
        if outcome != S.NOT_PERFORMED and plan_item.status not in (TreatmentPlanItem.Status.ACCEPTED,
                                                                   TreatmentPlanItem.Status.IN_PROGRESS):
            raise ConflictError(f"The plan item for {record.procedure.name} is "
                                f"{plan_item.get_status_display().lower()}, so it cannot be recorded as done. "
                                f"Record the patient's decision on the plan first, or sign it as not performed.")
    _require_charge_confirmed(record, outcome, confirm_charge)
    now = timezone.now()
    record.status, record.signed_at, record.signed_by = outcome, now, ctx.user
    record.completed_at = now if outcome != S.NOT_PERFORMED else None
    record.not_performed_reason = reason.strip()[:255] if outcome == S.NOT_PERFORMED else ""
    if outcome != S.NOT_PERFORMED:
        record.price, record.tax_rate = record.procedure.price, record.procedure.tax_rate
        for m in record.materials.select_related("item"):
            try:
                allocate_fefo(ctx, item=m.item, quantity=m.quantity, reference_type="dental_procedure",
                              reference_id=record.pk)
            except InsufficientStock as exc:
                raise ConflictError(f"Not enough {m.item.name} in stock to record {m.quantity.normalize():f} "
                                    f"{m.item.unit}. Correct the quantity, or receive the stock first.",
                                    fields={"materials": [str(exc)]}) from None
    record.version += 1
    record.save()
    record_event(ctx, action="dental_procedure.sign", object_type="dental_procedure", object_id=record.pk,
                 details={"number": record.number, "outcome": outcome, "price": str(record.price or ""),
                          **({"charge_confirmed": charge_check(record)["warning"]} if confirm_charge else {})})
    visit_event(ctx, record.visit_id, "dental.procedure",
                f"{record.procedure.name} ({record.location_label}): {record.get_status_display().lower()}")
    if record.plan_item_id:
        on_procedure_signed(ctx, record.plan_item, outcome)
    if create_recall and outcome != S.NOT_PERFORMED and record.follow_up_days and record.procedure.follow_up_kind:
        from .recalls import create_recall as make_recall

        make_recall(ctx, record.patient, kind=record.procedure.follow_up_kind,
                    due_date=timezone.localdate() + datetime.timedelta(days=record.follow_up_days),
                    note=(record.follow_up_recommendation or f"After {record.procedure.name}")[:255],
                    source_procedure=record)
    return record


@transaction.atomic
def amend_record(ctx: ActorContext, record: ProcedureRecord, *, field_name: str, text: str,
                 reason: str) -> ProcedureAmendment:
    record = ProcedureRecord.objects.select_for_update(of=("self",)).select_related("signed_by").get(pk=record.pk)
    if record.status == S.DRAFT:
        raise ConflictError("A draft is edited directly.")
    check_amend_author(ctx, record.signed_by, "procedure record")
    if field_name not in ProcedureRecord.TEXT_FIELDS:
        raise BusinessValidationError("Unknown section.", fields={"field_name": ["Unknown section."]})
    if not reason.strip() or not text.strip():
        raise BusinessValidationError("Both the corrected text and a reason are required.",
                                      fields={"reason" if not reason.strip() else "text": ["Required."]})
    previous = record.amendments.filter(field_name=field_name).order_by("-created_at").first()
    original = previous.amended_text if previous else getattr(record, field_name)
    amendment = ProcedureAmendment.objects.create(record=record, field_name=field_name, original_text=original,
                                                  amended_text=text.strip(), reason=reason.strip()[:255],
                                                  author=ctx.user)
    record_event(ctx, action="dental_procedure.amend", object_type="dental_procedure", object_id=record.pk,
                 details={"field": field_name, "reason": amendment.reason})
    return amendment


def billable_procedures(visit):
    """Signed records on the visit that the clinic's policy charges for (see docs/dental/clinical-workflows.md)."""
    return (ProcedureRecord.objects.filter(visit=visit)
            .filter(Q(status=S.COMPLETED)
                    | Q(status=S.SESSION_COMPLETED, procedure__billing_mode=DentalProcedure.BillingMode.PER_SESSION))
            .exclude(price__isnull=True).select_related("procedure").order_by("signed_at"))
