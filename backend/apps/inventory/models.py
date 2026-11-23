from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimestampedModel, UUIDModel
from apps.core.concurrency import Versioned


class Item(Versioned, TimestampedModel):
    """A stocked product: medicine, medical supply, consumable or reagent."""

    class Category(models.TextChoices):
        MEDICINE = "medicine", "Medicine"
        SUPPLY = "supply", "Medical supply"
        CONSUMABLE = "consumable", "Consumable"
        REAGENT = "reagent", "Laboratory reagent"

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=150)
    generic_name = models.CharField(max_length=150, blank=True)
    brand_name = models.CharField(max_length=150, blank=True)
    category = models.CharField(max_length=12, choices=Category.choices)
    class Controlled(models.TextChoices):
        NONE = "", "Not controlled"
        PSYCHOTROPIC = "psychotropic", "Psychotropic"
        NARCOTIC = "narcotic", "Narcotic"

    dosage_form = models.CharField(max_length=50, blank=True)  # tablet, capsule, syrup, injection...
    strength = models.CharField(max_length=50, blank=True)  # 500 mg, 250 mg/5 ml...
    route = models.CharField(max_length=30, blank=True)  # default route: oral, IV, IM, topical...
    therapeutic_category = models.CharField(max_length=80, blank=True)  # antibiotic, antimalarial...
    # Narcotic and psychotropic medicines follow EFDA Directive 1121/2025 (special prescription, register).
    controlled_class = models.CharField(max_length=12, choices=Controlled.choices, blank=True)
    # Allergy groups this medicine belongs to, e.g. "Penicillin, Beta-lactam". Matched against recorded allergies.
    allergy_groups = models.CharField(max_length=255, blank=True)
    warnings = models.CharField(max_length=255, blank=True)  # printed on the prescription, e.g. "Avoid alcohol"
    default_supplier = models.ForeignKey("Supplier", null=True, blank=True, on_delete=models.SET_NULL,
                                         related_name="+")
    unit = models.CharField(max_length=20, default="unit")  # dispensing / counting unit
    reorder_level = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # percent; see billing ServicePrice
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "inventory_item"
        ordering = ["name"]
        indexes = [models.Index(fields=["category", "is_active"], name="item_category_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(reorder_level__gte=0), name="item_reorder_nonneg"),
            models.CheckConstraint(condition=Q(selling_price__gte=0), name="item_price_nonneg"),
        ]

    def __str__(self) -> str:
        return f"{self.name} {self.strength}".strip()


class Supplier(Versioned, TimestampedModel):
    name = models.CharField(max_length=150, unique=True)
    contact_person = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    tin = models.CharField("TIN", max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "inventory_supplier"
        ordering = ["name"]


class Purchase(TimestampedModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchases")
    supplier_invoice_no = models.CharField(max_length=50, blank=True)
    purchase_date = models.DateField()
    notes = models.CharField(max_length=255, blank=True)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "inventory_purchase"
        ordering = ["-purchase_date", "-created_at"]


class Batch(UUIDModel):
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="batches")
    batch_number = models.CharField(max_length=50)
    expiry_date = models.DateField(null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_batch"
        ordering = ["expiry_date", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["item", "batch_number"], name="batch_item_number_unique"),
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name="batch_cost_nonneg"),
        ]


class StockMovement(UUIDModel):
    """
    The stock ledger. Quantity on hand is always SUM(quantity) per batch; nothing edits a
    stock number directly. Rows are never updated or deleted; mistakes are corrected with
    a reversing adjustment.
    """

    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Receipt"
        DISPENSE = "dispense", "Dispensed"
        ADJUSTMENT = "adjustment", "Adjustment"
        EXPIRED = "expired", "Expired / damaged write-off"

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="movements")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    reason = models.CharField(max_length=255, blank=True)
    purchase = models.ForeignKey(Purchase, null=True, blank=True, on_delete=models.PROTECT, related_name="movements")
    reference_type = models.CharField(max_length=30, blank=True)
    reference_id = models.CharField(max_length=64, blank=True)
    is_override = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_stock_movement"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["batch"], name="movement_batch_idx"),
            models.Index(fields=["item", "-created_at"], name="movement_item_idx"),
            models.Index(fields=["reference_type", "reference_id"], name="movement_ref_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=~Q(quantity=0), name="movement_nonzero"),
            models.CheckConstraint(
                condition=(Q(kind="receipt", quantity__gt=0) | Q(kind="dispense", quantity__lt=0)
                           | Q(kind="expired", quantity__lt=0) | Q(kind="adjustment")),
                name="movement_sign_matches_kind",
            ),
        ]
