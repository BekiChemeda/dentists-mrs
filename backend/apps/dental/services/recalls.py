"""
Follow-ups and recalls. Works entirely inside the clinic: no message is sent to patients by the system.
Booking a recall makes an ordinary appointment; attending it closes the recall.
"""

from __future__ import annotations

import datetime

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.core.modules import is_enabled
from apps.patients.models import Patient
from apps.scheduling.models import Appointment

from ..models import Recall, RecallContact

R = Recall.Status


@transaction.atomic
def create_recall(ctx: ActorContext, patient: Patient, *, kind: str, due_date: datetime.date, note: str = "",
                  source_procedure=None, source_encounter=None) -> Recall | None:
    if not is_enabled("recalls"):
        return None
    if kind not in Recall.Kind.values:
        raise BusinessValidationError("Choose the kind of follow-up.", fields={"kind": ["Invalid."]})
    if due_date < timezone.localdate():
        raise BusinessValidationError("The due date is in the past.", fields={"due_date": ["Past date."]})
    recall = Recall.objects.create(patient=patient, kind=kind, due_date=due_date, note=note.strip()[:255],
                                   source_procedure=source_procedure, source_encounter=source_encounter,
                                   created_by=ctx.user)
    record_event(ctx, action="dental_recall.create", object_type="recall", object_id=recall.pk,
                 details={"patient": str(patient.pk), "kind": kind, "due": due_date.isoformat()})
    return recall


def _lock_open(recall: Recall) -> Recall:
    recall = Recall.objects.select_for_update().get(pk=recall.pk)
    if recall.status not in Recall.OPEN:
        raise ConflictError(f"This recall is already {recall.get_status_display().lower()}.")
    return recall


@transaction.atomic
def book(ctx: ActorContext, recall: Recall, appointment: Appointment) -> Recall:
    recall = _lock_open(recall)
    if appointment.patient_id != recall.patient_id:
        raise BusinessValidationError("The appointment is for another patient.", fields={"appointment_id": ["Wrong patient."]})
    if appointment.status not in Appointment.BOOKED:
        raise ConflictError("Choose an appointment that is still booked.")
    recall.status, recall.appointment = R.BOOKED, appointment
    recall.save(update_fields=["status", "appointment", "updated_at"])
    record_event(ctx, action="dental_recall.book", object_type="recall", object_id=recall.pk,
                 details={"appointment": str(appointment.pk)})
    return recall


@transaction.atomic
def log_contact(ctx: ActorContext, recall: Recall, *, outcome: str, note: str = "") -> RecallContact:
    recall = _lock_open(recall)
    if outcome not in RecallContact.Outcome.values:
        raise BusinessValidationError("Choose what happened.", fields={"outcome": ["Invalid."]})
    contact = RecallContact.objects.create(recall=recall, outcome=outcome, note=note.strip()[:255],
                                           contacted_by=ctx.user)
    record_event(ctx, action="dental_recall.contact", object_type="recall", object_id=recall.pk,
                 details={"outcome": outcome})
    return contact


@transaction.atomic
def close(ctx: ActorContext, recall: Recall, *, status: str, reason: str = "",
          new_due_date: datetime.date | None = None) -> Recall:
    """Postpone (new due date), mark declined / unreachable / cancelled / attended."""
    recall = _lock_open(recall)
    if status == R.POSTPONED:
        if new_due_date is None or new_due_date < timezone.localdate():
            raise BusinessValidationError("Choose the new due date.", fields={"due_date": ["Required, not in the past."]})
        recall.due_date, recall.status, recall.appointment = new_due_date, R.POSTPONED, None
    elif status in (R.DECLINED, R.UNREACHABLE, R.CANCELLED, R.COMPLETED):
        if status != R.COMPLETED and not reason.strip():
            raise BusinessValidationError("Give the reason.", fields={"reason": ["Required."]})
        if status == R.UNREACHABLE and not recall.contacts.exists():
            raise ConflictError("Log at least one contact attempt before marking the patient unreachable.")
        recall.status = status
    else:
        raise BusinessValidationError("Unknown status.", fields={"status": ["Invalid."]})
    recall.closed_reason = reason.strip()[:255]
    recall.save()
    record_event(ctx, action="dental_recall.status", object_type="recall", object_id=recall.pk,
                 details={"status": status, "reason": recall.closed_reason,
                          **({"due": new_due_date.isoformat()} if new_due_date else {})})
    return recall


def sync_booked(ctx: ActorContext | None = None) -> int:
    """Booked recalls follow their appointment: attended -> completed; cancelled or missed -> due again."""
    changed = 0
    ctx = ctx or ActorContext.system("recalls")
    for recall in Recall.objects.filter(status=R.BOOKED).select_related("appointment"):
        appt = recall.appointment
        new = None
        if appt.status in (Appointment.Status.ARRIVED, Appointment.Status.COMPLETED):
            new = R.COMPLETED
        elif appt.status in (Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW):
            new = R.DUE
        if new:
            with transaction.atomic():
                Recall.objects.filter(pk=recall.pk, status=R.BOOKED).update(
                    status=new, appointment=None if new == R.DUE else appt, updated_at=timezone.now())
                record_event(ctx, action="dental_recall.status", object_type="recall", object_id=recall.pk,
                             details={"status": new, "appointment_status": appt.status})
            changed += 1
    return changed
