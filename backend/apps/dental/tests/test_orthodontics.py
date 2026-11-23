"""Orthodontics: assessment, cases, visits, retention, package instalments and per-visit charges. Synthetic data."""

import datetime
from decimal import Decimal

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.billing.models import InvoiceLine
from apps.dental.models import OrthoCase, OrthoInstalment, Recall

from .conftest import ok

API = "/api/v1/dental"


def _assessment(dental, enc, **extra):
    data = {"molar_right": "class_ii", "molar_left": "class_ii", "canine_right": "class_ii",
            "canine_left": "class_i", "incisor_relationship": "class_ii_div1", "overjet_mm": "7.5",
            "overbite_mm": "4", "crowding_upper": "moderate", "crowding_lower": "mild", "skeletal_pattern": "class_ii",
            "facial_profile": "convex", "oral_hygiene": "good", "problem_list": "Increased overjet, upper crowding",
            "objectives": "Reduce overjet, align arches", **extra}
    return ok(dental.dentist.put(f"{API}/encounters/{enc['id']}/ortho-assessment/", data, format="json"))


def _package(dental, p, **extra):
    data = {"appliance": "fixed_metal", "arches": "both", "expected_months": 18, "billing_mode": "package",
            "package_price": "60000", "deposit": "15000", "instalment_count": 9, "instalment_interval_days": 30,
            **extra}
    return ok(dental.dentist.post(f"{API}/patients/{p['id']}/ortho/cases/", data, format="json"), 201)


def _invoice(dental, p, v=None):
    body = {"patient_id": p["id"], **({"visit_id": v["id"]} if v else {})}
    r = dental.cashier.post("/api/v1/billing/invoices/", body, format="json")
    assert r.status_code in (200, 201), r.content
    return dental.cashier.post(f"/api/v1/billing/invoices/{r.json()['id']}/pull-charges/")


def _visit(dental, case, **data):
    return ok(dental.dentist.post(f"{API}/ortho/cases/{case['id']}/visits/", data, format="json"), 201)


def test_assessment_belongs_to_the_draft_examination(dental, exam):
    p, v, enc = exam()
    a = _assessment(dental, enc)
    assert a["overjet_mm"] == "7.5" and a["molar_right"] == "class_ii" and a["recorded_by"]["full_name"]
    # Version check: a stale save is refused.
    a2 = ok(dental.dentist.put(f"{API}/encounters/{enc['id']}/ortho-assessment/",
                               {"row_version": a["version"], "overjet_mm": "6"}, format="json"))
    r = dental.dentist.put(f"{API}/encounters/{enc['id']}/ortho-assessment/",
                           {"row_version": a["version"], "overjet_mm": "5"}, format="json")
    assert r.status_code == 409 and a2["overjet_mm"] == "6.0"
    # Values out of range or unknown choices are refused.
    assert dental.dentist.put(f"{API}/encounters/{enc['id']}/ortho-assessment/", {"overbite_mm": "-25"},
                              format="json").status_code == 400
    assert dental.dentist.put(f"{API}/encounters/{enc['id']}/ortho-assessment/", {"molar_left": "class_iv"},
                              format="json").status_code == 400
    # Only the examining dentist; assistants cannot; reception cannot even read it.
    assert dental.dentist2.put(f"{API}/encounters/{enc['id']}/ortho-assessment/", {"notes": "x"},
                               format="json").status_code == 403
    assert dental.dental_assistant.put(f"{API}/encounters/{enc['id']}/ortho-assessment/", {"notes": "x"},
                                       format="json").status_code == 403
    assert dental.receptionist.get(f"{API}/encounters/{enc['id']}/ortho-assessment/").status_code == 403
    assert ok(dental.dental_assistant.get(f"{API}/encounters/{enc['id']}/ortho-assessment/"))["id"] == a["id"]
    # Signed examination: the assessment is locked.
    ok(dental.dentist.patch(f"{API}/encounters/{enc['id']}/", {"version": enc["version"],
                                                                "chief_complaint": "Crooked teeth",
                                                                "assessment": "Class II div 1"},
                            format="json"))
    ok(dental.dentist.post(f"{API}/encounters/{enc['id']}/sign/"))
    assert dental.dentist.put(f"{API}/encounters/{enc['id']}/ortho-assessment/", {"notes": "late"},
                              format="json").status_code == 409


def test_package_case_schedule_billing_and_no_double_billing(dental, exam):
    p, v, enc = exam()
    assessment = _assessment(dental, enc)
    case = _package(dental, p, assessment_id=assessment["id"])
    assert case["number"].startswith("OC-") and case["status"] == "planned"
    inst = case["instalments"]
    # Deposit today, then 9 instalments of the remaining 45,000 every 30 days; amounts add up exactly.
    assert inst[0]["label"] == "Deposit" and inst[0]["amount"] == "15000.00"
    assert inst[0]["due_date"] == timezone.localdate().isoformat() and inst[0]["state"] == "due"
    assert len(inst) == 10 and sum(Decimal(i["amount"]) for i in inst) == Decimal("60000.00")
    assert inst[1]["due_date"] == (timezone.localdate() + datetime.timedelta(days=30)).isoformat()
    # One open case per patient.
    r = dental.dentist.post(f"{API}/patients/{p['id']}/ortho/cases/", {"appliance": "aligners",
                            "billing_mode": "per_visit", "per_visit_price": "800"}, format="json")
    assert r.status_code == 409
    # The cashier collects only what is due: the deposit.
    invoice = ok(_invoice(dental, p, v))
    lines = [line for line in invoice["lines"] if "Orthodontic treatment" in line["description"]]
    assert len(lines) == 1 and lines[0]["unit_price"] == "15000.00" and "Deposit" in lines[0]["description"]
    # Pulling again adds nothing; bring the next instalment forward and it is collected, once.
    invoice = ok(_invoice(dental, p, v))
    assert len([line for line in invoice["lines"] if "Orthodontic" in line["description"]]) == 1
    ok(dental.cashier.post(f"{API}/ortho/instalments/{inst[1]['id']}/bring-forward/", {}, format="json"))
    invoice = ok(_invoice(dental, p, v))
    assert len([line for line in invoice["lines"] if "Orthodontic" in line["description"]]) == 2
    ok(dental.cashier.post(f"/api/v1/billing/invoices/{invoice['id']}/issue/"))
    ok(dental.cashier.post(f"/api/v1/billing/invoices/{invoice['id']}/payments/",
                           {"method": "cash", "amount": invoice["total"]}, format="json"), 201)
    case = ok(dental.dentist.get(f"{API}/ortho/cases/{case['id']}/"))
    assert [i["state"] for i in case["instalments"][:3]] == ["paid", "paid", "scheduled"]
    assert case["billing_summary"]["paid"] == "20000.00" and case["billing_summary"]["scheduled"] == "40000.00"
    # A brought-forward instalment that is already invoiced cannot move again.
    assert dental.cashier.post(f"{API}/ortho/instalments/{inst[1]['id']}/bring-forward/", {},
                               format="json").status_code == 409
    # Package visits are not charged; an extra charge is, with its reason.
    ok(dental.dentist.post(f"{API}/ortho/cases/{case['id']}/start/"))
    ov = _visit(dental, case, kind="adjustment", upper_wire="0.014 NiTi", extra_charge="500",
                extra_charge_reason="Replacement bracket 21")["visit"]
    assert ov["charge"] is None
    invoice = ok(_invoice(dental, p, v))
    extra = [line for line in invoice["lines"] if "Replacement bracket" in line["description"]]
    assert len(extra) == 1 and extra[0]["unit_price"] == "500.00"
    assert InvoiceLine.objects.filter(source_type="ortho_instalment", is_void=False).count() == 2


def test_invoice_without_visit_collects_due_instalments(dental, exam):
    p, v, enc = exam()
    _package(dental, p, deposit="5000", package_price="20000", instalment_count=3)
    invoice = ok(_invoice(dental, p))
    assert [line["unit_price"] for line in invoice["lines"]] == ["5000.00"]


def test_per_visit_case_charges_each_visit_unless_reason(dental, exam):
    p, v, enc = exam()
    case = ok(dental.dentist.post(f"{API}/patients/{p['id']}/ortho/cases/", {
        "appliance": "fixed_ceramic", "billing_mode": "per_visit", "per_visit_price": "1200"}, format="json"), 201)
    assert case["instalments"] == [] and case["billing_label"] == "Charged per visit"
    # An adjustment before the braces are fitted is refused, with a hint.
    r = dental.dentist.post(f"{API}/ortho/cases/{case['id']}/visits/", {"kind": "adjustment"}, format="json")
    assert r.status_code == 409 and "fitting" in r.json()["error"]["message"]
    out = _visit(dental, case, kind="bonding", upper_wire="0.012 NiTi", lower_wire="0.012 NiTi",
                 next_interval_weeks=4, encounter_id=enc["id"])
    assert out["case"]["status"] == "active" and out["case"]["started_on"] == timezone.localdate().isoformat()
    assert out["visit"]["charge"] == "1200.00"
    # The next visit lands on the recall list.
    recall = Recall.objects.get(patient_id=p["id"], status="due")
    assert recall.kind == "ortho_adjustment" and recall.due_date == timezone.localdate() + datetime.timedelta(weeks=4)
    # Not charging needs a reason.
    r = dental.dentist.post(f"{API}/ortho/cases/{case['id']}/visits/", {"kind": "emergency",
                            "charge_this_visit": False}, format="json")
    assert r.status_code == 400
    _visit(dental, case, kind="emergency", charge_this_visit=False, no_charge_reason="Bracket came off within a week",
           breakages="21 bracket debonded")
    # The recall for the next adjustment was closed by the visit.
    recall.refresh_from_db()
    assert recall.status == "completed"
    invoice = ok(_invoice(dental, p, v))
    ortho_lines = [line for line in invoice["lines"] if "Orthodontic visit" in line["description"]]
    assert len(ortho_lines) == 1 and ortho_lines[0]["unit_price"] == "1200.00"


def test_debond_retention_and_completion(dental, exam):
    p, v, enc = exam()
    case = _package(dental, p, deposit="0", package_price="30000", instalment_count=2)
    _visit(dental, case, kind="bonding")
    out = _visit(dental, case, kind="debond", notes="Braces removed, good result")
    assert out["case"]["status"] == "retention" and out["case"]["debonded_on"]
    out = _visit(dental, case, kind="retainer_fit", retainer_upper="clear", retainer_lower="bonded",
                 next_interval_weeks=12)
    assert out["case"]["retainer_upper"] == "clear" and out["case"]["retainer_lower"] == "bonded"
    # In retention, adjustments are refused.
    assert dental.dentist.post(f"{API}/ortho/cases/{case['id']}/visits/", {"kind": "adjustment"},
                               format="json").status_code == 409
    done = ok(dental.dentist.post(f"{API}/ortho/cases/{case['id']}/complete/", {}, format="json"))
    assert done["status"] == "completed" and done["closed_on"]
    # A closed case takes no more visits; a new course can be started.
    assert dental.dentist.post(f"{API}/ortho/cases/{case['id']}/visits/", {"kind": "other"},
                               format="json").status_code == 409
    assert OrthoCase.objects.filter(patient_id=p["id"]).count() == 1


def test_discontinue_cancels_instalments_not_yet_invoiced(dental, exam):
    p, v, enc = exam()
    case = _package(dental, p, deposit="10000", package_price="40000", instalment_count=3)
    ok(_invoice(dental, p, v))  # deposit invoiced
    r = dental.dentist.post(f"{API}/ortho/cases/{case['id']}/discontinue/", {}, format="json")
    assert r.status_code == 400
    out = ok(dental.dentist.post(f"{API}/ortho/cases/{case['id']}/discontinue/",
                                 {"reason": "Family moved to another city"}, format="json"))
    states = [i["state"] for i in out["instalments"]]
    assert states[0] == "invoiced" and set(states[1:]) == {"cancelled"}
    assert out["status"] == "discontinued" and "3 instalment(s)" in out["events"][-1]["note"]


def test_change_billing_keeps_what_was_invoiced(dental, exam):
    p, v, enc = exam()
    case = _package(dental, p, deposit="10000", package_price="40000", instalment_count=3)
    ok(_invoice(dental, p, v))  # deposit invoiced
    # A reason is required; the price cannot drop below what was invoiced.
    assert dental.dentist.post(f"{API}/ortho/cases/{case['id']}/billing/", {
        "billing_mode": "package", "package_price": "50000", "instalment_count": 4}, format="json").status_code == 400
    assert dental.dentist.post(f"{API}/ortho/cases/{case['id']}/billing/", {
        "billing_mode": "package", "package_price": "8000", "instalment_count": 4, "reason": "x"},
        format="json").status_code == 400
    out = ok(dental.dentist.post(f"{API}/ortho/cases/{case['id']}/billing/", {
        "billing_mode": "package", "package_price": "50000", "instalment_count": 4,
        "reason": "Lower arch added to the treatment"}, format="json"))
    live = [i for i in out["instalments"] if i["status"] == "scheduled"]
    assert live[0]["state"] == "invoiced" and live[0]["amount"] == "10000.00"
    assert sum(Decimal(i["amount"]) for i in live) == Decimal("50000.00") and len(live) == 5
    assert len([i for i in out["instalments"] if i["status"] == "cancelled"]) == 3
    # Switching to per-visit cancels what is not yet invoiced.
    out = ok(dental.dentist.post(f"{API}/ortho/cases/{case['id']}/billing/", {
        "billing_mode": "per_visit", "per_visit_price": "1500", "reason": "Patient prefers to pay per visit"},
        format="json"))
    assert out["billing_mode"] == "per_visit"
    assert [i["state"] for i in out["instalments"] if i["status"] == "scheduled"] == ["invoiced"]
    assert AuditEvent.objects.filter(action="dental_ortho.billing_change", object_id=case["id"]).count() == 2


def test_void_visit_rules(dental, exam):
    p, v, enc = exam()
    case = ok(dental.dentist.post(f"{API}/patients/{p['id']}/ortho/cases/", {
        "appliance": "fixed_metal", "billing_mode": "per_visit", "per_visit_price": "1000"}, format="json"), 201)
    first = _visit(dental, case, kind="bonding")["visit"]
    second = _visit(dental, case, kind="adjustment")["visit"]
    # Another dentist without amend rights... the dentist role can amend, so use the assistant: refused.
    assert dental.dental_assistant.post(f"{API}/ortho/visits/{second['id']}/void/", {"reason": "x"},
                                        format="json").status_code == 403
    assert dental.dentist.post(f"{API}/ortho/visits/{second['id']}/void/", {}, format="json").status_code == 400
    out = ok(dental.dentist.post(f"{API}/ortho/visits/{second['id']}/void/", {"reason": "Recorded on the wrong case"},
                                 format="json"))
    assert next(x for x in out["visits"] if x["id"] == second["id"])["status"] == "entered_in_error"
    # The voided visit is not billed; once the other one is invoiced it cannot be voided.
    invoice = ok(_invoice(dental, p, v))
    assert len([line for line in invoice["lines"] if "Orthodontic visit" in line["description"]]) == 1
    assert dental.dentist.post(f"{API}/ortho/visits/{first['id']}/void/", {"reason": "x"},
                               format="json").status_code == 409


def test_patient_ortho_view_is_audited_and_scoped(dental, exam):
    p, v, enc = exam()
    _package(dental, p)
    data = ok(dental.dental_assistant.get(f"{API}/patients/{p['id']}/ortho/"))
    assert len(data["cases"]) == 1
    assert AuditEvent.objects.filter(action="dental_ortho.view", object_id=p["id"]).exists()
    assert dental.receptionist.get(f"{API}/patients/{p['id']}/ortho/").status_code == 403
    assert dental.cashier.get(f"{API}/patients/{p['id']}/ortho/").status_code == 403
    # The assistant can read but not create cases or record visits.
    assert dental.dental_assistant.post(f"{API}/patients/{p['id']}/ortho/cases/", {}, format="json").status_code == 403
    listing = ok(dental.dentist.get(f"{API}/ortho/cases/"))
    assert listing["count"] == 1 and listing["results"][0]["patient"]["mrn"] == p["mrn"]


def test_module_off_and_open_work(dental, exam, make_user):
    from apps.core import modules
    from apps.core.context import ActorContext

    p, v, enc = exam()
    case = _package(dental, p, deposit="0", package_price="10000", instalment_count=1)
    admin = make_user("system_admin", username="sys.admin.ortho")
    ctx = ActorContext(user=admin, ip_address="127.0.0.1", user_agent="test")
    work = modules.open_work("orthodontics")
    assert any("still open" in w for w in work) and any("not yet invoiced" in w for w in work)
    ok(dental.dentist.post(f"{API}/ortho/cases/{case['id']}/discontinue/", {"reason": "Test"}, format="json"))
    assert modules.open_work("orthodontics") == []
    modules.set_module(ctx, "orthodontics", False)
    assert dental.dentist.get(f"{API}/patients/{p['id']}/ortho/").status_code in (403, 409)
    assert dental.dentist.post(f"{API}/patients/{p['id']}/ortho/cases/", {}, format="json").status_code == 403
    modules.set_module(ctx, "orthodontics", True)
    assert ok(dental.dentist.get(f"{API}/patients/{p['id']}/ortho/"))["cases"][0]["status"] == "discontinued"


def test_ortho_reports(dental, exam):
    p, v, enc = exam()
    case = _package(dental, p)
    _visit(dental, case, kind="bonding", next_interval_weeks=4)
    rows = ok(dental.dentist.get("/api/v1/reports/dental_ortho_cases/"))["rows"]
    assert rows[0]["case"] == case["number"] and rows[0]["months"] == 0 and rows[0]["next_due"]
    today = timezone.localdate()
    rows = ok(dental.clinic_admin.get(f"/api/v1/reports/dental_ortho_instalments/?date_from={today}&date_to="
                                      f"{today + datetime.timedelta(days=40)}"))["rows"]
    assert [r["instalment"] for r in rows] == ["Deposit", "Instalment 1 of 9"]
    assert dental.dentist.get("/api/v1/reports/dental_ortho_instalments/").status_code == 403
    assert OrthoInstalment.objects.filter(case_id=case["id"]).count() == 10
