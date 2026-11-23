from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.approvals.models import ApprovalRequest
from apps.clinical.models import PrescriptionItem
from apps.core.models import UUIDModel
from apps.inventory.models import Item
from apps.patients.models import Patient


class Dispensation(UUIDModel):
    """Medicine handed to a patient against a prescription line. Never edited or deleted."""

    prescription_item = models.ForeignKey(PrescriptionItem, on_delete=models.PROTECT, related_name="dispensations")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="dispensations")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="dispensations")
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    override_approval = models.ForeignKey(ApprovalRequest, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    notes = models.CharField(max_length=255, blank=True)
    batch_choice_reason = models.CharField(max_length=255, blank=True)  # when not the earliest-expiring batch
    # Controlled medicines: what the pharmacist confirmed before handing over.
    special_form_checked = models.BooleanField(default=False)
    counselling_given = models.BooleanField(default=False)
    dispensed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    dispensed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pharmacy_dispensation"
        ordering = ["-dispensed_at"]
        indexes = [models.Index(fields=["patient", "-dispensed_at"], name="dispense_patient_idx")]
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="dispense_qty_positive")]
