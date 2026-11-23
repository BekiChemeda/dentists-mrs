from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimestampedModel


class ApprovalRequest(TimestampedModel):
    """
    Two-person rule for risky actions: dispensing beyond recorded stock, discounts and
    invoice voids. The approver must hold the kind's permission and cannot be the requester.
    An approved request can be used exactly once.
    """

    class Kind(models.TextChoices):
        DISPENSE_OVERRIDE = "dispense_override", "Dispense beyond recorded stock"
        DISCOUNT = "discount", "Invoice discount"
        INVOICE_VOID = "invoice_void", "Void invoice"
        REFUND = "refund", "Refund a payment"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        USED = "used", "Used"
        CANCELLED = "cancelled", "Cancelled"

    PERMISSION_FOR_KIND = {
        Kind.DISPENSE_OVERRIDE: "pharmacy.dispense.override",
        Kind.DISCOUNT: "billing.discount.approve",
        Kind.INVOICE_VOID: "billing.void.approve",
        # Refunds reverse money already received, like voids, so the same approvers decide them.
        Kind.REFUND: "billing.void.approve",
    }

    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    object_type = models.CharField(max_length=40)
    object_id = models.CharField(max_length=64)
    summary = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    reason = models.CharField(max_length=255)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=255, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "approvals_request"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "kind"], name="approval_status_idx"),
                   models.Index(fields=["object_type", "object_id"], name="approval_object_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(decided_by__isnull=True) | ~Q(decided_by=models.F("requested_by")),
                                   name="approval_not_self_decided"),
        ]
