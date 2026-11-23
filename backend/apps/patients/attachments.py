"""
Patient attachments: checks on upload and the API.

Accepted: PDF, JPEG and PNG, up to 10 MB (nginx refuses larger bodies too). The type is decided from
the file's content, never from its name or the browser's claim. Pictures are decoded and saved again,
which drops hidden metadata such as GPS location and anything appended to the file. PDFs are kept as
uploaded and are only ever offered as a download, never shown inside the application's pages.
Viewing an attachment is recorded in the audit log like opening the record.
"""
from __future__ import annotations

import hashlib
import io
import re

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.audit.services import record_event
from apps.core.api import PermissionedView, validated
from apps.core.permissions import AnyOf

from .models import Patient, PatientAttachment

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
VIEW = AnyOf(("clinical.view",))
ADD = AnyOf(("clinical.write", "patients.update"))


def _clean_name(name: str, ext: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "", (name or "").rsplit(".", 1)[0]).strip(" .")[:80] or "document"
    return f"{stem}.{ext}"


def check_file(raw: bytes, name: str) -> tuple[bytes, str, str]:
    """Return (bytes to store, content type, file name) or raise a validation error the user can act on."""
    if not raw:
        raise serializers.ValidationError({"file": ["The file is empty."]})
    if len(raw) > MAX_BYTES:
        raise serializers.ValidationError({"file": ["The file is larger than 10 MB. Scan at a lower resolution."]})
    if raw.startswith(b"%PDF-"):
        if b"%%EOF" not in raw[-2048:]:
            raise serializers.ValidationError({"file": ["This PDF is incomplete or damaged. Scan or save it again."]})
        return raw, "application/pdf", _clean_name(name, "pdf")
    if raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"\x89PNG\r\n\x1a\n"):
        from PIL import Image, ImageOps, UnidentifiedImageError

        try:
            with Image.open(io.BytesIO(raw)) as probe:
                if probe.format not in ("JPEG", "PNG"):
                    raise serializers.ValidationError({"file": ["Use a PDF, JPEG or PNG file."]})
                if probe.size[0] * probe.size[1] > MAX_PIXELS:
                    raise serializers.ValidationError({"file": ["The picture is too large in pixels. Use a smaller scan."]})
                probe.verify()
            with Image.open(io.BytesIO(raw)) as img:
                img = ImageOps.exif_transpose(img)
                out = io.BytesIO()
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                img.save(out, format="JPEG", quality=88, optimize=True)  # no metadata copied
                return out.getvalue(), "image/jpeg", _clean_name(name, "jpg")
        except serializers.ValidationError:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise serializers.ValidationError({"file": ["This picture cannot be read. Scan or photograph it again."]}) from exc
    raise serializers.ValidationError({"file": ["Use a PDF, JPEG or PNG file."]})


class AttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.full_name", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = PatientAttachment
        fields = ["id", "kind", "kind_label", "title", "document_date", "file_name", "content_type", "size_bytes",
                  "uploaded_by_name", "created_at"]


class AttachmentInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=PatientAttachment.Kind.choices)
    title = serializers.CharField(max_length=120)
    document_date = serializers.DateField(required=False, allow_null=True)

    def validate_document_date(self, value):
        if value and value > timezone.localdate():
            raise serializers.ValidationError("The document date cannot be in the future.")
        return value


class PatientAttachmentsView(PermissionedView):
    """GET: the patient's attachments (not removed). POST (multipart: file, kind, title, document_date)."""

    parser_classes = [MultiPartParser, JSONParser]
    # Reception can see what it attached (titles only); opening a file needs clinical.view.
    required_permissions = {"GET": AnyOf(("clinical.view", "patients.update")), "POST": ADD}

    def get(self, request, patient_id):
        patient = get_object_or_404(Patient, pk=patient_id)
        rows = (PatientAttachment.objects.filter(patient=patient, removed_at__isnull=True)
                .select_related("uploaded_by").defer("data"))
        return Response(AttachmentSerializer(rows, many=True).data)

    def post(self, request, patient_id):
        patient = get_object_or_404(Patient, pk=patient_id, merged_into__isnull=True)
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": ["Choose a file to attach."]})
        if upload.size > MAX_BYTES:
            raise serializers.ValidationError({"file": ["The file is larger than 10 MB. Scan at a lower resolution."]})
        data = validated(AttachmentInput, request.data)
        stored, content_type, file_name = check_file(upload.read(), upload.name)
        digest = hashlib.sha256(stored).hexdigest()
        with transaction.atomic():
            att = PatientAttachment.objects.create(
                patient=patient, kind=data["kind"], title=data["title"].strip(), document_date=data.get("document_date"),
                file_name=file_name, content_type=content_type, size_bytes=len(stored), sha256=digest, data=stored,
                uploaded_by=request.user)
            record_event(self.ctx(), action="patient.attachment_add", object_type="patient", object_id=patient.pk,
                         details={"attachment": str(att.pk), "kind": att.kind, "bytes": len(stored), "sha256": digest})
        return Response(AttachmentSerializer(att).data, status=status.HTTP_201_CREATED)


class AttachmentFileView(PermissionedView):
    """The file itself. Pictures may be shown inline for preview; PDFs are always a download."""

    required_permissions = {"GET": VIEW}

    def get(self, request, pk):
        att = get_object_or_404(PatientAttachment, pk=pk, removed_at__isnull=True)
        record_event(self.ctx(), action="patient.attachment_view", object_type="patient", object_id=att.patient_id,
                     details={"attachment": str(att.pk)})
        resp = HttpResponse(bytes(att.data), content_type=att.content_type)
        inline = att.content_type.startswith("image/") and request.query_params.get("download") != "1"
        resp["Content-Disposition"] = f'{"inline" if inline else "attachment"}; filename="{att.file_name}"'
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
        resp["Cache-Control"] = "no-store"
        return resp


class AttachmentRemoveInput(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class AttachmentRemoveView(PermissionedView):
    """Mark an attachment removed (wrong patient, unreadable scan). The file is kept, but no longer shown."""

    required_permissions = {"POST": ADD}

    def post(self, request, pk):
        data = validated(AttachmentRemoveInput, request.data)
        with transaction.atomic():
            att = get_object_or_404(PatientAttachment.objects.select_for_update(), pk=pk, removed_at__isnull=True)
            att.removed_at, att.removed_by, att.removed_reason = timezone.now(), request.user, data["reason"].strip()
            att.save(update_fields=["removed_at", "removed_by", "removed_reason"])
            record_event(self.ctx(), action="patient.attachment_remove", object_type="patient", object_id=att.patient_id,
                         details={"attachment": str(att.pk), "reason": att.removed_reason})
        return Response(status=status.HTTP_204_NO_CONTENT)
