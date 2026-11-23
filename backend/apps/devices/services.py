"""Licence, activation and device-bound sign-in. Views stay thin; every change here is audited."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError, DomainError, PermissionDeniedError

from . import attestation, licence
from .models import ActivationCode, Installation, MobileDevice

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
CODE_MINUTES = 15
CHALLENGE_SECONDS = 120
QR_PREFIX = "MRSACT1."
_LICENCE_CACHE = "devices:licence-ok"


class AppNotLicensed(DomainError):
    status_code = 403
    code = "app_not_licensed"


class DeviceNotActivated(DomainError):
    status_code = 401
    code = "device_not_activated"


# --- Licence ---

def current_licence() -> licence.Licence:
    inst = Installation.get()
    return licence.parse(inst.licence_text, installation_id=str(inst.installation_id))


def licence_status() -> dict:
    inst = Installation.get()
    active = MobileDevice.objects.filter(status=MobileDevice.Status.ACTIVE).count()
    base = {"installation_id": str(inst.installation_id), "active_devices": active,
            "installed_at": inst.licence_installed_at}
    try:
        lic = current_licence()
    except licence.LicenceError as exc:
        return {**base, "valid": False, "problem": str(exc)}
    problem = ""
    if not lic.mobile_app:
        problem = "This clinic's licence does not include the phone app."
    elif lic.expired():
        problem = f"The phone app licence ended on {lic.expires_on.isoformat()}. Contact your supplier to renew."
    return {**base, "valid": not problem, "problem": problem, "licence_id": lic.licence_id, "clinic_id": lic.clinic_id,
            "clinic_name": lic.clinic_name, "mobile_app": lic.mobile_app, "max_devices": lic.max_devices,
            "online_payments": lic.online_payments,
            "issued_on": lic.issued_on, "expires_on": lic.expires_on, "days_left": lic.days_left(),
            "addresses": lic.addresses}


def require_app_licence() -> licence.Licence:
    """The licence must be valid, include the app and not be expired. Cached for a minute."""
    try:
        lic = current_licence()
    except licence.LicenceError as exc:
        raise AppNotLicensed(f"The phone app is not licensed on this server. {exc}") from exc
    if not lic.mobile_app:
        raise AppNotLicensed("This clinic's licence does not include the phone app. Contact your supplier.")
    if lic.expired():
        raise AppNotLicensed("The phone app licence for this clinic has ended. Ask the clinic to renew it.")
    return lic


def app_licence_ok() -> bool:
    ok = cache.get(_LICENCE_CACHE)
    if ok is None:
        try:
            require_app_licence()
            ok = True
        except AppNotLicensed:
            ok = False
        cache.set(_LICENCE_CACHE, ok, 60)
    return ok


def install_licence(ctx: ActorContext, text: str) -> dict:
    inst = Installation.get()
    try:
        lic = licence.parse(text, installation_id=str(inst.installation_id))
    except licence.LicenceError as exc:
        record_event(ctx, action="devices.licence.install", outcome="failure", details={"reason": str(exc)})
        raise BusinessValidationError(str(exc), fields={"licence": [str(exc)]}) from exc
    inst.licence_text = lic.text
    inst.licence_installed_at = timezone.now()
    inst.licence_installed_by = ctx.user if getattr(ctx.user, "is_authenticated", False) else None
    inst.save()
    cache.delete(_LICENCE_CACHE)
    record_event(ctx, action="devices.licence.install", object_type="licence", object_id=lic.licence_id,
                 details={"clinic_id": lic.clinic_id, "mobile_app": lic.mobile_app, "max_devices": lic.max_devices,
                          "expires_on": lic.expires_on.isoformat()})
    return licence_status()


# --- Activation codes ---

def _hash(code: str) -> str:
    return hashlib.sha256(attestation.normalise_code(code).encode()).hexdigest()


def _new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def create_activation_code(ctx: ActorContext, *, label: str = "", for_user=None) -> dict:
    lic = require_app_licence()
    _check_seats(lic)
    code = _new_code()
    row = ActivationCode.objects.create(code_hash=_hash(code), label=label[:80], for_user=for_user, created_by=ctx.user,
                                        expires_at=timezone.now() + timedelta(minutes=CODE_MINUTES))
    record_event(ctx, action="devices.code.create", object_type="activation_code", object_id=row.pk,
                 details={"label": row.label, "for_user": getattr(for_user, "username", "")})
    payload = {"licence": lic.text, "code": code}
    pin = getattr(settings, "MOBILE_TLS_CERT_SHA256", "")
    if pin:
        payload["pin"] = pin.lower().replace(":", "")
    qr = QR_PREFIX + licence.b64u_encode(json.dumps(payload, separators=(",", ":")).encode())
    return {"id": str(row.pk), "code": code, "expires_at": row.expires_at, "qr": qr, "clinic_name": lic.clinic_name,
            "address": lic.addresses.get("clinic", "")}


def _check_seats(lic: licence.Licence) -> None:
    active = MobileDevice.objects.filter(status=MobileDevice.Status.ACTIVE).count()
    if active >= lic.max_devices:
        raise ConflictError(f"All {lic.max_devices} phones allowed by the licence are in use. Switch off a phone "
                            f"that is no longer used, or ask your supplier for more.",
                            extra={"max_devices": lic.max_devices, "active_devices": active})


@transaction.atomic
def activate(ctx: ActorContext, *, code: str, chain: list[str], public_key: str = "", label: str = "",
             model_name: str = "", os_version: str = "") -> MobileDevice:
    lic = require_app_licence()
    row = ActivationCode.objects.select_for_update().filter(code_hash=_hash(code)).first()
    now = timezone.now()
    if row is None or row.used_at is not None or row.expires_at <= now:
        record_event(ctx, action="devices.activate", outcome="failure", details={"reason": "bad_code"})
        raise BusinessValidationError("This activation code is wrong, used or expired. Ask the administrator for a "
                                      "new one.", fields={"code": ["Wrong, used or expired."]})
    _check_seats(lic)

    strict = getattr(settings, "MOBILE_REQUIRE_HARDWARE_KEY", True)
    try:
        proof = attestation.verify(chain, code)
        key_der, storage, boot = proof.public_key_der, proof.security_level, proof.boot_state
    except attestation.AttestationError as exc:
        if strict:
            record_event(ctx, action="devices.activate", outcome="failure", details={"reason": str(exc)})
            raise BusinessValidationError(str(exc)) from exc
        # Development servers only (MOBILE_REQUIRE_HARDWARE_KEY=false, e.g. an emulator): an unproven key.
        try:
            key_der = base64.b64decode(public_key, validate=True)
            _load_key(key_der)
        except Exception as exc2:  # noqa: BLE001
            raise BusinessValidationError("The phone's key could not be read.") from exc2
        storage, boot = MobileDevice.KeyStorage.SOFTWARE, "unknown"

    row.used_at = now
    row.save(update_fields=["used_at"])
    device = MobileDevice.objects.create(
        label=(label or row.label)[:80], model_name=model_name[:80], os_version=os_version[:40], public_key=key_der,
        key_storage=storage, boot_state=boot, for_user=row.for_user, activation_code=row)
    record_event(ctx, action="devices.activate", object_type="mobile_device", object_id=device.pk,
                 details={"issued_by": row.created_by.username, "label": device.label, "model": device.model_name, "key_storage": storage, "boot_state": boot})
    return device


# --- Sign-in proof ---

def _load_key(der: bytes) -> ec.EllipticCurvePublicKey:
    key = serialization.load_der_public_key(der)
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
        raise ValueError("P-256 key expected")
    return key


def new_challenge(device_id: str) -> str:
    nonce = secrets.token_urlsafe(24)
    cache.set(f"devices:challenge:{nonce}", str(device_id), CHALLENGE_SECONDS)
    return nonce


def verify_sign_in(*, device_id: str, nonce: str, signature: str) -> MobileDevice:
    """The phone signs "mrs-login:<nonce>" with its hardware key. The nonce works once."""
    refuse = DeviceNotActivated("This phone is not activated for this clinic. Ask the administrator to activate it.")
    if not device_id or not nonce or not signature:
        raise refuse
    key = f"devices:challenge:{nonce}"
    expected = cache.get(key)
    cache.delete(key)
    if expected is None or expected != str(device_id):
        raise DeviceNotActivated("The sign-in request expired. Try again.")
    device = MobileDevice.objects.filter(pk=device_id).first()
    if device is None or not device.is_active:
        raise refuse
    try:
        _load_key(bytes(device.public_key)).verify(base64.b64decode(signature, validate=True),
                                                    f"mrs-login:{nonce}".encode(), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        raise refuse from None
    return device


def note_sign_in(device: MobileDevice, user) -> None:
    if device.for_user_id and device.for_user_id != user.pk:
        raise PermissionDeniedError("This phone is activated for another member of staff.")
    MobileDevice.objects.filter(pk=device.pk).update(last_seen_at=timezone.now(), last_user=user)


# --- Switching a phone off ---

@transaction.atomic
def revoke(ctx: ActorContext, device: MobileDevice, reason: str) -> MobileDevice:
    from apps.accounts.models import UserSession

    if not device.is_active:
        return device
    now = timezone.now()
    device.status, device.revoked_at, device.revoked_by, device.revoke_reason = (
        MobileDevice.Status.REVOKED, now, ctx.user, reason[:200])
    device.save(update_fields=["status", "revoked_at", "revoked_by", "revoke_reason"])
    ended = UserSession.objects.filter(device=device, ended_at__isnull=True).update(
        ended_at=now, end_reason=UserSession.EndReason.REVOKED)
    record_event(ctx, action="devices.revoke", object_type="mobile_device", object_id=device.pk,
                 details={"label": device.label, "reason": device.revoke_reason, "sessions_ended": ended})
    return device
