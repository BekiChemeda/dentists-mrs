"""Clinic logo upload: who may change it, and that only a clean re-encoded PNG is ever served."""

import io

import pytest
from PIL import Image
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.core.models import ClinicSettings

pytestmark = pytest.mark.django_db


def _png(size=(200, 120), color=(20, 90, 160)) -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    buf.seek(0)
    buf.name = "logo.png"
    return buf


def _jpeg_with_trailing_junk() -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), (200, 30, 30)).save(buf, format="JPEG")
    data = buf.getvalue() + b"<script>alert(1)</script>"
    out = io.BytesIO(data)
    out.name = "logo.jpg"
    return out


def _upload(client, f):
    return client.post("/api/v1/settings/clinic/logo/", {"logo": f}, format="multipart")


def test_system_admin_and_clinic_admin_can_set_logo(sysadmin, staff, login):
    for client in (login(sysadmin, client=APIClient()), staff.clinic_admin):
        r = _upload(client, _png())
        assert r.status_code == 200, r.content
        assert r.json()["has_logo"] is True and r.json()["logo_version"]
    assert AuditEvent.objects.filter(action="settings.logo_update").count() == 2


@pytest.mark.parametrize("role", ["receptionist", "doctor", "cashier", "nurse"])
def test_other_staff_cannot_change_logo(staff, role):
    client = getattr(staff, role)
    assert _upload(client, _png()).status_code == 403
    assert client.delete("/api/v1/settings/clinic/logo/").status_code == 403


def test_logo_is_public_and_re_encoded(staff):
    assert APIClient().get("/api/v1/branding/logo/").status_code == 404
    assert _upload(staff.clinic_admin, _jpeg_with_trailing_junk()).status_code == 200
    r = APIClient().get("/api/v1/branding/logo/")
    assert r.status_code == 200
    assert r["Content-Type"] == "image/png" and r["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in r["Content-Security-Policy"]
    body = r.content
    assert body.startswith(b"\x89PNG") and b"<script>" not in body
    assert Image.open(io.BytesIO(body)).size == (300, 300)
    # Cached copies are revalidated with the ETag.
    again = APIClient().get("/api/v1/branding/logo/", HTTP_IF_NONE_MATCH=r["ETag"])
    assert again.status_code == 304


def test_large_logo_is_shrunk(staff):
    assert _upload(staff.clinic_admin, _png(size=(2000, 1000))).status_code == 200
    img = Image.open(io.BytesIO(bytes(ClinicSettings.get().logo_png)))
    assert max(img.size) == 512 and img.size == (512, 256)


@pytest.mark.parametrize("content,name", [
    (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "logo.svg"),
    (b"GIF89a" + b"\x00" * 50, "logo.gif"),
    (b"not a picture at all", "logo.png"),
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, "broken.png"),
])
def test_bad_files_are_refused(staff, content, name):
    f = io.BytesIO(content)
    f.name = name
    r = _upload(staff.clinic_admin, f)
    assert r.status_code == 400
    assert r.json()["error"]["fields"]["logo"]
    assert not ClinicSettings.get().logo_png


def test_tiny_and_oversized_files_are_refused(staff):
    assert _upload(staff.clinic_admin, _png(size=(10, 10))).status_code == 400
    big = io.BytesIO(b"\x89PNG" + b"0" * (2 * 1024 * 1024 + 10))
    big.name = "big.png"
    assert _upload(staff.clinic_admin, big).status_code == 400


def test_missing_file_is_a_clear_error(staff):
    r = staff.clinic_admin.post("/api/v1/settings/clinic/logo/", {}, format="multipart")
    assert r.status_code == 400 and "Choose a picture" in r.json()["error"]["fields"]["logo"][0]


def test_remove_logo(staff):
    _upload(staff.clinic_admin, _png())
    assert staff.clinic_admin.delete("/api/v1/settings/clinic/logo/").status_code == 204
    assert APIClient().get("/api/v1/branding/logo/").status_code == 404
    settings_body = staff.receptionist.get("/api/v1/settings/clinic/").json()
    assert settings_body["has_logo"] is False and settings_body["logo_version"] is None
    assert AuditEvent.objects.filter(action="settings.logo_remove").exists()


def test_logo_change_does_not_conflict_with_open_settings_form(staff):
    """Changing the logo must not make someone's open clinic-settings form stale."""
    admin = staff.clinic_admin
    v = admin.get("/api/v1/settings/clinic/").json()["row_version"]
    _upload(admin, _png())
    r = admin.patch("/api/v1/settings/clinic/", {"phone": "0115550000", "row_version": v}, format="json")
    assert r.status_code == 200
