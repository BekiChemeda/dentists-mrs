"""Helpers shared by the dental services."""

from __future__ import annotations

from apps.core.exceptions import BusinessValidationError, ConflictError, PermissionDeniedError
from apps.scheduling.models import Visit

from .. import teeth
from ..models import DentalEncounter


def location(data: dict, *, tooth_required: bool = False, allowed_scopes=None) -> dict:
    """Validated scope/tooth/surfaces/region from request data, or a validation error the user can act on."""
    try:
        return teeth.clean_location(data.get("scope") or "", data.get("tooth"), data.get("surfaces") or "",
                                    data.get("region") or "", tooth_required=tooth_required,
                                    allowed_scopes=allowed_scopes)
    except teeth.ToothError as exc:
        raise BusinessValidationError(str(exc), fields={exc.field: [str(exc)]}) from None


def check_teeth_list(values, field: str = "teeth") -> list[int]:
    out = []
    for v in values or []:
        try:
            out.append(teeth.check_tooth(v))
        except teeth.ToothError as exc:
            raise BusinessValidationError(str(exc), fields={field: [str(exc)]}) from None
    return sorted(set(out))


def open_encounter(encounter: DentalEncounter, *, lock: bool = True) -> DentalEncounter:
    """A draft examination on an open visit: the only place new clinical entries can go."""
    qs = DentalEncounter.objects.select_related("visit", "patient")
    enc = (qs.select_for_update(of=("self",)) if lock else qs).get(pk=encounter.pk)
    if enc.status != DentalEncounter.Status.DRAFT:
        raise ConflictError("This examination is signed. Corrections are made with an amendment, or in a new "
                            "examination.")
    if enc.visit.status in (Visit.Status.COMPLETED, Visit.Status.CANCELLED):
        raise ConflictError("This visit is closed. Reopen it to add to the examination.")
    return enc


def own_open_encounter(ctx, encounter: DentalEncounter) -> DentalEncounter:
    enc = open_encounter(encounter)
    if enc.dentist_id != ctx.user.pk:
        raise PermissionDeniedError("Only the dentist who started this examination can change it.")
    return enc


def same_patient(obj, patient_id, label: str) -> None:
    if obj is not None and obj.patient_id != patient_id:
        raise BusinessValidationError(f"The {label} belongs to another patient.", fields={label: ["Wrong patient."]})
