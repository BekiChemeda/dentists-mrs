"""Dispensing against prescriptions with FEFO stock deduction and the two-person override rule."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.approvals import services as approvals
from apps.approvals.models import ApprovalRequest
from apps.audit.services import record_event
from apps.clinical.models import Prescription, PrescriptionItem
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.inventory.models import Item
from apps.inventory.services import allocate_fefo
from apps.scheduling.services import visit_event

from .models import Dispensation


def _resolve_item(rx_item: PrescriptionItem, item_id) -> Item:
    if rx_item.item_id:
        if item_id and str(item_id) != str(rx_item.item_id):
            raise ConflictError("This line was prescribed as a specific catalogue medicine.")
        return rx_item.item
    if not item_id:
        raise BusinessValidationError("Choose the catalogue medicine that matches this prescription line.",
                                      fields={"item_id": ["Required for free-text prescriptions."]})
    item = Item.objects.filter(pk=item_id, category=Item.Category.MEDICINE, is_active=True).first()
    if item is None:
        raise BusinessValidationError("Unknown medicine.", fields={"item_id": ["Not in catalogue."]})
    return item


def _controlled_dispensing_checks(ctx, rx: Prescription, rx_item: PrescriptionItem, quantity: Decimal, *,
                                  override, special_form_checked: bool, counselling_given: bool) -> None:
    """EFDA Narcotic and Psychotropic Medicine Control Directive No. 1121/2025, dispensing side (Art. 26)."""
    from django.utils import timezone

    from apps.patients.api import age_of

    if not ctx.user.registration_number.strip():
        raise ConflictError("Only a registered pharmacist may dispense controlled medicines: add your registration "
                            "number to your staff account (Art. 26(1)).")
    if age_of(rx.patient.birth_date) < 18:
        raise ConflictError("Controlled medicines are not dispensed to anyone under 18 (Art. 26(4)).")
    if (timezone.now() - rx.created_at).days > 15:
        raise ConflictError("This special prescription is older than 15 days and can no longer be dispensed "
                            "(Art. 26(2)).")
    if rx_item.quantity_dispensed > 0 or quantity != rx_item.quantity:
        raise ConflictError("A controlled prescription is dispensed once, in full (Art. 26(8)).")
    if override is not None:
        raise ConflictError("Controlled medicines cannot be dispensed beyond recorded stock.")
    problems = {}
    if not special_form_checked:
        problems["special_form_checked"] = ["Confirm you checked the original special prescription form."]
    if not counselling_given:
        problems["counselling_given"] = ["Confirm the patient was counselled (Art. 26(5))."]
    if problems:
        raise BusinessValidationError("Confirm the controlled-medicine checks.", fields=problems)


@transaction.atomic
def dispense(ctx: ActorContext, rx_item: PrescriptionItem, *, quantity: Decimal, item_id=None,
             override_approval_id=None, notes: str = "", batch_id=None, batch_reason: str = "",
             special_form_checked: bool = False, counselling_given: bool = False) -> Dispensation:
    rx_item = PrescriptionItem.objects.select_for_update(of=("self",)).select_related("prescription", "item").get(pk=rx_item.pk)
    rx = Prescription.objects.select_for_update().select_related("encounter").get(pk=rx_item.prescription_id)
    if rx.status not in Prescription.OPEN:
        raise ConflictError(f"This prescription is {rx.get_status_display().lower()}.")
    remaining = rx_item.quantity - rx_item.quantity_dispensed
    if quantity <= 0:
        raise BusinessValidationError("Quantity must be positive.", fields={"quantity": ["Must be > 0."]})
    if quantity > remaining:
        raise ConflictError(f"Only {remaining.normalize():f} remain to dispense on this line.")
    item = _resolve_item(rx_item, item_id)

    override = None
    if override_approval_id:
        override = approvals.consume(ctx, override_approval_id, kind=ApprovalRequest.Kind.DISPENSE_OVERRIDE,
                                     object_type="prescription_item", object_id=rx_item.pk)
        if override.quantity is not None and override.quantity < quantity:
            raise ConflictError("The approved override covers a smaller quantity.")

    if rx.controlled_class or item.controlled_class:
        _controlled_dispensing_checks(ctx, rx, rx_item, quantity, override=override,
                                      special_form_checked=special_form_checked, counselling_given=counselling_given)
    if batch_id is not None:
        from apps.inventory.models import Batch
        from django.db.models import F, Q
        from django.utils import timezone

        first = (Batch.objects.filter(item=item).filter(Q(expiry_date__isnull=True) |
                                                        Q(expiry_date__gte=timezone.localdate()))
                 .order_by(F("expiry_date").asc(nulls_last=True), "created_at").first())
        if first is not None and str(first.pk) != str(batch_id) and not batch_reason.strip():
            raise BusinessValidationError("This is not the batch that expires first. Give a reason for using it.",
                                          fields={"batch_reason": ["Required."]})
    dispensation = Dispensation.objects.create(
        prescription_item=rx_item, patient=rx.patient, item=item, quantity=quantity, unit_price=item.selling_price,
        override_approval=override, notes=notes.strip(), dispensed_by=ctx.user,
        batch_choice_reason=batch_reason.strip(), special_form_checked=special_form_checked,
        counselling_given=counselling_given)
    allocate_fefo(ctx, item=item, quantity=quantity, reference_type="dispensation", reference_id=dispensation.pk,
                  allow_shortfall=override is not None, first_batch_id=batch_id)

    rx_item.quantity_dispensed += quantity
    if rx_item.item_id is None:
        rx_item.item = item
    rx_item.save(update_fields=["quantity_dispensed", "item"])
    lines = list(rx.items.all())
    done = all(line.quantity_dispensed >= line.quantity for line in lines)
    rx.status = Prescription.Status.DISPENSED if done else Prescription.Status.PARTIAL
    rx.save(update_fields=["status", "updated_at"])
    visit_event(ctx, rx.visit_id, "pharmacy.dispense",
                f"Dispensed {quantity.normalize():f} × {item}" + (" (stock override)" if override else ""))
    record_event(ctx, action="pharmacy.dispense", object_type="dispensation", object_id=dispensation.pk,
                 details={"patient": str(rx.patient_id), "item": item.code, "quantity": str(quantity),
                          "override": str(override.pk) if override else ""})
    return dispensation


def request_override(ctx: ActorContext, rx_item: PrescriptionItem, *, quantity: Decimal, reason: str):
    return approvals.request_approval(
        ctx, kind=ApprovalRequest.Kind.DISPENSE_OVERRIDE, object_type="prescription_item", object_id=rx_item.pk,
        summary=f"Dispense {quantity.normalize():f} × {rx_item.drug_name} for {rx_item.prescription.patient.full_name}"
                f" beyond recorded stock",
        reason=reason, quantity=quantity)
