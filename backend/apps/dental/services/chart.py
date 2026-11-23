"""
Odontogram: dated findings (ADR 0006). Nothing is overwritten. The chart at a moment is computed from the findings
recorded by then that were neither voided nor resolved by then.
"""

from __future__ import annotations

import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.patients.models import Patient

from ..models import DentalDiagnosis, DentalEncounter, FindingType, ToothFinding
from .common import location, open_encounter, same_patient

_SCOPES_FOR = {
    FindingType.AppliesTo.TOOTH: ("tooth",),
    FindingType.AppliesTo.SURFACE: ("surfaces",),
    FindingType.AppliesTo.EITHER: ("tooth", "surfaces"),
    FindingType.AppliesTo.AREA: ("region", "mouth"),
}


@transaction.atomic
def record_finding(ctx: ActorContext, encounter: DentalEncounter, data: dict) -> ToothFinding:
    """Anyone with dental.chart.record may add to an open examination (e.g. the assistant at the chair)."""
    enc = open_encounter(encounter)
    ftype = FindingType.objects.filter(pk=data.get("finding_type_id"), is_active=True).first()
    if ftype is None:
        raise BusinessValidationError("Choose a finding from the list.", fields={"finding_type_id": ["Required."]})
    where = location(data, allowed_scopes=_SCOPES_FOR[ftype.applies_to])
    diagnosis = None
    if data.get("diagnosis_id"):
        diagnosis = DentalDiagnosis.objects.filter(pk=data["diagnosis_id"], is_removed=False).first()
        if diagnosis is None:
            raise BusinessValidationError("Unknown diagnosis.", fields={"diagnosis_id": ["Not found."]})
        same_patient(diagnosis, enc.patient_id, "diagnosis_id")
    finding = ToothFinding.objects.create(patient=enc.patient, encounter=enc, finding_type=ftype,
                                          is_existing_work=ftype.kind == FindingType.Kind.EXISTING,
                                          note=(data.get("note") or "").strip()[:255], diagnosis=diagnosis,
                                          recorded_by=ctx.user, **where)
    record_event(ctx, action="dental_finding.record", object_type="dental_encounter", object_id=enc.pk,
                 details={"finding": str(finding.pk), "type": ftype.code, "where": finding.location_label})
    return finding


@transaction.atomic
def remove_finding(ctx: ActorContext, finding: ToothFinding) -> None:
    """A typing slip in the examination still being written. Afterwards use resolve or void."""
    finding = ToothFinding.objects.select_for_update().get(pk=finding.pk)
    enc = open_encounter(finding.encounter)
    if finding.resolved_at or finding.voided_at:
        raise ConflictError("This finding already has a later change; it cannot be removed.")
    record_event(ctx, action="dental_finding.remove", object_type="dental_encounter", object_id=enc.pk,
                 details={"finding": str(finding.pk), "type": finding.finding_type.code,
                          "where": finding.location_label})
    finding.delete()


@transaction.atomic
def resolve_finding(ctx: ActorContext, finding: ToothFinding, encounter: DentalEncounter, note: str) -> ToothFinding:
    """The finding is no longer true (restored, extracted, healed), as established in a later examination."""
    enc = open_encounter(encounter)
    finding = ToothFinding.objects.select_for_update().get(pk=finding.pk)
    same_patient(finding, enc.patient_id, "finding")
    if finding.encounter_id == enc.pk:
        raise ConflictError("This finding was recorded in this examination: remove it instead.")
    if finding.resolved_at or finding.voided_at:
        raise ConflictError("This finding is already resolved or marked as entered in error.")
    if not note.strip():
        raise BusinessValidationError("Say why it no longer applies (e.g. restored, extracted).",
                                      fields={"note": ["Required."]})
    finding.resolved_at, finding.resolved_in, finding.resolved_by = timezone.now(), enc, ctx.user
    finding.resolution_note = note.strip()[:255]
    finding.save(update_fields=["resolved_at", "resolved_in", "resolved_by", "resolution_note"])
    record_event(ctx, action="dental_finding.resolve", object_type="dental_encounter", object_id=enc.pk,
                 details={"finding": str(finding.pk), "note": finding.resolution_note})
    return finding


@transaction.atomic
def void_finding(ctx: ActorContext, finding: ToothFinding, reason: str) -> ToothFinding:
    """Entered in error on a signed examination. The finding stays in the history, struck through."""
    finding = ToothFinding.objects.select_for_update().select_related("encounter").get(pk=finding.pk)
    if finding.encounter.status == DentalEncounter.Status.DRAFT:
        raise ConflictError("The examination is still a draft: remove the finding instead.")
    if finding.voided_at:
        raise ConflictError("Already marked as entered in error.")
    if not reason.strip():
        raise BusinessValidationError("Give the reason.", fields={"reason": ["Required."]})
    finding.voided_at, finding.voided_by, finding.void_reason = timezone.now(), ctx.user, reason.strip()[:255]
    finding.save(update_fields=["voided_at", "voided_by", "void_reason"])
    record_event(ctx, action="dental_finding.void", object_type="dental_encounter", object_id=finding.encounter_id,
                 details={"finding": str(finding.pk), "reason": finding.void_reason})
    return finding


# ---------------------------------------------------------------------------
# Reading the chart
# ---------------------------------------------------------------------------
def active_at(qs, at: datetime.datetime):
    """Findings that were true at `at` (recorded by then, not voided, not yet resolved)."""
    return (qs.filter(recorded_at__lte=at, voided_at__isnull=True)
            .filter(Q(resolved_at__isnull=True) | Q(resolved_at__gt=at)))


def as_of_moment(patient: Patient, *, at: datetime.datetime | None = None,
                 encounter: DentalEncounter | None = None) -> datetime.datetime:
    """'As of an examination' = as of when it was signed (or now, if it is still a draft)."""
    if encounter is not None:
        if encounter.patient_id != patient.pk:
            raise BusinessValidationError("The examination belongs to another patient.")
        return encounter.signed_at or timezone.now()
    return at or timezone.now()


def findings_qs_all():
    return ToothFinding.objects.select_related("finding_type", "recorded_by", "resolved_by", "voided_by", "diagnosis",
                                               "encounter", "resolved_in")


def findings_qs(patient: Patient):
    return findings_qs_all().filter(patient=patient)


def chart_at(patient: Patient, at: datetime.datetime) -> list[ToothFinding]:
    return list(active_at(findings_qs(patient), at).order_by("recorded_at"))


def compare(patient: Patient, earlier: datetime.datetime, later: datetime.datetime) -> dict:
    before = {f.pk: f for f in chart_at(patient, earlier)}
    after = {f.pk: f for f in chart_at(patient, later)}
    return {"added": [after[k] for k in after.keys() - before.keys()],
            "no_longer_present": [before[k] for k in before.keys() - after.keys()],
            "unchanged": [after[k] for k in after.keys() & before.keys()]}
