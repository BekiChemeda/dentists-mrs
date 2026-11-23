"""Patient registration, search, duplicate detection and audited updates."""

from __future__ import annotations

import datetime
import re

from django.contrib.postgres.search import TrigramSimilarity
from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Concat
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.core.numbering import next_number

from .models import Allergy, EmergencyContact, Patient, PatientChange

DEMOGRAPHIC_FIELDS = (
    "first_name", "middle_name", "last_name", "sex", "birth_date", "birth_date_estimated", "phone",
    "alt_phone", "region", "city", "subcity_woreda", "kebele", "house_number", "national_id",
    "blood_group", "known_conditions", "past_history", "current_medications",
)


def normalize_phone(raw: str) -> str:
    """Ethiopian numbers to the local 10-digit form: +251911223344 / 911223344 -> 0911223344."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if digits.startswith("251") and len(digits) == 12:
        digits = "0" + digits[3:]
    elif len(digits) == 9 and digits[0] in "79":
        digits = "0" + digits
    if not (9 <= len(digits) <= 15):
        raise BusinessValidationError("Invalid phone number.", fields={"phone": ["Enter a valid phone number."]})
    return digits


def birth_date_from_age(age_years: int, today: datetime.date | None = None) -> datetime.date:
    today = today or timezone.localdate()
    return datetime.date(today.year - age_years, 7, 1)


def search_patients(query: str, *, include_inactive: bool = False):
    """Everyday search shows active records only. Inactive (moved away, deceased) records are found on
    request; merged duplicates are never listed themselves, their MRN leads to the surviving record."""
    qs = Patient.objects.filter(merged_into__isnull=True) if include_inactive else Patient.objects.filter(is_active=True)
    query = (query or "").strip()
    if not query:
        return qs.order_by("-created_at")
    condition = Q(mrn__iexact=query) | Q(national_id__iexact=query) | Q(merged_records__mrn__iexact=query)
    digits = re.sub(r"\D", "", query)
    if len(digits) >= 6 and len(digits) == len(query.replace(" ", "").lstrip("+")):
        tail = digits[-9:]
        condition |= Q(phone__endswith=tail) | Q(alt_phone__endswith=tail)
    terms = [t for t in query.split() if not t.isdigit()]
    if terms:
        name_q = Q()
        for term in terms:
            name_q &= Q(first_name__icontains=term) | Q(middle_name__icontains=term) | Q(last_name__icontains=term)
        condition |= name_q
    return qs.filter(condition).distinct().order_by("first_name", "middle_name", "last_name")


def new_mrn() -> str:
    """The clinic's medical record number: one running sequence, at least five digits (00001, 00002, ...).

    Records registered before this format keep their original number."""
    return f"{next_number('mrn_serial'):05d}"


def find_possible_duplicates(*, first_name: str, middle_name: str, last_name: str, birth_date, phone: str,
                             alt_phone: str = "", national_id: str = "", sex: str = "",
                             birth_date_estimated: bool = False, exclude_id=None, limit: int = 5):
    """
    Possible existing records for a new registration. Each candidate carries the reason it matched.

    Strong matches (shown first): same national ID; same phone number (main or second, either way).
    Name matches: similar full name (trigram >= 0.55) and the same sex, with the birth year within one
    year, or within three years when either birth date is an estimate (age given instead of a date).
    """
    full = " ".join(p for p in (first_name, middle_name, last_name) if p).lower()
    name_expr = Concat("first_name", Value(" "), "middle_name", Value(" "), "last_name")
    # Records marked inactive (moved away) count too: a returning patient must be reactivated, not re-registered.
    qs = (Patient.objects.filter(merged_into__isnull=True).exclude(inactive_kind=Patient.InactiveKind.DECEASED)
          .annotate(similarity=TrigramSimilarity(name_expr, full)))
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    found: dict = {}

    def add(patient, reason: str, rank: int) -> None:
        if not patient.is_active:
            reason += " (inactive record: reactivate it instead of registering again)"
        current = found.get(patient.pk)
        if current is None or rank < current[1]:
            found[patient.pk] = (patient, rank, reason)

    if national_id.strip():
        for p in qs.filter(national_id__iexact=national_id.strip()):
            add(p, "Same national ID", 0)
    phones = [p for p in (phone, alt_phone) if p]
    if phones:
        for p in qs.filter(Q(phone__in=phones) | Q(alt_phone__in=phones)):
            add(p, "Same phone number", 1)
    if birth_date:
        name_q = Q(similarity__gte=0.55)
        if sex:
            name_q &= Q(sex=sex)
        for p in qs.filter(name_q).order_by("-similarity")[:20]:
            spread = 3 if (birth_date_estimated or p.birth_date_estimated) else 1
            if abs(p.birth_date.year - birth_date.year) <= spread:
                add(p, "Similar name and age", 2)
    ranked = sorted(found.values(), key=lambda x: (x[1], -getattr(x[0], "similarity", 0)))
    out = []
    for patient, _rank, reason in ranked[:limit]:
        patient.match_reason = reason
        out.append(patient)
    return out


def _prepare(data: dict) -> dict:
    data = dict(data)
    for key in ("phone", "alt_phone"):
        if key in data:
            data[key] = normalize_phone(data[key])
    age = data.pop("age_years", None)
    if not data.get("birth_date"):
        if age is None:
            if "birth_date" in data or "age_years" in data:
                raise BusinessValidationError("Enter a date of birth or an estimated age.",
                                              fields={"birth_date": ["Date of birth or age is required."]})
        else:
            data["birth_date"] = birth_date_from_age(age)
            data["birth_date_estimated"] = True
    if data.get("birth_date") and data["birth_date"] > timezone.localdate():
        raise BusinessValidationError("Date of birth is in the future.",
                                      fields={"birth_date": ["Cannot be in the future."]})
    for key, value in list(data.items()):
        if isinstance(value, str):
            data[key] = value.strip()
    return data


@transaction.atomic
def register_patient(ctx: ActorContext, data: dict, *, emergency_contacts=(), allergies=(),
                     confirm_not_duplicate: bool = False) -> Patient:
    data = _prepare(data)
    if "birth_date" not in data:
        raise BusinessValidationError("Enter a date of birth or an estimated age.",
                                      fields={"birth_date": ["Date of birth or age is required."]})
    if not confirm_not_duplicate:
        dupes = find_possible_duplicates(first_name=data["first_name"], middle_name=data.get("middle_name", ""),
                                         last_name=data.get("last_name", ""), birth_date=data["birth_date"],
                                         phone=data.get("phone", ""), alt_phone=data.get("alt_phone", ""),
                                         national_id=data.get("national_id", ""), sex=data.get("sex", ""),
                                         birth_date_estimated=data.get("birth_date_estimated", False))
        if dupes:
            raise PossibleDuplicate(dupes)
    mrn = new_mrn()
    patient = Patient(mrn=mrn, created_by=ctx.user, updated_by=ctx.user,
                      **{k: v for k, v in data.items() if k in DEMOGRAPHIC_FIELDS})
    patient.full_clean()
    patient.save()
    for c in emergency_contacts:
        EmergencyContact.objects.create(patient=patient, name=c["name"].strip(),
                                        relationship=c.get("relationship", "").strip(),
                                        phone=normalize_phone(c["phone"]))
    for a in allergies:
        Allergy.objects.create(patient=patient, substance=a["substance"].strip(), reaction=a.get("reaction", ""),
                               severity=a.get("severity", Allergy.Severity.MODERATE), recorded_by=ctx.user)
    record_event(ctx, action="patient.register", object_type="patient", object_id=patient.pk,
                 details={"mrn": mrn, "duplicate_warning_overridden": confirm_not_duplicate})
    return patient


class PossibleDuplicate(ConflictError):
    code = "possible_duplicate"

    def __init__(self, candidates):
        super().__init__(
            "This patient may already be registered. Check the matches before continuing.",
            extra={"candidates": [
                {"id": str(p.pk), "mrn": p.mrn, "full_name": p.full_name, "sex": p.sex,
                 "birth_date": p.birth_date.isoformat(), "phone": p.phone,
                 "reason": getattr(p, "match_reason", "")}
                for p in candidates
            ]},
        )


@transaction.atomic
def require_active(patient: Patient) -> None:
    """New records go on the surviving chart, never on a merged or inactive one."""
    if patient.merged_into_id:
        target = patient.merged_into
        raise ConflictError(f"This record was merged into {target.full_name} ({target.mrn}). Use that record.")
    if not patient.is_active:
        if patient.inactive_kind == Patient.InactiveKind.DECEASED:
            raise ConflictError(f"This patient is recorded as deceased ({patient.date_of_death:%d %b %Y}). "
                                "Nothing new can be added to the record.")
        raise ConflictError("This patient record is inactive. A clinic administrator or doctor can reactivate it "
                            "from the record if the patient returns.")


def update_patient(ctx: ActorContext, patient: Patient, data: dict) -> Patient:
    patient = Patient.objects.select_for_update().get(pk=patient.pk)
    require_active(patient)
    data = _prepare(data)
    changes = {}
    for key, value in data.items():
        if key not in DEMOGRAPHIC_FIELDS:
            continue
        old = getattr(patient, key)
        if old != value:
            changes[key] = {"from": str(old), "to": str(value)}
            setattr(patient, key, value)
    if changes:
        patient.updated_by = ctx.user
        patient.full_clean()
        patient.save()
        PatientChange.objects.bulk_create([
            PatientChange(patient=patient, field=k, old_value=v["from"], new_value=v["to"], changed_by=ctx.user)
            for k, v in changes.items()])
        record_event(ctx, action="patient.update", object_type="patient", object_id=patient.pk, details=changes)
    return patient


@transaction.atomic
def set_emergency_contacts(ctx: ActorContext, patient: Patient, contacts: list[dict]) -> None:
    old = list(patient.emergency_contacts.values("name", "relationship", "phone"))
    patient.emergency_contacts.all().delete()  # demographic data, fully captured in the audit diff below
    new = []
    for c in contacts:
        obj = EmergencyContact.objects.create(patient=patient, name=c["name"].strip(),
                                              relationship=c.get("relationship", "").strip(),
                                              phone=normalize_phone(c["phone"]))
        new.append({"name": obj.name, "relationship": obj.relationship, "phone": obj.phone})
    if old != new:
        def fmt(rows):
            return "; ".join(f"{r['name']} ({r['relationship'] or 'contact'}) {r['phone']}" for r in rows)

        PatientChange.objects.create(patient=patient, field="emergency_contacts", old_value=fmt(old),
                                     new_value=fmt(new), changed_by=ctx.user)
        record_event(ctx, action="patient.contacts_update", object_type="patient", object_id=patient.pk,
                     details={"from": old, "to": new})


@transaction.atomic
def add_allergy(ctx: ActorContext, patient: Patient, *, substance: str, reaction: str = "",
                severity: str = Allergy.Severity.MODERATE) -> Allergy:
    if patient.allergies.filter(is_active=True, substance__iexact=substance.strip()).exists():
        raise ConflictError("This allergy is already recorded.")
    allergy = Allergy.objects.create(patient=patient, substance=substance.strip(), reaction=reaction.strip(),
                                     severity=severity, recorded_by=ctx.user)
    record_event(ctx, action="patient.allergy_add", object_type="patient", object_id=patient.pk,
                 details={"substance": allergy.substance, "severity": severity})
    return allergy


@transaction.atomic
def inactivate_allergy(ctx: ActorContext, allergy: Allergy, reason: str) -> Allergy:
    if not reason.strip():
        raise BusinessValidationError("A reason is required.", fields={"reason": ["Required."]})
    allergy.is_active = False
    allergy.inactive_reason = reason.strip()
    allergy.save(update_fields=["is_active", "inactive_reason", "updated_at"])
    record_event(ctx, action="patient.allergy_inactivate", object_type="patient", object_id=allergy.patient_id,
                 details={"substance": allergy.substance, "reason": allergy.inactive_reason})
    return allergy


def record_view(ctx: ActorContext, patient: Patient) -> None:
    """Access to a patient record is itself audited."""
    record_event(ctx, action="patient.view", object_type="patient", object_id=patient.pk)


# ---------------------------------------------------------------------------
# Merging duplicate records
# ---------------------------------------------------------------------------
# Demographic fields copied from the duplicate only where the kept record has nothing.
MERGE_FILL_FIELDS = ("phone", "alt_phone", "national_id", "region", "city", "subcity_woreda", "kebele", "house_number",
                     "blood_group", "known_conditions", "past_history", "current_medications")


@transaction.atomic
def merge_patients(ctx: ActorContext, keep: Patient, duplicate: Patient, *, reason: str) -> dict:
    """Move everything recorded under `duplicate` to `keep` and retire the duplicate.

    Nothing is deleted: the duplicate keeps its MRN, is marked inactive and points to the kept record,
    so a search or an old paper file that cites it still leads to the right chart."""
    from apps.scheduling.models import Appointment, Visit

    if not reason.strip():
        raise BusinessValidationError("Say why these records are the same person.", fields={"reason": ["Required."]})
    if keep.pk == duplicate.pk:
        raise BusinessValidationError("Choose two different records.", fields={"duplicate_id": ["Same record."]})
    keep, duplicate = (Patient.objects.select_for_update().get(pk=pk) for pk in (keep.pk, duplicate.pk))
    for p in (keep, duplicate):
        if p.merged_into_id or not p.is_active:
            raise ConflictError(f"{p.full_name} ({p.mrn}) is already merged or inactive.")
    if keep.sex != duplicate.sex:
        raise ConflictError("The two records have different sex. Correct the wrong record before merging.")

    # Two open visits or two active appointments on the same day cannot both belong to one patient.
    open_days = set(Visit.objects.filter(patient=keep, status__in=Visit.OPEN).values_list("visit_date", flat=True))
    clash = Visit.objects.filter(patient=duplicate, status__in=Visit.OPEN, visit_date__in=open_days).first()
    if clash:
        raise ConflictError(f"Both records have an open visit on {clash.visit_date}. Complete or cancel one first.")
    appt_days = set(Appointment.objects.filter(patient=keep, status__in=Appointment.ACTIVE)
                    .values_list("scheduled_date", flat=True))
    clash = Appointment.objects.filter(patient=duplicate, status__in=Appointment.ACTIVE,
                                       scheduled_date__in=appt_days).first()
    if clash:
        raise ConflictError(f"Both records have an appointment on {clash.scheduled_date}. Cancel one first.")

    moved = {}
    for rel in Patient._meta.related_objects:
        if rel.field.name != "patient" or rel.related_model is Patient:
            continue
        n = rel.related_model.objects.filter(patient=duplicate).update(patient=keep)
        if n:
            moved[rel.related_model._meta.label] = n

    # The same allergy recorded on both: keep one active entry.
    seen = set()
    for allergy in keep.allergies.filter(is_active=True).order_by("created_at"):
        key = allergy.substance.strip().lower()
        if key in seen:
            allergy.is_active = False
            allergy.inactive_reason = f"Duplicate entry after merging {duplicate.mrn}"
            allergy.save(update_fields=["is_active", "inactive_reason", "updated_at"])
        seen.add(key)

    filled = {}
    for field in MERGE_FILL_FIELDS:
        if not getattr(keep, field) and getattr(duplicate, field):
            filled[field] = getattr(duplicate, field)
            setattr(keep, field, getattr(duplicate, field))
    if keep.birth_date is None and duplicate.birth_date is not None:
        keep.birth_date, keep.birth_date_estimated = duplicate.birth_date, duplicate.birth_date_estimated
        filled["birth_date"] = str(duplicate.birth_date)
    keep.updated_by = ctx.user
    keep.save()
    PatientChange.objects.bulk_create(
        [PatientChange(patient=keep, field="merged_record", old_value="",
                       new_value=f"{duplicate.full_name} ({duplicate.mrn}): {reason.strip()}", changed_by=ctx.user)]
        + [PatientChange(patient=keep, field=f, old_value="", new_value=str(v), changed_by=ctx.user)
           for f, v in filled.items()])

    duplicate.is_active = False
    duplicate.merged_into = keep
    duplicate.merged_at = timezone.now()
    duplicate.merged_by = ctx.user
    duplicate.merge_reason = reason.strip()[:255]
    duplicate.updated_by = ctx.user
    duplicate.save()
    details = {"kept": keep.mrn, "merged": duplicate.mrn, "reason": duplicate.merge_reason, "moved": moved,
               "filled": list(filled)}
    record_event(ctx, action="patient.merge", object_type="patient", object_id=keep.pk, details=details)
    record_event(ctx, action="patient.merged_into", object_type="patient", object_id=duplicate.pk, details=details)
    return details


@transaction.atomic
def deactivate_patient(ctx: ActorContext, patient: Patient, *, kind: str, note: str = "",
                       date_of_death: datetime.date | None = None) -> Patient:
    """Mark a record inactive (moved away, other) or deceased. Nothing is deleted. Future appointments are
    cancelled. Refused while the patient has an open visit, so that visit is closed properly first."""
    from apps.scheduling.models import Appointment, Visit
    from apps.scheduling.services import cancel_appointment

    patient = Patient.objects.select_for_update().get(pk=patient.pk)
    require_active(patient)
    if kind not in Patient.InactiveKind.values:
        raise BusinessValidationError("Choose why the record is inactive.", fields={"kind": ["Invalid choice."]})
    note = (note or "").strip()
    if kind == Patient.InactiveKind.DECEASED:
        if date_of_death is None:
            raise BusinessValidationError("Enter the date of death.", fields={"date_of_death": ["Required."]})
        if date_of_death > timezone.localdate():
            raise BusinessValidationError("The date of death cannot be in the future.",
                                          fields={"date_of_death": ["In the future."]})
        if date_of_death < patient.birth_date:
            raise BusinessValidationError("The date of death is before the date of birth.",
                                          fields={"date_of_death": ["Before birth."]})
    else:
        date_of_death = None
        if not note:
            raise BusinessValidationError("Give the reason.", fields={"note": ["Required."]})
    if Visit.objects.filter(patient=patient, status__in=Visit.OPEN).exists():
        raise ConflictError("The patient has an open visit. Complete it on the waiting list first "
                            "(choose how the visit ended), then mark the record.")
    patient.is_active = False
    patient.inactive_kind = kind
    patient.inactive_note = note
    patient.date_of_death = date_of_death
    patient.inactivated_at = timezone.now()
    patient.inactivated_by = ctx.user
    patient.updated_by = ctx.user
    patient.save()
    label = Patient.InactiveKind(kind).label
    reason = f"Patient record marked inactive: {label}"
    cancelled = 0
    for appt in Appointment.objects.filter(patient=patient, status__in=Appointment.BOOKED,
                                           scheduled_at__gte=timezone.now()):
        cancel_appointment(ctx, appt, reason)
        cancelled += 1
    PatientChange.objects.create(patient=patient, field="status", old_value="Active",
                                 new_value=label + (f" ({date_of_death:%d %b %Y})" if date_of_death else ""),
                                 changed_by=ctx.user)
    record_event(ctx, action="patient.deactivate", object_type="patient", object_id=patient.pk,
                 details={"kind": kind, "note": note, "date_of_death": str(date_of_death or ""),
                          "appointments_cancelled": cancelled})
    return patient


@transaction.atomic
def reactivate_patient(ctx: ActorContext, patient: Patient, *, reason: str) -> Patient:
    """Undo a deactivation, e.g. the patient came back or was marked deceased in error. Reason required."""
    patient = Patient.objects.select_for_update().get(pk=patient.pk)
    if patient.merged_into_id:
        raise ConflictError("A merged duplicate cannot be reactivated; use the record it was merged into.")
    if patient.is_active:
        raise ConflictError("This record is already active.")
    reason = (reason or "").strip()
    if not reason:
        raise BusinessValidationError("Give the reason.", fields={"reason": ["Required."]})
    before = Patient.InactiveKind(patient.inactive_kind).label if patient.inactive_kind else "Inactive"
    details = {"was": patient.inactive_kind, "date_of_death": str(patient.date_of_death or ""), "reason": reason}
    patient.is_active = True
    patient.inactive_kind = ""
    patient.inactive_note = ""
    patient.date_of_death = None
    patient.inactivated_at = None
    patient.inactivated_by = None
    patient.updated_by = ctx.user
    patient.save()
    PatientChange.objects.create(patient=patient, field="status", old_value=before, new_value=f"Active ({reason})",
                                 changed_by=ctx.user)
    record_event(ctx, action="patient.reactivate", object_type="patient", object_id=patient.pk, details=details)
    return patient
