"""
Orthodontics: the assessment in a dental examination, the treatment course (case), what was done at each
orthodontic visit, retention, and how the course is paid for.

Two ways to charge, chosen per case and changeable later with a reason:

* package: one agreed price for the whole course, paid as an optional deposit plus instalments on a schedule.
  Instalments become invoice lines when they fall due (or when brought forward). Visits are not charged.
* per visit: each orthodontic visit is charged at the case's per-visit price unless the dentist records why not.

Either way an extra charge (lost retainer, broken appliance) can be added to a visit with its reason. Nothing is
charged twice: invoice lines carry the instalment or visit they came from (see apps/billing/services.py).
Clinical vocabulary here is a starter list pending clinical review (docs/dental/clinical-review-log.md, R-15).
"""

from __future__ import annotations

import datetime
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import CharField, Exists, OuterRef, QuerySet
from django.db.models.functions import Cast
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import record_event
from apps.billing.models import Invoice, InvoiceLine
from apps.core.concurrency import check_version
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError, PermissionDeniedError
from apps.core.modules import is_enabled
from apps.core.numbering import next_number
from apps.patients.models import Patient
from apps.scheduling.models import Visit

from ..models import (
    DentalEncounter, OrthoAssessment, OrthoCase, OrthoCaseEvent, OrthoInstalment, OrthoVisit, Recall, TreatmentPlan,
)
from . import recalls as recall_svc
from .common import own_open_encounter, same_patient

C = OrthoCase.Status
K = OrthoVisit.Kind
CENT = Decimal("0.01")
INSTALMENT_SOURCE = "ortho_instalment"
VISIT_SOURCE = "ortho_visit"
EXTRA_SOURCE = "ortho_extra"


def _require_module() -> None:
    if not is_enabled("orthodontics"):
        raise ConflictError("Orthodontics is switched off for this clinic.")


def _money(value, field: str, *, required: bool = False) -> Decimal | None:
    if value in (None, ""):
        if required:
            raise BusinessValidationError("Enter the amount.", fields={field: ["Required."]})
        return None
    try:
        amount = Decimal(str(value)).quantize(CENT)
    except (InvalidOperation, ValueError):
        raise BusinessValidationError("Enter an amount in birr.", fields={field: ["Not a number."]}) from None
    if amount < 0:
        raise BusinessValidationError("The amount cannot be negative.", fields={field: ["Negative."]})
    return amount


def _int(value, field: str, low: int, high: int, *, required: bool = False) -> int | None:
    if value in (None, ""):
        if required:
            raise BusinessValidationError("This is required.", fields={field: ["Required."]})
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise BusinessValidationError("Enter a whole number.", fields={field: ["Not a whole number."]}) from None
    if not low <= number <= high:
        raise BusinessValidationError(f"Enter a number from {low} to {high}.", fields={field: [f"{low}–{high}."]})
    return number


def _choice(value, choices, field: str) -> str:
    value = value or ""
    if value and value not in choices.values:
        raise BusinessValidationError("Choose one of the options.", fields={field: ["Invalid choice."]})
    return value


def _event(ctx: ActorContext, case: OrthoCase, action: str, note: str = "", **details) -> None:
    OrthoCaseEvent.objects.create(case=case, action=action, note=note[:255], actor=ctx.user)
    record_event(ctx, action=f"dental_ortho.{action}", object_type="ortho_case", object_id=case.pk,
                 details={"number": case.number, "patient": str(case.patient_id), **details})


# ===========================================================================
# Assessment
# ===========================================================================
@transaction.atomic
def save_assessment(ctx: ActorContext, encounter: DentalEncounter, data: dict,
                    expected_version: int | None = None) -> OrthoAssessment:
    """Create or update the orthodontic assessment of a draft examination (the examining dentist only)."""
    _require_module()
    enc = own_open_encounter(ctx, encounter)
    values: dict = {}
    for field, choices in OrthoAssessment.CHOICE_FIELDS.items():
        if field in data:
            values[field] = _choice(data.get(field), choices, field)
    for field in OrthoAssessment.TEXT_FIELDS:
        if field in data:
            limit = OrthoAssessment._meta.get_field(field).max_length
            text = str(data.get(field) or "").strip()
            values[field] = text[:limit] if limit else text
    for field in ("overjet_mm", "overbite_mm"):
        if field in data:
            raw = data.get(field)
            if raw in (None, ""):
                values[field] = None
                continue
            try:
                mm = Decimal(str(raw)).quantize(Decimal("0.1"))
            except (InvalidOperation, ValueError):
                raise BusinessValidationError("Enter millimetres, e.g. 4 or -2.5.", fields={field: ["Not a number."]}) \
                    from None
            if not Decimal(-20) <= mm <= Decimal(20):
                raise BusinessValidationError("Enter a value from -20 to 20 mm.", fields={field: ["Out of range."]})
            values[field] = mm
    existing = OrthoAssessment.objects.select_for_update().filter(encounter=enc).first()
    if existing is None:
        assessment = OrthoAssessment.objects.create(patient=enc.patient, encounter=enc, recorded_by=ctx.user, **values)
        action = "dental_ortho.assessment_create"
    else:
        check_version(existing, expected_version, object_type="ortho_assessment", label="orthodontic assessment")
        for field, value in values.items():
            setattr(existing, field, value)
        existing.save()
        assessment = existing
        action = "dental_ortho.assessment_update"
    record_event(ctx, action=action, object_type="ortho_assessment", object_id=assessment.pk,
                 details={"patient": str(enc.patient_id), "encounter": str(enc.pk), "fields": sorted(values)})
    return assessment


# ===========================================================================
# Billing state
# ===========================================================================
def _billed_line(source_type: str):
    return InvoiceLine.objects.filter(source_type=source_type, source_id=Cast(OuterRef("pk"), CharField()),
                                      is_void=False)


def unbilled_instalments(qs: QuerySet) -> QuerySet:
    """Scheduled instalments that are not on any live invoice line yet."""
    return qs.filter(status=OrthoInstalment.Status.SCHEDULED).exclude(Exists(_billed_line(INSTALMENT_SOURCE)))


def instalment_lines(instalments) -> dict[str, InvoiceLine]:
    """Instalment id → the live invoice line that charged it, with its invoice."""
    ids = [str(i.pk) for i in instalments]
    lines = (InvoiceLine.objects.filter(source_type=INSTALMENT_SOURCE, source_id__in=ids, is_void=False)
             .select_related("invoice"))
    return {line.source_id: line for line in lines}


def instalment_state(inst: OrthoInstalment, line: InvoiceLine | None, today: datetime.date | None = None) -> str:
    """scheduled / due / overdue / invoiced / part_paid / paid / cancelled, for display."""
    today = today or timezone.localdate()
    if inst.status == OrthoInstalment.Status.CANCELLED:
        return "cancelled"
    if line is not None:
        status = line.invoice.status
        if status == Invoice.Status.PAID:
            return "paid"
        if status == Invoice.Status.PARTIAL:
            return "part_paid"
        return "invoiced"
    if inst.due_date < today:
        return "overdue"
    return "due" if inst.due_date == today else "scheduled"


def due_instalment_charges(patient_id, on_date: datetime.date) -> list[dict]:
    """Instalments of this patient due on or before `on_date` and not yet invoiced, as invoice charges."""
    qs = unbilled_instalments(OrthoInstalment.objects.filter(case__patient_id=patient_id, due_date__lte=on_date))
    return [{"kind": InvoiceLine.Kind.PROCEDURE,
             "description": f"Orthodontic treatment {i.case.number}: {i.label} (due {i.due_date:%d %b %Y})"[:200],
             "quantity": Decimal(1), "unit_price": i.amount, "source_type": INSTALMENT_SOURCE,
             "source_id": str(i.pk)}
            for i in qs.select_related("case").order_by("due_date", "sequence")]


def visit_charges(visit: Visit) -> list[dict]:
    """Per-visit charges and extra charges from orthodontic visit records on this clinic visit."""
    charges = []
    for ov in (OrthoVisit.objects.filter(visit=visit, status=OrthoVisit.Status.RECORDED)
               .select_related("case").order_by("created_at")):
        if ov.charge:
            charges.append({"kind": InvoiceLine.Kind.PROCEDURE,
                            "description": f"Orthodontic visit {ov.case.number}: {ov.get_kind_display()}"[:200],
                            "quantity": Decimal(1), "unit_price": ov.charge, "source_type": VISIT_SOURCE,
                            "source_id": str(ov.pk)})
        if ov.extra_charge:
            charges.append({"kind": InvoiceLine.Kind.PROCEDURE,
                            "description": f"Orthodontics {ov.case.number}: {ov.extra_charge_reason}"[:200],
                            "quantity": Decimal(1), "unit_price": ov.extra_charge, "source_type": EXTRA_SOURCE,
                            "source_id": str(ov.pk)})
    return charges


def _is_billed(source_type: str, pk) -> bool:
    return InvoiceLine.objects.filter(source_type=source_type, source_id=str(pk), is_void=False).exists()


def billed_total(case: OrthoCase) -> Decimal:
    """What has been put on live invoices for this case's instalments."""
    lines = instalment_lines(case.instalments.all())
    return sum((line.line_total for line in lines.values()), Decimal("0.00"))


# ===========================================================================
# Instalment schedule
# ===========================================================================
def _schedule(case: OrthoCase, *, amount: Decimal, deposit: Decimal, count: int, interval_days: int,
              first_date: datetime.date) -> list[OrthoInstalment]:
    """Split `amount` into an optional deposit (due on first_date) and `count` equal instalments."""
    start = (case.instalments.order_by("-sequence").values_list("sequence", flat=True).first() or 0) + 1
    rows: list[OrthoInstalment] = []
    if deposit > 0:
        rows.append(OrthoInstalment(case=case, sequence=start, label="Deposit", due_date=first_date, amount=deposit))
    rest = amount - deposit
    if rest > 0:
        base = (rest / count).quantize(CENT, rounding=ROUND_DOWN)
        offset = 1 if deposit > 0 else 0
        for k in range(count):
            share = base if k < count - 1 else rest - base * (count - 1)
            if share <= 0:
                continue
            rows.append(OrthoInstalment(
                case=case, sequence=start + len(rows), label=f"Instalment {k + 1} of {count}",
                due_date=first_date + datetime.timedelta(days=interval_days * (k + offset)), amount=share))
    return OrthoInstalment.objects.bulk_create(rows)


def _schedule_input(data: dict, *, amount: Decimal, allow_deposit: bool) -> dict:
    deposit = _money(data.get("deposit"), "deposit") or Decimal("0.00") if allow_deposit else Decimal("0.00")
    if deposit > amount:
        raise BusinessValidationError("The deposit is more than the package price.", fields={"deposit": ["Too high."]})
    count = _int(data.get("instalment_count"), "instalment_count", 1, 60, required=amount - deposit > 0) or 1
    interval = _int(data.get("instalment_interval_days"), "instalment_interval_days", 7, 92) or 30
    first = data.get("first_payment_date") or timezone.localdate()
    if isinstance(first, str):
        try:
            first = datetime.date.fromisoformat(first)
        except ValueError:
            raise BusinessValidationError("Enter a date.", fields={"first_payment_date": ["Invalid date."]}) from None
    if first < timezone.localdate() - datetime.timedelta(days=31):
        raise BusinessValidationError("The first payment date is too far in the past.",
                                      fields={"first_payment_date": ["Too early."]})
    return {"deposit": deposit, "count": count, "interval_days": interval, "first_date": first}


def _cancel_unbilled(case: OrthoCase, reason: str) -> int:
    ids = list(unbilled_instalments(case.instalments.all()).values_list("pk", flat=True))
    OrthoInstalment.objects.filter(pk__in=ids).update(status=OrthoInstalment.Status.CANCELLED,
                                                      cancelled_reason=reason[:255], updated_at=timezone.now())
    return len(ids)


# ===========================================================================
# Cases
# ===========================================================================
def _orthodontist(pk, ctx: ActorContext) -> User:
    if not pk:
        return ctx.user
    user = User.objects.filter(pk=pk, is_active=True).first()
    if user is None or not user.has_permissions(["dental.ortho.manage"]):
        raise BusinessValidationError("Choose a dentist who manages orthodontic cases.",
                                      fields={"orthodontist_id": ["Not allowed."]})
    return user


def _billing_fields(data: dict) -> dict:
    mode = data.get("billing_mode")
    if mode not in OrthoCase.Billing.values:
        raise BusinessValidationError("Choose how the treatment is charged.", fields={"billing_mode": ["Required."]})
    if mode == OrthoCase.Billing.PACKAGE:
        return {"billing_mode": mode, "package_price": _money(data.get("package_price"), "package_price",
                                                               required=True)}
    return {"billing_mode": mode, "per_visit_price": _money(data.get("per_visit_price"), "per_visit_price",
                                                             required=True)}


@transaction.atomic
def create_case(ctx: ActorContext, patient: Patient, data: dict) -> OrthoCase:
    _require_module()
    Patient.objects.select_for_update().filter(pk=patient.pk).first()  # one open case at a time, even when racing
    if OrthoCase.objects.filter(patient=patient, status__in=OrthoCase.OPEN).exists():
        raise ConflictError("This patient already has an open orthodontic case. Complete or discontinue it first.")
    appliance = data.get("appliance")
    if appliance not in OrthoCase.Appliance.values:
        raise BusinessValidationError("Choose the appliance.", fields={"appliance": ["Required."]})
    arches = data.get("arches") or OrthoCase.Arches.BOTH
    if arches not in OrthoCase.Arches.values:
        raise BusinessValidationError("Choose the arches.", fields={"arches": ["Invalid."]})
    assessment = plan = None
    if data.get("assessment_id"):
        assessment = OrthoAssessment.objects.filter(pk=data["assessment_id"]).first()
        if assessment is None:
            raise BusinessValidationError("Unknown assessment.", fields={"assessment_id": ["Not found."]})
        same_patient(assessment, patient.pk, "assessment_id")
    if data.get("plan_id"):
        plan = TreatmentPlan.objects.filter(pk=data["plan_id"]).first()
        if plan is None:
            raise BusinessValidationError("Unknown treatment plan.", fields={"plan_id": ["Not found."]})
        same_patient(plan, patient.pk, "plan_id")
    billing = _billing_fields(data)
    schedule = None
    if billing["billing_mode"] == OrthoCase.Billing.PACKAGE:
        schedule = _schedule_input(data, amount=billing["package_price"], allow_deposit=True)
        billing["deposit"] = schedule["deposit"]
    year = timezone.localdate().year
    case = OrthoCase.objects.create(
        number=f"OC-{year}-{next_number('dental_ortho_case', str(year)):05d}", patient=patient, assessment=assessment,
        plan=plan, orthodontist=_orthodontist(data.get("orthodontist_id"), ctx), appliance=appliance, arches=arches,
        objectives=str(data.get("objectives") or "").strip(), notes=str(data.get("notes") or "").strip(),
        expected_months=_int(data.get("expected_months"), "expected_months", 1, 96), created_by=ctx.user, **billing)
    if schedule:
        _schedule(case, amount=case.package_price, deposit=schedule["deposit"], count=schedule["count"],
                  interval_days=schedule["interval_days"], first_date=schedule["first_date"])
    _event(ctx, case, "create", f"{case.get_appliance_display()}; {case.get_billing_mode_display()}",
           billing_mode=case.billing_mode, package_price=str(case.package_price or ""),
           per_visit_price=str(case.per_visit_price or ""))
    return case


def lock_case(case: OrthoCase, expected_version: int | None = None) -> OrthoCase:
    case = OrthoCase.objects.select_for_update().get(pk=case.pk)
    check_version(case, expected_version, object_type="ortho_case", label="orthodontic case")
    return case


@transaction.atomic
def update_case(ctx: ActorContext, case: OrthoCase, data: dict, expected_version: int | None = None) -> OrthoCase:
    """Clinical details of the case. Prices and status have their own actions."""
    _require_module()
    case = lock_case(case, expected_version)
    if case.status not in OrthoCase.OPEN:
        raise ConflictError("This case is closed.")
    changed = []
    if "orthodontist_id" in data:
        case.orthodontist = _orthodontist(data["orthodontist_id"], ctx)
        changed.append("orthodontist")
    if "appliance" in data:
        if data["appliance"] not in OrthoCase.Appliance.values:
            raise BusinessValidationError("Choose the appliance.", fields={"appliance": ["Invalid."]})
        case.appliance = data["appliance"]
        changed.append("appliance")
    if "arches" in data:
        if data["arches"] not in OrthoCase.Arches.values:
            raise BusinessValidationError("Choose the arches.", fields={"arches": ["Invalid."]})
        case.arches = data["arches"]
        changed.append("arches")
    for field in ("objectives", "notes"):
        if field in data:
            setattr(case, field, str(data[field] or "").strip())
            changed.append(field)
    if "expected_months" in data:
        case.expected_months = _int(data["expected_months"], "expected_months", 1, 96)
        changed.append("expected_months")
    if "retention_review_months" in data:
        case.retention_review_months = _int(data["retention_review_months"], "retention_review_months", 1, 60)
        changed.append("retention_review_months")
    for field in ("retainer_upper", "retainer_lower"):
        if field in data:
            setattr(case, field, _choice(data[field], OrthoCase.Retainer, field))
            changed.append(field)
    case.save()
    if changed:
        record_event(ctx, action="dental_ortho.update", object_type="ortho_case", object_id=case.pk,
                     details={"number": case.number, "fields": changed})
    return case


@transaction.atomic
def change_status(ctx: ActorContext, case: OrthoCase, action: str, *, reason: str = "",
                  on_date: datetime.date | None = None) -> OrthoCase:
    """start (planned → active), retention (active → retention), complete, discontinue."""
    _require_module()
    case = lock_case(case)
    today = on_date or timezone.localdate()
    if action == "start":
        if case.status != C.PLANNED:
            raise ConflictError("Only a planned case can be started.")
        case.status, case.started_on = C.ACTIVE, today
    elif action == "retention":
        if case.status != C.ACTIVE:
            raise ConflictError("Only a case in active treatment can move to retention.")
        case.status, case.debonded_on = C.RETENTION, case.debonded_on or today
    elif action == "complete":
        if case.status not in (C.ACTIVE, C.RETENTION):
            raise ConflictError("Only a case in active treatment or retention can be completed.")
        case.status, case.closed_on, case.closed_reason = C.COMPLETED, today, reason.strip()[:255]
    elif action == "discontinue":
        if case.status not in OrthoCase.OPEN:
            raise ConflictError("This case is already closed.")
        if not reason.strip():
            raise BusinessValidationError("Give the reason.", fields={"reason": ["Required."]})
        case.status, case.closed_on, case.closed_reason = C.DISCONTINUED, today, reason.strip()[:255]
        cancelled = _cancel_unbilled(case, f"Case discontinued: {reason.strip()}")
        if cancelled:
            reason = f"{reason.strip()} ({cancelled} instalment(s) not yet invoiced were cancelled)"
    else:
        raise BusinessValidationError("Unknown action.", fields={"action": ["Invalid."]})
    case.save()
    _event(ctx, case, action, reason.strip(), status=case.status)
    return case


@transaction.atomic
def change_billing(ctx: ActorContext, case: OrthoCase, data: dict) -> OrthoCase:
    """
    Change the price or the way the case is charged, with a reason. What is already invoiced stays as it is:
    for a package, the new price minus what has been invoiced is rescheduled; instalments not yet invoiced are
    cancelled and replaced.
    """
    _require_module()
    case = lock_case(case, data.get("version"))
    if case.status not in OrthoCase.OPEN:
        raise ConflictError("This case is closed.")
    reason = str(data.get("reason") or "").strip()
    if not reason:
        raise BusinessValidationError("Give the reason for the change.", fields={"reason": ["Required."]})
    billing = _billing_fields(data)
    already = billed_total(case)
    old = f"{case.get_billing_mode_display()}: " + (
        f"{case.package_price} ETB" if case.billing_mode == OrthoCase.Billing.PACKAGE else f"{case.per_visit_price} ETB")
    cancelled = _cancel_unbilled(case, f"Billing changed: {reason}")
    case.billing_mode = billing["billing_mode"]
    if case.billing_mode == OrthoCase.Billing.PACKAGE:
        price = billing["package_price"]
        if price < already:
            raise BusinessValidationError(f"{already} ETB has already been invoiced; the package price cannot be "
                                          "lower than that.", fields={"package_price": ["Below what is invoiced."]})
        nothing_invoiced = already == 0
        schedule = _schedule_input(data, amount=price - already, allow_deposit=nothing_invoiced)
        case.package_price = price
        case.deposit = schedule["deposit"] if nothing_invoiced else min(case.deposit, price)
        case.save()
        _schedule(case, amount=price - already, deposit=schedule["deposit"], count=schedule["count"],
                  interval_days=schedule["interval_days"], first_date=schedule["first_date"])
        new = f"{case.get_billing_mode_display()}: {price} ETB ({already} ETB already invoiced)"
    else:
        case.per_visit_price = billing["per_visit_price"]
        case.save()
        new = f"{case.get_billing_mode_display()}: {case.per_visit_price} ETB per visit"
    _event(ctx, case, "billing_change", f"{old} → {new}. {reason}"[:255], cancelled_instalments=cancelled)
    return case


@transaction.atomic
def bring_forward(ctx: ActorContext, inst: OrthoInstalment, reason: str = "") -> OrthoInstalment:
    """Make an instalment due today, so the cashier can take it early."""
    _require_module()
    inst = OrthoInstalment.objects.select_for_update().select_related("case").get(pk=inst.pk)
    if inst.status != OrthoInstalment.Status.SCHEDULED or _is_billed(INSTALMENT_SOURCE, inst.pk):
        raise ConflictError("Only an instalment that is not invoiced yet can be brought forward.")
    today = timezone.localdate()
    if inst.due_date <= today:
        return inst
    old = inst.due_date
    inst.due_date = today
    inst.save(update_fields=["due_date", "updated_at"])
    _event(ctx, inst.case, "instalment_forward", f"{inst.label}: due {old:%d %b %Y} → today. {reason}".strip(),
           instalment=str(inst.pk))
    return inst


# ===========================================================================
# Visits
# ===========================================================================
# What a visit does to the case.
STARTS = {K.BONDING, K.ALIGNER}
ALLOWED_WHEN = {
    C.PLANNED: {K.RECORDS, K.BONDING, K.ALIGNER, K.OTHER},
    C.ACTIVE: {K.RECORDS, K.ADJUSTMENT, K.ALIGNER, K.EMERGENCY, K.DEBOND, K.RETAINER_FIT, K.OTHER, K.BONDING},
    C.RETENTION: {K.RECORDS, K.RETENTION_REVIEW, K.RETAINER_FIT, K.EMERGENCY, K.OTHER},
}


def _clinic_visit(case: OrthoCase, data: dict) -> tuple[Visit, DentalEncounter | None]:
    encounter = None
    if data.get("encounter_id"):
        encounter = DentalEncounter.objects.select_related("visit").filter(pk=data["encounter_id"]).first()
        if encounter is None:
            raise BusinessValidationError("Unknown examination.", fields={"encounter_id": ["Not found."]})
        same_patient(encounter, case.patient_id, "encounter_id")
        visit = encounter.visit
    elif data.get("visit_id"):
        visit = Visit.objects.filter(pk=data["visit_id"]).first()
        if visit is None:
            raise BusinessValidationError("Unknown visit.", fields={"visit_id": ["Not found."]})
        same_patient(visit, case.patient_id, "visit_id")
    else:
        visit = (Visit.objects.filter(patient_id=case.patient_id, visit_date=timezone.localdate())
                 .exclude(status__in=[Visit.Status.COMPLETED, Visit.Status.CANCELLED]).order_by("-created_at").first())
        if visit is None:
            raise ConflictError("The patient has no open visit today. Add them to the waiting list first.")
    if visit.status in (Visit.Status.COMPLETED, Visit.Status.CANCELLED):
        raise ConflictError("This visit is closed. Reopen it to record the orthodontic visit.")
    return visit, encounter


@transaction.atomic
def record_visit(ctx: ActorContext, case: OrthoCase, data: dict) -> OrthoVisit:
    _require_module()
    case = lock_case(case)
    kind = data.get("kind")
    if kind not in K.values:
        raise BusinessValidationError("Choose what was done.", fields={"kind": ["Required."]})
    if case.status not in OrthoCase.OPEN:
        raise ConflictError("This case is closed.")
    if kind not in ALLOWED_WHEN[case.status]:
        hint = {C.PLANNED: "Record the fitting of the braces or the first aligners first.",
                C.ACTIVE: "Record the removal of the braces first.",
                C.RETENTION: "The case is in retention."}[case.status]
        raise ConflictError(f"“{K(kind).label}” cannot be recorded while the case is "
                            f"{case.get_status_display().lower()}. {hint}")
    visit, encounter = _clinic_visit(case, data)
    charge, no_charge_reason = None, ""
    if case.billing_mode == OrthoCase.Billing.PER_VISIT:
        if data.get("charge_this_visit", True) in (False, "false", 0, "0"):
            no_charge_reason = str(data.get("no_charge_reason") or "").strip()
            if not no_charge_reason:
                raise BusinessValidationError("Say why this visit is not charged.",
                                              fields={"no_charge_reason": ["Required."]})
        else:
            charge = case.per_visit_price
    extra = _money(data.get("extra_charge"), "extra_charge") or Decimal("0.00")
    extra_reason = str(data.get("extra_charge_reason") or "").strip()
    if extra > 0 and not extra_reason:
        raise BusinessValidationError("Say what the extra charge is for.", fields={"extra_charge_reason": ["Required."]})
    ov = OrthoVisit.objects.create(
        case=case, visit=visit, encounter=encounter, kind=kind,
        upper_wire=str(data.get("upper_wire") or "").strip()[:60],
        lower_wire=str(data.get("lower_wire") or "").strip()[:60],
        elastics=str(data.get("elastics") or "").strip()[:120],
        aligner_number=_int(data.get("aligner_number"), "aligner_number", 1, 200),
        breakages=str(data.get("breakages") or "").strip()[:255],
        oral_hygiene=_choice(data.get("oral_hygiene"), OrthoAssessment.Hygiene, "oral_hygiene"),
        compliance=_choice(data.get("compliance"), OrthoAssessment.Hygiene, "compliance"),
        notes=str(data.get("notes") or "").strip(),
        next_interval_weeks=_int(data.get("next_interval_weeks"), "next_interval_weeks", 1, 52),
        performed_by=ctx.user, charge=charge, no_charge_reason=no_charge_reason[:255],
        extra_charge=extra, extra_charge_reason=extra_reason[:120] if extra > 0 else "")
    # What the visit does to the case.
    if kind in STARTS and case.status == C.PLANNED:
        case.status, case.started_on = C.ACTIVE, timezone.localdate()
        case.save()
        _event(ctx, case, "start", f"{ov.get_kind_display()} recorded", status=case.status)
    elif kind in (K.DEBOND, K.RETAINER_FIT) and case.status == C.ACTIVE:
        case.status, case.debonded_on = C.RETENTION, timezone.localdate()
        case.save()
        _event(ctx, case, "retention", f"{ov.get_kind_display()} recorded", status=case.status)
    if kind == K.RETAINER_FIT:
        for field in ("retainer_upper", "retainer_lower"):
            if data.get(field):
                setattr(case, field, _choice(data[field], OrthoCase.Retainer, field))
        case.save()
    record_event(ctx, action="dental_ortho.visit", object_type="ortho_visit", object_id=ov.pk,
                 details={"case": case.number, "patient": str(case.patient_id), "kind": kind,
                          "charge": str(charge or ""), "extra_charge": str(extra or "")})
    _follow_up(ctx, case, ov)
    return ov


def _follow_up(ctx: ActorContext, case: OrthoCase, ov: OrthoVisit) -> None:
    """The visit closes open orthodontic recalls; the next interval, if given, opens a new one."""
    if not is_enabled("recalls"):
        return
    for recall in Recall.objects.filter(patient_id=case.patient_id, kind=Recall.Kind.ORTHO_ADJUSTMENT,
                                        status__in=Recall.OPEN):
        recall_svc.close(ctx, recall, status=Recall.Status.COMPLETED, reason=f"Seen: {ov.get_kind_display()}")
    if ov.next_interval_weeks:
        due = timezone.localdate() + datetime.timedelta(weeks=ov.next_interval_weeks)
        label = "Retention review" if case.status == C.RETENTION else "Next orthodontic visit"
        recall_svc.create_recall(ctx, case.patient, kind=Recall.Kind.ORTHO_ADJUSTMENT, due_date=due,
                                 note=f"{label} ({case.number})", source_encounter=ov.encounter)


@transaction.atomic
def void_visit(ctx: ActorContext, ov: OrthoVisit, reason: str) -> OrthoVisit:
    """Mark a visit record entered in error. It stays in the history; a charge already invoiced blocks this."""
    _require_module()
    ov = OrthoVisit.objects.select_for_update().select_related("case").get(pk=ov.pk)
    if ov.status != OrthoVisit.Status.RECORDED:
        raise ConflictError("This visit record is already marked as entered in error.")
    if ov.performed_by_id != ctx.user.pk and not ctx.user.has_permissions(["dental.amend"]):
        raise PermissionDeniedError("Only the person who recorded this visit, or someone who can amend dental "
                                    "records, can mark it as entered in error.")
    if not reason.strip():
        raise BusinessValidationError("Give the reason.", fields={"reason": ["Required."]})
    if _is_billed(VISIT_SOURCE, ov.pk) or _is_billed(EXTRA_SOURCE, ov.pk):
        raise ConflictError("This visit is already on an invoice. Ask the cashier to remove the line or void the "
                            "invoice first.")
    ov.status, ov.voided_at, ov.voided_by, ov.void_reason = (OrthoVisit.Status.ENTERED_IN_ERROR, timezone.now(),
                                                              ctx.user, reason.strip()[:255])
    ov.save()
    _event(ctx, ov.case, "visit_void", f"{ov.get_kind_display()}: {reason.strip()}", visit=str(ov.pk))
    return ov
