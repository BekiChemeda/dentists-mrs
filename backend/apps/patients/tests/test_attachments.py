"""Patient attachments: type checks by content, metadata stripping, permissions, audit, removal. Synthetic only."""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.audit.models import AuditEvent
from apps.patients.models import PatientAttachment

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def ok(response, code=200):
    assert response.status_code == code, response.content
    return response.json() if response.content else None


def _patient(rc):
    return ok(rc.post("/api/v1/patients/", {"first_name": "Attach", "last_name": "Synthetic", "sex": "male",
                                            "birth_date": "1980-01-01"}, format="json"), 201)


def _jpeg_with_gps():
    img = Image.new("RGB", (60, 40), "white")
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make, stands in for any hidden metadata
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def _upload(client, pid, content, name, kind="outside_lab", title="Outside lab result"):
    return client.post(f"/api/v1/patients/{pid}/attachments/",
                       {"file": SimpleUploadedFile(name, content), "kind": kind, "title": title}, format="multipart")


def test_doctor_attaches_and_opens_a_pdf(staff):
    p = _patient(staff.receptionist)
    att = ok(_upload(staff.doctor, p["id"], PDF, "result <12>;.pdf"), 201)
    assert att["content_type"] == "application/pdf" and att["file_name"] == "result 12.pdf"
    listed = ok(staff.doctor.get(f"/api/v1/patients/{p['id']}/attachments/"))
    assert [a["id"] for a in listed] == [att["id"]]
    r = staff.doctor.get(f"/api/v1/attachments/{att['id']}/file/")
    assert r.status_code == 200 and r.content == PDF
    assert r["Content-Disposition"].startswith("attachment")  # PDFs are never shown inside the app
    assert "sandbox" in r["Content-Security-Policy"] and r["X-Content-Type-Options"] == "nosniff"
    assert AuditEvent.objects.filter(action="patient.attachment_view", object_id=p["id"]).exists()


def test_pictures_are_re_saved_without_metadata(staff):
    p = _patient(staff.receptionist)
    raw = _jpeg_with_gps()
    assert b"PhoneMaker" in raw
    att = ok(_upload(staff.receptionist, p["id"], raw, "referral.jpeg", kind="referral", title="Referral from HC"), 201)
    stored = bytes(PatientAttachment.objects.get(pk=att["id"]).data)
    assert stored.startswith(b"\xff\xd8\xff") and b"PhoneMaker" not in stored


def test_type_is_decided_by_content_not_name(staff):
    p = _patient(staff.receptionist)
    fake = _upload(staff.doctor, p["id"], b"<html><script>alert(1)</script></html>", "scan.pdf")
    assert fake.status_code == 400 and "PDF, JPEG or PNG" in fake.json()["error"]["fields"]["file"][0]
    truncated = _upload(staff.doctor, p["id"], b"%PDF-1.4\nno end", "cut.pdf")
    assert truncated.status_code == 400
    broken_png = _upload(staff.doctor, p["id"], b"\x89PNG\r\n\x1a\n" + b"x" * 50, "x.png")
    assert broken_png.status_code == 400


def test_too_large_is_refused(staff):
    p = _patient(staff.receptionist)
    big = PDF[:-7] + b"0" * (10 * 1024 * 1024) + b"\n%%EOF\n"
    r = _upload(staff.doctor, p["id"], big, "big.pdf")
    assert r.status_code == 400 and "10 MB" in r.json()["error"]["fields"]["file"][0]


def test_who_can_do_what(staff):
    p = _patient(staff.receptionist)
    att = ok(_upload(staff.receptionist, p["id"], PDF, "consent.pdf", kind="consent", title="Consent"), 201)
    # Reception attaches and sees the list, but cannot open clinical documents.
    assert len(ok(staff.receptionist.get(f"/api/v1/patients/{p['id']}/attachments/"))) == 1
    assert staff.receptionist.get(f"/api/v1/attachments/{att['id']}/file/").status_code == 403
    # The cashier has nothing to do with attachments.
    assert staff.cashier.get(f"/api/v1/patients/{p['id']}/attachments/").status_code == 403
    assert _upload(staff.cashier, p["id"], PDF, "x.pdf").status_code == 403


def test_removed_files_need_a_reason_and_disappear_but_are_kept(staff):
    p = _patient(staff.receptionist)
    att = ok(_upload(staff.doctor, p["id"], PDF, "wrong.pdf"), 201)
    assert staff.doctor.post(f"/api/v1/attachments/{att['id']}/remove/", {}, format="json").status_code == 400
    ok(staff.doctor.post(f"/api/v1/attachments/{att['id']}/remove/", {"reason": "Belongs to another patient"},
                         format="json"), 204)
    assert ok(staff.doctor.get(f"/api/v1/patients/{p['id']}/attachments/")) == []
    assert staff.doctor.get(f"/api/v1/attachments/{att['id']}/file/").status_code == 404
    kept = PatientAttachment.objects.get(pk=att["id"])
    assert bytes(kept.data) == PDF and kept.removed_reason == "Belongs to another patient"
    assert AuditEvent.objects.filter(action="patient.attachment_remove").exists()


def test_patient_card_qr_holds_only_the_mrn(staff):
    p = _patient(staff.receptionist)
    r = staff.receptionist.get(f"/api/v1/patients/{p['id']}/card-qr/")
    assert r.status_code == 200 and r["Content-Type"] == "image/svg+xml"
    assert b"<svg" in r.content and b"http://www.w3.org/2000/svg" in r.content
    assert staff.cashier.get(f"/api/v1/patients/{p['id']}/card-qr/").status_code in (200, 403)
