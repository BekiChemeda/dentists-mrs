"""
Phones allowed to use the Android app, and the licence that says whether this clinic may use it.

A phone is activated once with a one-time code from an administrator. During activation it creates a
key pair inside its security chip; the private key never leaves the phone. Every app sign-in then has to
be signed with that key, so a copied app, a copied phone backup or a borrowed code from another clinic
cannot sign in here.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Installation(models.Model):
    """One row. Identifies this server installation; the licence is issued for this ID."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    installation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    licence_text = models.TextField(blank=True)
    licence_installed_at = models.DateTimeField(null=True, blank=True)
    licence_installed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                             on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "devices_installation"
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="installation_singleton")]

    @classmethod
    def get(cls) -> "Installation":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ActivationCode(models.Model):
    """A one-time code shown to an administrator. Only its hash is stored."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code_hash = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=80, blank=True)
    # When set, the phone can only be used by this person.
    for_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "devices_activation_code"


class MobileDevice(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Switched off"

    class KeyStorage(models.TextChoices):
        STRONGBOX = "strongbox", "Separate security chip"
        TEE = "tee", "Phone's secure area"
        SOFTWARE = "software", "Software only (not proven)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=80, blank=True)
    model_name = models.CharField(max_length=80, blank=True)
    os_version = models.CharField(max_length=40, blank=True)
    # SubjectPublicKeyInfo (DER) of the phone's P-256 key, as proven by the attestation certificate.
    public_key = models.BinaryField()
    key_storage = models.CharField(max_length=10, choices=KeyStorage.choices)
    boot_state = models.CharField(max_length=20, blank=True)
    for_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    activation_code = models.OneToOneField(ActivationCode, on_delete=models.PROTECT, related_name="device")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    activated_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    revoke_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "devices_mobile_device"
        indexes = [models.Index(fields=["status"], name="device_status_idx")]

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE
