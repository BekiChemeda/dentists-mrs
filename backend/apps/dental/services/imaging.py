"""
Dental images (ADR 0007). Bytes are written once to DENTAL_IMAGE_ROOT under an opaque random name; the database
row holds the metadata and the SHA-256. The original bytes are kept exactly as uploaded (no re-compression of
radiographs); a separate JPEG preview is generated for the browser. Files are never overwritten or deleted by the
application: a wrong image is withdrawn, a correction is a new upload that names the image it replaces.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import os
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.core.modules import is_enabled
from apps.patients.models import Patient

from .. import teeth
from ..models import DentalEncounter, DentalImage, DentalImageChange
from .common import check_teeth_list, same_patient

MAX_PIXELS = 80_000_000
PREVIEW_EDGE = 1600
FORMATS = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png"), "TIFF": ("image/tiff", "tif")}


def root() -> Path:
    return Path(settings.DENTAL_IMAGE_ROOT)


def _path(key: str) -> Path:
    """Resolve a storage key inside the image root; anything else is refused (no path traversal)."""
    base = root().resolve()
    target = (base / key).resolve()
    if base not in target.parents:
        raise ConflictError("Invalid image location.")
    return target


def _write_once(key: str, data: bytes) -> None:
    target = _path(key)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.partial")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if target.exists():
            raise ConflictError("Image storage clash; try again.")
        os.link(tmp, target)  # fails if the name exists: an image is never overwritten
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def check_image(raw: bytes) -> tuple[str, str, int, int, bytes]:
    """Validate by content, never by name. Returns (content type, extension, width, height, preview JPEG)."""
    if not raw:
        raise BusinessValidationError("The file is empty.", fields={"file": ["Empty."]})
    limit = settings.DENTAL_IMAGE_MAX_BYTES
    if len(raw) > limit:
        raise BusinessValidationError(f"The file is larger than {limit // (1024 * 1024)} MB.", fields={"file": ["Too large."]})
    if raw[128:132] == b"DICM":
        raise BusinessValidationError("DICOM files are not supported. Export the image as PNG or TIFF from the X-ray "
                                      "software.", fields={"file": ["DICOM not supported."]})
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            if fmt not in FORMATS:
                raise BusinessValidationError("Use a JPEG, PNG or TIFF image.", fields={"file": ["Unsupported type."]})
            width, height = probe.size
            if width * height > MAX_PIXELS:
                raise BusinessValidationError("The picture is too large in pixels.", fields={"file": ["Too many pixels."]})
            probe.verify()
        with Image.open(io.BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode.startswith("I;16"):
                img = img.convert("I")
            if img.mode == "I":
                # 16-bit greyscale radiographs: scaled to 8 bits for the preview only.
                img = img.point(lambda v: v * (1 / 256)).convert("L")
            elif img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=85)  # preview only; the original is kept unchanged
    except BusinessValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise BusinessValidationError("This image cannot be read. Export or photograph it again.",
                                      fields={"file": ["Unreadable."]}) from exc
    content_type, ext = FORMATS[fmt]
    return content_type, ext, width, height, out.getvalue()


def _clean_meta(data: dict, patient_id) -> dict:
    out = {}
    if "kind" in data:
        if data["kind"] not in DentalImage.Kind.values:
            raise BusinessValidationError("Choose the image type.", fields={"kind": ["Required."]})
        out["kind"] = data["kind"]
    if "teeth" in data:
        out["teeth"] = check_teeth_list(data["teeth"])
    if "region" in data:
        if data["region"] and data["region"] not in teeth.REGIONS:
            raise BusinessValidationError("Unknown region.", fields={"region": ["Invalid."]})
        out["region"] = data["region"] or ""
    if "description" in data:
        out["description"] = (data["description"] or "").strip()[:255]
    if "captured_at" in data:
        if data["captured_at"] and data["captured_at"] > timezone.now() + datetime.timedelta(minutes=5):
            raise BusinessValidationError("The capture time is in the future.", fields={"captured_at": ["Future."]})
        out["captured_at"] = data["captured_at"]
    if "referring_dentist" in data:
        out["referring_dentist"] = data["referring_dentist"]
    return out


def upload(ctx: ActorContext, patient: Patient, raw: bytes, original_name: str, data: dict) -> DentalImage:
    if not is_enabled("dental_imaging"):
        raise ConflictError("The dental imaging module is switched off for this clinic.")
    if patient.merged_into_id:
        raise ConflictError("This record was merged; upload to the record it was merged into.")
    meta = _clean_meta(data, patient.pk)
    if "kind" not in meta:
        raise BusinessValidationError("Choose the image type.", fields={"kind": ["Required."]})
    content_type, ext, width, height, preview = check_image(raw)
    digest = hashlib.sha256(raw).hexdigest()
    key_id = uuid.uuid4().hex
    key, preview_key = f"{key_id[:2]}/{key_id}.{ext}", f"{key_id[:2]}/{key_id}.preview.jpg"
    _write_once(key, raw)
    _write_once(preview_key, preview)
    try:
        with transaction.atomic():
            encounter = None
            if data.get("encounter_id"):
                encounter = DentalEncounter.objects.filter(pk=data["encounter_id"]).first()
                if encounter is None:
                    raise BusinessValidationError("Unknown examination.", fields={"encounter_id": ["Not found."]})
                same_patient(encounter, patient.pk, "encounter_id")
            replaces = None
            if data.get("replaces_id"):
                replaces = DentalImage.objects.select_for_update().filter(pk=data["replaces_id"]).first()
                if replaces is None:
                    raise BusinessValidationError("Unknown image.", fields={"replaces_id": ["Not found."]})
                same_patient(replaces, patient.pk, "replaces_id")
            safe_name = "".join(c for c in os.path.basename(original_name or "") if c.isalnum() or c in "._- ")[:120]
            image = DentalImage.objects.create(
                patient=patient, encounter=encounter, visit=encounter.visit if encounter else None,
                uploaded_by=ctx.user, original_name=safe_name or f"image.{ext}", content_type=content_type,
                size_bytes=len(raw), sha256=digest, width=width, height=height, storage_key=key,
                preview_key=preview_key, replaces=replaces, **meta)
            if replaces is not None and replaces.status == DentalImage.Status.ACTIVE:
                replaces.status, replaces.withdrawn_at, replaces.withdrawn_by = (DentalImage.Status.WITHDRAWN,
                                                                                 timezone.now(), ctx.user)
                replaces.withdrawn_reason = f"Replaced by a corrected image ({image.pk})"
                replaces.save(update_fields=["status", "withdrawn_at", "withdrawn_by", "withdrawn_reason"])
            record_event(ctx, action="dental_image.upload", object_type="patient", object_id=patient.pk,
                         details={"image": str(image.pk), "kind": image.kind, "bytes": len(raw), "sha256": digest,
                                  **({"replaces": str(replaces.pk)} if replaces else {})})
    except Exception:
        # The database refused the record: the files we just wrote belong to nothing. Remove only those.
        for k in (key, preview_key):
            try:
                os.unlink(_path(k))
            except FileNotFoundError:
                pass
        raise
    return image


def open_file(image: DentalImage, *, preview: bool):
    """The stored file opened for reading, so a large radiograph is streamed rather than read into memory."""
    key = image.preview_key if preview and image.preview_key else image.storage_key
    try:
        return _path(key).open("rb")
    except FileNotFoundError:
        raise ConflictError("The image file is missing on the server. Tell the system administrator "
                            "(restore it from backup).") from None


def read(image: DentalImage, *, preview: bool) -> bytes:
    key = image.preview_key if preview and image.preview_key else image.storage_key
    try:
        return _path(key).read_bytes()
    except FileNotFoundError:
        raise ConflictError("The image file is missing on the server. Tell the system administrator "
                            "(restore it from backup).") from None


@transaction.atomic
def update_metadata(ctx: ActorContext, image: DentalImage, data: dict, reason: str) -> DentalImage:
    image = DentalImage.objects.select_for_update().get(pk=image.pk)
    if image.status != DentalImage.Status.ACTIVE:
        raise ConflictError("This image was withdrawn.")
    if not reason.strip():
        raise BusinessValidationError("Give the reason for the correction.", fields={"reason": ["Required."]})
    meta = _clean_meta(data, image.patient_id)
    changed = []
    for key, value in meta.items():
        old = getattr(image, key)
        if old != value:
            DentalImageChange.objects.create(image=image, field_name=key, old_value=str(getattr(old, "pk", old) or ""),
                                             new_value=str(getattr(value, "pk", value) or ""), reason=reason.strip()[:255],
                                             changed_by=ctx.user)
            setattr(image, key, value)
            changed.append(key)
    if changed:
        image.save()
        record_event(ctx, action="dental_image.update", object_type="patient", object_id=image.patient_id,
                     details={"image": str(image.pk), "fields": changed, "reason": reason.strip()})
    return image


@transaction.atomic
def withdraw(ctx: ActorContext, image: DentalImage, reason: str) -> DentalImage:
    image = DentalImage.objects.select_for_update().get(pk=image.pk)
    if image.status != DentalImage.Status.ACTIVE:
        raise ConflictError("This image was already withdrawn.")
    if not reason.strip():
        raise BusinessValidationError("Give the reason (e.g. wrong patient).", fields={"reason": ["Required."]})
    image.status, image.withdrawn_at, image.withdrawn_by = DentalImage.Status.WITHDRAWN, timezone.now(), ctx.user
    image.withdrawn_reason = reason.strip()[:255]
    image.save(update_fields=["status", "withdrawn_at", "withdrawn_by", "withdrawn_reason"])
    record_event(ctx, action="dental_image.withdraw", object_type="patient", object_id=image.patient_id,
                 details={"image": str(image.pk), "reason": image.withdrawn_reason})
    return image


def verify_all() -> list[str]:
    """Every image row has its file and the file's SHA-256 matches. Used by verify_dental_images and backups."""
    problems = []
    for image in DentalImage.objects.only("id", "storage_key", "sha256", "preview_key").iterator():
        try:
            data = _path(image.storage_key).read_bytes()
        except FileNotFoundError:
            problems.append(f"{image.pk}: file missing ({image.storage_key})")
            continue
        if hashlib.sha256(data).hexdigest() != image.sha256:
            problems.append(f"{image.pk}: checksum does not match ({image.storage_key})")
        if image.preview_key and not _path(image.preview_key).exists():
            problems.append(f"{image.pk}: preview missing ({image.preview_key})")
    return problems


def storage_usage() -> dict:
    total, files = 0, 0
    base = root()
    if base.exists():
        for path in base.rglob("*"):
            if path.is_file():
                files += 1
                total += path.stat().st_size
    return {"files": files, "bytes": total, "path": str(base)}
