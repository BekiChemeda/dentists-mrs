"""
Payments by phone. The clinic's own Chapa or telebirr merchant account receives the money; this system only
asks the provider to send a prompt to the patient's phone and records the payment once the provider confirms
it. Cash and other methods are still recorded by hand in billing.

Secrets (API keys, passwords) are stored sealed (apps/core/secretbox.py) and never returned by the API.
"""
from __future__ import annotations

import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def _token() -> str:
    return secrets.token_urlsafe(24)


class GatewaySettings(models.Model):
    """One row, changed by holders of payments.gateway.manage (system administrators)."""

    class ChapaMethod(models.TextChoices):
        TELEBIRR = "telebirr", "telebirr (through Chapa)"
        MPESA = "mpesa", "M-Pesa"
        CBEBIRR = "cbebirr", "CBE Birr"
        EBIRR = "ebirr", "E-birr"

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    chapa_enabled = models.BooleanField(default=False)
    chapa_secret_key = models.TextField(blank=True)  # sealed
    chapa_webhook_secret = models.TextField(blank=True)  # sealed; the "secret hash" set in the Chapa dashboard
    chapa_methods = models.JSONField(default=list, blank=True)

    telebirr_enabled = models.BooleanField(default=False)
    telebirr_endpoint = models.URLField(blank=True)
    telebirr_third_party_id = models.CharField(max_length=80, blank=True)
    telebirr_password = models.TextField(blank=True)  # sealed
    telebirr_identifier = models.CharField(max_length=80, blank=True)
    telebirr_identifier_type = models.CharField(max_length=4, default="12")
    telebirr_security_credential = models.TextField(blank=True)  # sealed
    telebirr_short_code = models.CharField(max_length=20, blank=True)
    # Telebirr sends the result to this public address; the token makes the address unguessable.
    telebirr_public_base_url = models.URLField(blank=True)
    telebirr_callback_token = models.CharField(max_length=64, default=_token)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        db_table = "payments_gateway_settings"
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="gateway_settings_singleton")]

    @classmethod
    def get(cls) -> "GatewaySettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class OnlinePayment(models.Model):
    class Provider(models.TextChoices):
        CHAPA = "chapa", "Chapa"
        TELEBIRR = "telebirr", "telebirr"

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for the patient"
        SUCCEEDED = "succeeded", "Paid"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "No answer"
        CANCELLED = "cancelled", "Stopped"
        # Confirmed by the provider after the invoice was settled another way: the money must be refunded.
        UNAPPLIED = "unapplied", "Paid twice: refund needed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey("billing.Invoice", on_delete=models.PROTECT, related_name="online_payments")
    provider = models.CharField(max_length=10, choices=Provider.choices)
    method = models.CharField(max_length=10)
    phone = models.CharField(max_length=13)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # Our reference: random, sent to the provider and used to match its answer.
    reference = models.CharField(max_length=40, unique=True)
    provider_reference = models.CharField(max_length=80, blank=True)
    conversation_id = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    message = models.CharField(max_length=255, blank=True)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    started_from = models.CharField(max_length=10, default="web")
    created_at = models.DateTimeField(default=timezone.now)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    payment = models.OneToOneField("billing.Payment", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="online_payment")

    class Meta:
        db_table = "payments_online_payment"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"], name="onlinepay_status_idx")]
        constraints = [
            # One request at a time per invoice, so a patient is never asked to pay the same bill twice at once.
            models.UniqueConstraint(fields=["invoice"], condition=models.Q(status="pending"), name="onlinepay_one_pending"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="onlinepay_amount_positive"),
        ]
