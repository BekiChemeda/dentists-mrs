"""Triage, consultations, diagnoses and prescriptions."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.inventory.models import Item
from apps.scheduling.models import Visit
from apps.notifications.services import notify_permission_holders, notify_user
from apps.scheduling.services import transition_visit, visit_event

from .vitals_reference import interpret

from apps.core.numbering import next_number

from .models import (
    Diagnosis, Encounter, IcdCode, InternalReferral, MedicalCertificate, NoteAmendment, Prescription,
    PrescriptionItem, Referral, VitalSigns,
)

VITAL_FIELDS = ("systolic", "diastolic", "temperature_c", "heart_rate", "respiratory_rate", "spo2", "weight_kg",
                "height_cm", "pain_score")
TRIAGE_TEXT_FIELDS = ("chief_complaint", "complaint_duration", "symptoms", "current_medications", "observations", "notes")


def compute_bmi(weight_kg, height_cm) -> Decimal | None:
    if not weight_kg or not height_cm:
        return None
    meters = Decimal(height_cm) / 100
    return (Decimal(weight_kg) / (meters * meters)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------
@transaction.atomic
def record_vitals(ctx: ActorContext, visit: Visit, data: dict, *, priority: str | None = None) -> VitalSigns:
    if visit.status in (Visit.Status.COMPLETED, Visit.Status.CANCELLED):
        raise ConflictError("Vital signs cannot be added to a closed visit.")
    values = {k: data.get(k) for k in VITAL_FIELDS}
    if all(v is None for v in values.values()) and not (data.get("chief_complaint") or "").strip():
        raise BusinessValidationError("Enter at least one measurement or the main complaint.")
    if values["systolic"] and values["diastolic"] and values["diastolic"] >= values["systolic"]:
        raise BusinessValidationError("Diastolic pressure must be lower than systolic.",
                                      fields={"diastolic": ["Must be lower than systolic."]})
    assessment = {k: (data.get(k) or "").strip() for k in TRIAGE_TEXT_FIELDS}
    destination = None
    if data.get("triage_to"):
        from apps.accounts.models import Department

        destination = Department.objects.filter(code=data["triage_to"], receives_triage=True, is_active=True).first()
        if destination is None:
            raise BusinessValidationError("Choose one of the listed departments.",
                                          fields={"triage_to": ["Not an active triage destination."]})
    vitals = VitalSigns(visit=visit, patient=visit.patient, recorded_by=ctx.user,
                        bmi=compute_bmi(values["weight_kg"], values["height_cm"]),
                        consciousness=data.get("consciousness") or "", on_oxygen=data.get("on_oxygen"),
                        general_appearance=data.get("general_appearance") or "",
                        triage_to=data.get("triage_to") or "",
                        allergies_confirmed=data.get("allergies_confirmed"), **assessment, **values)
    vitals.full_clean()
    vitals.save()
    reading = interpret({**values, "consciousness": vitals.consciousness, "on_oxygen": vitals.on_oxygen},
                        birth_date=visit.patient.birth_date, on=timezone.localdate())
    if reading["worst"] == "critical":
        # Critical readings reach the doctor immediately, whatever the queue order.
        texts = "; ".join(f["text"] for f in reading["flags"].values() if f["level"] == "critical") or \
            "NEWS2 high risk"
        target = visit.assigned_doctor
        if target is not None:
            notify_user(target, kind="critical_vitals", title=f"Critical vital signs: {visit.patient.full_name}",
                        body=texts, link="/queue")
        else:
            notify_permission_holders("clinical.write", kind="critical_vitals",
                                      title=f"Critical vital signs: {visit.patient.full_name}", body=texts,
                                      link="/queue")
    if priority and priority != visit.priority:
        Visit.objects.filter(pk=visit.pk).update(priority=priority)
    parts = [f"{label} {value}" for label, value in (
        ("BP", f"{values['systolic']}/{values['diastolic']}" if values["systolic"] and values["diastolic"] else None),
        ("T", f"{values['temperature_c']} °C" if values["temperature_c"] is not None else None),
        ("HR", values["heart_rate"]), ("RR", values["respiratory_rate"]),
        ("SpO₂", f"{values['spo2']}%" if values["spo2"] is not None else None)) if value is not None]
    summary = "Triage recorded" + (f": {', '.join(parts)}" if parts else "")
    if reading["worst"] != "normal":
        summary += f" ({reading['worst']})"
    if vitals.triage_to:
        summary += f"; sent to {destination.name}"
        Visit.objects.filter(pk=visit.pk).update(department=vitals.triage_to)
    visit_event(ctx, visit, "triage", summary)
    if priority and priority != visit.priority:
        visit_event(ctx, visit, "queue.priority", f"Priority set to {priority} at triage")
    if visit.status == Visit.Status.WAITING_TRIAGE:
        transition_visit(ctx, visit, Visit.Status.WAITING_DOCTOR)
    record_event(ctx, action="triage.vitals", object_type="visit", object_id=visit.pk,
                 details={"patient": str(visit.patient_id), **({"priority": priority} if priority else {})})
    return vitals


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------
def _own_draft(ctx: ActorContext, encounter: Encounter) -> Encounter:
    encounter = Encounter.objects.select_for_update().get(pk=encounter.pk)
    if encounter.status != Encounter.Status.DRAFT:
        raise ConflictError("This consultation is signed. Use an amendment to correct it.")
    if encounter.doctor_id != ctx.user.pk:
        raise ConflictError("Only the doctor who started this consultation can edit it.")
    return encounter


def orderable_encounter(ctx: ActorContext, encounter: Encounter) -> Encounter:
    """Investigations and prescriptions belong to the doctor's own consultation. They can be sent before or after
    the note is signed (the signed text never changes), but not once the visit is closed."""
    encounter = Encounter.objects.select_for_update().select_related("visit").get(pk=encounter.pk)
    if encounter.doctor_id != ctx.user.pk:
        raise ConflictError("Only the doctor who wrote this consultation can order from it.")
    if encounter.visit.status in (Visit.Status.COMPLETED, Visit.Status.CANCELLED):
        raise ConflictError("This visit is closed. Reopen it to order more.")
    return encounter


@transaction.atomic
def start_encounter(ctx: ActorContext, visit: Visit) -> Encounter:
    visit = Visit.objects.select_for_update().get(pk=visit.pk)
    existing = Encounter.objects.filter(visit=visit, doctor=ctx.user, status=Encounter.Status.DRAFT).first()
    if existing:
        return existing
    if visit.status not in Visit.OPEN:
        raise ConflictError("This visit is closed. Reopen it to add another consultation.")
    if visit.status == Visit.Status.WAITING_TRIAGE:
        # Seen without triage (e.g. an emergency taken straight in). Recorded so it is visible later.
        visit_event(ctx, visit, "triage.skipped", "Seen by the doctor without triage")
        transition_visit(ctx, visit, Visit.Status.WAITING_DOCTOR)
    is_review = visit.encounters.filter(status=Encounter.Status.SIGNED).exists()
    pending_referral = (InternalReferral.objects.select_for_update()
                        .filter(visit=visit, status=InternalReferral.Status.PENDING).first())
    transition_visit(ctx, visit, Visit.Status.IN_CONSULTATION)
    if visit.assigned_doctor_id is None:
        Visit.objects.filter(pk=visit.pk).update(assigned_doctor=ctx.user)
    # Prefill from the patient record and today's triage so the doctor confirms rather than retypes.
    patient = visit.patient
    allergies = "; ".join(f"{a.substance} ({a.severity})" for a in patient.allergies.filter(is_active=True))
    triage = visit.vital_signs.order_by("-recorded_at").first()
    history = "\n".join(x for x in (patient.known_conditions, patient.past_history) if x)
    medications = (triage.current_medications if triage and triage.current_medications else patient.current_medications)
    encounter = Encounter.objects.create(
        visit=visit, patient=patient, doctor=ctx.user,
        chief_complaint="" if is_review else (triage.chief_complaint if triage else ""),
        complaint_duration="" if is_review or not triage else triage.complaint_duration,
        general_appearance=triage.general_appearance if triage else "",
        allergy_notes=f"Recorded allergies: {allergies}" if allergies else "",
        past_medical_history=history, medication_history=medications or "")
    if pending_referral is not None and pending_referral.referred_by_id != ctx.user.pk:
        pending_referral.status = InternalReferral.Status.SEEN
        pending_referral.seen_encounter = encounter
        pending_referral.seen_at = timezone.now()
        pending_referral.save(update_fields=["status", "seen_encounter", "seen_at", "updated_at"])
        record_event(ctx, action="internal_referral.seen", object_type="internal_referral",
                     object_id=pending_referral.pk, details={"encounter": str(encounter.pk)})
    record_event(ctx, action="encounter.start", object_type="encounter", object_id=encounter.pk,
                 details={"visit": str(visit.pk), "patient": str(visit.patient_id), "review": is_review})
    if is_review:
        visit_event(ctx, visit, "consultation.review", f"Review consultation started by Dr. {ctx.user.full_name}")
    return encounter


@transaction.atomic
def update_encounter(ctx: ActorContext, encounter: Encounter, data: dict, *, version: int) -> Encounter:
    encounter = _own_draft(ctx, encounter)
    if version != encounter.version:
        raise ConflictError("This note was changed elsewhere. Reload before saving to avoid losing changes.")
    changed = []
    for name in Encounter.NOTE_FIELDS + ("follow_up_date",):
        if name in data and getattr(encounter, name) != data[name]:
            setattr(encounter, name, data[name])
            changed.append(name)
    if changed:
        encounter.version += 1
        encounter.save()
        # Content is not copied into the audit log: notes are clinical data with their own history.
        record_event(ctx, action="encounter.update", object_type="encounter", object_id=encounter.pk,
                     details={"fields": changed, "version": encounter.version})
    return encounter


@transaction.atomic
def sign_encounter(ctx: ActorContext, encounter: Encounter) -> Encounter:
    encounter = _own_draft(ctx, encounter)
    missing = {}
    if not encounter.chief_complaint.strip():
        missing["chief_complaint"] = ["Required before signing."]
    if not encounter.diagnoses.filter(is_removed=False).exists():
        missing["diagnoses"] = ["Add the physician diagnosis before signing."]
    if not encounter.plan.strip():
        missing["plan"] = ["Write the treatment plan before signing."]
    if missing:
        raise BusinessValidationError("The note is incomplete.", fields=missing)
    encounter.status = Encounter.Status.SIGNED
    encounter.signed_at = timezone.now()
    encounter.version += 1
    encounter.save()
    record_event(ctx, action="encounter.sign", object_type="encounter", object_id=encounter.pk,
                 details={"patient": str(encounter.patient_id)})
    visit_event(ctx, encounter.visit_id, "consultation.signed", f"Consultation signed by Dr. {ctx.user.full_name}")
    # Signing does not close the visit: the patient moves on to laboratory, pharmacy and billing.
    visit = Visit.objects.select_for_update().get(pk=encounter.visit_id)
    other_drafts = visit.encounters.filter(status=Encounter.Status.DRAFT).exclude(pk=encounter.pk).exists()
    if visit.status == Visit.Status.IN_CONSULTATION and not other_drafts:
        transition_visit(ctx, visit, Visit.Status.AFTER_CONSULTATION)
    return encounter


@transaction.atomic
def amend_encounter(ctx: ActorContext, encounter: Encounter, *, field_name: str, text: str,
                    reason: str) -> NoteAmendment:
    encounter = Encounter.objects.select_for_update().get(pk=encounter.pk)
    if encounter.status != Encounter.Status.SIGNED:
        raise ConflictError("Draft notes are edited directly; amendments are for signed notes.")
    if field_name not in Encounter.NOTE_FIELDS:
        raise BusinessValidationError("Unknown note section.", fields={"field_name": ["Unknown section."]})
    if not reason.strip() or not text.strip():
        raise BusinessValidationError("Both the corrected text and a reason are required.",
                                      fields={"reason": ["Required."]} if not reason.strip() else {"text": ["Required."]})
    previous = encounter.amendments.filter(field_name=field_name).order_by("-created_at").first()
    original = previous.amended_text if previous else getattr(encounter, field_name)
    amendment = NoteAmendment.objects.create(encounter=encounter, field_name=field_name, original_text=original,
                                             amended_text=text.strip(), reason=reason.strip(), author=ctx.user)
    record_event(ctx, action="encounter.amend", object_type="encounter", object_id=encounter.pk,
                 details={"field": field_name, "reason": amendment.reason})
    return amendment


# ---------------------------------------------------------------------------
# Diagnoses
# ---------------------------------------------------------------------------
@transaction.atomic
def add_diagnosis(ctx: ActorContext, encounter: Encounter, *, icd_code: str | None, description: str,
                  kind: str, certainty: str) -> Diagnosis:
    encounter = _own_draft(ctx, encounter)
    # The physician diagnosis is always coded, so reports and HMIS counts can rely on it.
    if not (icd_code or "").strip():
        raise BusinessValidationError("Choose the diagnosis from the ICD-10 list.",
                                      fields={"icd_code": ["Required."]})
    icd = IcdCode.objects.filter(pk=icd_code.strip().upper()).first()
    if icd is None:
        raise BusinessValidationError("Unknown ICD-10 code.", fields={"icd_code": ["Not found."]})
    description = (description or "").strip() or (icd.title if icd else "")
    if not description:
        raise BusinessValidationError("Enter a diagnosis.", fields={"description": ["Required."]})
    dx = Diagnosis.objects.create(encounter=encounter, patient=encounter.patient, icd=icd, description=description,
                                  kind=kind, certainty=certainty, created_by=ctx.user)
    record_event(ctx, action="diagnosis.add", object_type="encounter", object_id=encounter.pk,
                 details={"icd": icd.code if icd else "", "kind": kind})
    return dx


@transaction.atomic
def remove_diagnosis(ctx: ActorContext, dx: Diagnosis) -> None:
    _own_draft(ctx, dx.encounter)
    Diagnosis.objects.filter(pk=dx.pk).update(is_removed=True)
    record_event(ctx, action="diagnosis.remove", object_type="encounter", object_id=dx.encounter_id,
                 details={"diagnosis": str(dx.pk)})


# ---------------------------------------------------------------------------
# Prescriptions
# ---------------------------------------------------------------------------
def allergy_conflicts(patient, item: Item | None, drug_name: str) -> list[str]:
    """Recorded allergies that match this medicine by name, generic name or allergy group."""
    words = {drug_name.lower()}
    if item is not None:
        words |= {item.name.lower(), item.generic_name.lower()}
        words |= {g.strip().lower() for g in item.allergy_groups.split(",") if g.strip()}
    words.discard("")
    hits = []
    for allergy in patient.allergies.filter(is_active=True):
        sub = allergy.substance.strip().lower()
        if sub and any(sub in w or w in sub for w in words):
            hits.append(f"{allergy.substance} ({allergy.severity})")
    return hits


class AllergyWarning(ConflictError):
    code = "allergy_warning"

    def __init__(self, conflicts: dict[int, list[str]]):
        super().__init__("A prescribed medicine matches a recorded allergy. Change it, or give a reason to continue.",
                         extra={"conflicts": {str(k): v for k, v in conflicts.items()}})


def _controlled_checks(ctx, encounter: Encounter, item: Item, line: dict, *, serial: str, weight) -> None:
    """EFDA Narcotic and Psychotropic Medicine Control Directive No. 1121/2025, prescribing side."""
    from apps.core.models import ClinicSettings

    problems = {}
    level = ClinicSettings.get().facility_level
    if item.controlled_class == Item.Controlled.NARCOTIC and level == ClinicSettings.FacilityLevel.MEDIUM_CLINIC:
        raise ConflictError("A medium clinic may prescribe psychotropic but not narcotic medicines "
                            "(EFDA Directive 1121/2025, Art. 27).")
    if not ctx.user.registration_number.strip():
        raise ConflictError("Your professional registration number must be on your staff account before you can "
                            "prescribe controlled medicines (Directive 1121/2025, Art. 22).")
    patient = encounter.patient
    from apps.patients.api import age_of

    if age_of(patient.birth_date) < 18:
        raise ConflictError("Controlled medicines cannot be dispensed to patients under 18 "
                            "(Directive 1121/2025, Art. 26(4)).")
    if not encounter.diagnoses.filter(is_removed=False).exists():
        problems["diagnosis"] = ["Add the diagnosis first: it is required on the special prescription."]
    if not (patient.city or patient.subcity_woreda or patient.kebele):
        problems["address"] = ["The patient's address is required on the special prescription."]
    if not serial.strip():
        problems["special_form_serial"] = ["Enter the serial number of the special prescription form."]
    if weight is None:
        problems["patient_weight_kg"] = ["Enter the patient's weight."]
    days = line.get("duration_days")
    if not days:
        problems["duration_days"] = ["Give the duration."]
    elif days > 90:
        problems["duration_days"] = ["No more than three months' supply at a time (Art. 25(9))."]
    if problems:
        raise BusinessValidationError("The controlled-medicine prescription is incomplete.", fields=problems)


def _resolve_prescription_lines(items: list[dict]) -> list[tuple]:
    if not items:
        raise BusinessValidationError("Add at least one medicine.", fields={"items": ["Required."]})
    resolved = []
    for line in items:
        item = None
        if line.get("item_id"):
            item = Item.objects.filter(pk=line["item_id"], category=Item.Category.MEDICINE, is_active=True).first()
            if item is None:
                raise BusinessValidationError("Unknown medicine.", fields={"items": ["Medicine not in catalogue."]})
        name = (line.get("drug_name") or "").strip() or (str(item) if item else "")
        if not name:
            raise BusinessValidationError("Each line needs a medicine.", fields={"items": ["Medicine required."]})
        resolved.append((line, item, name))
    return resolved


def _write_prescription(ctx: ActorContext, *, patient, visit_id, resolved: list[tuple], notes: str,
                        encounter: Encounter | None = None, dental_encounter=None, controlled_class: str = "",
                        special_form_serial: str = "", patient_weight_kg=None) -> Prescription:
    """Allergy check, numbering, lines, audit and the pharmacy notice: the same for medical and dental prescriptions."""
    conflicts = {}
    for n, (line, item, name) in enumerate(resolved):
        hits = allergy_conflicts(patient, item, name)
        if hits and not (line.get("allergy_override_reason") or "").strip():
            conflicts[n] = hits
    if conflicts:
        raise AllergyWarning(conflicts)

    year = timezone.localdate().year
    from apps.core.modules import is_enabled

    # Without the pharmacy module the prescription is printed for the patient instead of queued here.
    pharmacy_on = is_enabled("pharmacy")
    rx = Prescription.objects.create(number=f"RX-{year}-{next_number('prescription', str(year)):05d}",
                                     visit_id=visit_id, encounter=encounter, dental_encounter=dental_encounter,
                                     patient=patient, prescriber=ctx.user,
                                     notes=notes.strip(), controlled_class=controlled_class,
                                     special_form_serial=special_form_serial.strip() if controlled_class else "",
                                     patient_weight_kg=patient_weight_kg if controlled_class else None,
                                     status=Prescription.Status.ACTIVE if pharmacy_on else Prescription.Status.EXTERNAL)
    overrides = []
    for line, item, name in resolved:
        override = (line.get("allergy_override_reason") or "").strip()
        if override and allergy_conflicts(patient, item, name):
            overrides.append({"drug": name, "reason": override})
        PrescriptionItem.objects.create(
            prescription=rx, item=item, drug_name=name, strength=item.strength if item else "",
            dosage_form=item.dosage_form if item else "", dose=line["dose"].strip(),
            route=(line.get("route") or (item.route if item and item.route else "oral")),
            frequency=line["frequency"].strip(), duration_days=line.get("duration_days"),
            quantity=line["quantity"], instructions=line.get("instructions", "").strip(),
            warnings=item.warnings if item else "", allergy_override_reason=override)
    record_event(ctx, action="prescription.create", object_type="prescription", object_id=rx.pk,
                 details={"patient": str(patient.pk), "items": len(resolved),
                          **({"dental_encounter": str(dental_encounter.pk)} if dental_encounter else {}),
                          **({"controlled": controlled_class, "form_serial": rx.special_form_serial}
                             if controlled_class else {}),
                          **({"allergy_overrides": overrides} if overrides else {})})
    visit_event(ctx, visit_id, "prescription", f"Prescribed: {', '.join(l.drug_name for l in rx.items.all())}")
    if pharmacy_on:
        patient_name, drugs = patient.full_name, ", ".join(l.drug_name for l in rx.items.all())
        transaction.on_commit(lambda: notify_permission_holders(
            "pharmacy.dispense", kind="prescription", title=f"Prescription waiting: {patient_name}", body=drugs,
            link=f"/pharmacy?rx={rx.pk}"))
    return rx


@transaction.atomic
def create_prescription(ctx: ActorContext, encounter: Encounter, items: list[dict], notes: str = "", *,
                        special_form_serial: str = "", patient_weight_kg=None) -> Prescription:
    encounter = orderable_encounter(ctx, encounter)
    if not encounter.diagnoses.filter(is_removed=False).exists():
        raise BusinessValidationError("Add the physician diagnosis before prescribing.",
                                      fields={"diagnoses": ["Required before prescribing."]})
    resolved = _resolve_prescription_lines(items)

    controlled = [(line, item) for line, item, _ in resolved if item is not None and item.controlled_class]
    controlled_class = ""
    if controlled:
        if len(resolved) > 1:
            raise BusinessValidationError("A controlled medicine must be on its own prescription "
                                          "(Directive 1121/2025, Art. 25(4)).", fields={"items": ["One medicine only."]})
        line, item = controlled[0]
        if patient_weight_kg is None:
            latest = encounter.visit.vital_signs.exclude(weight_kg__isnull=True).order_by("-recorded_at").first()
            patient_weight_kg = latest.weight_kg if latest else None
        _controlled_checks(ctx, encounter, item, line, serial=special_form_serial, weight=patient_weight_kg)
        controlled_class = item.controlled_class
    return _write_prescription(ctx, patient=encounter.patient, visit_id=encounter.visit_id, resolved=resolved,
                               notes=notes, encounter=encounter, controlled_class=controlled_class,
                               special_form_serial=special_form_serial, patient_weight_kg=patient_weight_kg)


@transaction.atomic
def create_dental_prescription(ctx: ActorContext, dental_encounter, items: list[dict],
                               notes: str = "") -> Prescription:
    """
    A prescription from a dental examination (ADR 0009). The dentist decides the medicine and dose; the system checks
    the catalogue and the shared allergy list. Controlled medicines need the paper special prescription (review R-09).
    """
    from apps.dental.models import DentalEncounter

    enc = DentalEncounter.objects.select_for_update().select_related("visit", "patient").get(pk=dental_encounter.pk)
    if enc.dentist_id != ctx.user.pk:
        raise ConflictError("Only the dentist who wrote this examination can prescribe from it.")
    if enc.visit.status in (Visit.Status.COMPLETED, Visit.Status.CANCELLED):
        raise ConflictError("This visit is closed. Reopen it to prescribe.")
    resolved = _resolve_prescription_lines(items)
    if any(item is not None and item.controlled_class for _l, item, _n in resolved):
        raise ConflictError("Narcotic and psychotropic medicines are not prescribed from a dental examination in "
                            "this system. Use the official special prescription form.")
    return _write_prescription(ctx, patient=enc.patient, visit_id=enc.visit_id, resolved=resolved, notes=notes,
                               dental_encounter=enc)


@transaction.atomic
def cancel_prescription(ctx: ActorContext, rx: Prescription, reason: str) -> Prescription:
    rx = Prescription.objects.select_for_update().get(pk=rx.pk)
    if rx.prescriber_id != ctx.user.pk:
        raise ConflictError("Only the prescriber can cancel this prescription.")
    if rx.status != Prescription.Status.ACTIVE:
        raise ConflictError("Prescriptions that are partly or fully dispensed cannot be cancelled.")
    if not reason.strip():
        raise BusinessValidationError("A reason is required.", fields={"reason": ["Required."]})
    rx.status = Prescription.Status.CANCELLED
    rx.cancel_reason = reason.strip()
    rx.save(update_fields=["status", "cancel_reason", "updated_at"])
    record_event(ctx, action="prescription.cancel", object_type="prescription", object_id=rx.pk,
                 details={"reason": rx.cancel_reason})
    return rx


# ---------------------------------------------------------------------------
# Referrals and certificates
# ---------------------------------------------------------------------------
def _own_encounter(ctx: ActorContext, encounter: Encounter) -> Encounter:
    encounter = Encounter.objects.select_for_update().get(pk=encounter.pk)
    if encounter.doctor_id != ctx.user.pk:
        raise ConflictError("Only the doctor responsible for this consultation can do this.")
    return encounter


@transaction.atomic
def create_referral(ctx: ActorContext, encounter: Encounter, *, to_facility: str, to_department: str = "",
                    urgency: str = "routine", reason: str, clinical_summary: str = "",
                    treatment_given: str = "") -> Referral:
    encounter = _own_encounter(ctx, encounter)
    if not to_facility.strip() or not reason.strip():
        raise BusinessValidationError("Enter where the patient is referred and why.",
                                      fields={"to_facility" if not to_facility.strip() else "reason": ["Required."]})
    year = timezone.localdate().year
    referral = Referral.objects.create(
        number=f"REF-{year}-{next_number('referral', str(year)):05d}", encounter=encounter, patient=encounter.patient,
        to_facility=to_facility.strip(), to_department=to_department.strip(), urgency=urgency, reason=reason.strip(),
        clinical_summary=clinical_summary.strip(), treatment_given=treatment_given.strip(), referred_by=ctx.user)
    record_event(ctx, action="referral.create", object_type="referral", object_id=referral.pk,
                 details={"number": referral.number, "to": referral.to_facility, "urgency": urgency})
    visit_event(ctx, encounter.visit_id, "referral", f"Referred to {referral.to_facility}"
                f"{' (' + referral.to_department + ')' if referral.to_department else ''}, {urgency}")
    return referral


@transaction.atomic
def cancel_referral(ctx: ActorContext, referral: Referral, reason: str) -> Referral:
    referral = Referral.objects.select_for_update().get(pk=referral.pk)
    if referral.referred_by_id != ctx.user.pk:
        raise ConflictError("Only the referring doctor can cancel this referral.")
    if referral.status == Referral.Status.CANCELLED:
        raise ConflictError("This referral is already cancelled.")
    if not reason.strip():
        raise BusinessValidationError("A reason is required.", fields={"reason": ["Required."]})
    referral.status, referral.cancel_reason = Referral.Status.CANCELLED, reason.strip()
    referral.save(update_fields=["status", "cancel_reason", "updated_at"])
    record_event(ctx, action="referral.cancel", object_type="referral", object_id=referral.pk,
                 details={"reason": referral.cancel_reason})
    return referral


@transaction.atomic
def issue_certificate(ctx: ActorContext, encounter: Encounter, *, kind: str, start_date=None, end_date=None,
                      include_diagnosis: bool = False, diagnosis_text: str = "", remarks: str = "") -> MedicalCertificate:
    encounter = _own_encounter(ctx, encounter)
    if kind == MedicalCertificate.Kind.SICK_LEAVE and not (start_date and end_date):
        raise BusinessValidationError("Give the first and last day of sick leave.",
                                      fields={"start_date": ["Required for sick leave."]})
    if start_date and end_date and end_date < start_date:
        raise BusinessValidationError("The last day is before the first day.", fields={"end_date": ["Check the dates."]})
    if include_diagnosis and not diagnosis_text.strip():
        primary = encounter.diagnoses.filter(is_removed=False).order_by("kind", "created_at").first()
        diagnosis_text = primary.description if primary else ""
    year = timezone.localdate().year
    cert = MedicalCertificate.objects.create(
        number=f"CERT-{year}-{next_number('certificate', str(year)):05d}", encounter=encounter,
        patient=encounter.patient, kind=kind, start_date=start_date, end_date=end_date,
        include_diagnosis=include_diagnosis, diagnosis_text=diagnosis_text.strip() if include_diagnosis else "",
        remarks=remarks.strip(), issued_by=ctx.user)
    record_event(ctx, action="certificate.issue", object_type="certificate", object_id=cert.pk,
                 details={"number": cert.number, "kind": kind, "days": cert.days})
    visit_event(ctx, encounter.visit_id, "certificate",
                f"{cert.get_kind_display()} certificate issued" + (f" ({cert.days} days)" if cert.days else ""))
    return cert


@transaction.atomic
def cancel_certificate(ctx: ActorContext, cert: MedicalCertificate, reason: str) -> MedicalCertificate:
    cert = MedicalCertificate.objects.select_for_update().get(pk=cert.pk)
    if cert.issued_by_id != ctx.user.pk:
        raise ConflictError("Only the issuing doctor can cancel this certificate.")
    if cert.is_cancelled:
        raise ConflictError("This certificate is already cancelled.")
    if not reason.strip():
        raise BusinessValidationError("A reason is required.", fields={"reason": ["Required."]})
    cert.is_cancelled, cert.cancel_reason = True, reason.strip()
    cert.save(update_fields=["is_cancelled", "cancel_reason", "updated_at"])
    record_event(ctx, action="certificate.cancel", object_type="certificate", object_id=cert.pk,
                 details={"reason": cert.cancel_reason})
    return cert


# ---------------------------------------------------------------------------
# Internal referrals (to another department of this clinic, same visit)
# ---------------------------------------------------------------------------
@transaction.atomic
def create_internal_referral(ctx: ActorContext, encounter: Encounter, *, to_department: str, reason: str,
                             urgency: str = "routine", to_doctor_id=None) -> InternalReferral:
    """Send the patient to another department's waiting list. The referring note may be signed or still a
    draft; the patient leaves this doctor's consultation either way."""
    from apps.accounts.models import Department, User

    encounter = _own_encounter(ctx, encounter)
    visit = Visit.objects.select_for_update().select_related("patient").get(pk=encounter.visit_id)
    if visit.status not in (Visit.Status.IN_CONSULTATION, Visit.Status.AFTER_CONSULTATION, Visit.Status.WAITING_DOCTOR):
        raise ConflictError("Only a patient in an open consultation can be referred within the clinic.")
    reason = (reason or "").strip()
    if not reason:
        raise BusinessValidationError("Write why the patient is referred.", fields={"reason": ["Required."]})
    dept = Department.objects.filter(code=to_department, receives_triage=True, is_active=True).first()
    if dept is None:
        raise BusinessValidationError("Choose a department that sees patients.",
                                      fields={"to_department": ["Not a department that sees patients."]})
    if dept.code == visit.department:
        raise BusinessValidationError("The patient is already in this department.",
                                      fields={"to_department": ["Same department."]})
    if urgency not in InternalReferral.Urgency.values:
        raise BusinessValidationError("Invalid urgency.", fields={"urgency": ["Invalid choice."]})
    doctor = None
    if to_doctor_id:
        doctor = User.objects.filter(pk=to_doctor_id, is_active=True, roles__permissions__code="clinical.write").first()
        if doctor is None:
            raise BusinessValidationError("Choose an active doctor.", fields={"to_doctor_id": ["Not an active doctor."]})
        if doctor.pk == ctx.user.pk:
            raise BusinessValidationError("Refer to another doctor.", fields={"to_doctor_id": ["That is you."]})
    if InternalReferral.objects.filter(visit=visit, status=InternalReferral.Status.PENDING).exists():
        raise ConflictError("This patient already has an internal referral waiting. Cancel it first to change it.")

    referral = InternalReferral.objects.create(
        visit=visit, patient=visit.patient, from_encounter=encounter, from_department=visit.department,
        to_department=dept.code, to_doctor=doctor, urgency=urgency, reason=reason, referred_by=ctx.user)
    if visit.status != Visit.Status.WAITING_DOCTOR:
        transition_visit(ctx, visit, Visit.Status.WAITING_DOCTOR)
    rank = {"routine": 0, "urgent": 1, "emergency": 2}
    updates = {"department": dept.code, "assigned_doctor": doctor}
    if rank[urgency] > rank.get(visit.priority, 0):
        updates["priority"] = urgency
    Visit.objects.filter(pk=visit.pk).update(**updates)
    visit_event(ctx, visit.pk, "referral.internal",
                f"Referred within the clinic to {dept.name}"
                f"{' (Dr. ' + doctor.full_name + ')' if doctor else ''}, {urgency}: {reason[:120]}")
    record_event(ctx, action="internal_referral.create", object_type="internal_referral", object_id=referral.pk,
                 details={"visit": str(visit.pk), "from": visit.department, "to": dept.code, "urgency": urgency,
                          "to_doctor": str(doctor.pk) if doctor else ""})
    link = f"/patients/{visit.patient_id}"
    if doctor:
        notify_user(doctor, kind="internal_referral", title=f"Patient referred to you: {visit.patient.full_name}",
                    body=f"From Dr. {ctx.user.full_name}, {urgency}.", link=link)
    else:
        for user in User.objects.filter(is_active=True, department=dept,
                                        roles__permissions__code="clinical.write").distinct():
            notify_user(user, kind="internal_referral", title=f"Patient referred to {dept.name}",
                        body=f"{visit.patient.full_name}, from Dr. {ctx.user.full_name}, {urgency}.", link=link)
    return referral


@transaction.atomic
def cancel_internal_referral(ctx: ActorContext, referral: InternalReferral, reason: str) -> InternalReferral:
    """Only while it is still waiting. The patient goes back to the referring department's waiting list."""
    referral = InternalReferral.objects.select_for_update().get(pk=referral.pk)
    if referral.referred_by_id != ctx.user.pk:
        raise ConflictError("Only the referring doctor can cancel this referral.")
    if referral.status != InternalReferral.Status.PENDING:
        raise ConflictError("The patient has already been seen; this referral can no longer be cancelled.")
    reason = (reason or "").strip()
    if not reason:
        raise BusinessValidationError("Give the reason.", fields={"reason": ["Required."]})
    referral.status = InternalReferral.Status.CANCELLED
    referral.cancel_reason = reason
    referral.save(update_fields=["status", "cancel_reason", "updated_at"])
    Visit.objects.filter(pk=referral.visit_id, status=Visit.Status.WAITING_DOCTOR).update(
        department=referral.from_department, assigned_doctor=referral.from_encounter.doctor)
    visit_event(ctx, referral.visit_id, "referral.internal_cancel", f"Internal referral cancelled: {reason[:120]}")
    record_event(ctx, action="internal_referral.cancel", object_type="internal_referral", object_id=referral.pk,
                 details={"reason": reason})
    return referral
