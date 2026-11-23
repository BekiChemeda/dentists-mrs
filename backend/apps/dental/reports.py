"""
Dental reports, registered into the shared report registry (apps.reports.reports.REPORTS).

Read-only queries over clinic-local date ranges. They reuse the shared permissions: operational, clinical and
financial reports, and CSV export (audited by the report view). Patient details only where the worklist needs them.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceLine
from apps.inventory.models import StockMovement
from apps.reports.reports import Column, Report, _dt_range
from apps.scheduling.models import Appointment

from .models import (
    DentalDiagnosis, DentalImage, ProcedureRecord, Recall, TreatmentPlan, TreatmentPlanItem,
)

ZERO = Decimal("0.00")
LIVE_INVOICES = (Invoice.Status.ISSUED, Invoice.Status.PARTIAL, Invoice.Status.PAID)


def plans_by_status(df, dt):
    start, end = _dt_range(df, dt)
    from .services.plans import estimated_total

    rows: dict[str, dict] = {}
    for plan in TreatmentPlan.objects.filter(created_at__range=(start, end)).prefetch_related("items"):
        r = rows.setdefault(plan.status, {"status": plan.get_status_display(), "plans": 0, "estimated": ZERO})
        r["plans"] += 1
        r["estimated"] += estimated_total(plan)
    return sorted(rows.values(), key=lambda r: -r["plans"])


def pending_items(df=None, dt=None):
    qs = (TreatmentPlanItem.objects.filter(status__in=["accepted", "in_progress", "deferred", "proposed"])
          .exclude(plan__status__in=TreatmentPlan.CLOSED)
          .select_related("plan__patient", "procedure").order_by("plan__patient__last_name", "plan__number", "sequence"))
    today = timezone.localdate()
    return [{"patient": i.plan.patient.full_name, "mrn": i.plan.patient.mrn, "plan": i.plan.number,
             "procedure": i.procedure.name, "where": i.location_label, "status": i.get_status_display(),
             "priority": i.get_priority_display(), "fee": i.estimated_fee,
             "waiting_days": (today - timezone.localtime(i.decision_at or i.created_at).date()).days}
            for i in qs[:2000]]


def procedures_done(df, dt):
    start, end = _dt_range(df, dt)
    rows = (ProcedureRecord.objects.filter(signed_at__range=(start, end)).exclude(status="not_performed")
            .values("procedure__name", "procedure__category", "performed_by__first_name", "performed_by__last_name")
            .annotate(completed=Count("id", filter=Q(status="completed")),
                      sessions=Count("id", filter=Q(status="session_completed")), value=Sum("price"))
            .order_by("procedure__category", "procedure__name"))
    return [{"procedure": r["procedure__name"], "category": r["procedure__category"],
             "clinician": f"{r['performed_by__first_name']} {r['performed_by__last_name']}".strip(),
             "completed": r["completed"], "sessions": r["sessions"], "value": r["value"] or ZERO} for r in rows]


def procedures_by_category(df, dt):
    start, end = _dt_range(df, dt)
    rows = (ProcedureRecord.objects.filter(signed_at__range=(start, end)).exclude(status="not_performed")
            .values("procedure__category").annotate(records=Count("id"), patients=Count("patient", distinct=True))
            .order_by("-records"))
    from .models import DentalProcedure

    labels = dict(DentalProcedure.Category.choices)
    return [{"category": labels.get(r["procedure__category"], r["procedure__category"]), "records": r["records"],
             "patients": r["patients"]} for r in rows]


def follow_ups_due(df, dt):
    qs = (Recall.objects.filter(due_date__range=(df, dt), status__in=Recall.OPEN)
          .select_related("patient").order_by("due_date"))
    return [{"due": r.due_date, "patient": r.patient.full_name, "mrn": r.patient.mrn, "phone": r.patient.phone,
             "kind": r.get_kind_display(), "status": r.get_status_display(), "attempts": r.contacts.count()}
            for r in qs[:2000]]


def imaging_workload(df, dt):
    start, end = _dt_range(df, dt)
    labels = dict(DentalImage.Kind.choices)
    rows = (DentalImage.objects.filter(uploaded_at__range=(start, end)).values("kind")
            .annotate(images=Count("id"), patients=Count("patient", distinct=True),
                      withdrawn=Count("id", filter=Q(status="withdrawn"))).order_by("-images"))
    return [{"kind": labels.get(r["kind"], r["kind"]), "images": r["images"], "patients": r["patients"],
             "withdrawn": r["withdrawn"]} for r in rows]


def common_dental_diagnoses(df, dt):
    start, end = _dt_range(df, dt)
    rows = (DentalDiagnosis.objects.filter(is_removed=False, encounter__status="signed",
                                           encounter__signed_at__range=(start, end))
            .values("code", "term_text").annotate(cases=Count("id"), patients=Count("patient", distinct=True))
            .order_by("-cases", "code"))
    return [{"diagnosis": f"{r['code']} {r['term_text']}", "cases": r["cases"], "patients": r["patients"]}
            for r in rows[:200]]


def _dental_lines(df, dt):
    start, end = _dt_range(df, dt)
    return InvoiceLine.objects.filter(source_type="dental_procedure", is_void=False,
                                      invoice__status__in=LIVE_INVOICES, invoice__issued_at__range=(start, end))


def revenue_by_procedure(df, dt):
    records = {str(r.pk): r for r in ProcedureRecord.objects.filter(
        pk__in=list(_dental_lines(df, dt).values_list("source_id", flat=True))).select_related("procedure")}
    rows: dict[str, dict] = {}
    for line in _dental_lines(df, dt):
        rec = records.get(line.source_id)
        name = rec.procedure.name if rec else line.description
        r = rows.setdefault(name, {"procedure": name, "charges": 0, "amount": ZERO})
        r["charges"] += 1
        r["amount"] += line.line_total
    return sorted(rows.values(), key=lambda r: -r["amount"])


def revenue_by_dentist(df, dt):
    records = {str(r.pk): r for r in ProcedureRecord.objects.filter(
        pk__in=list(_dental_lines(df, dt).values_list("source_id", flat=True))).select_related("performed_by")}
    rows: dict[str, dict] = {}
    for line in _dental_lines(df, dt):
        rec = records.get(line.source_id)
        who = rec.performed_by.full_name if rec else "Unknown"
        r = rows.setdefault(who, {"clinician": who, "charges": 0, "amount": ZERO})
        r["charges"] += 1
        r["amount"] += line.line_total
    return sorted(rows.values(), key=lambda r: -r["amount"])


def material_usage(df, dt):
    start, end = _dt_range(df, dt)
    moves = StockMovement.objects.filter(reference_type="dental_procedure", created_at__range=(start, end))
    names = dict(ProcedureRecord.objects.filter(pk__in=list(moves.values_list("reference_id", flat=True)))
                 .values_list("id", "procedure__name"))
    names = {str(k): v for k, v in names.items()}
    rows: dict[tuple, dict] = {}
    for m in moves.select_related("item"):
        key = (names.get(m.reference_id, "?"), m.item.name)
        r = rows.setdefault(key, {"procedure": key[0], "item": key[1], "unit": m.item.unit, "quantity": Decimal(0),
                                  "records": set()})
        r["quantity"] += -m.quantity
        r["records"].add(m.reference_id)
    out = []
    for r in rows.values():
        r["records"] = len(r["records"])
        out.append(r)
    return sorted(out, key=lambda r: (r["procedure"], r["item"]))


def estimates_vs_invoiced(df, dt):
    """For plan items completed in the range: the estimate agreed with the patient vs what was invoiced for the
    procedure records that carried them out (issued, part-paid or paid invoices). Not a profit figure."""
    start, end = _dt_range(df, dt)
    items = (TreatmentPlanItem.objects.filter(status="completed",
                                              procedures__status="completed", procedures__signed_at__range=(start, end))
             .select_related("plan__patient", "procedure").distinct())
    out = []
    for item in items:
        rec_ids = [str(pk) for pk in item.procedures.values_list("pk", flat=True)]
        invoiced = (InvoiceLine.objects.filter(source_type="dental_procedure", source_id__in=rec_ids, is_void=False,
                                               invoice__status__in=LIVE_INVOICES)
                    .aggregate(t=Sum("line_total"))["t"] or ZERO)
        out.append({"plan": item.plan.number, "patient": item.plan.patient.full_name, "procedure": item.procedure.name,
                    "where": item.location_label, "estimated": item.estimated_fee, "invoiced": invoiced,
                    "difference": invoiced - item.estimated_fee})
    return out


def chair_use(df, dt):
    rows = (Appointment.objects.filter(scheduled_date__range=(df, dt), room__isnull=False)
            .exclude(status__in=[Appointment.Status.CANCELLED])
            .values("room__name").annotate(appointments=Count("id"), minutes=Sum("duration_minutes"),
                                           no_shows=Count("id", filter=Q(status="no_show")))
            .order_by("room__name"))
    return [{"chair": r["room__name"], "appointments": r["appointments"], "booked_hours": round((r["minutes"] or 0) / 60, 1),
             "no_shows": r["no_shows"]} for r in rows]



def ortho_cases(df=None, dt=None):
    """Open orthodontic cases: how long in treatment, when last seen, when the next visit is due."""
    from .models import OrthoCase, OrthoVisit

    today = timezone.localdate()
    next_due = {r.patient_id: r.due_date for r in Recall.objects.filter(kind=Recall.Kind.ORTHO_ADJUSTMENT,
                                                                        status__in=Recall.OPEN).order_by("-due_date")}
    rows = []
    for case in (OrthoCase.objects.filter(status__in=OrthoCase.OPEN).select_related("patient", "orthodontist")
                 .order_by("patient__last_name")):
        last = (OrthoVisit.objects.filter(case=case, status="recorded").select_related("visit")
                .order_by("-created_at").first())
        months = None
        if case.started_on:
            months = (today.year - case.started_on.year) * 12 + today.month - case.started_on.month
        rows.append({"case": case.number, "patient": case.patient.full_name, "mrn": case.patient.mrn,
                     "phone": case.patient.phone, "status": case.get_status_display(),
                     "appliance": case.get_appliance_display(), "orthodontist": case.orthodontist.full_name,
                     "started": case.started_on, "months": months, "expected": case.expected_months,
                     "last_visit": last.visit.visit_date if last else None,
                     "next_due": next_due.get(case.patient_id), "billing": case.get_billing_mode_display()})
    return rows


def ortho_instalments(df, dt):
    """Package instalments due in the period, and earlier ones still not invoiced, with their invoice state."""
    from .models import OrthoInstalment
    from .services.ortho import instalment_lines, instalment_state

    today = timezone.localdate()
    qs = (OrthoInstalment.objects.filter(status="scheduled").filter(Q(due_date__range=(df, dt)) | Q(due_date__lt=df))
          .select_related("case__patient").order_by("due_date", "case__number", "sequence"))
    items = list(qs[:5000])
    lines = instalment_lines(items)
    labels = {"scheduled": "Scheduled", "due": "Due today", "overdue": "Overdue, not invoiced",
              "invoiced": "Invoiced, unpaid", "part_paid": "Part paid", "paid": "Paid"}
    rows = []
    for inst in items:
        line = lines.get(str(inst.pk))
        state = instalment_state(inst, line, today)
        if inst.due_date < df and state == "paid":
            continue  # earlier instalments are listed only while something is still owed
        rows.append({"due": inst.due_date, "case": inst.case.number, "patient": inst.case.patient.full_name,
                     "mrn": inst.case.patient.mrn, "phone": inst.case.patient.phone, "instalment": inst.label,
                     "amount": inst.amount, "state": labels.get(state, state),
                     "invoice": line.invoice.number if line else ""})
    return rows

def _c(*spec):
    return tuple(Column(*s) for s in spec)


DENTAL_REPORTS = [
    Report("dental_plans", "Treatment plans by status", "Plans created in the period and their current status, "
           "with the estimate of what was agreed (an estimate, not an invoice).", "reports.clinical",
           _c(("status", "Status"), ("plans", "Plans", "number"), ("estimated", "Estimated (ETB)", "money")),
           plans_by_status),
    Report("dental_pending_items", "Pending treatment", "Plan items accepted, in progress, deferred or awaiting the "
           "patient's decision, on open plans.", "reports.clinical",
           _c(("patient", "Patient"), ("mrn", "MRN"), ("plan", "Plan"), ("procedure", "Procedure"), ("where", "Tooth"),
              ("status", "Status"), ("priority", "Priority"), ("fee", "Estimate (ETB)", "money"),
              ("waiting_days", "Days waiting", "number")), pending_items, uses_dates=False),
    Report("dental_procedures", "Procedures performed", "Signed procedure records by procedure and clinician "
           "(completed, and sessions of multi-visit treatment).", "reports.clinical",
           _c(("procedure", "Procedure"), ("category", "Category"), ("clinician", "Clinician"),
              ("completed", "Completed", "number"), ("sessions", "Sessions", "number"),
              ("value", "Value at catalogue price (ETB)", "money")), procedures_done),
    Report("dental_procedure_categories", "Procedures by category", "Signed procedure records per category.",
           "reports.clinical", _c(("category", "Category"), ("records", "Records", "number"),
                                  ("patients", "Patients", "number")), procedures_by_category),
    Report("dental_follow_ups", "Follow-ups and recalls due", "Open recalls due in the period, with contact "
           "attempts.", "reports.operational",
           _c(("due", "Due", "date"), ("patient", "Patient"), ("mrn", "MRN"), ("phone", "Phone"), ("kind", "Follow-up"),
              ("status", "Status"), ("attempts", "Contact attempts", "number")), follow_ups_due),
    Report("dental_imaging", "Imaging workload", "Images uploaded by type.", "reports.operational",
           _c(("kind", "Type"), ("images", "Images", "number"), ("patients", "Patients", "number"),
              ("withdrawn", "Withdrawn", "number")), imaging_workload),
    Report("dental_diagnoses", "Common dental diagnoses", "Diagnoses on signed dental examinations.",
           "reports.clinical", _c(("diagnosis", "Diagnosis"), ("cases", "Cases", "number"),
                                  ("patients", "Patients", "number")), common_dental_diagnoses),
    Report("dental_revenue_procedure", "Dental revenue by procedure", "Invoiced procedure charges (issued, "
           "part-paid and paid invoices) by procedure.", "reports.financial",
           _c(("procedure", "Procedure"), ("charges", "Charges", "number"), ("amount", "Amount (ETB)", "money")),
           revenue_by_procedure),
    Report("dental_revenue_dentist", "Dental revenue by clinician", "Invoiced procedure charges by the clinician "
           "who performed them.", "reports.financial",
           _c(("clinician", "Clinician"), ("charges", "Charges", "number"), ("amount", "Amount (ETB)", "money")),
           revenue_by_dentist),
    Report("dental_materials", "Materials used by procedure", "Stock deducted when procedure records were signed.",
           "reports.operational",
           _c(("procedure", "Procedure"), ("item", "Item"), ("unit", "Unit"), ("quantity", "Quantity", "number"),
              ("records", "Procedure records", "number")), material_usage),
    Report("dental_estimates", "Estimates compared with invoices", "Plan items completed in the period: the estimate "
           "agreed with the patient and the amount invoiced for the work. A difference is not an error in itself.",
           "reports.financial",
           _c(("plan", "Plan"), ("patient", "Patient"), ("procedure", "Procedure"), ("where", "Tooth"),
              ("estimated", "Estimated (ETB)", "money"), ("invoiced", "Invoiced (ETB)", "money"),
              ("difference", "Difference (ETB)", "money")), estimates_vs_invoiced),
    Report("dental_chairs", "Chair use", "Booked appointments and hours per chair or room.", "reports.operational",
           _c(("chair", "Chair"), ("appointments", "Appointments", "number"), ("booked_hours", "Booked hours", "number"),
              ("no_shows", "No-shows", "number")), chair_use),
    Report("dental_ortho_cases", "Orthodontic patients", "Open orthodontic cases: months in treatment, last visit "
           "and next visit due.", "reports.clinical",
           _c(("case", "Case"), ("patient", "Patient"), ("mrn", "MRN"), ("phone", "Phone"), ("status", "Status"),
              ("appliance", "Appliance"), ("orthodontist", "Dentist"), ("started", "Started", "date"),
              ("months", "Months in treatment", "number"), ("expected", "Expected months", "number"),
              ("last_visit", "Last visit", "date"), ("next_due", "Next visit due", "date"),
              ("billing", "Charged")), ortho_cases, uses_dates=False),
    Report("dental_ortho_instalments", "Orthodontic instalments", "Package instalments due in the period, and "
           "earlier ones not yet invoiced or paid.", "reports.financial",
           _c(("due", "Due", "date"), ("case", "Case"), ("patient", "Patient"), ("mrn", "MRN"), ("phone", "Phone"),
              ("instalment", "Instalment"), ("amount", "Amount (ETB)", "money"), ("state", "State"),
              ("invoice", "Invoice")), ortho_instalments),
]
