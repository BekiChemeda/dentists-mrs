"""
Read-only report queries. Each report returns columns and rows for a date range.
Dates are clinic-local (Africa/Addis_Ababa).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Callable

from django.db.models import Count, F, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceLine, Payment
from apps.clinical.models import Diagnosis, Encounter
from apps.inventory.models import Item
from apps.inventory.services import batches_with_stock, items_with_stock
from apps.laboratory.models import LabOrderItem
from apps.patients.models import Patient
from apps.pharmacy.models import Dispensation
from apps.scheduling.models import Appointment, Visit


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str = "text"  # text | number | money | date


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    description: str
    permission: str
    columns: tuple[Column, ...]
    run: Callable[..., list[dict]]
    uses_dates: bool = True
    # Reports that can be limited to one department take a `dept` keyword (a Department code). The visit's
    # department is where the patient was sent at triage or by an internal referral.
    by_department: bool = False


def _dt_range(date_from, date_to):
    tz = timezone.get_current_timezone()
    start = datetime.datetime.combine(date_from, datetime.time.min, tzinfo=tz)
    end = datetime.datetime.combine(date_to, datetime.time.max, tzinfo=tz)
    return start, end


def registrations(df, dt):
    start, end = _dt_range(df, dt)
    rows = (Patient.objects.filter(created_at__range=(start, end)).annotate(day=TruncDate("created_at"))
            .values("day").annotate(total=Count("id"), female=Count("id", filter=Q(sex="female")),
                                    male=Count("id", filter=Q(sex="male"))).order_by("day"))
    return [{"date": r["day"], "total": r["total"], "female": r["female"], "male": r["male"]} for r in rows]


def _dept(qs, path: str, dept: str | None):
    return qs.filter(**{path: dept}) if dept else qs


def visits(df, dt, dept=None):
    rows = (_dept(Visit.objects.filter(visit_date__range=(df, dt)), "department", dept).values("visit_date")
            .annotate(total=Count("id"), walk_in=Count("id", filter=Q(kind="walk_in")),
                      appointment=Count("id", filter=Q(kind="appointment")),
                      completed=Count("id", filter=Q(status="completed")),
                      cancelled=Count("id", filter=Q(status="cancelled"))).order_by("visit_date"))
    return [{"date": r["visit_date"], **{k: r[k] for k in ("total", "walk_in", "appointment", "completed",
                                                            "cancelled")}} for r in rows]


def consultations(df, dt, dept=None):
    start, end = _dt_range(df, dt)
    rows = (_dept(Encounter.objects.filter(signed_at__range=(start, end)), "visit__department", dept)
            .values("doctor__first_name", "doctor__last_name").annotate(total=Count("id"),
                                                                        patients=Count("patient", distinct=True))
            .order_by("-total"))
    return [{"doctor": f"{r['doctor__first_name']} {r['doctor__last_name']}", "consultations": r["total"],
             "patients": r["patients"]} for r in rows]


def appointments(df, dt):
    rows = (Appointment.objects.filter(scheduled_date__range=(df, dt)).values("status").annotate(total=Count("id"))
            .order_by("status"))
    labels = dict(Appointment.Status.choices)
    return [{"status": labels.get(r["status"], r["status"]), "total": r["total"]} for r in rows]


def lab_requests(df, dt, dept=None):
    start, end = _dt_range(df, dt)
    rows = (_dept(LabOrderItem.objects.filter(order__created_at__range=(start, end)), "order__visit__department", dept)
            .values("test__code", "test__name")
            .annotate(requested=Count("id"), verified=Count("id", filter=Q(status="verified")),
                      cancelled=Count("id", filter=Q(status="cancelled")),
                      abnormal=Count("id", filter=Q(flag__in=["L", "H", "A", "LL", "HH", "AA"], status="verified")))
            .order_by("-requested"))
    return [{"test": f"{r['test__name']} ({r['test__code']})", "requested": r["requested"], "verified": r["verified"],
             "abnormal": r["abnormal"], "cancelled": r["cancelled"]} for r in rows]


def lab_results(df, dt, dept=None):
    """Verified results per test: flags, critical results and turnaround from request to verification."""
    start, end = _dt_range(df, dt)
    items = (_dept(LabOrderItem.objects.filter(status="verified", verified_at__range=(start, end)),
                   "order__visit__department", dept)
             .select_related("test", "order"))
    groups: dict[str, dict] = {}
    for i in items:
        g = groups.setdefault(i.test.code, {"test": f"{i.test.name} ({i.test.code})", "department": i.test.category,
                                            "results": 0, "normal": 0, "abnormal": 0, "critical": 0,
                                            "unacknowledged": 0, "_tat": []})
        g["results"] += 1
        if i.flag in ("LL", "HH", "AA"):
            g["critical"] += 1
            if not i.critical_acknowledged_at:
                g["unacknowledged"] += 1
        elif i.flag in ("L", "H", "A"):
            g["abnormal"] += 1
        elif i.flag == "N":
            g["normal"] += 1
        g["_tat"].append((i.verified_at - i.order.created_at).total_seconds() / 60)
    out = []
    for g in sorted(groups.values(), key=lambda x: -x["results"]):
        tat = sorted(g.pop("_tat"))
        mid = len(tat) // 2
        g["median_minutes"] = round(tat[mid] if len(tat) % 2 else (tat[mid - 1] + tat[mid]) / 2) if tat else None
        out.append(g)
    return out


def pharmacy_stock(df=None, dt=None):
    today = timezone.localdate()
    out = []
    items = items_with_stock(Item.objects.filter(is_active=True, category=Item.Category.MEDICINE)).order_by("name")
    for item in items:
        next_expiry = (batches_with_stock(item).filter(on_hand__gt=0, expiry_date__gte=today)
                       .order_by("expiry_date").values_list("expiry_date", flat=True).first())
        out.append({"code": item.code, "medicine": str(item), "unit": item.unit, "usable": item.usable,
                    "reorder_level": item.reorder_level, "status": "Low" if item.usable <= item.reorder_level else "OK",
                    "next_expiry": next_expiry})
    return out


def dispensing(df, dt):
    start, end = _dt_range(df, dt)
    rows = (Dispensation.objects.filter(dispensed_at__range=(start, end)).values("item__code", "item__name")
            .annotate(quantity=Sum("quantity"), times=Count("id"), value=Sum(F("quantity") * F("unit_price")))
            .order_by("-quantity"))
    return [{"medicine": f"{r['item__name']} ({r['item__code']})", "times": r["times"], "quantity": r["quantity"],
             "value": r["value"]} for r in rows]


def revenue(df, dt):
    """Money received per day by method, less refunds paid out that day (net = what stays with the clinic)."""
    from apps.billing.models import Refund

    start, end = _dt_range(df, dt)
    pay = Payment.objects.filter(received_at__range=(start, end))
    rows = {r["day"]: r for r in (pay.annotate(day=TruncDate("received_at")).values("day")
                                  .annotate(total=Sum("amount"), receipts=Count("id"),
                                            **{m: Sum("amount", filter=Q(method=m)) for m in Payment.Method.values}))}
    refunds = {r["day"]: r["refunded"] for r in (Refund.objects.filter(refunded_at__range=(start, end))
                                                 .annotate(day=TruncDate("refunded_at")).values("day")
                                                 .annotate(refunded=Sum("amount")))}
    out = []
    for day in sorted(set(rows) | set(refunds)):
        r = rows.get(day, {})
        received = r.get("total") or Decimal("0")
        refunded = refunds.get(day) or Decimal("0")
        out.append({"date": day, "receipts": r.get("receipts", 0), "received": received, "refunded": refunded,
                    "total": received - refunded, **{m: r.get(m) or Decimal("0") for m in Payment.Method.values}})
    return out


def revenue_by_category(df, dt):
    start, end = _dt_range(df, dt)
    rows = (InvoiceLine.objects.filter(is_void=False, invoice__issued_at__range=(start, end))
            .exclude(invoice__status=Invoice.Status.VOID).values("kind")
            .annotate(lines=Count("id"), amount=Sum("line_total")).order_by("-amount"))
    labels = dict(InvoiceLine.Kind.choices)
    return [{"category": labels.get(r["kind"], r["kind"]), "lines": r["lines"], "amount": r["amount"]} for r in rows]


def outstanding(df=None, dt=None):
    today = timezone.localdate()
    out = []
    for inv in (Invoice.objects.select_related("patient")
                .filter(status__in=[Invoice.Status.ISSUED, Invoice.Status.PARTIAL]).order_by("issued_at")):
        out.append({"invoice": inv.number, "patient": inv.patient.full_name, "mrn": inv.patient.mrn,
                    "issued": timezone.localtime(inv.issued_at).date() if inv.issued_at else None,
                    "days_open": (today - timezone.localtime(inv.issued_at).date()).days if inv.issued_at else None,
                    "total": inv.total, "paid": inv.amount_paid, "balance": inv.balance})
    return out


def inventory_valuation(df=None, dt=None):
    out = []
    for b in batches_with_stock().filter(on_hand__gt=0).order_by("item__name", "expiry_date"):
        out.append({"item": str(b.item), "category": b.item.get_category_display(), "batch": b.batch_number,
                    "expiry": b.expiry_date, "on_hand": b.on_hand, "unit_cost": b.unit_cost,
                    "value": (b.on_hand * b.unit_cost).quantize(Decimal("0.01"))})
    return out


def common_diagnoses(df, dt, dept=None):
    start, end = _dt_range(df, dt)
    rows = (_dept(Diagnosis.objects.filter(is_removed=False, encounter__status=Encounter.Status.SIGNED,
                                           encounter__signed_at__range=(start, end)), "encounter__visit__department", dept)
            .values("icd__code", "icd__title", "description")
            .annotate(cases=Count("id"), patients=Count("patient", distinct=True)).order_by("-cases"))
    merged: dict[str, dict] = {}
    for r in rows:
        key = r["icd__code"] or r["description"].strip().lower()
        label = f"{r['icd__code']} {r['icd__title']}" if r["icd__code"] else r["description"]
        entry = merged.setdefault(key, {"diagnosis": label, "cases": 0, "patients": 0})
        entry["cases"] += r["cases"]
        entry["patients"] += r["patients"]
    return sorted(merged.values(), key=lambda e: -e["cases"])[:30]


# Age bands for the OPD morbidity report. These are the clinic's own grouping, chosen to separate infants,
# under-fives, school-age children, adults and older adults. They are NOT verified against the national
# HMIS / ESV-ICD-11 reporting form; check the current MoH form before using this report for official returns.
AGE_BANDS = (("age_lt1", "<1 y", 0, 0), ("age_1_4", "1–4 y", 1, 4), ("age_5_14", "5–14 y", 5, 14),
             ("age_15_29", "15–29 y", 15, 29), ("age_30_64", "30–64 y", 30, 64), ("age_65", "65+ y", 65, 200))


def _age_on(birth: datetime.date | None, day: datetime.date) -> int | None:
    if birth is None:
        return None
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def opd_morbidity(df, dt, dept=None):
    """Diagnoses on signed notes, by sex, new or repeat visit and age band.

    New visit = the patient's first visit to this clinic; repeat = any later visit."""
    start, end = _dt_range(df, dt)
    rows = (_dept(Diagnosis.objects.filter(is_removed=False, encounter__status=Encounter.Status.SIGNED,
                                           encounter__signed_at__range=(start, end)), "encounter__visit__department", dept)
            .select_related("icd", "patient", "encounter__visit"))
    first_visit = dict(Visit.objects.exclude(status=Visit.Status.CANCELLED).values("patient_id")
                       .annotate(first=Min("visit_date")).values_list("patient_id", "first"))
    groups: dict[str, dict] = {}
    for d in rows:
        key = d.icd_id or d.description.strip().lower()
        label = f"{d.icd_id} {d.icd.title}" if d.icd_id else d.description
        g = groups.setdefault(key, {"diagnosis": label, "total": 0, "male": 0, "female": 0, "new": 0, "repeat": 0,
                                    **{b[0]: 0 for b in AGE_BANDS}, "age_unknown": 0})
        visit_date = d.encounter.visit.visit_date
        g["total"] += 1
        g[d.patient.sex if d.patient.sex in ("male", "female") else "female"] += 1
        g["new" if first_visit.get(d.patient_id) == visit_date else "repeat"] += 1
        age = _age_on(d.patient.birth_date, visit_date)
        band = next((b[0] for b in AGE_BANDS if age is not None and b[2] <= age <= b[3]), "age_unknown")
        g[band] += 1
    return sorted(groups.values(), key=lambda g: -g["total"])


def staff_activity(df, dt, dept=None):
    """Work recorded per staff member. A workload view, not a quality measure: counts depend on the role."""
    from apps.accounts.models import User
    from apps.clinical.models import VitalSigns

    start, end = _dt_range(df, dt)
    counts: dict = {}

    def add(qs, by, column):
        for row in qs.values(by).annotate(n=Count("id")):
            if row[by]:
                counts.setdefault(row[by], {})[column] = row["n"]

    add(Patient.objects.filter(created_at__range=(start, end)), "created_by", "registrations")
    add(Visit.objects.filter(created_at__range=(start, end)), "created_by", "check_ins")
    add(VitalSigns.objects.filter(recorded_at__range=(start, end)), "recorded_by", "triages")
    add(Encounter.objects.filter(signed_at__range=(start, end)), "doctor", "consultations")
    add(LabOrderItem.objects.filter(entered_at__range=(start, end)), "entered_by", "lab_results")
    add(Dispensation.objects.filter(dispensed_at__range=(start, end)), "dispensed_by", "dispensed")
    add(Payment.objects.filter(received_at__range=(start, end)), "received_by", "payments")
    users = User.objects.filter(pk__in=counts).select_related("department").prefetch_related("roles")
    if dept:
        users = users.filter(department__code=dept)
    rows = []
    for u in users:
        c = counts[u.pk]
        rows.append({"staff": u.full_name, "department": u.department.name if u.department else "",
                     "roles": ", ".join(r.name for r in u.roles.all()),
                     **{k: c.get(k, 0) for k in ("registrations", "check_ins", "triages", "consultations",
                                                  "lab_results", "dispensed", "payments")}})
    return sorted(rows, key=lambda r: r["staff"])


def department_activity(df, dt, dept=None):
    """Per department: visits, consultations, waiting time to the doctor, and patients referred in and out
    within the clinic. A visit counts for the department it ended in (where triage or a referral sent it)."""
    from statistics import median

    from apps.accounts.models import Department
    from apps.clinical.models import InternalReferral

    names = {d.code: d.name for d in Department.objects.all()}
    visits_qs = _dept(Visit.objects.filter(visit_date__range=(df, dt)).exclude(status=Visit.Status.CANCELLED),
                      "department", dept)
    groups: dict[str, dict] = {}

    def group(code: str) -> dict:
        return groups.setdefault(code, {"department": names.get(code, code) if code else "Not assigned (no triage)",
                                        "visits": 0, "completed": 0, "seen": 0, "consultations": 0,
                                        "referred_in": 0, "referred_out": 0, "_waits": []})

    for v in visits_qs.only("department", "status", "arrived_at", "consultation_started_at"):
        g = group(v.department)
        g["visits"] += 1
        g["completed"] += v.status == Visit.Status.COMPLETED
        if v.consultation_started_at:
            g["seen"] += 1
            g["_waits"].append((v.consultation_started_at - v.arrived_at).total_seconds() / 60)
    start, end = _dt_range(df, dt)
    for row in (_dept(Encounter.objects.filter(signed_at__range=(start, end)), "visit__department", dept)
                .values("visit__department").annotate(n=Count("id"))):
        group(row["visit__department"])["consultations"] = row["n"]
    refs = InternalReferral.objects.filter(created_at__range=(start, end)).exclude(status="cancelled")
    for row in refs.values("to_department").annotate(n=Count("id")):
        if not dept or row["to_department"] == dept:
            group(row["to_department"])["referred_in"] = row["n"]
    for row in refs.values("from_department").annotate(n=Count("id")):
        if not dept or row["from_department"] == dept:
            group(row["from_department"])["referred_out"] = row["n"]
    out = []
    for g in groups.values():
        waits = g.pop("_waits")
        g["median_wait"] = round(median(waits)) if waits else None
        g["longest_wait"] = round(max(waits)) if waits else None
        out.append(g)
    return sorted(out, key=lambda g: -g["visits"])


def _cols(*spec):
    return tuple(Column(*s) for s in spec)


REPORTS: dict[str, Report] = {r.key: r for r in [
    Report("staff_activity", "Staff activity", "Work recorded per staff member: registrations, check-ins, triage, "
           "consultations, lab results, dispensing and payments. A workload view, not a quality measure.",
           "reports.staff",
           _cols(("staff", "Staff"), ("department", "Department"), ("roles", "Roles"),
                 ("registrations", "Registrations", "number"), ("check_ins", "Check-ins", "number"),
                 ("triages", "Triage", "number"), ("consultations", "Consultations", "number"),
                 ("lab_results", "Lab results", "number"), ("dispensed", "Dispensed", "number"),
                 ("payments", "Payments", "number")), staff_activity),
    Report("department_activity", "Department activity", "Visits, consultations, waiting time from arrival to "
           "the doctor, and patients referred between departments, per department.", "reports.operational",
           _cols(("department", "Department"), ("visits", "Visits", "number"), ("completed", "Completed", "number"),
                 ("seen", "Seen by a doctor", "number"), ("consultations", "Signed consultations", "number"),
                 ("median_wait", "Median wait (min)", "number"), ("longest_wait", "Longest wait (min)", "number"),
                 ("referred_in", "Referred in", "number"), ("referred_out", "Referred out", "number")),
           department_activity, by_department=True),
    Report("registrations", "Patient registrations", "New patients registered per day.", "reports.operational",
           _cols(("date", "Date", "date"), ("total", "Total", "number"), ("female", "Female", "number"),
                 ("male", "Male", "number")), registrations),
    Report("visits", "Patient visits", "Visits per day by type and outcome.", "reports.operational",
           _cols(("date", "Date", "date"), ("total", "Total", "number"), ("walk_in", "Walk-in", "number"),
                 ("appointment", "Appointment", "number"), ("completed", "Completed", "number"),
                 ("cancelled", "Cancelled", "number")), visits),
    Report("consultations", "Doctor consultations", "Signed consultations per doctor.", "reports.clinical",
           _cols(("doctor", "Doctor"), ("consultations", "Consultations", "number"),
                 ("patients", "Distinct patients", "number")), consultations),
    Report("appointments", "Appointments", "Appointments by outcome.", "reports.operational",
           _cols(("status", "Status"), ("total", "Appointments", "number")), appointments),
    Report("lab_requests", "Laboratory requests", "Tests requested, verified and abnormal.", "reports.operational",
           _cols(("test", "Test"), ("requested", "Requested", "number"), ("verified", "Verified", "number"),
                 ("abnormal", "Abnormal", "number"), ("cancelled", "Cancelled", "number")), lab_requests),
    Report("lab_results", "Laboratory results", "Verified results by test: normal, abnormal, critical and "
           "median time from request to verification.", "reports.clinical",
           _cols(("test", "Test"), ("department", "Department"), ("results", "Results", "number"),
                 ("normal", "Normal", "number"), ("abnormal", "Abnormal", "number"),
                 ("critical", "Critical", "number"), ("unacknowledged", "Critical not acknowledged", "number"),
                 ("median_minutes", "Median turnaround (min)", "number")), lab_results),
    Report("pharmacy_stock", "Pharmacy stock", "Usable stock of every medicine today.", "reports.operational",
           _cols(("code", "Code"), ("medicine", "Medicine"), ("unit", "Unit"), ("usable", "Usable stock", "number"),
                 ("reorder_level", "Reorder level", "number"), ("status", "Status"), ("next_expiry", "Next expiry",
                                                                                         "date")),
           pharmacy_stock, uses_dates=False),
    Report("dispensing", "Medicines dispensed", "Quantities and value dispensed.", "reports.operational",
           _cols(("medicine", "Medicine"), ("times", "Dispensings", "number"), ("quantity", "Quantity", "number"),
                 ("value", "Value (ETB)", "money")), dispensing),
    Report("revenue", "Revenue by day", "Payments received per day and method.", "reports.financial",
           _cols(("date", "Date", "date"), ("receipts", "Receipts", "number"), ("received", "Received (ETB)", "money"),
                 ("refunded", "Refunded (ETB)", "money"), ("total", "Net (ETB)", "money"),
                 *[(m, label, "money") for m, label in Payment.Method.choices]), revenue),
    Report("revenue_by_category", "Revenue by category", "Invoiced amounts by charge type.", "reports.financial",
           _cols(("category", "Category"), ("lines", "Charges", "number"), ("amount", "Amount (ETB)", "money")),
           revenue_by_category),
    Report("outstanding", "Outstanding payments", "Issued invoices with a balance due.", "reports.financial",
           _cols(("invoice", "Invoice"), ("patient", "Patient"), ("mrn", "MRN"), ("issued", "Issued", "date"),
                 ("days_open", "Days open", "number"), ("total", "Total", "money"), ("paid", "Paid", "money"),
                 ("balance", "Balance", "money")), outstanding, uses_dates=False),
    Report("inventory", "Inventory valuation", "Stock on hand by batch at cost.", "reports.operational",
           _cols(("item", "Item"), ("category", "Category"), ("batch", "Batch"), ("expiry", "Expiry", "date"),
                 ("on_hand", "On hand", "number"), ("unit_cost", "Unit cost", "money"), ("value", "Value (ETB)", "money")),
           inventory_valuation, uses_dates=False),
    Report("opd_morbidity", "OPD morbidity", "Diagnoses on signed notes by sex, new or repeat visit and age "
           "band. Clinic grouping, not the official HMIS form.", "reports.clinical",
           _cols(("diagnosis", "Diagnosis (ICD-10)"), ("total", "Total", "number"), ("male", "Male", "number"),
                 ("female", "Female", "number"), ("new", "New visit", "number"), ("repeat", "Repeat visit", "number"),
                 *[(b[0], b[1], "number") for b in AGE_BANDS], ("age_unknown", "Age unknown", "number")),
           opd_morbidity),
    Report("diagnoses", "Common diagnoses", "Most frequent diagnoses on signed consultations.", "reports.clinical",
           _cols(("diagnosis", "Diagnosis"), ("cases", "Cases", "number"), ("patients", "Patients", "number")),
           common_diagnoses),
]}

# Reports that can be limited to one department (none of the financial ones).
for _key in ("staff_activity", "visits", "consultations", "lab_requests", "lab_results", "opd_morbidity", "diagnoses"):
    REPORTS[_key] = replace(REPORTS[_key], by_department=True)
