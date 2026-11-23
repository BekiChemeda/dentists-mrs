"""Dental examinations: start, edit, sign, amend; diagnoses; medical risk review; dental profile."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.patients.models import Patient
from apps.scheduling.models import Visit
from apps.scheduling.services import transition_visit, visit_event

from ..models import (
    DentalDiagnosis, DentalDiagnosisTerm, DentalEncounter, DentalEncounterAmendment, DentalProfile,
    DentalProfileChange, MedicalRiskReview,
)
from ..starter_data import RISK_ANSWERS, RISK_QUESTION_KEYS
from .common import location, own_open_encounter


# ---------------------------------------------------------------------------
# Examination
# ---------------------------------------------------------------------------
@transaction.atomic
def start_encounter(ctx: ActorContext, visit: Visit) -> DentalEncounter:
    """Open (or return the dentist's existing) draft examination for a visit. The visit moves to consultation."""
    visit = Visit.objects.select_for_update().select_related("patient").get(pk=visit.pk)
    existing = DentalEncounter.objects.filter(visit=visit, dentist=ctx.user, status=DentalEncounter.Status.DRAFT).first()
    if existing:
        return existing
    if visit.status not in Visit.OPEN:
        raise ConflictError("This visit is closed. Reopen it to add another examination.")
    if visit.kind == Visit.Kind.LAB_ONLY:
        raise ConflictError("This is a laboratory-only visit.")
    if visit.status == Visit.Status.WAITING_TRIAGE:
        visit_event(ctx, visit, "triage.skipped", "Seen by the dentist without triage")
        transition_visit(ctx, visit, Visit.Status.WAITING_DOCTOR)
    is_review = visit.dental_encounters.filter(status=DentalEncounter.Status.SIGNED).exists()
    transition_visit(ctx, visit, Visit.Status.IN_CONSULTATION)
    if visit.assigned_doctor_id is None:
        Visit.objects.filter(pk=visit.pk).update(assigned_doctor=ctx.user)
    patient = visit.patient
    latest_review = MedicalRiskReview.objects.filter(patient=patient).order_by("-reviewed_at").first()
    history = "\n".join(x for x in (patient.known_conditions, patient.past_history) if x)
    enc = DentalEncounter.objects.create(visit=visit, patient=patient, dentist=ctx.user, risk_review=latest_review,
                                         medical_history_review=history)
    record_event(ctx, action="dental_encounter.start", object_type="dental_encounter", object_id=enc.pk,
                 details={"visit": str(visit.pk), "patient": str(patient.pk), "review": is_review})
    visit_event(ctx, visit, "dental.examination", f"Dental examination started by Dr. {ctx.user.full_name}")
    return enc


def _clean_structured(data: dict) -> dict:
    out = {}
    if "pain_teeth" in data:
        from .common import check_teeth_list

        out["pain_teeth"] = check_teeth_list(data["pain_teeth"], "pain_teeth")
    if "pain_sensitivity" in data:
        values = list(dict.fromkeys(data["pain_sensitivity"] or []))
        bad = [v for v in values if v not in DentalEncounter.SENSITIVITY]
        if bad:
            raise BusinessValidationError("Unknown sensitivity.", fields={"pain_sensitivity": [", ".join(bad)]})
        out["pain_sensitivity"] = values
    for key in ("pain_present", "pain_severity", "pain_pattern", "mouth_opening_mm", "follow_up_date"):
        if key in data:
            out[key] = data[key]
    if out.get("pain_severity") is not None and not 0 <= out["pain_severity"] <= 10:
        raise BusinessValidationError("Pain severity is 0 to 10.", fields={"pain_severity": ["0-10."]})
    return out


@transaction.atomic
def update_encounter(ctx: ActorContext, encounter: DentalEncounter, data: dict, *, version: int) -> DentalEncounter:
    enc = own_open_encounter(ctx, encounter)
    if version != enc.version:
        raise ConflictError("This examination was changed elsewhere. Reload before saving so nothing is lost.",
                            extra={"current_version": enc.version})
    values = {k: data[k] for k in DentalEncounter.NOTE_FIELDS if k in data}
    values.update(_clean_structured(data))
    changed = [k for k, v in values.items() if getattr(enc, k) != v]
    if changed:
        for k in changed:
            setattr(enc, k, values[k])
        enc.version += 1
        enc.save()
        record_event(ctx, action="dental_encounter.update", object_type="dental_encounter", object_id=enc.pk,
                     details={"fields": changed, "version": enc.version})
    return enc


@transaction.atomic
def sign_encounter(ctx: ActorContext, encounter: DentalEncounter) -> DentalEncounter:
    enc = own_open_encounter(ctx, encounter)
    missing = {}
    if not enc.chief_complaint.strip():
        missing["chief_complaint"] = ["Record the chief complaint (or the reason for the visit) before signing."]
    has_dx = enc.diagnoses.filter(is_removed=False).exists()
    if not has_dx and not enc.assessment.strip():
        missing["diagnoses"] = ["Add a diagnosis or write the assessment before signing."]
    if missing:
        raise BusinessValidationError("The examination is incomplete.", fields=missing)
    enc.status = DentalEncounter.Status.SIGNED
    enc.signed_at = timezone.now()
    enc.version += 1
    enc.save()
    record_event(ctx, action="dental_encounter.sign", object_type="dental_encounter", object_id=enc.pk,
                 details={"patient": str(enc.patient_id), "findings": enc.findings.count(),
                          "diagnoses": enc.diagnoses.filter(is_removed=False).count()})
    visit_event(ctx, enc.visit_id, "dental.signed", f"Dental examination signed by Dr. {ctx.user.full_name}")
    # Signing never closes the visit: billing, imaging and prescriptions may continue.
    visit = Visit.objects.select_for_update().get(pk=enc.visit_id)
    other_drafts = (visit.dental_encounters.filter(status=DentalEncounter.Status.DRAFT).exclude(pk=enc.pk).exists()
                    or visit.encounters.filter(status="draft").exists())
    if visit.status == Visit.Status.IN_CONSULTATION and not other_drafts:
        transition_visit(ctx, visit, Visit.Status.AFTER_CONSULTATION)
    return enc


@transaction.atomic
def amend_encounter(ctx: ActorContext, encounter: DentalEncounter, *, field_name: str, text: str,
                    reason: str) -> DentalEncounterAmendment:
    enc = DentalEncounter.objects.select_for_update().get(pk=encounter.pk)
    if enc.status != DentalEncounter.Status.SIGNED:
        raise ConflictError("A draft is edited directly; amendments are for signed examinations.")
    if field_name not in DentalEncounter.NOTE_FIELDS:
        raise BusinessValidationError("Unknown section.", fields={"field_name": ["Unknown section."]})
    if not reason.strip():
        raise BusinessValidationError("Give the reason for the correction.", fields={"reason": ["Required."]})
    if not text.strip():
        raise BusinessValidationError("Write the corrected text.", fields={"text": ["Required."]})
    previous = enc.amendments.filter(field_name=field_name).order_by("-created_at").first()
    original = previous.amended_text if previous else getattr(enc, field_name)
    amendment = DentalEncounterAmendment.objects.create(encounter=enc, field_name=field_name, original_text=original,
                                                        amended_text=text.strip(), reason=reason.strip(),
                                                        author=ctx.user)
    record_event(ctx, action="dental_encounter.amend", object_type="dental_encounter", object_id=enc.pk,
                 details={"field": field_name, "reason": amendment.reason})
    return amendment


# ---------------------------------------------------------------------------
# Diagnoses
# ---------------------------------------------------------------------------
@transaction.atomic
def add_diagnosis(ctx: ActorContext, encounter: DentalEncounter, data: dict) -> DentalDiagnosis:
    enc = own_open_encounter(ctx, encounter)
    term = DentalDiagnosisTerm.objects.filter(pk=data.get("term_id"), is_active=True).first()
    if term is None:
        raise BusinessValidationError("Choose the diagnosis from the list.", fields={"term_id": ["Required."]})
    where = location(data)
    dx = DentalDiagnosis.objects.create(
        encounter=enc, patient=enc.patient, term=term, code_system=term.code_system, code=term.code,
        term_text=term.term, source_version=term.source_version, certainty=data.get("certainty") or "confirmed",
        status=data.get("status") or "active", notes=(data.get("notes") or "").strip(), recorded_by=ctx.user, **where)
    record_event(ctx, action="dental_diagnosis.add", object_type="dental_encounter", object_id=enc.pk,
                 details={"code": term.code, "where": dx.location_label})
    return dx


@transaction.atomic
def remove_diagnosis(ctx: ActorContext, dx: DentalDiagnosis) -> None:
    own_open_encounter(ctx, dx.encounter)
    if dx.treatment_plans.exists() or dx.findings.exists():
        raise ConflictError("This diagnosis is used by a treatment plan or chart finding. Unlink it there first.")
    DentalDiagnosis.objects.filter(pk=dx.pk).update(is_removed=True)
    record_event(ctx, action="dental_diagnosis.remove", object_type="dental_encounter", object_id=dx.encounter_id,
                 details={"diagnosis": str(dx.pk), "code": dx.code})


@transaction.atomic
def resolve_diagnosis(ctx: ActorContext, dx: DentalDiagnosis, note: str) -> DentalDiagnosis:
    dx = DentalDiagnosis.objects.select_for_update().get(pk=dx.pk)
    if dx.is_removed or dx.status == DentalDiagnosis.Status.RESOLVED:
        raise ConflictError("This diagnosis is already resolved or was removed.")
    if not note.strip():
        raise BusinessValidationError("Say how it was resolved.", fields={"note": ["Required."]})
    dx.status, dx.resolved_at, dx.resolved_by = DentalDiagnosis.Status.RESOLVED, timezone.now(), ctx.user
    dx.resolution_note = note.strip()[:255]
    dx.save(update_fields=["status", "resolved_at", "resolved_by", "resolution_note"])
    record_event(ctx, action="dental_diagnosis.resolve", object_type="dental_encounter", object_id=dx.encounter_id,
                 details={"diagnosis": str(dx.pk), "code": dx.code})
    return dx


# ---------------------------------------------------------------------------
# Medical risk review
# ---------------------------------------------------------------------------
def _clean_answers(answers: dict) -> dict:
    if not isinstance(answers, dict):
        raise BusinessValidationError("Answer the questions.", fields={"answers": ["Required."]})
    out, problems = {}, {}
    for key in RISK_QUESTION_KEYS:
        raw = answers.get(key) or {}
        answer = raw.get("answer") if isinstance(raw, dict) else raw
        detail = (raw.get("detail") or "").strip()[:500] if isinstance(raw, dict) else ""
        if answer not in RISK_ANSWERS:
            problems[key] = ["Answer yes, no, unknown or not applicable."]
            continue
        if answer == "yes" and not detail:
            problems[key] = ["Give the detail."]
        out[key] = {"answer": answer, "detail": detail}
    unknown = set(answers) - set(RISK_QUESTION_KEYS)
    if unknown:
        problems["answers"] = [f"Unknown question: {', '.join(sorted(unknown))}"]
    if problems:
        raise BusinessValidationError("The medical history review is incomplete.", fields=problems)
    return out


@transaction.atomic
def record_risk_review(ctx: ActorContext, patient: Patient, *, answers: dict, allergies_reviewed: bool,
                       medications_reviewed: bool, notes: str = "", encounter: DentalEncounter | None = None
                       ) -> MedicalRiskReview:
    clean = _clean_answers(answers)
    if encounter is not None:
        encounter = own_open_encounter(ctx, encounter)
        if encounter.patient_id != patient.pk:
            raise BusinessValidationError("The examination belongs to another patient.")
    previous = MedicalRiskReview.objects.filter(patient=patient).order_by("-reviewed_at").first()
    changed = None if previous is None else (
        {k: v["answer"] for k, v in previous.answers.items()} != {k: v["answer"] for k, v in clean.items()}
        or any(previous.answers.get(k, {}).get("detail", "") != v["detail"] for k, v in clean.items()))
    review = MedicalRiskReview.objects.create(patient=patient, encounter=encounter, reviewed_by=ctx.user,
                                              answers=clean, allergies_reviewed=allergies_reviewed,
                                              medications_reviewed=medications_reviewed, notes=notes.strip(),
                                              previous=previous, changed_since_previous=changed)
    if encounter is not None:
        DentalEncounter.objects.filter(pk=encounter.pk).update(risk_review=review)
    record_event(ctx, action="dental_risk_review.record", object_type="patient", object_id=patient.pk,
                 details={"review": str(review.pk), "changed": changed,
                          "yes": sorted(k for k, v in clean.items() if v["answer"] == "yes")})
    return review


# ---------------------------------------------------------------------------
# Dental profile
# ---------------------------------------------------------------------------
def profile_for(patient: Patient) -> DentalProfile:
    profile, _ = DentalProfile.objects.get_or_create(patient=patient)
    return profile


@transaction.atomic
def update_profile(ctx: ActorContext, profile: DentalProfile, data: dict) -> DentalProfile:
    """Called inside guarded_edit (version check). Every changed field is kept in DentalProfileChange."""
    changed = []
    for key in DentalProfile.FIELDS:
        if key not in data:
            continue
        value = (data[key] or "").strip()
        old = getattr(profile, key)
        if old != value:
            DentalProfileChange.objects.create(profile=profile, field_name=key, old_value=old, new_value=value,
                                               changed_by=ctx.user)
            setattr(profile, key, value)
            changed.append(key)
    if changed:
        profile.updated_by = ctx.user
        profile.save()
        record_event(ctx, action="dental_profile.update", object_type="patient", object_id=profile.patient_id,
                     details={"fields": changed})
    return profile

