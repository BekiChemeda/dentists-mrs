"""
Modules: parts of the system a clinic can switch off when it does not use them (e.g. a two-person clinic
with no laboratory, pharmacy or stock).

Switching a module off:
* hides it everywhere: the permissions that belong to it are taken away from every role while it is off,
  so its pages disappear from menus and its API answers 403 with a clear message;
* changes the visit flow where needed (no triage step, no billing check when closing a visit, ...);
* keeps all its data: switching it back on restores everything exactly as it was.

A module cannot be switched off while it has unfinished work (tests waiting, medicines not dispensed,
unpaid invoices, future appointments). Patients, visits, consultations, the audit log, accounts and
backups are not modules: they are always on.

Only the system administrator (system.security.manage) changes modules; everyone can see which are on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone


@dataclass(frozen=True)
class Module:
    key: str
    name: str
    description: str
    # Permissions that only make sense with this module; removed from every role while it is off.
    permissions: frozenset[str] = field(default_factory=frozenset)
    # Modules that must be on for this one to work.
    requires: tuple[str, ...] = ()
    # What changes for staff when it is off, shown on the Modules screen.
    when_off: str = ""


MODULES: dict[str, Module] = {m.key: m for m in [
    Module("triage", "Triage (nurse step)",
           "Patients wait for a nurse to record the complaint and vital signs before the doctor.",
           when_off="New patients go straight to the doctors' waiting list. Doctors can still record vital signs."),
    Module("appointments", "Appointments and calendar", "Booking, rescheduling and the clinic calendar.",
           frozenset({"appointments.view", "appointments.manage"}),
           when_off="Only walk-in visits. Doctors cannot book follow-ups; write the return date in the plan."),
    Module("laboratory", "Laboratory", "Test requests, specimens, results and verification.",
           frozenset({"lab.request", "lab.view", "lab.result.enter", "lab.result.verify", "lab.catalog.manage"}),
           when_off="Doctors cannot request tests in the system; send patients to an outside laboratory with a "
                    "written request. Earlier results stay in patient records."),
    Module("inventory", "Stock (inventory)", "Medicine and supply stock, batches, receiving and adjustments.",
           frozenset({"inventory.view", "inventory.manage", "inventory.adjust"}),
           when_off="No stock records. The pharmacy module needs stock, so it is switched off too."),
    Module("pharmacy", "Pharmacy", "Dispensing prescriptions from stock and the controlled-medicine register.",
           frozenset({"pharmacy.view", "pharmacy.dispense", "pharmacy.dispense.override", "medicines.manage"}),
           requires=("inventory",),
           when_off="Doctors still prescribe; the patient gets a printed prescription to buy outside. "
                    "Closing a visit no longer waits for dispensing."),
    Module("billing", "Billing and payments", "Invoices, payments, receipts, discounts, voids and refunds.",
           frozenset({"billing.view", "billing.invoice", "billing.payment", "billing.discount.approve",
                      "billing.void.approve", "reports.financial"}),
           when_off="No invoices or payments in the system (use the clinic's own receipt book). Closing a visit "
                    "no longer checks payment. Financial reports are hidden."),
    Module("reports", "Reports", "Operational, clinical and staff reports and exports.",
           frozenset({"reports.operational", "reports.clinical", "reports.export", "reports.staff",
                      "reports.financial"}),
           when_off="The Reports page and the home-page graphs are hidden."),
    # Dental MRS. Examinations, the chart, diagnoses, treatment plans and procedures are always on.
    Module("periodontal", "Periodontal chart", "Six-site periodontal examinations with comparison over time.",
           when_off="The periodontal chart is hidden and no new periodontal examinations can be recorded. "
                    "Earlier charts stay in patient records."),
    Module("dental_imaging", "Dental imaging", "Radiographs and clinical photographs stored on the clinic server.",
           frozenset({"dental.imaging.view", "dental.imaging.upload", "dental.imaging.manage"}),
           when_off="No image upload or viewing. Image files stay on the server and in backups."),
    Module("dental_lab", "Dental laboratory cases", "Crowns, bridges and dentures sent to the dental technician.",
           frozenset({"dental.labcase.manage", "dental.labcase.work"}),
           when_off="No laboratory cases in the system; track outside laboratory work on paper."),
    Module("recalls", "Recalls and follow-ups", "The list of patients due for a review or preventive recall.",
           frozenset({"dental.recall.manage"}),
           when_off="No recall list. Dentists write the review date in the examination note."),
    Module("orthodontics", "Orthodontics",
           "Orthodontic assessments, treatment courses (braces, aligners, retainers), visit records, and package "
           "prices paid in instalments or charges per visit.",
           frozenset({"dental.ortho.manage"}),
           when_off="No orthodontic assessments, cases or instalments. Earlier records stay in patient records."),
]}

# People who see patients: medical doctors and dentists. Used for doctor lists, queue access and alerts.
CLINICIAN_PERMISSIONS = ("clinical.write", "dental.write")


def _settings():
    from .models import SystemSettings

    return SystemSettings.get()


def disabled_modules() -> frozenset[str]:
    """Keys of modules switched off. Dependencies are applied (pharmacy is off when stock is off)."""
    off = set(_settings().disabled_modules or [])
    for key, module in MODULES.items():
        if any(req in off for req in module.requires):
            off.add(key)
    return frozenset(k for k in off if k in MODULES)


def is_enabled(key: str) -> bool:
    return key not in disabled_modules()


def disabled_permissions(off: frozenset[str] | None = None) -> frozenset[str]:
    off = disabled_modules() if off is None else off
    codes: set[str] = set()
    for key in off:
        codes |= MODULES[key].permissions
    return frozenset(codes)


def module_for_permission(code: str, off: frozenset[str] | None = None) -> Module | None:
    """The switched-off module that removes this permission, if any."""
    off = disabled_modules() if off is None else off
    for key in off:
        if code in MODULES[key].permissions:
            return MODULES[key]
    return None


# --------------------------------------------------------------------------- open work
def open_work(key: str) -> list[str]:
    """Unfinished work that stops a module being switched off, in plain words."""
    from apps.billing.models import Invoice
    from apps.clinical.models import Prescription
    from apps.laboratory.models import LabOrderItem
    from apps.scheduling.models import Appointment, Visit

    found: list[str] = []
    if key == "laboratory":
        n = LabOrderItem.objects.exclude(status__in=[LabOrderItem.Status.VERIFIED, LabOrderItem.Status.CANCELLED]).count()
        if n:
            found.append(f"{n} laboratory test(s) not yet verified or cancelled")
    elif key in ("pharmacy", "inventory"):
        n = Prescription.objects.filter(status__in=[Prescription.Status.ACTIVE, Prescription.Status.PARTIAL]).count()
        if n:
            found.append(f"{n} prescription(s) waiting to be dispensed")
    elif key == "billing":
        n = Invoice.objects.filter(status__in=[Invoice.Status.DRAFT, Invoice.Status.ISSUED, Invoice.Status.PARTIAL]).count()
        if n:
            found.append(f"{n} invoice(s) still draft or not fully paid")
    elif key == "appointments":
        n = Appointment.objects.filter(status__in=Appointment.BOOKED, scheduled_at__gte=timezone.now()).count()
        if n:
            found.append(f"{n} future appointment(s) booked")
    elif key == "triage":
        n = Visit.objects.filter(status=Visit.Status.WAITING_TRIAGE).count()
        if n:
            found.append(f"{n} patient(s) waiting for triage")
    elif key == "periodontal":
        from apps.dental.models import PeriodontalExam

        n = PeriodontalExam.objects.filter(encounter__status="draft").count()
        if n:
            found.append(f"{n} periodontal chart(s) on unsigned examinations")
    elif key == "dental_lab":
        from apps.dental.models import DentalLabCase

        n = DentalLabCase.objects.filter(status__in=DentalLabCase.OPEN).count()
        if n:
            found.append(f"{n} laboratory case(s) not yet delivered or cancelled")
    elif key == "orthodontics":
        from apps.dental.models import OrthoCase, OrthoInstalment
        from apps.dental.services.ortho import unbilled_instalments

        n = OrthoCase.objects.filter(status__in=OrthoCase.OPEN).count()
        if n:
            found.append(f"{n} orthodontic case(s) still open (planned, active or in retention)")
        m = unbilled_instalments(OrthoInstalment.objects.all()).count()
        if m:
            found.append(f"{m} orthodontic instalment(s) not yet invoiced")
    elif key == "recalls":
        from apps.dental.models import Recall

        n = Recall.objects.filter(status=Recall.Status.BOOKED).count()
        if n:
            found.append(f"{n} recall(s) booked and not yet attended")
    return found


def describe() -> list[dict]:
    off = disabled_modules()
    chosen_off = set(_settings().disabled_modules or [])
    rows = []
    for key, m in MODULES.items():
        rows.append({
            "key": key, "name": m.name, "description": m.description, "when_off": m.when_off,
            "enabled": key not in off,
            # Off only because something it needs is off (e.g. pharmacy when stock is off).
            "off_because_of": [r for r in m.requires if r in off] if key in off and key not in chosen_off else [],
            "requires": list(m.requires),
            "needed_by": [k for k, other in MODULES.items() if key in other.requires],
            "permissions": sorted(m.permissions),
        })
    return rows


@transaction.atomic
def set_module(ctx, key: str, enabled: bool) -> list[dict]:
    from apps.audit.services import record_event
    from .exceptions import BusinessValidationError, ConflictError
    from .models import SystemSettings

    if key not in MODULES:
        raise BusinessValidationError("Unknown module.", fields={"key": ["Unknown module."]})
    settings = SystemSettings.objects.select_for_update().get(pk=1)
    chosen_off = set(settings.disabled_modules or [])
    module = MODULES[key]
    if enabled:
        missing = [r for r in module.requires if r in chosen_off]
        if missing:
            names = ", ".join(MODULES[r].name for r in missing)
            raise ConflictError(f"{module.name} needs {names}. Switch that on first.")
        chosen_off.discard(key)
    else:
        affected = [key] + [k for k, other in MODULES.items() if key in other.requires and k not in chosen_off]
        problems = [f"{MODULES[k].name}: {p}" for k in affected for p in open_work(k)]
        if problems:
            raise ConflictError(f"{module.name} still has unfinished work. Finish or cancel it first.",
                                extra={"open_work": problems})
        chosen_off.add(key)
    before = sorted(settings.disabled_modules or [])
    settings.disabled_modules = sorted(chosen_off)
    settings.save(update_fields=["disabled_modules"])
    record_event(ctx, action="system.module_on" if enabled else "system.module_off", object_type="module",
                 object_id=key, details={"module": key, "disabled_before": before,
                                         "disabled_after": settings.disabled_modules})
    return describe()


# --------------------------------------------------------------------------- permission matrix layout
ACTIONS = [("view", "View"), ("create", "Create or request"), ("work", "Do the work"), ("approve", "Approve or verify"),
           ("export", "Export"), ("admin", "Set up and manage")]

# Rows of the permission matrix: an area of work, the module that can switch it off (if any), and each
# permission's column. Every permission in the catalogue appears exactly once (checked by a test).
AREAS: list[tuple[str, str, str | None, dict[str, str]]] = [
    ("patients", "Patients", None, {"patients.view": "view", "patients.create": "create", "patients.update": "work",
                                    "patients.export": "export", "patients.merge": "admin", "patients.status": "admin"}),
    ("queue", "Waiting list and visits", None, {"queue.manage": "work"}),
    ("triage", "Triage and vital signs", None, {"triage.record": "work"}),
    ("clinical", "Consultations", None, {"clinical.view": "view", "prescriptions.create": "create",
                                         "clinical.write": "work", "clinical.amend": "approve"}),
    ("appointments", "Appointments", "appointments", {"appointments.view": "view", "appointments.manage": "work"}),
    ("laboratory", "Laboratory", "laboratory", {"lab.view": "view", "lab.request": "create", "lab.result.enter": "work",
                                                "lab.result.verify": "approve", "lab.catalog.manage": "admin"}),
    ("pharmacy", "Pharmacy", "pharmacy", {"pharmacy.view": "view", "pharmacy.dispense": "work",
                                          "pharmacy.dispense.override": "approve", "medicines.manage": "admin"}),
    ("inventory", "Stock", "inventory", {"inventory.view": "view", "inventory.adjust": "work",
                                         "inventory.manage": "admin"}),
    ("billing", "Billing", "billing", {"billing.view": "view", "billing.invoice": "create", "billing.payment": "work",
                                       "billing.discount.approve": "approve", "billing.void.approve": "approve",
                                       "payments.gateway.manage": "admin"}),
    ("reports", "Reports", "reports", {"reports.operational": "view", "reports.clinical": "view",
                                       "reports.financial": "view", "reports.staff": "view", "reports.export": "export"}),
    ("dental", "Dental records", None, {"dental.view": "view", "dental.write": "work",
                                         "dental.chart.record": "work", "dental.amend": "approve",
                                         "dental.catalog.manage": "admin"}),
    ("dental_plans", "Treatment plans and procedures", None, {"dental.plan.manage": "create",
                                                              "dental.procedure.record": "work",
                                                              "dental.procedure.sign": "approve"}),
    ("dental_imaging", "Dental imaging", "dental_imaging", {"dental.imaging.view": "view",
                                                            "dental.imaging.upload": "create",
                                                            "dental.imaging.manage": "admin"}),
    ("dental_lab", "Dental laboratory cases", "dental_lab", {"dental.labcase.manage": "create",
                                                             "dental.labcase.work": "work"}),
    ("recalls", "Recalls", "recalls", {"dental.recall.manage": "work"}),
    ("orthodontics", "Orthodontics", "orthodontics", {"dental.ortho.manage": "work"}),
    ("clinic", "Clinic administration", None, {"audit.operational": "view", "staff.manage": "admin",
                                               "departments.manage": "admin", "announcements.manage": "admin",
                                               "settings.manage": "admin", "branding.manage": "admin",
                                               "devices.manage": "admin"}),
    ("system", "System administration", None, {"users.view": "view", "system.health.view": "view", "audit.view": "view",
                                               "users.manage": "admin", "roles.manage": "admin",
                                               "sessions.manage": "admin", "backups.manage": "admin",
                                               "system.security.manage": "admin"}),
]


def permission_layout() -> dict:
    from apps.accounts.catalog import PERMISSIONS, PRIVILEGED_PERMISSIONS

    off = disabled_modules()
    areas = []
    for key, name, module_key, perms in AREAS:
        areas.append({
            "key": key, "name": name, "module": module_key, "module_on": module_key not in off if module_key else True,
            "permissions": [{"code": code, "action": action, "label": PERMISSIONS[code][1],
                             "privileged": code in PRIVILEGED_PERMISSIONS} for code, action in perms.items()],
        })
    return {"actions": [{"key": k, "label": label} for k, label in ACTIONS], "areas": areas}
