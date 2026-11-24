"""Dental catalogues: procedures and prices, chart findings, diagnosis terms. Edited by dental.catalog.manage."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.accounts.models import Role
from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.inventory.models import Item

from ..models import DentalDiagnosisTerm, DentalProcedure, FindingType, ProcedureDefaultMaterial, Recall


def _audit_value(value):
    return value if isinstance(value, (bool, int, list, type(None))) else str(value)


def _save(ctx, model, obj, data: dict, *, unique: dict, object_type: str):
    created = obj is None
    changes: dict = {}
    if created:
        if model.objects.filter(**unique).exists():
            raise ConflictError("An entry with this code already exists.", fields={"code": ["Already used."]})
        obj = model(**data)
        changes = {k: _audit_value(v) for k, v in sorted(data.items())}
    else:
        for key, value in data.items():
            before = getattr(obj, key)
            setattr(obj, key, value)
            # Compare after the field has normalised the value (e.g. "500" and Decimal("500.00")).
            field = model._meta.get_field(key)
            after = field.to_python(value) if hasattr(field, "to_python") else value
            if before != after:
                changes[key] = {"from": _audit_value(before), "to": _audit_value(after)}
    obj.save()
    # Before and after values, so a sequence of price edits can be reconstructed from the log.
    label = getattr(obj, "name", None) or getattr(obj, "term", None) or ""
    record_event(ctx, action=f"{object_type}.{'create' if created else 'update'}", object_type=object_type,
                 object_id=obj.pk, details={"code": getattr(obj, "code", ""), "name": str(label),
                                            "changes": changes})
    return obj


@transaction.atomic
def save_finding_type(ctx: ActorContext, data: dict, obj: FindingType | None = None) -> FindingType:
    data = {k: v for k, v in data.items() if k != "row_version"}
    return _save(ctx, FindingType, obj, data, unique={"code": data.get("code")}, object_type="dental_finding_type")


@transaction.atomic
def save_diagnosis_term(ctx: ActorContext, data: dict, obj: DentalDiagnosisTerm | None = None) -> DentalDiagnosisTerm:
    data = {k: v for k, v in data.items() if k != "row_version"}
    unique = {"code_system": data.get("code_system", getattr(obj, "code_system", "ICD-10")), "code": data.get("code")}
    return _save(ctx, DentalDiagnosisTerm, obj, data, unique=unique, object_type="dental_diagnosis_term")


@transaction.atomic
def save_procedure(ctx: ActorContext, data: dict, obj: DentalProcedure | None = None) -> DentalProcedure:
    data = {k: v for k, v in data.items() if k not in ("row_version", "default_materials")}
    roles = data.get("performer_roles")
    if roles is not None:
        known = set(Role.objects.filter(code__in=roles).values_list("code", flat=True))
        if set(roles) - known:
            raise BusinessValidationError("Unknown role.", fields={"performer_roles": sorted(set(roles) - known)})
        data["performer_roles"] = sorted(set(roles))
    kind = data.get("follow_up_kind")
    if kind and kind not in Recall.Kind.values:
        raise BusinessValidationError("Unknown follow-up kind.", fields={"follow_up_kind": ["Invalid."]})
    return _save(ctx, DentalProcedure, obj, data, unique={"code": data.get("code")}, object_type="dental_procedure_type")


@transaction.atomic
def set_default_materials(ctx: ActorContext, procedure: DentalProcedure, rows: list[dict]) -> DentalProcedure:
    clean = []
    for row in rows:
        item = Item.objects.filter(pk=row.get("item_id"), is_active=True).first()
        if item is None or item.category in Item.REUSABLE:
            raise BusinessValidationError("Choose a consumable stock item.", fields={"default_materials": ["Invalid item."]})
        quantity = Decimal(str(row.get("quantity") or 0))
        if quantity <= 0:
            raise BusinessValidationError("Quantities must be positive.", fields={"default_materials": ["Must be > 0."]})
        clean.append((item, quantity))
    ProcedureDefaultMaterial.objects.filter(procedure=procedure).delete()
    ProcedureDefaultMaterial.objects.bulk_create(
        [ProcedureDefaultMaterial(procedure=procedure, item=i, quantity=q) for i, q in clean])
    record_event(ctx, action="dental_procedure_type.materials", object_type="dental_procedure_type",
                 object_id=procedure.pk, details={"materials": [i.code for i, _ in clean]})
    return procedure
