from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.approvals.models import ApprovalRequest
from apps.core.models import TimestampedModel, UUIDModel
from apps.patients.models import Patient
from apps.scheduling.models import Visit
from apps.core.concurrency import Versioned


class ServicePrice(Versioned, TimestampedModel):
    """Price list for non-stock services (consultation, procedures, dressing, certificates...)."""

    class Category(models.TextChoices):
        CONSULTATION = "consultation", "Consultation"
        PROCEDURE = "procedure", "Procedure"
        OTHER = "other", "Other service"

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=15, choices=Category.choices)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    # Percent. Medical services are generally VAT-exempt in Ethiopia; set only on the accountant's advice.
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "billing_service_price"
        ordering = ["category", "name"]
        constraints = [models.CheckConstraint(condition=Q(price__gte=0), name="service_price_nonneg")]


class Invoice(TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued — unpaid"
        PARTIAL = "partial", "Partly paid"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    number = models.CharField(max_length=20, unique=True)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="invoices")
    visit = models.ForeignKey(Visit, null=True, blank=True, on_delete=models.PROTECT, related_name="invoices")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_approval = models.ForeignKey(ApprovalRequest, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    void_approval = models.ForeignKey(ApprovalRequest, null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="+")
    void_reason = models.CharField(max_length=255, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "billing_invoice"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"], name="invoice_status_idx"),
                   models.Index(fields=["patient", "-created_at"], name="invoice_patient_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(subtotal__gte=0, discount_amount__gte=0, total__gte=0, amount_paid__gte=0,
                                               tax_amount__gte=0), name="invoice_amounts_nonneg"),
            models.CheckConstraint(condition=Q(discount_amount__lte=F("subtotal")), name="invoice_discount_le_subtotal"),
            models.CheckConstraint(condition=Q(total=F("subtotal") - F("discount_amount") + F("tax_amount")),
                                   name="invoice_total_consistent"),
            models.CheckConstraint(condition=Q(amount_paid__lte=F("total")), name="invoice_paid_le_total"),
        ]

    @property
    def balance(self):
        return self.total - self.amount_paid


class InvoiceLine(UUIDModel):
    class Kind(models.TextChoices):
        CONSULTATION = "consultation", "Consultation"
        LAB = "lab", "Laboratory"
        MEDICATION = "medication", "Medication"
        PROCEDURE = "procedure", "Procedure"
        OTHER = "other", "Other"

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="lines")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # What was billed, so the same lab test or dispensing is never charged twice.
    source_type = models.CharField(max_length=20, blank=True)
    source_id = models.CharField(max_length=64, blank=True)
    is_void = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_invoice_line"
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0, unit_price__gte=0, line_total__gte=0),
                                   name="invoice_line_amounts"),
            models.UniqueConstraint(fields=["source_type", "source_id"],
                                    condition=~Q(source_type="") & Q(is_void=False), name="invoice_line_source_once"),
        ]


class Payment(UUIDModel):
    """Money received. Payments are never edited or deleted."""

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        TELEBIRR = "telebirr", "telebirr"
        CBE_BIRR = "cbe_birr", "CBE Birr"
        MPESA = "mpesa", "M-Pesa"
        EBIRR = "ebirr", "E-birr"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        CARD = "card", "Card"
        INSURANCE = "insurance", "Insurance / credit"

    receipt_number = models.CharField(max_length=20, unique=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=15, choices=Method.choices)
    reference = models.CharField(max_length=80, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_payment"
        ordering = ["-received_at"]
        indexes = [models.Index(fields=["-received_at"], name="payment_received_idx")]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive")]


class Refund(UUIDModel):
    """Money returned to a patient against a payment, after a second person approved it. Never edited."""

    number = models.CharField(max_length=20, unique=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="refunds")
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=15, choices=Payment.Method.choices)
    reference = models.CharField(max_length=80, blank=True)
    reason = models.CharField(max_length=255)
    approval = models.ForeignKey(ApprovalRequest, on_delete=models.PROTECT, related_name="+")
    refunded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    refunded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_refund"
        ordering = ["-refunded_at"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="refund_amount_positive")]
