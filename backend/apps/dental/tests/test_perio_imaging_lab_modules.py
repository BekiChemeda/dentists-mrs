"""Periodontal chart, imaging, laboratory cases, modules and reports. Synthetic data only."""

import io

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.dental.models import DentalImage

from .conftest import ok, procedure

pytestmark = pytest.mark.django_db


def _sign_exam(dental, enc):
    enc = ok(dental.dentist.get(f"/api/v1/dental/encounters/{enc['id']}/"))
    ok(dental.dentist.patch(f"/api/v1/dental/encounters/{enc['id']}/", {
        "version": enc["version"], "chief_complaint": "Gum review", "assessment": "See perio chart"}, format="json"))
    return ok(dental.dentist.post(f"/api/v1/dental/encounters/{enc['id']}/sign/"))


# --------------------------------------------------------------------------- periodontal
def test_unticked_boxes_on_probed_sites_count_as_no(dental, exam):
    """The screen sends nothing for an unticked box. A probed site without a bleeding tick did not bleed; plaque is
    only counted once it is recorded somewhere in the chart, so a chart without plaque scores shows no plaque %."""
    p, v, enc = exam()
    url = f"/api/v1/dental/encounters/{enc['id']}/perio/"
    sites = {site: {"probing_depth_mm": 3, "gingival_margin_mm": 0} for site in ("MB", "B", "DB", "ML", "L", "DL")}
    sites["MB"]["bleeding"] = True
    out = ok(dental.dental_hygienist.put(url, {"teeth": [{"tooth": 46, "sites": sites},
                                                         {"tooth": 47, "sites": {"B": {"probing_depth_mm": 2}}}]},
                                         format="json"))
    assert out["summary"]["bleeding"] == {"positive": 1, "assessed": 7, "percent": 14.3}
    assert out["summary"]["plaque"] == {"positive": 0, "assessed": 0, "percent": None}
    sites["L"]["plaque"] = True
    out = ok(dental.dental_hygienist.put(url, {"version": out["version"], "teeth": [{"tooth": 46, "sites": sites}]},
                                         format="json"))
    assert out["summary"]["plaque"] == {"positive": 1, "assessed": 6, "percent": 16.7}


def test_perio_entry_validation_and_calculations(dental, exam):
    p, v, enc = exam()
    url = f"/api/v1/dental/encounters/{enc['id']}/perio/"
    body = {"teeth": [
        {"tooth": 16, "mobility": 1, "furcation": 2, "sites": {
            "MB": {"probing_depth_mm": 5, "gingival_margin_mm": 2, "bleeding": True, "plaque": True},
            "B": {"probing_depth_mm": 3, "gingival_margin_mm": 0, "bleeding": False, "plaque": False},
            "DB": {"not_measured": True, "not_measured_reason": "Crown margin"}}},
        {"tooth": 11, "sites": {"B": {"probing_depth_mm": 2, "gingival_margin_mm": -1, "bleeding": False}}},
        {"tooth": 48, "missing": True},
    ]}
    exam_out = ok(dental.dental_hygienist.put(url, body, format="json"))
    t16 = next(t for t in exam_out["teeth"] if t["tooth"] == 16)
    assert t16["sites"]["MB"]["cal_mm"] == 7 and t16["sites"]["B"]["cal_mm"] == 3
    assert t16["sites"]["DB"]["not_measured"] and t16["sites"]["DB"]["probing_depth_mm"] is None
    assert "ML" not in t16["sites"]  # blank stays blank, never zero
    t11 = next(t for t in exam_out["teeth"] if t["tooth"] == 11)
    assert t11["sites"]["B"]["cal_mm"] == 1
    s = exam_out["summary"]
    assert s["bleeding"] == {"positive": 1, "assessed": 3, "percent": 33.3}
    # Plaque is recorded in this chart, so the probed site on 11 with no tick counts as "no plaque".
    assert s["plaque"] == {"positive": 1, "assessed": 3, "percent": 33.3}
    assert s["pd_4_or_more"] == 1 and s["teeth_missing"] == 1
    assert s["sites_not_measured"] == 1
    version = exam_out["version"]
    # Out-of-range values are refused, never changed.
    for bad in ({"tooth": 16, "sites": {"MB": {"probing_depth_mm": 22}}},
                {"tooth": 16, "sites": {"MB": {"probing_depth_mm": 2.5}}},
                {"tooth": 16, "mobility": 4},
                {"tooth": 33, "furcation": 1},  # a canine has no furcation
                {"tooth": 16, "sites": {"XX": {"probing_depth_mm": 2}}},
                {"tooth": 48, "missing": True, "sites": {"B": {"probing_depth_mm": 3}}},
                {"tooth": 16, "sites": {"B": {"not_measured": True, "probing_depth_mm": 3}}},
                {"tooth": 21, "excluded": True}):
        r = dental.dentist.put(url, {"version": version, "teeth": [bad]}, format="json")
        assert r.status_code == 400, bad
    # A stale version is refused (two people entering the same chart).
    assert dental.dentist.put(url, {"version": version - 1, "teeth": []}, format="json").status_code == 409
    # Receptionists cannot enter or read measurements.
    assert dental.receptionist.put(url, body, format="json").status_code == 403
    assert dental.receptionist.get(url).status_code == 403
    # Signed: frozen.
    _sign_exam(dental, enc)
    assert dental.dentist.put(url, {"version": version, "teeth": []}, format="json").status_code == 409


def test_perio_comparison(dental, exam):
    p, v, enc1 = exam()
    ok(dental.dentist.put(f"/api/v1/dental/encounters/{enc1['id']}/perio/", {"teeth": [
        {"tooth": 36, "sites": {"MB": {"probing_depth_mm": 6, "gingival_margin_mm": 1}}}]}, format="json"))
    _sign_exam(dental, enc1)
    ok(dental.receptionist.post(f"/api/v1/visits/{v['id']}/complete/", {"outcome": "completed"}, format="json"))
    from apps.scheduling.models import Visit

    Visit.objects.filter(pk=v["id"]).update(visit_date="2020-01-01")
    v2 = ok(dental.receptionist.post("/api/v1/visits/", {"patient_id": p["id"]}, format="json"), 201)
    enc2 = ok(dental.dentist.post(f"/api/v1/dental/visits/{v2['id']}/encounters/"), 201)
    ok(dental.dentist.put(f"/api/v1/dental/encounters/{enc2['id']}/perio/", {"teeth": [
        {"tooth": 36, "sites": {"MB": {"probing_depth_mm": 4, "gingival_margin_mm": 1}}}]}, format="json"))
    exams = ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/perio/"))
    assert len(exams) == 2
    cmp = ok(dental.dentist.get(f"/api/v1/dental/perio/compare/?a={exams[0]['id']}&b={exams[1]['id']}"))
    row = next(r for r in cmp["sites"] if r["tooth"] == 36 and r["site"] == "MB")
    assert row["pd_before"] == 6 and row["pd_after"] == 4 and row["pd_change"] == -2 and row["cal_change"] == -2


def test_perio_module_off(dental, exam, sysadmin, login):
    _, _, enc = exam()
    admin = login(sysadmin, client=APIClient())
    ok(admin.patch("/api/v1/system/modules/periodontal/", {"enabled": False}, format="json"))
    r = dental.dentist.put(f"/api/v1/dental/encounters/{enc['id']}/perio/", {"teeth": []}, format="json")
    assert r.status_code == 409 and "switched off" in r.json()["error"]["message"]


# --------------------------------------------------------------------------- imaging
def _png(size=(40, 30), mode="L"):
    from PIL import Image

    buf = io.BytesIO()
    Image.new(mode, size, 128).save(buf, format="PNG")
    buf.seek(0)
    buf.name = "radiograph.png"
    return buf


def test_image_upload_view_audit_and_withdraw(dental, patient, settings):
    p = patient()
    url = f"/api/v1/dental/patients/{p['id']}/images/"
    r = dental.imaging_staff.post(url, {"file": _png(), "kind": "periapical", "teeth": "36, 37",
                                        "description": "Pre-operative"}, format="multipart")
    img = ok(r, 201)
    assert img["teeth"] == [36, 37] and img["width"] == 40 and len(img["sha256"]) == 64
    row = DentalImage.objects.get(pk=img["id"])
    stored = settings.DENTAL_IMAGE_ROOT / row.storage_key
    assert stored.exists() and stored.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"  # original bytes kept
    assert oct(stored.stat().st_mode & 0o777) == "0o600"
    # The file is served only through the API, after the permission check, and every view is audited.
    resp = dental.dentist.get(f"/api/v1/dental/images/{img['id']}/file/")
    assert resp.status_code == 200 and resp["Content-Type"] == "image/png" and resp["Cache-Control"] == "no-store"
    assert resp["X-Content-Type-Options"] == "nosniff"
    prev = dental.dentist.get(f"/api/v1/dental/images/{img['id']}/file/?preview=1")
    assert prev["Content-Type"] == "image/jpeg"
    assert AuditEvent.objects.filter(action="dental_image.view").count() == 2
    for who in (dental.receptionist, dental.cashier, dental.dental_technician):
        assert who.get(f"/api/v1/dental/images/{img['id']}/file/").status_code == 403
        assert who.get(url).status_code == 403
    # Corrections keep history and need a reason.
    assert dental.imaging_staff.patch(f"/api/v1/dental/images/{img['id']}/", {"teeth": [46]},
                                      format="json").status_code == 400
    fixed = ok(dental.imaging_staff.patch(f"/api/v1/dental/images/{img['id']}/",
                                          {"teeth": [46], "reason": "Wrong tooth"}, format="json"))
    assert fixed["teeth"] == [46] and fixed["changes"][0]["old"] == "[36, 37]"
    assert dental.dental_assistant.post(f"/api/v1/dental/images/{img['id']}/withdraw/", {"reason": "x"},
                                        format="json").status_code == 403
    ok(dental.imaging_staff.post(f"/api/v1/dental/images/{img['id']}/withdraw/", {"reason": "Wrong patient"},
                                 format="json"))
    assert dental.dentist.get(f"/api/v1/dental/images/{img['id']}/file/").status_code == 404
    assert stored.exists()  # never deleted
    assert not ok(dental.dentist.get(url))
    assert ok(dental.dentist.get(url + "?include_withdrawn=1"))[0]["status"] == "withdrawn"


def test_replacement_upload_withdraws_the_original(dental, patient):
    p = patient()
    url = f"/api/v1/dental/patients/{p['id']}/images/"
    first = ok(dental.dentist.post(url, {"file": _png(), "kind": "bitewing"}, format="multipart"), 201)
    second = ok(dental.dentist.post(url, {"file": _png((50, 50)), "kind": "bitewing", "replaces_id": first["id"]},
                                    format="multipart"), 201)
    assert second["replaces"] == first["id"]
    assert DentalImage.objects.get(pk=first["id"]).status == "withdrawn"


def test_image_content_checks(dental, patient, settings):
    p = patient()
    url = f"/api/v1/dental/patients/{p['id']}/images/"
    fake = io.BytesIO(b"%PDF-1.4 not an image")
    fake.name = "x.png"
    assert dental.dentist.post(url, {"file": fake, "kind": "other"}, format="multipart").status_code == 400
    dicom = io.BytesIO(b"\0" * 128 + b"DICM" + b"\0" * 100)
    dicom.name = "scan.dcm"
    r = dental.dentist.post(url, {"file": dicom, "kind": "panoramic"}, format="multipart")
    assert r.status_code == 400 and "DICOM" in r.json()["error"]["message"]
    assert dental.dentist.post(url, {"file": _png(), "kind": "nonsense"}, format="multipart").status_code == 400
    settings.DENTAL_IMAGE_MAX_BYTES = 10
    assert dental.dentist.post(url, {"file": _png(), "kind": "other"}, format="multipart").status_code == 400
    assert not DentalImage.objects.exists()


def test_16_bit_radiograph_preview(dental, patient):
    from PIL import Image

    p = patient()
    buf = io.BytesIO()
    Image.new("I;16", (64, 64), 30000).save(buf, format="PNG")
    buf.seek(0)
    buf.name = "sensor.png"
    img = ok(dental.dentist.post(f"/api/v1/dental/patients/{p['id']}/images/", {"file": buf, "kind": "periapical"},
                                 format="multipart"), 201)
    assert dental.dentist.get(f"/api/v1/dental/images/{img['id']}/file/?preview=1").status_code == 200


def test_verify_images_command_detects_tampering(dental, patient, settings):
    from django.core.management import CommandError, call_command

    p = patient()
    img = ok(dental.dentist.post(f"/api/v1/dental/patients/{p['id']}/images/", {"file": _png(), "kind": "other"},
                                 format="multipart"), 201)
    call_command("verify_dental_images", verbosity=0)
    path = settings.DENTAL_IMAGE_ROOT / DentalImage.objects.get(pk=img["id"]).storage_key
    path.chmod(0o600)
    path.write_bytes(b"changed")
    with pytest.raises(CommandError):
        call_command("verify_dental_images", verbosity=0)


def test_imaging_module_off(dental, patient, sysadmin, login):
    p = patient()
    admin = login(sysadmin, client=APIClient())
    ok(admin.patch("/api/v1/system/modules/dental_imaging/", {"enabled": False}, format="json"))
    r = dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/images/")
    assert r.status_code == 403 and "switched off" in r.json()["error"]["message"]
    # Examinations and the chart still work.
    ok(dental.dentist.get(f"/api/v1/dental/patients/{p['id']}/chart/"))


# --------------------------------------------------------------------------- laboratory cases
def test_lab_case_flow_and_technician_scope(dental, patient, make_user, login):
    p = patient()
    other_tech = make_user("dental_technician", username="tech.two")
    tech2 = login(other_tech, client=APIClient())
    case = ok(dental.dentist.post(f"/api/v1/dental/patients/{p['id']}/lab-cases/", {
        "case_type": "crown", "teeth": [16], "shade": "A2", "instructions": "Zirconia crown, 1 mm reduction",
        "technician_id": str(dental.users.dental_technician.pk)}, format="json"), 201)
    assert case["number"].startswith("LC-") and case["status"] == "requested"
    # The technician sees name and MRN only, and only their own cases.
    mine = ok(dental.dental_technician.get("/api/v1/dental/lab-cases/"))["results"]
    assert [c["id"] for c in mine] == [case["id"]] and set(mine[0]["patient"]) == {"id", "mrn", "full_name"}
    assert not ok(tech2.get("/api/v1/dental/lab-cases/"))["results"]
    assert tech2.get(f"/api/v1/dental/lab-cases/{case['id']}/").status_code == 404
    assert dental.dental_technician.get(f"/api/v1/dental/patients/{p['id']}/chart/").status_code == 403
    # Moves: technician works, dentist delivers.
    url = f"/api/v1/dental/lab-cases/{case['id']}/move/"
    assert dental.dental_technician.post(url, {"status": "delivered"}, format="json").status_code == 409
    ok(dental.dental_technician.post(url, {"status": "in_progress"}, format="json"))
    ok(dental.dental_technician.post(url, {"status": "ready", "note": "Shade checked"}, format="json"))
    done = ok(dental.dentist.post(url, {"status": "delivered"}, format="json"))
    assert done["status"] == "delivered" and [e["status"] for e in done["events"]] == [
        "requested", "in_progress", "ready", "delivered"]


# --------------------------------------------------------------------------- modules and roles
def test_module_off_refused_with_open_work(dental, patient, sysadmin, login):
    p = patient()
    ok(dental.dentist.post(f"/api/v1/dental/patients/{p['id']}/lab-cases/", {
        "case_type": "denture", "instructions": "Upper complete denture"}, format="json"), 201)
    admin = login(sysadmin, client=APIClient())
    r = admin.patch("/api/v1/system/modules/dental_lab/", {"enabled": False}, format="json")
    assert r.status_code == 409 and r.json()["error"]["open_work"]


def test_dental_defaults_command(db):
    from django.core.management import call_command

    from apps.core.modules import disabled_modules

    call_command("apply_dental_defaults", verbosity=0)
    assert {"triage", "laboratory", "pharmacy"} <= disabled_modules()


def test_default_roles_follow_the_permission_matrix(db):
    from apps.accounts.models import Role

    def perms(code):
        return set(Role.objects.get(code=code).permissions.values_list("code", flat=True))

    assert "dental.write" in perms("dentist") and "dental.write" not in perms("dental_assistant")
    assert "dental.procedure.sign" not in perms("dental_assistant")
    assert perms("dental_technician") == {"dental.labcase.work"}
    assert not any(c.startswith("dental.") for c in perms("system_admin"))
    assert not {"dental.view"} & perms("receptionist") and "dental.recall.manage" in perms("receptionist")
    assert "dental.catalog.manage" in perms("clinic_admin") and "dental.view" not in perms("clinic_admin")


# --------------------------------------------------------------------------- reports
def test_dental_reports_run_and_respect_permissions(dental, exam, catalog_data):
    p, v, enc = exam()
    plan = ok(dental.dentist.post(f"/api/v1/dental/patients/{p['id']}/plans/", {"title": "Plan"}, format="json"), 201)
    ok(dental.dentist.post(f"/api/v1/dental/plans/{plan['id']}/items/", {
        "procedure_id": procedure(catalog_data, "OS-EXT")["id"], "scope": "tooth", "tooth": 38}, format="json"), 201)
    rec = ok(dental.dentist.post(f"/api/v1/dental/encounters/{enc['id']}/procedures/", {
        "procedure_id": procedure(catalog_data, "PR-SCL")["id"]}, format="json"), 201)
    ok(dental.dentist.post(f"/api/v1/dental/procedure-records/{rec['id']}/sign/", {"outcome": "completed"},
                           format="json"))
    keys = {r["key"] for r in ok(dental.clinic_admin.get("/api/v1/reports/"))}
    assert {"dental_plans", "dental_procedures", "dental_follow_ups", "dental_revenue_procedure",
            "dental_estimates", "dental_chairs", "dental_materials"} <= keys
    for key in ("dental_plans", "dental_pending_items", "dental_procedures", "dental_procedure_categories",
                "dental_follow_ups", "dental_imaging", "dental_diagnoses", "dental_revenue_procedure",
                "dental_revenue_dentist", "dental_materials", "dental_estimates", "dental_chairs"):
        ok(dental.clinic_admin.get(f"/api/v1/reports/{key}/"))
    rows = ok(dental.clinic_admin.get("/api/v1/reports/dental_procedures/"))["rows"]
    assert rows and rows[0]["procedure"] == "Scaling and polishing"
    # Financial reports need reports.financial: the dentist does not have it.
    assert dental.dentist.get("/api/v1/reports/dental_revenue_procedure/").status_code == 403
    # CSV export is audited.
    r = dental.clinic_admin.get("/api/v1/reports/dental_pending_items/?export=csv")
    assert r.status_code == 200 and AuditEvent.objects.filter(action="report.export",
                                                              object_id="dental_pending_items").exists()
