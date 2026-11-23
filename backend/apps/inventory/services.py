"""Stock ledger: receipts, adjustments, stock queries and FEFO allocation."""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError

from .models import Batch, Item, Purchase, StockMovement, Supplier

ZERO = Decimal("0")
_DEC = DecimalField(max_digits=14, decimal_places=3)


def batch_on_hand_subquery():
    return Coalesce(
        Subquery(StockMovement.objects.filter(batch=OuterRef("pk")).values("batch")
                 .annotate(total=Sum("quantity")).values("total")[:1], output_field=_DEC),
        Value(ZERO, output_field=_DEC))


def items_with_stock(qs=None):
    qs = qs if qs is not None else Item.objects.all()
    today = timezone.localdate()
    on_hand = Coalesce(Sum("movements__quantity"), Value(ZERO, output_field=_DEC), output_field=_DEC)
    usable = Coalesce(
        Sum("movements__quantity", filter=Q(movements__batch__expiry_date__isnull=True)
            | Q(movements__batch__expiry_date__gte=today)),
        Value(ZERO, output_field=_DEC), output_field=_DEC)
    return qs.annotate(on_hand=on_hand, usable=usable)


def batches_with_stock(item: Item | None = None):
    qs = Batch.objects.select_related("item", "supplier").annotate(on_hand=batch_on_hand_subquery())
    if item is not None:
        qs = qs.filter(item=item)
    return qs


def low_stock_items():
    return [i for i in items_with_stock(Item.objects.filter(is_active=True)).order_by("name")
            if i.usable <= i.reorder_level]


def expiring_batches(days: int = 90):
    limit = timezone.localdate() + datetime.timedelta(days=days)
    return (batches_with_stock().filter(expiry_date__isnull=False, expiry_date__lte=limit, on_hand__gt=0)
            .order_by("expiry_date"))


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
ITEM_FIELDS = ("code", "name", "generic_name", "brand_name", "category", "dosage_form", "strength", "unit", "route",
               "therapeutic_category", "controlled_class", "allergy_groups", "warnings", "default_supplier",
               "reorder_level", "selling_price", "is_active")


@transaction.atomic
def save_item(ctx: ActorContext, data: dict, item: Item | None = None) -> Item:
    creating = item is None
    item = item or Item()
    if creating and Item.objects.filter(code__iexact=data["code"].strip()).exists():
        raise ConflictError("An item with this code already exists.", fields={"code": ["Already used."]})
    changes = {}
    for key in ITEM_FIELDS:
        if key in data:
            value = data[key].strip() if isinstance(data[key], str) else data[key]
            if creating or getattr(item, key) != value:
                changes[key] = str(value)
                setattr(item, key, value)
    item.full_clean()
    item.save()
    if changes:
        record_event(ctx, action="item.create" if creating else "item.update", object_type="item", object_id=item.pk,
                     details=changes)
    return item


@transaction.atomic
def save_supplier(ctx: ActorContext, data: dict, supplier: Supplier | None = None) -> Supplier:
    creating = supplier is None
    supplier = supplier or Supplier()
    for key, value in data.items():
        setattr(supplier, key, value.strip() if isinstance(value, str) else value)
    supplier.full_clean()
    supplier.save()
    record_event(ctx, action="supplier.create" if creating else "supplier.update", object_type="supplier",
                 object_id=supplier.pk, details={"name": supplier.name})
    return supplier


# ---------------------------------------------------------------------------
# Movements
# ---------------------------------------------------------------------------
@transaction.atomic
def receive_purchase(ctx: ActorContext, *, supplier: Supplier, purchase_date: datetime.date, lines: list[dict],
                     supplier_invoice_no: str = "", notes: str = "") -> Purchase:
    if not lines:
        raise BusinessValidationError("Add at least one line.", fields={"lines": ["Required."]})
    purchase = Purchase.objects.create(supplier=supplier, purchase_date=purchase_date, received_by=ctx.user,
                                       supplier_invoice_no=supplier_invoice_no.strip(), notes=notes.strip())
    total = ZERO
    today = timezone.localdate()
    for line in lines:
        item: Item = line["item"]
        if line["quantity"] <= 0:
            raise BusinessValidationError("Quantities must be positive.", fields={"lines": ["Quantity must be > 0."]})
        if line.get("expiry_date") and line["expiry_date"] <= today:
            raise BusinessValidationError(f"{item.name}: expiry date has already passed.",
                                          fields={"lines": ["Expired stock cannot be received."]})
        batch, created = Batch.objects.get_or_create(
            item=item, batch_number=line["batch_number"].strip(),
            defaults={"expiry_date": line.get("expiry_date"), "unit_cost": line.get("unit_cost") or ZERO,
                      "supplier": supplier})
        if not created and line.get("expiry_date") and batch.expiry_date != line["expiry_date"]:
            raise ConflictError(f"Batch {batch.batch_number} of {item.name} is already recorded with expiry "
                                f"{batch.expiry_date}.")
        StockMovement.objects.create(item=item, batch=batch, kind=StockMovement.Kind.RECEIPT,
                                     quantity=line["quantity"], purchase=purchase, created_by=ctx.user,
                                     reference_type="purchase", reference_id=str(purchase.pk))
        total += (line.get("unit_cost") or ZERO) * line["quantity"]
    purchase.total_cost = total.quantize(Decimal("0.01"))
    purchase.save(update_fields=["total_cost"])
    record_event(ctx, action="stock.receive", object_type="purchase", object_id=purchase.pk,
                 details={"supplier": supplier.name, "lines": len(lines), "total_cost": str(purchase.total_cost)})
    return purchase


def _lock_batch_stock(batch_ids) -> dict:
    """Lock batches (row locks) and return their current quantity on hand."""
    list(Batch.objects.select_for_update().filter(pk__in=batch_ids).order_by("pk").values_list("pk", flat=True))
    rows = StockMovement.objects.filter(batch_id__in=batch_ids).values("batch_id").annotate(total=Sum("quantity"))
    stock = {pk: ZERO for pk in batch_ids}
    stock.update({r["batch_id"]: r["total"] for r in rows})
    return stock


@transaction.atomic
def adjust_stock(ctx: ActorContext, *, batch: Batch, quantity: Decimal, kind: str, reason: str) -> StockMovement:
    if kind not in (StockMovement.Kind.ADJUSTMENT, StockMovement.Kind.EXPIRED):
        raise BusinessValidationError("Invalid adjustment type.")
    if not reason.strip():
        raise BusinessValidationError("A reason is required.", fields={"reason": ["Required."]})
    if quantity == 0 or (kind == StockMovement.Kind.EXPIRED and quantity > 0):
        raise BusinessValidationError("Write-offs must reduce stock.", fields={"quantity": ["Must be negative."]})
    on_hand = _lock_batch_stock([batch.pk])[batch.pk]
    if on_hand + quantity < 0:
        raise ConflictError(f"Only {on_hand} {batch.item.unit} of batch {batch.batch_number} are in stock.")
    movement = StockMovement.objects.create(item=batch.item, batch=batch, kind=kind, quantity=quantity,
                                            reason=reason.strip(), created_by=ctx.user)
    record_event(ctx, action="stock.adjust", object_type="batch", object_id=batch.pk,
                 details={"item": batch.item.code, "batch": batch.batch_number, "quantity": str(quantity),
                          "kind": kind, "reason": movement.reason})
    if quantity < 0:
        check_reorder_level(batch.item)
    return movement


def allocate_fefo(ctx: ActorContext, *, item: Item, quantity: Decimal, reference_type: str, reference_id,
                  allow_shortfall: bool = False, first_batch_id=None) -> list[StockMovement]:
    """
    Deduct `quantity` from non-expired batches, earliest expiry first (FEFO).
    Must run inside the caller's transaction. Raises InsufficientStock unless an approved
    override allows the shortfall, which is then booked against the newest batch.
    """
    today = timezone.localdate()
    batches = list(Batch.objects.filter(item=item).filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today))
                   .order_by(F("expiry_date").asc(nulls_last=True), "created_at"))
    if first_batch_id is not None:
        # The pharmacist picked a batch (e.g. the one physically on the shelf); it is used first.
        chosen = [b for b in batches if str(b.pk) == str(first_batch_id)]
        if not chosen:
            raise ConflictError("That batch is expired, empty or belongs to another medicine.")
        batches = chosen + [b for b in batches if b.pk != chosen[0].pk]
    stock = _lock_batch_stock([b.pk for b in batches]) if batches else {}
    available = sum((max(v, ZERO) for v in stock.values()), ZERO)
    if available < quantity and not allow_shortfall:
        raise InsufficientStock(item, available, quantity)
    if not batches:
        raise ConflictError(f"No usable batch of {item.name} exists to record this against.")

    movements, remaining = [], quantity
    for batch in batches:
        take = min(max(stock[batch.pk], ZERO), remaining)
        if take > 0:
            movements.append(StockMovement.objects.create(
                item=item, batch=batch, kind=StockMovement.Kind.DISPENSE, quantity=-take, created_by=ctx.user,
                reference_type=reference_type, reference_id=str(reference_id)))
            remaining -= take
        if remaining == 0:
            break
    if remaining > 0:  # approved override: record the shortfall explicitly
        movements.append(StockMovement.objects.create(
            item=item, batch=batches[-1], kind=StockMovement.Kind.DISPENSE, quantity=-remaining, created_by=ctx.user,
            reference_type=reference_type, reference_id=str(reference_id), is_override=True,
            reason="Dispensed beyond recorded stock under approved override"))
    check_reorder_level(item)
    return movements


def check_reorder_level(item: Item) -> None:
    """After stock goes down: tell stock managers once when usable stock reaches the reorder level."""
    if item.reorder_level <= 0 or not item.is_active:
        return
    usable = items_with_stock(Item.objects.filter(pk=item.pk)).get().usable

    def _send():
        from apps.notifications.services import notify_permission_holders

        notify_permission_holders(
            "inventory.manage", kind="low_stock", once=True, link=f"/inventory?item={item.pk}",
            title=f"Low stock: {item.name}",
            body=f"{usable.normalize():f} {item.unit} usable; reorder level is {item.reorder_level.normalize():f}.")

    if usable <= item.reorder_level:
        transaction.on_commit(_send)


class InsufficientStock(ConflictError):
    code = "insufficient_stock"

    def __init__(self, item, available, requested):
        super().__init__(
            f"Only {available.normalize():f} {item.unit} of {item.name} are in usable stock; "
            f"{requested.normalize():f} requested.",
            extra={"available": str(available), "requested": str(requested)})
