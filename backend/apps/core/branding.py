"""
Clinic logo.

An uploaded picture is never stored or served as it arrived. The server decodes it, checks it, shrinks
it and writes a fresh PNG, which drops anything hidden in the original file (scripts in an SVG, extra
data appended to an image, camera metadata). Only PNG and JPEG are accepted; SVG is refused because it
can carry script.

Who may change it: holders of branding.manage (built-in: system administrator and clinic
administrator). Anyone may view it, including the sign-in page, since a clinic's logo is not secret.
"""

import hashlib
import io

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .api import PermissionedView
from .models import ClinicSettings

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_SOURCE_PIXELS = 25_000_000  # refuse "decompression bombs" before decoding them
MAX_SIDE = 512
MIN_SIDE = 32
ALLOWED_FORMATS = {"PNG", "JPEG"}


def process_logo(raw: bytes) -> bytes:
    """Return a clean PNG, or raise serializers.ValidationError with a message for the user."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if len(raw) > MAX_UPLOAD_BYTES:
        raise serializers.ValidationError({"logo": ["The picture is larger than 2 MB. Use a smaller file."]})
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            width, height = probe.size
            if fmt not in ALLOWED_FORMATS:
                raise serializers.ValidationError({"logo": ["Use a PNG or JPEG picture."]})
            if width * height > MAX_SOURCE_PIXELS:
                raise serializers.ValidationError({"logo": ["The picture is too large in pixels. Use one under 5000 x 5000."]})
            if min(width, height) < MIN_SIDE:
                raise serializers.ValidationError({"logo": [f"The picture is too small. Use one at least {MIN_SIDE} pixels on each side."]})
            probe.verify()  # catches truncated and corrupted files
        with Image.open(io.BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGBA")
            img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="PNG", optimize=True)  # no metadata copied
            return out.getvalue()
    except serializers.ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise serializers.ValidationError({"logo": ["This file is not a picture that can be read. Use a PNG or JPEG."]}) from exc


def logo_version(obj: ClinicSettings) -> str | None:
    return obj.logo_updated_at.strftime("%Y%m%d%H%M%S%f") if obj.logo_png and obj.logo_updated_at else None


class ClinicLogoView(APIView):
    """Public read of the logo. 404 when the clinic has none."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        obj = ClinicSettings.get()
        if not obj.logo_png:
            return Response({"detail": "No logo."}, status=status.HTTP_404_NOT_FOUND)
        data = bytes(obj.logo_png)
        etag = '"' + hashlib.sha256(data).hexdigest()[:32] + '"'
        if request.headers.get("If-None-Match") == etag:
            resp = HttpResponse(status=304)
        else:
            resp = HttpResponse(data, content_type="image/png")
        resp["ETag"] = etag
        resp["Cache-Control"] = "public, max-age=300"
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Content-Security-Policy"] = "default-src 'none'; sandbox"
        resp["Content-Disposition"] = 'inline; filename="clinic-logo.png"'
        return resp


class ClinicLogoManageView(PermissionedView):
    """Upload (POST, multipart field "logo") or remove (DELETE) the logo."""

    # JSON is accepted only so a malformed request gets the normal CSRF/validation answer, not 415.
    parser_classes = [MultiPartParser, JSONParser]
    required_permissions = {"POST": ("branding.manage",), "DELETE": ("branding.manage",)}

    def post(self, request):
        from apps.audit.services import record_event

        upload = request.FILES.get("logo")
        if upload is None:
            raise serializers.ValidationError({"logo": ["Choose a picture to upload."]})
        if upload.size > MAX_UPLOAD_BYTES:
            raise serializers.ValidationError({"logo": ["The picture is larger than 2 MB. Use a smaller file."]})
        png = process_logo(upload.read())
        with transaction.atomic():
            obj = ClinicSettings.objects.select_for_update().get_or_create(pk=1)[0]
            replaced = bool(obj.logo_png)
            obj.logo_png = png
            obj.logo_updated_at = timezone.now()
            obj.save(update_fields=["logo_png", "logo_updated_at", "updated_at"])
            record_event(self.ctx(), action="settings.logo_update", object_type="clinic_settings", object_id=1,
                         details={"replaced": replaced, "stored_bytes": len(png),
                                  "sha256": hashlib.sha256(png).hexdigest()})
        return Response({"has_logo": True, "logo_version": logo_version(obj)}, status=status.HTTP_200_OK)

    def delete(self, request):
        from apps.audit.services import record_event

        with transaction.atomic():
            obj = ClinicSettings.objects.select_for_update().get_or_create(pk=1)[0]
            if obj.logo_png:
                obj.logo_png = None
                obj.logo_updated_at = timezone.now()
                obj.save(update_fields=["logo_png", "logo_updated_at", "updated_at"])
                record_event(self.ctx(), action="settings.logo_remove", object_type="clinic_settings", object_id=1,
                             details={})
        return Response(status=status.HTTP_204_NO_CONTENT)
