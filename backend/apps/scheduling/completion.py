"""
Closing a visit.

A visit is not complete just because one department finished. After the consultation, the
laboratory, pharmacy and cashier work in parallel and in any order. Completing the visit is a
separate, explicit step that lists what is still open and records why the visit is being
closed anyway (patient left, referred, will come back for results, etc.).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError

from .models import Appointment, Visit
from .services import visit_event


@dataclass
class Outstanding:
    draft_notes: list[str] = field(default_factory=list)
    lab_pending: list[str] = field(default_factory=list)
    medicines_pending: list[str] = field(default_factory=list)
    unbilled: list[str] = field(default_factory=list)
    balance_due: str = "0.00"
    open_invoices: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        """Draft notes always block: an unsigned note cannot be left behind on a closed visit."""
        return bool(self.draft_notes)

    @property
    def any(self) -> bool:
        return bool(self.draft_notes or self.lab_pending or self.medicines_pending or self.unbilled
                    or self.open_invoices or Decimal(self.balance_due) > 0)

    def as_dict(self) -> dict:
        return {**asdict(self), "any": self.any, "blocking": self.blocking}


def outstanding_for(visit: Visit) -> Outstanding:
    from apps.billing.services import unbilled_charges
    from apps.billing.models import Invoice
    from apps.clinical.models import Encounter, Prescription
    from apps.laboratory.models import LabOrderItem

    from apps.core.modules import disabled_modules

    off = disabled_modules()
    out = Outstanding()
    for enc in Encounter.objects.filter(visit=visit, status=Encounter.Status.DRAFT).select_related("doctor"):
        out.draft_notes.append(f"Unsigned consultation by Dr. {enc.doctor.full_name}")
    from apps.dental.models import DentalEncounter, ProcedureRecord

    for enc in DentalEncounter.objects.filter(visit=visit, status=DentalEncounter.Status.DRAFT).select_related("dentist"):
        out.draft_notes.append(f"Unsigned dental examination by Dr. {enc.dentist.full_name}")
    for rec in (ProcedureRecord.objects.filter(visit=visit, status=ProcedureRecord.Status.DRAFT)
                .select_related("procedure", "performed_by")):
        out.draft_notes.append(f"Unsigned procedure record: {rec.procedure.name} ({rec.location_label}), "
                               f"{rec.performed_by.full_name}")
    for item in ([] if "laboratory" in off else LabOrderItem.objects.filter(order__visit=visit)
                 .exclude(status__in=[LabOrderItem.Status.VERIFIED, LabOrderItem.Status.CANCELLED])
                 .select_related("test")):
        out.lab_pending.append(f"{item.test.name}: {item.get_status_display().lower()}")
    for rx in ([] if "pharmacy" in off else Prescription.objects.filter(visit=visit,
                                           status__in=[Prescription.Status.ACTIVE, Prescription.Status.PARTIAL])
               .prefetch_related("items")):
        for line in rx.items.all():
            if line.quantity_dispensed < line.quantity:
                left = (line.quantity - line.quantity_dispensed).normalize()
                out.medicines_pending.append(f"{line.drug_name}: {left:f} not dispensed")
    if "billing" in off:  # the clinic takes payment outside the system
        return out
    out.unbilled = [c["description"] for c in unbilled_charges(visit)]
    balance = Decimal("0")
    for inv in Invoice.objects.filter(visit=visit).exclude(status=Invoice.Status.VOID):
        if inv.status == Invoice.Status.DRAFT:
            out.open_invoices.append(f"{inv.number} is still a draft")
        balance += inv.balance if inv.status in (Invoice.Status.ISSUED, Invoice.Status.PARTIAL) else 0
    out.balance_due = f"{balance:.2f}"
    return out


@transaction.atomic
def complete_visit(ctx: ActorContext, visit: Visit, *, outcome: str, note: str = "",
                   acknowledge_outstanding: bool = False) -> Visit:
    from apps.clinical.models import Prescription

    visit = Visit.objects.select_for_update().get(pk=visit.pk)
    if visit.status == Visit.Status.COMPLETED:
        raise ConflictError("This visit is already complete.")
    if visit.status != Visit.Status.AFTER_CONSULTATION:
        raise ConflictError("A visit can be completed after the consultation is signed. "
                            "Patients who leave before seeing the doctor are removed from the queue instead.")
    if outcome not in Visit.Outcome.values:
        raise BusinessValidationError("Choose how the visit ended.", fields={"outcome": ["Required."]})
    note = note.strip()
    if outcome in (Visit.Outcome.REFERRED, Visit.Outcome.LEFT_EARLY) and not note:
        raise BusinessValidationError("Add a short note explaining the outcome.", fields={"note": ["Required."]})

    out = outstanding_for(visit)
    if out.blocking:
        raise ConflictError("Sign or discard the open consultation, examination or procedure record before completing "
                            "the visit.",
                            extra={"outstanding": out.as_dict()})
    if out.any and not acknowledge_outstanding:
        raise ConflictError("Some services for this visit are not finished.", extra={"outstanding": out.as_dict()})
    if out.any and not note:
        raise BusinessValidationError("Explain why the visit is closed with services still open.",
                                      fields={"note": ["Required when services are still open."]})

    # Medicines the patient will not collect: close the prescription so it leaves the pharmacy worklist.
    closed_rx = 0
    for rx in Prescription.objects.select_for_update().filter(
            visit=visit, status__in=[Prescription.Status.ACTIVE, Prescription.Status.PARTIAL]):
        rx.status = Prescription.Status.NOT_COLLECTED
        rx.cancel_reason = f"Visit closed: {note}"[:255]
        rx.save(update_fields=["status", "cancel_reason", "updated_at"])
        closed_rx += 1

    visit.status = Visit.Status.COMPLETED
    visit.outcome = outcome
    visit.completion_note = note[:500]
    visit.completed_at = timezone.now()
    visit.completed_by = ctx.user
    visit.called_at = None
    visit.save()
    if visit.appointment_id:
        Appointment.objects.filter(pk=visit.appointment_id).update(status=Appointment.Status.COMPLETED)
    record_event(ctx, action="visit.complete", object_type="visit", object_id=visit.pk,
                 details={"outcome": outcome, "note": note, "outstanding": out.as_dict() if out.any else {},
                          "prescriptions_closed": closed_rx})
    summary = f"Visit completed: {visit.get_outcome_display().lower()}"
    if note:
        summary += f" ({note})"
    visit_event(ctx, visit, "completed", summary)
    return visit


def close_finished_visits(now=None) -> list[str]:
    """
    Close visits that are finished: the consultation was signed at least `auto_complete_minutes` ago
    (the clinic setting; 0 = never) and nothing is outstanding. The wait leaves the doctor time to add a
    test or prescription after signing. Visits with anything still open are left for staff, exactly as
    before. Run every few minutes by the mrs-visits timer. Returns the ids of the visits closed.
    """
    from datetime import timedelta

    from apps.clinical.models import Encounter
    from apps.core.models import ClinicSettings

    minutes = ClinicSettings.get().auto_complete_minutes
    if not minutes:
        return []
    now = now or timezone.now()
    cutoff = now - timedelta(minutes=minutes)
    ctx = ActorContext.system("auto_complete")
    closed = []
    candidates = (Visit.objects.filter(status=Visit.Status.AFTER_CONSULTATION)
                  .exclude(encounters__status=Encounter.Status.DRAFT)
                  .exclude(encounters__signed_at__gt=cutoff)
                  .filter(encounters__signed_at__lte=cutoff).distinct())
    for visit in candidates:
        if outstanding_for(visit).any:
            continue
        follow_up = Appointment.objects.filter(source_encounter__visit=visit).exclude(
            status=Appointment.Status.CANCELLED).exists()
        try:
            complete_visit(ctx, visit, note="Closed automatically: everything for this visit was finished.",
                           outcome=Visit.Outcome.FOLLOW_UP if follow_up else Visit.Outcome.COMPLETED)
        except ConflictError:
            continue  # changed meanwhile (for example a new test was requested); staff will handle it
        closed.append(str(visit.pk))
    return closed
