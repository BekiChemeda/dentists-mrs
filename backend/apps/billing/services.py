"""Invoices, charges, payments, discounts and voids. Money uses Decimal throughout."""

from __future__ import annotations

from typing import TYPE_CHECKING

from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.approvals import services as approvals
from apps.approvals.models import ApprovalRequest
from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.core.numbering import next_number
from apps.laboratory.models import LabOrderItem
from apps.pharmacy.models import Dispensation
from apps.scheduling.services import visit_event

from .models import Invoice, InvoiceLine, Payment, ServicePrice

if TYPE_CHECKING:
    from .models import Refund

CENT = Decimal("0.01")
CONSULTATION_CODE = "CONSULT"


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _lock(invoice: Invoice) -> Invoice:
    return Invoice.objects.select_for_update().get(pk=invoice.pk)


def _recalculate(invoice: Invoice) -> None:
    lines = list(invoice.lines.filter(is_void=False))
    invoice.subtotal = money(sum((l.line_total for l in lines), Decimal("0")))
    if invoice.discount_amount > invoice.subtotal:
        invoice.discount_amount = invoice.subtotal
    # Tax is charged on what the patient actually pays: each line's tax is reduced by the discount share.
    gross_tax = sum((l.line_total * l.tax_rate / 100 for l in lines), Decimal("0"))
    share = (invoice.subtotal - invoice.discount_amount) / invoice.subtotal if invoice.subtotal else Decimal("0")
    invoice.tax_amount = money(gross_tax * share)
    invoice.total = invoice.subtotal - invoice.discount_amount + invoice.tax_amount


@transaction.atomic
def create_invoice(ctx: ActorContext, *, patient, visit=None) -> Invoice:
    if visit is not None and visit.patient_id != patient.pk:
        raise BusinessValidationError("The visit belongs to another patient.")
    year = timezone.localdate().year
    invoice = Invoice.objects.create(number=f"INV-{year}-{next_number('invoice', str(year)):06d}", patient=patient,
                                     visit=visit, created_by=ctx.user)
    record_event(ctx, action="invoice.create", object_type="invoice", object_id=invoice.pk,
                 details={"number": invoice.number, "patient": str(patient.pk)})
    return invoice


def _add_line(invoice, *, kind, description, quantity, unit_price, source_type="", source_id="",
              tax_rate=Decimal("0")) -> InvoiceLine:
    quantity = Decimal(quantity)
    unit_price = money(unit_price)
    try:
        with transaction.atomic():
            return InvoiceLine.objects.create(invoice=invoice, kind=kind, description=description[:200],
                                              quantity=quantity, unit_price=unit_price,
                                              line_total=money(quantity * unit_price), source_type=source_type,
                                              source_id=str(source_id) if source_id else "",
                                              tax_rate=tax_rate or Decimal("0"))
    except IntegrityError as exc:
        raise ConflictError(f"'{description}' is already billed on another invoice.") from exc


def _require_draft(invoice: Invoice) -> None:
    if invoice.status != Invoice.Status.DRAFT:
        raise ConflictError("Only draft invoices can be changed. Issued invoices are corrected by voiding.")


@transaction.atomic
def add_service_line(ctx: ActorContext, invoice: Invoice, *, service: ServicePrice | None = None,
                     description: str = "", unit_price=None, quantity=1) -> InvoiceLine:
    invoice = _lock(invoice)
    _require_draft(invoice)
    if service is not None:
        kind = {"consultation": InvoiceLine.Kind.CONSULTATION, "procedure": InvoiceLine.Kind.PROCEDURE}.get(
            service.category, InvoiceLine.Kind.OTHER)
        # A visit's consultation fee can be charged once; other services may repeat.
        once = service.category == ServicePrice.Category.CONSULTATION and invoice.visit_id
        line = _add_line(invoice, kind=kind, description=service.name, quantity=quantity, unit_price=service.price,
                         source_type="visit" if once else "", source_id=invoice.visit_id if once else "",
                         tax_rate=service.tax_rate)
    else:
        if not description.strip() or unit_price is None:
            raise BusinessValidationError("Enter a description and price.", fields={"description": ["Required."]})
        line = _add_line(invoice, kind=InvoiceLine.Kind.OTHER, description=description.strip(), quantity=quantity,
                         unit_price=unit_price)
    _recalculate(invoice)
    invoice.save()
    record_event(ctx, action="invoice.line_add", object_type="invoice", object_id=invoice.pk,
                 details={"description": line.description, "amount": str(line.line_total)})
    return line


LAB_BILLABLE = {
    "ordered": (LabOrderItem.Status.ORDERED, LabOrderItem.Status.COLLECTED, LabOrderItem.Status.RESULTED,
                LabOrderItem.Status.VERIFIED),
    "collected": (LabOrderItem.Status.COLLECTED, LabOrderItem.Status.RESULTED, LabOrderItem.Status.VERIFIED),
    "verified": (LabOrderItem.Status.VERIFIED,),
}


def _visit_service(visit):
    """The consultation service for a visit: the appointment's booked service, else the clinic default."""
    appt = getattr(visit, "appointment", None)
    if appt is not None and appt.service_id and appt.service.is_active \
            and appt.service.category == ServicePrice.Category.CONSULTATION:
        return appt.service
    return ServicePrice.objects.filter(code=CONSULTATION_CODE, is_active=True).first()


def unbilled_charges(visit) -> list[dict]:
    """
    Charges for a visit that are billable under the clinic's policy and not yet on a live invoice.

    Policy: the consultation is billable once a consultation was started; laboratory tests are
    billable from the point set in clinic settings (requested, collected or verified); medicines
    only when actually dispensed, never because they were prescribed.
    """
    from apps.core.models import ClinicSettings

    billed = set(InvoiceLine.objects.filter(is_void=False).exclude(source_type="")
                 .values_list("source_type", "source_id"))
    charges: list[dict] = []
    consult = _visit_service(visit)
    settings_row = ClinicSettings.get()
    # Dental visits are charged by procedure; the consultation fee only if the clinic chose to add one.
    consulted = visit.encounters.exists() or (settings_row.bill_consultation_for_dental
                                              and visit.dental_encounters.exists())
    if consult and ("visit", str(visit.pk)) not in billed and consulted:
        charges.append({"kind": InvoiceLine.Kind.CONSULTATION, "description": consult.name, "quantity": Decimal(1),
                        "unit_price": consult.price, "source_type": "visit", "source_id": str(visit.pk),
                        "tax_rate": consult.tax_rate})
    point = settings_row.lab_billing_point
    for item in (LabOrderItem.objects.select_related("test")
                 .filter(order__visit_id=visit.pk, status__in=LAB_BILLABLE[point], is_chargeable=True)):
        if ("lab_item", str(item.pk)) not in billed:
            charges.append({"kind": InvoiceLine.Kind.LAB, "description": f"Lab: {item.test.name}",
                            "quantity": Decimal(1), "unit_price": item.price, "source_type": "lab_item",
                            "source_id": str(item.pk)})
    for d in (Dispensation.objects.select_related("item")
              .filter(prescription_item__prescription__visit_id=visit.pk)):
        if ("dispensation", str(d.pk)) not in billed:
            charges.append({"kind": InvoiceLine.Kind.MEDICATION, "description": str(d.item), "quantity": d.quantity,
                            "unit_price": d.unit_price, "source_type": "dispensation", "source_id": str(d.pk),
                            "tax_rate": d.item.tax_rate})
    from apps.dental.services.procedures import billable_procedures

    for rec in billable_procedures(visit):
        if ("dental_procedure", str(rec.pk)) not in billed:
            session = f" (session {rec.session_number})" if rec.status == "session_completed" else ""
            where = f" — {rec.location_label}" if rec.scope != "mouth" else ""
            charges.append({"kind": InvoiceLine.Kind.PROCEDURE, "description": f"{rec.procedure.name}{where}{session}"[:200],
                            "quantity": Decimal(1), "unit_price": rec.price, "source_type": "dental_procedure",
                            "source_id": str(rec.pk), "tax_rate": rec.tax_rate})
    return charges


@transaction.atomic
def add_pending_charges(ctx: ActorContext, invoice: Invoice) -> int:
    """Pull the visit's unbilled charges (see unbilled_charges for the policy) onto a draft invoice."""
    invoice = _lock(invoice)
    _require_draft(invoice)
    if not invoice.visit_id:
        raise ConflictError("Link the invoice to a visit to collect its charges.")
    added = 0
    for charge in unbilled_charges(invoice.visit):
        _add_line(invoice, **charge)
        added += 1
    _recalculate(invoice)
    invoice.save()
    if added:
        record_event(ctx, action="invoice.charges_pull", object_type="invoice", object_id=invoice.pk,
                     details={"lines_added": added})
    return added


@transaction.atomic
def remove_line(ctx: ActorContext, line: InvoiceLine) -> None:
    invoice = _lock(line.invoice)
    _require_draft(invoice)
    InvoiceLine.objects.filter(pk=line.pk).update(is_void=True)
    _recalculate(invoice)
    invoice.save()
    record_event(ctx, action="invoice.line_remove", object_type="invoice", object_id=invoice.pk,
                 details={"description": line.description, "amount": str(line.line_total)})


@transaction.atomic
def issue_invoice(ctx: ActorContext, invoice: Invoice) -> Invoice:
    invoice = _lock(invoice)
    _require_draft(invoice)
    _recalculate(invoice)
    if invoice.subtotal <= 0:
        raise ConflictError("Add at least one charge before issuing the invoice.")
    invoice.status = Invoice.Status.ISSUED if invoice.total > 0 else Invoice.Status.PAID
    invoice.issued_at = timezone.now()
    invoice.save()
    record_event(ctx, action="invoice.issue", object_type="invoice", object_id=invoice.pk,
                 details={"number": invoice.number, "total": str(invoice.total)})
    if invoice.visit_id:
        visit_event(ctx, invoice.visit_id, "billing.issue", f"Invoice {invoice.number} issued: {invoice.total} ETB")
    return invoice


@transaction.atomic
def record_payment(ctx: ActorContext, invoice: Invoice, *, amount, method: str, reference: str = "") -> Payment:
    invoice = _lock(invoice)
    amount = money(amount)
    if invoice.status not in (Invoice.Status.ISSUED, Invoice.Status.PARTIAL):
        raise ConflictError("Payments can only be taken on issued, unpaid invoices.")
    from apps.payments.models import OnlinePayment

    if OnlinePayment.objects.filter(invoice=invoice, status=OnlinePayment.Status.PENDING).exists():
        raise ConflictError("A payment request is waiting on the patient's phone for this invoice. Wait for it, or "
                            "stop it before taking the payment another way.")
    if amount <= 0:
        raise BusinessValidationError("Amount must be positive.", fields={"amount": ["Must be > 0."]})
    if amount > invoice.balance:
        raise ConflictError(f"The balance is {invoice.balance} ETB; the payment is larger.",
                            fields={"amount": [f"Maximum {invoice.balance}."]})
    if method != Payment.Method.CASH and not reference.strip():
        raise BusinessValidationError("Enter the transaction reference.", fields={"reference": ["Required."]})
    year = timezone.localdate().year
    payment = Payment.objects.create(receipt_number=f"RCT-{year}-{next_number('receipt', str(year)):06d}",
                                     invoice=invoice, amount=amount, method=method, reference=reference.strip(),
                                     received_by=ctx.user)
    invoice.amount_paid += amount
    invoice.status = Invoice.Status.PAID if invoice.amount_paid == invoice.total else Invoice.Status.PARTIAL
    invoice.save()
    record_event(ctx, action="payment.record", object_type="invoice", object_id=invoice.pk,
                 details={"receipt": payment.receipt_number, "amount": str(amount), "method": method})
    if invoice.visit_id:
        visit_event(ctx, invoice.visit_id, "billing.payment",
                    f"Payment {amount} ETB ({payment.get_method_display()}), receipt {payment.receipt_number}")
    return payment


def request_discount(ctx: ActorContext, invoice: Invoice, *, amount, reason: str) -> ApprovalRequest:
    amount = money(amount)
    if invoice.status not in (Invoice.Status.DRAFT, Invoice.Status.ISSUED, Invoice.Status.PARTIAL):
        raise ConflictError("Discounts can only be requested on open invoices.")
    if amount <= 0 or amount > invoice.subtotal:
        raise BusinessValidationError("Discount must be between 0 and the invoice subtotal.",
                                      fields={"amount": ["Out of range."]})
    return approvals.request_approval(ctx, kind=ApprovalRequest.Kind.DISCOUNT, object_type="invoice",
                                      object_id=invoice.pk, amount=amount, reason=reason,
                                      summary=f"Discount of {amount} ETB on {invoice.number} "
                                              f"({invoice.patient.full_name})")


@transaction.atomic
def apply_discount(ctx: ActorContext, invoice: Invoice, approval_id) -> Invoice:
    invoice = _lock(invoice)
    approval = approvals.consume(ctx, approval_id, kind=ApprovalRequest.Kind.DISCOUNT, object_type="invoice",
                                 object_id=invoice.pk)
    if invoice.status not in (Invoice.Status.DRAFT, Invoice.Status.ISSUED, Invoice.Status.PARTIAL):
        raise ConflictError("This invoice is closed.")
    new_discount = invoice.discount_amount + approval.amount
    if invoice.subtotal - new_discount < invoice.amount_paid:
        raise ConflictError("The discount would make the total less than what has already been paid.")
    invoice.discount_amount = new_discount
    invoice.discount_approval = approval
    _recalculate(invoice)
    if invoice.status != Invoice.Status.DRAFT:
        invoice.status = Invoice.Status.PAID if invoice.amount_paid == invoice.total else (
            Invoice.Status.PARTIAL if invoice.amount_paid > 0 else Invoice.Status.ISSUED)
    invoice.save()
    record_event(ctx, action="invoice.discount", object_type="invoice", object_id=invoice.pk,
                 details={"amount": str(approval.amount), "approval": str(approval.pk),
                          "approved_by": approval.decided_by.username})
    return invoice


def request_void(ctx: ActorContext, invoice: Invoice, *, reason: str) -> ApprovalRequest:
    if invoice.status == Invoice.Status.VOID:
        raise ConflictError("This invoice is already void.")
    if invoice.amount_paid > 0:
        raise ConflictError("Refund the payments on this invoice first; then it can be voided.")
    return approvals.request_approval(ctx, kind=ApprovalRequest.Kind.INVOICE_VOID, object_type="invoice",
                                      object_id=invoice.pk, reason=reason, amount=invoice.total,
                                      summary=f"Void {invoice.number} ({invoice.patient.full_name}, "
                                              f"{invoice.total} ETB)")


@transaction.atomic
def void_invoice(ctx: ActorContext, invoice: Invoice, approval_id) -> Invoice:
    invoice = _lock(invoice)
    approval = approvals.consume(ctx, approval_id, kind=ApprovalRequest.Kind.INVOICE_VOID, object_type="invoice",
                                 object_id=invoice.pk)
    if invoice.amount_paid > 0:
        raise ConflictError("Invoices with payments cannot be voided.")
    invoice.status = Invoice.Status.VOID
    invoice.void_approval = approval
    invoice.void_reason = approval.reason
    invoice.save()
    # Free the charges so they can be billed again on a corrected invoice.
    invoice.lines.update(is_void=True)
    record_event(ctx, action="invoice.void", object_type="invoice", object_id=invoice.pk,
                 details={"approval": str(approval.pk), "reason": approval.reason})
    return invoice


# ---------------------------------------------------------------------------
# Refunds: money given back against a specific payment, approved by a second person.
# ---------------------------------------------------------------------------
def refundable(payment: Payment) -> Decimal:
    done = payment.refunds.aggregate(s=Sum("amount"))["s"] or Decimal("0")
    return payment.amount - done


def request_refund(ctx: ActorContext, payment: Payment, *, amount, reason: str) -> ApprovalRequest:
    amount = money(amount)
    if amount <= 0 or amount > refundable(payment):
        raise BusinessValidationError(f"You can refund up to {refundable(payment)} ETB from this payment.",
                                      fields={"amount": ["Out of range."]})
    return approvals.request_approval(
        ctx, kind=ApprovalRequest.Kind.REFUND, object_type="payment", object_id=payment.pk, amount=amount,
        reason=reason, summary=f"Refund {amount} ETB of receipt {payment.receipt_number} "
                               f"({payment.invoice.patient.full_name}, {payment.invoice.number})")


@transaction.atomic
def apply_refund(ctx: ActorContext, payment: Payment, approval_id, *, method: str, reference: str = "") -> "Refund":
    from .models import Refund

    payment = Payment.objects.select_for_update().select_related("invoice").get(pk=payment.pk)
    invoice = _lock(payment.invoice)
    approval = approvals.consume(ctx, approval_id, kind=ApprovalRequest.Kind.REFUND, object_type="payment",
                                 object_id=payment.pk)
    if approval.amount > refundable(payment):
        raise ConflictError("The approved amount is more than can still be refunded from this payment.")
    if method != Payment.Method.CASH and not reference.strip():
        raise BusinessValidationError("Enter the transaction reference of the refund.", fields={"reference": ["Required."]})
    year = timezone.localdate().year
    refund = Refund.objects.create(number=f"RFD-{year}-{next_number('refund', str(year)):06d}", invoice=invoice,
                                   payment=payment, amount=approval.amount, method=method, reference=reference.strip(),
                                   reason=approval.reason, approval=approval, refunded_by=ctx.user)
    invoice.amount_paid -= refund.amount
    invoice.status = Invoice.Status.PAID if invoice.amount_paid == invoice.total and invoice.total > 0 else (
        Invoice.Status.PARTIAL if invoice.amount_paid > 0 else Invoice.Status.ISSUED)
    invoice.save()
    record_event(ctx, action="payment.refund", object_type="invoice", object_id=invoice.pk,
                 details={"refund": refund.number, "receipt": payment.receipt_number, "amount": str(refund.amount),
                          "approved_by": approval.decided_by.username})
    if invoice.visit_id:
        visit_event(ctx, invoice.visit_id, "billing.refund",
                    f"Refund {refund.amount} ETB ({refund.number}) against receipt {payment.receipt_number}")
    return refund


SERVICE_FIELDS = ("code", "name", "category", "price", "tax_rate", "is_active")


@transaction.atomic
def save_service(ctx: ActorContext, data: dict, service: ServicePrice | None = None) -> ServicePrice:
    creating = service is None
    if creating and ServicePrice.objects.filter(code__iexact=data["code"]).exists():
        raise ConflictError("A service with this code already exists.", fields={"code": ["Already used."]})
    service = service or ServicePrice()
    changes = {}
    for key in SERVICE_FIELDS:
        if key in data and (creating or getattr(service, key) != data[key]):
            changes[key] = str(data[key])
            setattr(service, key, data[key])
    service.full_clean()
    service.save()
    record_event(ctx, action="price.create" if creating else "price.update", object_type="service_price",
                 object_id=service.pk, details=changes)
    return service
