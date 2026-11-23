"""Appointments, check-in, walk-ins and the daily queue."""

from __future__ import annotations

import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.core.numbering import next_number

from apps.notifications.services import notify_permission_holders, notify_user

from .models import Appointment, Visit, VisitEvent


def visit_event(ctx: ActorContext | None, visit_or_id, kind: str, summary: str) -> None:
    """Append a line to the visit timeline. Called inside the caller's transaction."""
    visit_id = getattr(visit_or_id, "pk", visit_or_id)
    VisitEvent.objects.create(visit_id=visit_id, actor=ctx.user if ctx else None, kind=kind, summary=summary[:255])


def _hm(dt) -> str:
    return f"{timezone.localtime(dt):%d %b %Y %H:%M}"


def doctors():
    """Staff who see patients: medical doctors and dentists."""
    from apps.core.modules import CLINICIAN_PERMISSIONS

    return (User.objects.filter(is_active=True, roles__permissions__code__in=CLINICIAN_PERMISSIONS)
            .distinct().order_by("first_name", "last_name"))


def _require_doctor(user: User | None) -> None:
    if user is not None and not doctors().filter(pk=user.pk).exists():
        raise BusinessValidationError("The selected staff member cannot see patients.",
                                      fields={"doctor_id": ["Choose a doctor or dentist."]})


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------
@transaction.atomic
def _check_slot(*, doctor, patient, scheduled_at, duration_minutes, exclude_id=None, room=None) -> datetime.date:
    if scheduled_at < timezone.now() - datetime.timedelta(minutes=5):
        raise BusinessValidationError("Appointments cannot be booked in the past.",
                                      fields={"scheduled_at": ["Choose a future time."]})
    from apps.core.hours import outside_hours
    from apps.core.models import ClinicSettings

    closed = outside_hours(ClinicSettings.get().opening_hours, scheduled_at, duration_minutes)
    if closed:
        raise BusinessValidationError(f"{closed} Choose a time inside the opening hours.",
                                      fields={"scheduled_at": ["Outside opening hours."]})
    local_date = timezone.localtime(scheduled_at).date()
    end = scheduled_at + datetime.timedelta(minutes=duration_minutes)
    # Lock the doctor's appointments for that day so two receptionists cannot take the same slot.
    same_day = Appointment.objects.select_for_update().filter(
        doctor=doctor, scheduled_date=local_date, status__in=Appointment.ACTIVE)
    if exclude_id:
        same_day = same_day.exclude(pk=exclude_id)
    for other in same_day:
        other_end = other.scheduled_at + datetime.timedelta(minutes=other.duration_minutes)
        if other.scheduled_at < end and other_end > scheduled_at:
            raise ConflictError(
                f"Dr. {doctor.full_name} already has an appointment at "
                f"{timezone.localtime(other.scheduled_at):%H:%M}.", fields={"scheduled_at": ["Slot taken."]})
    if room is not None:
        if not room.is_active:
            raise BusinessValidationError("This chair or room is no longer in use.", fields={"room_id": ["Inactive."]})
        chair = Appointment.objects.select_for_update().filter(room=room, scheduled_date=local_date,
                                                               status__in=Appointment.ACTIVE)
        if exclude_id:
            chair = chair.exclude(pk=exclude_id)
        for other in chair:
            other_end = other.scheduled_at + datetime.timedelta(minutes=other.duration_minutes)
            if other.scheduled_at < end and other_end > scheduled_at:
                raise ConflictError(f"{room.name} is already booked at {timezone.localtime(other.scheduled_at):%H:%M}.",
                                    fields={"room_id": ["Chair taken."]})
    others = Appointment.objects.filter(patient=patient, scheduled_date=local_date, status__in=Appointment.ACTIVE)
    if exclude_id:
        others = others.exclude(pk=exclude_id)
    if others.exists():
        raise ConflictError("This patient already has an appointment on that day.",
                            fields={"scheduled_at": ["Duplicate appointment for this patient."]})
    return local_date


@transaction.atomic
def book_appointment(ctx: ActorContext, *, patient, doctor, scheduled_at: datetime.datetime,
                     duration_minutes: int | None = None, reason: str = "", notes: str = "", service=None,
                     source_encounter=None, appointment_type=None, room=None) -> Appointment:
    from apps.patients.services import require_active

    require_active(patient)
    _require_doctor(doctor)
    if doctor is None:
        raise BusinessValidationError("Choose a doctor.", fields={"doctor_id": ["Required."]})
    if service is not None and not service.is_active:
        raise BusinessValidationError("This service is no longer offered.", fields={"service_id": ["Inactive."]})
    if appointment_type is not None:
        if not appointment_type.is_active:
            raise BusinessValidationError("This appointment type is no longer used.",
                                          fields={"appointment_type_id": ["Inactive."]})
        duration_minutes = duration_minutes or appointment_type.default_minutes
        room = room or appointment_type.default_room
    duration_minutes = duration_minutes or 15
    local_date = _check_slot(doctor=doctor, patient=patient, scheduled_at=scheduled_at,
                             duration_minutes=duration_minutes, room=room)
    try:
        with transaction.atomic():
            appt = Appointment.objects.create(patient=patient, doctor=doctor, scheduled_at=scheduled_at,
                                              scheduled_date=local_date, duration_minutes=duration_minutes,
                                              reason=reason.strip(), notes=notes.strip(), service=service,
                                              source_encounter=source_encounter, appointment_type=appointment_type,
                                              room=room, created_by=ctx.user)
    except IntegrityError as exc:
        raise ConflictError("This patient already has an appointment on that day.") from exc
    record_event(ctx, action="appointment.book", object_type="appointment", object_id=appt.pk,
                 details={"patient": str(patient.pk), "doctor": doctor.username,
                          "at": timezone.localtime(scheduled_at).isoformat(),
                          **({"type": appointment_type.code} if appointment_type else {}),
                          **({"room": room.name} if room else {}),
                          **({"follow_up_of": str(source_encounter.pk)} if source_encounter else {})})
    if doctor != ctx.user:
        notify_user(doctor, kind="appointment", title=f"New appointment: {patient.full_name}",
                    body=f"{_hm(scheduled_at)}{' · ' + appt.reason if appt.reason else ''}",
                    link=f"/appointments?date={local_date.isoformat()}")
    return appt


@transaction.atomic
def confirm_appointment(ctx: ActorContext, appt: Appointment) -> Appointment:
    appt = Appointment.objects.select_for_update().get(pk=appt.pk)
    if appt.status != Appointment.Status.SCHEDULED:
        raise ConflictError("Only scheduled appointments can be confirmed.")
    appt.status = Appointment.Status.CONFIRMED
    appt.confirmed_at = timezone.now()
    appt.save(update_fields=["status", "confirmed_at", "updated_at"])
    record_event(ctx, action="appointment.confirm", object_type="appointment", object_id=appt.pk)
    return appt


@transaction.atomic
def reschedule_appointment(ctx: ActorContext, appt: Appointment, *, scheduled_at: datetime.datetime,
                           duration_minutes: int | None = None, doctor=None, reason: str = "",
                           room=...) -> Appointment:
    appt = Appointment.objects.select_for_update().get(pk=appt.pk)
    if appt.status not in Appointment.BOOKED:
        raise ConflictError("Only appointments that have not started can be rescheduled.")
    doctor = doctor or appt.doctor
    _require_doctor(doctor)
    duration = duration_minutes or appt.duration_minutes
    room = appt.room if room is ... else room
    local_date = _check_slot(doctor=doctor, patient=appt.patient, scheduled_at=scheduled_at,
                             duration_minutes=duration, exclude_id=appt.pk, room=room)
    old = {"at": timezone.localtime(appt.scheduled_at).isoformat(), "doctor": appt.doctor.username}
    appt.scheduled_at, appt.scheduled_date, appt.duration_minutes, appt.doctor = scheduled_at, local_date, duration, doctor
    appt.room = room
    # A moved appointment needs confirming again.
    appt.status, appt.confirmed_at = Appointment.Status.SCHEDULED, None
    appt.reschedule_count += 1
    appt.save()
    record_event(ctx, action="appointment.reschedule", object_type="appointment", object_id=appt.pk,
                 details={"from": old, "to": {"at": timezone.localtime(scheduled_at).isoformat(),
                                               "doctor": doctor.username}, "reason": reason.strip()})
    if doctor != ctx.user:
        notify_user(doctor, kind="appointment", title=f"Appointment moved: {appt.patient.full_name}",
                    body=_hm(scheduled_at), link=f"/appointments?date={local_date.isoformat()}")
    return appt


@transaction.atomic
def cancel_appointment(ctx: ActorContext, appt: Appointment, reason: str, *, no_show: bool = False) -> Appointment:
    appt = Appointment.objects.select_for_update().get(pk=appt.pk)
    if appt.status not in Appointment.BOOKED:
        raise ConflictError(f"Only booked appointments can be {'marked no-show' if no_show else 'cancelled'}.")
    if no_show and appt.scheduled_at > timezone.now():
        raise ConflictError("An appointment can be marked as a no-show only after its time has passed.")
    if not no_show and not reason.strip():
        raise BusinessValidationError("A reason is required.", fields={"reason": ["Required."]})
    appt.status = Appointment.Status.NO_SHOW if no_show else Appointment.Status.CANCELLED
    appt.cancel_reason = reason.strip()
    appt.save(update_fields=["status", "cancel_reason", "updated_at"])
    record_event(ctx, action="appointment.no_show" if no_show else "appointment.cancel", object_type="appointment",
                 object_id=appt.pk, details={"reason": appt.cancel_reason})
    return appt


# ---------------------------------------------------------------------------
# Visits and queue
# ---------------------------------------------------------------------------
def _create_visit(ctx, *, patient, kind, doctor=None, appointment=None, priority=Visit.Priority.ROUTINE) -> Visit:
    from apps.patients.services import require_active

    require_active(patient)
    today = timezone.localdate()
    if Visit.objects.filter(patient=patient, visit_date=today, status__in=Visit.OPEN).exists():
        raise ConflictError("This patient is already in today's queue.")
    number = next_number("queue", today.isoformat())
    try:
        with transaction.atomic():
            from apps.core.modules import is_enabled

            # Without the triage module, patients go straight to the doctors' waiting list.
            first = (Visit.Status.WAITING_TRIAGE if is_enabled("triage") or kind == Visit.Kind.LAB_ONLY
                     else Visit.Status.WAITING_DOCTOR)
            visit = Visit.objects.create(patient=patient, appointment=appointment, visit_date=today,
                                         queue_number=number, kind=kind, priority=priority, status=first,
                                         assigned_doctor=doctor, arrived_at=timezone.now(), created_by=ctx.user)
    except IntegrityError as exc:
        raise ConflictError("This patient is already in today's queue.") from exc
    record_event(ctx, action="visit.check_in", object_type="visit", object_id=visit.pk,
                 details={"patient": str(patient.pk), "kind": kind, "queue_number": number})
    label = "Arrived for appointment" if appointment else "Registered as walk-in"
    visit_event(ctx, visit, "arrived", f"{label}, queue number {number}, priority {visit.get_priority_display().lower()}")
    if doctor is not None and doctor != ctx.user:
        notify_user(doctor, kind="arrival", title=f"Patient arrived: {patient.full_name}",
                    body=f"Queue number {number}", link="/queue")
    if priority == Visit.Priority.EMERGENCY:
        _alert_emergency(ctx, visit)
    return visit


def _alert_emergency(ctx, visit: Visit) -> None:
    for perm in ("triage.record", "clinical.write", "dental.write"):
        notify_permission_holders(perm, kind="emergency", title=f"EMERGENCY: {visit.patient.full_name}",
                                  body=f"Queue number {visit.queue_number}", link="/queue", exclude_user=ctx.user)


@transaction.atomic
def check_in(ctx: ActorContext, appt: Appointment) -> Visit:
    appt = Appointment.objects.select_for_update().get(pk=appt.pk)
    if appt.status not in Appointment.BOOKED:
        raise ConflictError("Only booked appointments can be checked in.")
    if appt.scheduled_date != timezone.localdate():
        raise ConflictError("This appointment is not for today.")
    visit = _create_visit(ctx, patient=appt.patient, kind=Visit.Kind.APPOINTMENT, doctor=appt.doctor,
                          appointment=appt)
    appt.status = Appointment.Status.ARRIVED
    appt.save(update_fields=["status", "updated_at"])
    return visit


@transaction.atomic
def register_walk_in(ctx: ActorContext, *, patient, doctor=None, priority=Visit.Priority.ROUTINE) -> Visit:
    _require_doctor(doctor)
    return _create_visit(ctx, patient=patient, kind=Visit.Kind.WALK_IN, doctor=doctor, priority=priority)


_TRANSITIONS = {
    Visit.Status.WAITING_TRIAGE: {Visit.Status.WAITING_DOCTOR, Visit.Status.CANCELLED},
    Visit.Status.WAITING_DOCTOR: {Visit.Status.IN_CONSULTATION, Visit.Status.WAITING_TRIAGE, Visit.Status.CANCELLED},
    # A doctor can pause (patient back to the waiting list) or sign (patient moves on to other services).
    Visit.Status.IN_CONSULTATION: {Visit.Status.AFTER_CONSULTATION, Visit.Status.WAITING_DOCTOR},
    # After consultation the patient may go back to the doctor (e.g. to review results), or the visit is closed.
    Visit.Status.AFTER_CONSULTATION: {Visit.Status.WAITING_DOCTOR, Visit.Status.IN_CONSULTATION,
                                      Visit.Status.COMPLETED},
    Visit.Status.COMPLETED: {Visit.Status.AFTER_CONSULTATION},  # reopen, with a reason
}

_EVENT_TEXT = {
    Visit.Status.WAITING_TRIAGE: "Sent back to triage",
    Visit.Status.WAITING_DOCTOR: "Waiting for the doctor",
    Visit.Status.IN_CONSULTATION: "Consultation started",
    Visit.Status.AFTER_CONSULTATION: "Consultation finished; other services may continue",
    Visit.Status.CANCELLED: "Visit cancelled",
}


def transition_visit(ctx: ActorContext, visit: Visit, new_status: str, *, reason: str = "") -> Visit:
    """Called inside the caller's transaction."""
    visit = Visit.objects.select_for_update().get(pk=visit.pk)
    if visit.status == new_status:
        return visit
    if new_status not in _TRANSITIONS.get(visit.status, set()):
        raise ConflictError(f"A visit cannot move from '{visit.get_status_display()}' "
                            f"to '{Visit.Status(new_status).label}'.")
    old = visit.status
    visit.status = new_status
    fields = ["status", "updated_at"]
    now = timezone.now()
    if new_status == Visit.Status.IN_CONSULTATION and not visit.consultation_started_at:
        visit.consultation_started_at = now
        fields.append("consultation_started_at")
    if new_status == Visit.Status.COMPLETED:
        raise ConflictError("Use visit completion to close a visit.")
    if old == Visit.Status.COMPLETED:
        if not reason.strip():
            raise BusinessValidationError("A reason is required to reopen a visit.", fields={"reason": ["Required."]})
        visit.completed_at, visit.completed_by, visit.outcome, visit.completion_note = None, None, "", ""
        fields += ["completed_at", "completed_by", "outcome", "completion_note"]
        if visit.appointment_id:
            Appointment.objects.filter(pk=visit.appointment_id).update(status=Appointment.Status.ARRIVED)
    if new_status in Visit.WAITING:
        visit.called_at, visit.called_by, visit.called_room = None, None, ""
        fields += ["called_at", "called_by", "called_room"]
    if new_status == Visit.Status.CANCELLED:
        if not reason.strip():
            raise BusinessValidationError("A reason is required.", fields={"reason": ["Required."]})
        visit.cancel_reason = reason.strip()
        fields.append("cancel_reason")
    visit.save(update_fields=fields)
    record_event(ctx, action="visit.status", object_type="visit", object_id=visit.pk,
                 details={"from": old, "to": new_status, **({"reason": reason} if reason else {})})
    text = "Visit reopened" if old == Visit.Status.COMPLETED else _EVENT_TEXT.get(new_status, new_status)
    visit_event(ctx, visit, f"status.{new_status}", f"{text}{': ' + reason.strip() if reason.strip() else ''}")
    return visit


@transaction.atomic
def update_queue_entry(ctx: ActorContext, visit: Visit, *, status: str | None = None, doctor=..., priority=None,
                       reason: str = "") -> Visit:
    if status:
        if status in (Visit.Status.IN_CONSULTATION, Visit.Status.COMPLETED):
            raise ConflictError("Consultations are started and completed from the consultation screen.")
        if status == Visit.Status.WAITING_DOCTOR and visit.status == Visit.Status.WAITING_TRIAGE:
            from apps.core.models import ClinicSettings

            if not ClinicSettings.get().allow_skip_triage:
                raise ConflictError("This clinic requires triage before the doctor. A doctor can still take an "
                                    "emergency straight in from the waiting list.")
        visit = transition_visit(ctx, visit, status, reason=reason)
    changes = {}
    if doctor is not ...:
        _require_doctor(doctor)
        if visit.assigned_doctor_id != (doctor.pk if doctor else None):
            changes["doctor"] = {"from": str(visit.assigned_doctor_id or ""), "to": str(doctor.pk if doctor else "")}
            visit.assigned_doctor = doctor
    if priority and priority != visit.priority:
        changes["priority"] = {"from": visit.priority, "to": priority}
        visit.priority = priority
    if changes:
        visit.save(update_fields=["assigned_doctor", "priority", "updated_at"])
        record_event(ctx, action="visit.update", object_type="visit", object_id=visit.pk, details=changes)
        if "doctor" in changes:
            visit_event(ctx, visit, "queue.reassign",
                        f"Assigned to Dr. {visit.assigned_doctor.full_name}" if visit.assigned_doctor
                        else "Assigned to the first available doctor")
            if visit.assigned_doctor and visit.assigned_doctor != ctx.user:
                notify_user(visit.assigned_doctor, kind="arrival", title=f"Patient assigned: {visit.patient.full_name}",
                            body=f"Queue number {visit.queue_number}", link="/queue")
        if "priority" in changes:
            visit_event(ctx, visit, "queue.priority", f"Priority set to {visit.get_priority_display().lower()}"
                        + (f": {reason.strip()}" if reason.strip() else ""))
            if visit.priority == Visit.Priority.EMERGENCY:
                _alert_emergency(ctx, visit)
    return visit


# ---------------------------------------------------------------------------
# Queue handling: call, skip, return. These change the queue only, never the clinical record.
# ---------------------------------------------------------------------------
PRIORITY_RANK = {Visit.Priority.EMERGENCY: 0, Visit.Priority.URGENT: 1, Visit.Priority.ROUTINE: 2}


def queue_order(visit: Visit) -> tuple:
    """Emergencies first, then urgent, then routine; skipped patients go to the end; then arrival order."""
    return (visit.skipped_at is not None, PRIORITY_RANK.get(visit.priority, 3), visit.queue_number)


def _lock_open(visit: Visit) -> Visit:
    visit = Visit.objects.select_for_update().get(pk=visit.pk)
    if visit.status not in Visit.WAITING:
        raise ConflictError("Only waiting patients can be called or skipped.")
    return visit


@transaction.atomic
def call_next(ctx: ActorContext, *, stage: str) -> Visit | None:
    """Call the next waiting patient for triage or for this doctor. Returns None if nobody is waiting."""
    status = {"triage": Visit.Status.WAITING_TRIAGE, "doctor": Visit.Status.WAITING_DOCTOR}.get(stage)
    if status is None:
        raise BusinessValidationError("Unknown queue stage.")
    qs = Visit.objects.select_for_update().filter(visit_date=timezone.localdate(), status=status)
    if stage == "doctor":
        from django.db.models import Q

        qs = qs.filter(Q(assigned_doctor=ctx.user) | Q(assigned_doctor__isnull=True))
    candidates = sorted(qs, key=queue_order)
    if not candidates:
        return None
    return call_patient(ctx, candidates[0])


@transaction.atomic
def call_patient(ctx: ActorContext, visit: Visit) -> Visit:
    visit = _lock_open(visit)
    room = ctx.user.room.name if getattr(ctx.user, "room_id", None) and ctx.user.room.is_active else ""
    visit.called_at, visit.called_by, visit.called_room = timezone.now(), ctx.user, room
    visit.skipped_at, visit.skip_reason = None, ""
    visit.save(update_fields=["called_at", "called_by", "called_room", "skipped_at", "skip_reason", "updated_at"])
    record_event(ctx, action="queue.call", object_type="visit", object_id=visit.pk, details={"room": room})
    visit_event(ctx, visit, "queue.call", f"Called by {ctx.user.full_name}" + (f" to {room}" if room else ""))
    return visit


@transaction.atomic
def skip_patient(ctx: ActorContext, visit: Visit, reason: str) -> Visit:
    visit = _lock_open(visit)
    if not reason.strip():
        raise BusinessValidationError("A reason is required.", fields={"reason": ["Required."]})
    visit.skipped_at, visit.skip_reason = timezone.now(), reason.strip()
    visit.called_at, visit.called_by = None, None
    visit.save(update_fields=["skipped_at", "skip_reason", "called_at", "called_by", "updated_at"])
    record_event(ctx, action="queue.skip", object_type="visit", object_id=visit.pk, details={"reason": visit.skip_reason})
    visit_event(ctx, visit, "queue.skip", f"Skipped: {visit.skip_reason}")
    return visit


@transaction.atomic
def return_to_queue(ctx: ActorContext, visit: Visit) -> Visit:
    visit = _lock_open(visit)
    if visit.skipped_at is None:
        raise ConflictError("This patient was not skipped.")
    visit.skipped_at, visit.skip_reason = None, ""
    visit.save(update_fields=["skipped_at", "skip_reason", "updated_at"])
    record_event(ctx, action="queue.return", object_type="visit", object_id=visit.pk)
    visit_event(ctx, visit, "queue.return", "Returned to the queue")
    return visit


# ---------------------------------------------------------------------------
# Appointment types
# ---------------------------------------------------------------------------
@transaction.atomic
def save_appointment_type(ctx: ActorContext, data: dict, *, appt_type=None, room=...):
    from .models import AppointmentType

    data = dict(data)
    data.pop("row_version", None)
    created = appt_type is None
    if created:
        if AppointmentType.objects.filter(code=data["code"]).exists():
            raise ConflictError("An appointment type with this code exists.", fields={"code": ["Already used."]})
        appt_type = AppointmentType(**data, default_room=None if room is ... else room)
    else:
        for key, value in data.items():
            setattr(appt_type, key, value)
        if room is not ...:
            appt_type.default_room = room
    appt_type.save()
    record_event(ctx, action="appointment_type.create" if created else "appointment_type.update",
                 object_type="appointment_type", object_id=appt_type.pk,
                 details={"code": appt_type.code, "fields": sorted(data)})
    return appt_type
