"""
Source of truth for permission codes and the *default* role definitions.

`sync_catalog` inserts missing permissions and missing roles. It never removes
permissions from a role an administrator has customised, so upgrades are safe.
Adding a permission here + running `manage.py migrate` (or `sync_permissions`) is how a
new module registers its permissions.
"""

PERMISSIONS: dict[str, tuple[str, str]] = {
    # code: (module, description)
    "users.view": ("accounts", "View staff accounts and roles"),
    "users.manage": ("accounts", "Create, edit, activate, deactivate accounts and reset passwords"),
    "roles.manage": ("accounts", "Create roles and change role permissions"),
    "sessions.manage": ("accounts", "End other users' sessions"),
    "devices.manage": ("accounts", "Activate staff phones for the app and switch them off"),
    "audit.view": ("audit", "View the audit trail"),
    "settings.manage": ("core", "Change clinic settings"),
    "branding.manage": ("core", "Change the clinic logo shown on screens and printed documents"),
    "backups.manage": ("core", "Run and verify backups"),
    "system.health.view": ("system", "View server health, errors, storage and backup status"),
    "system.security.manage": ("system", "Change security policies and maintenance mode"),
    "staff.manage": ("accounts", "Add clinic staff and edit their profiles, using non-privileged roles only"),
    "departments.manage": ("accounts", "Create and edit departments and assign staff to them"),
    "announcements.manage": ("notifications", "Publish announcements to staff"),
    "audit.operational": ("audit", "View the operational audit trail (no security or system events)"),
    "patients.view": ("patients", "Search and view patient demographics"),
    "patients.create": ("patients", "Register patients"),
    "patients.update": ("patients", "Edit patient demographics"),
    "patients.merge": ("patients", "Merge duplicate patient records"),
    "patients.status": ("patients", "Mark patient records inactive (moved away, deceased) and reactivate them"),
    "patients.export": ("patients", "Export patient lists"),
    "appointments.view": ("scheduling", "View appointments"),
    "appointments.manage": ("scheduling", "Book, change and cancel appointments"),
    "queue.manage": ("scheduling", "Check in patients and manage the waiting queue"),
    "triage.record": ("triage", "Record vital signs and triage priority"),
    "clinical.view": ("clinical", "View clinical notes, diagnoses and history"),
    "clinical.write": ("clinical", "Write and sign consultation notes and diagnoses"),
    "clinical.amend": ("clinical", "Amend signed clinical notes with a reason"),
    "prescriptions.create": ("clinical", "Prescribe medicines"),
    "lab.request": ("laboratory", "Request laboratory tests"),
    "lab.view": ("laboratory", "View laboratory requests and results"),
    "lab.result.enter": ("laboratory", "Enter laboratory results"),
    "lab.result.verify": ("laboratory", "Verify laboratory results"),
    "lab.catalog.manage": ("laboratory", "Define laboratory tests and reference ranges"),
    "pharmacy.view": ("pharmacy", "View prescriptions and dispensing records"),
    "pharmacy.dispense": ("pharmacy", "Dispense medicines"),
    "pharmacy.dispense.override": ("pharmacy", "Approve dispensing above recorded stock"),
    "medicines.manage": ("pharmacy", "Maintain the medicine catalogue"),
    "inventory.view": ("inventory", "View stock levels and movements"),
    "inventory.manage": ("inventory", "Receive stock, manage suppliers and purchases"),
    "inventory.adjust": ("inventory", "Record stock adjustments"),
    "billing.view": ("billing", "View invoices and payments"),
    "billing.invoice": ("billing", "Create invoices"),
    "billing.payment": ("billing", "Record payments and print receipts"),
    "billing.discount.approve": ("billing", "Approve discounts"),
    "billing.void.approve": ("billing", "Approve invoice voids and refunds"),
    "payments.gateway.manage": ("billing", "Set up payments by phone (Chapa, telebirr) and their keys"),
    "reports.operational": ("reports", "View operational reports"),
    "reports.clinical": ("reports", "View clinical reports"),
    "reports.financial": ("reports", "View financial reports"),
    "reports.export": ("reports", "Export reports to CSV/PDF"),
    "reports.staff": ("reports", "View staff activity reports"),
    # Dental (apps/dental). Reports, prescriptions, billing and stock reuse the shared permissions above.
    "dental.view": ("dental", "View dental examinations, chart, periodontal charts, diagnoses, plans and procedures"),
    "dental.write": ("dental", "Write and sign dental examinations, diagnoses and medical risk reviews"),
    "dental.chart.record": ("dental", "Record tooth findings and periodontal measurements in an open examination"),
    "dental.amend": ("dental", "Amend signed dental records and mark chart entries as entered in error"),
    "dental.plan.manage": ("dental", "Create, present and revise treatment plans and record the patient's decision"),
    "dental.procedure.record": ("dental", "Prepare procedure records and the materials used"),
    "dental.procedure.sign": ("dental", "Sign procedure records you performed"),
    "dental.imaging.view": ("dental", "View dental images"),
    "dental.imaging.upload": ("dental", "Upload dental images"),
    "dental.imaging.manage": ("dental", "Correct dental image details and withdraw images uploaded in error"),
    "dental.labcase.manage": ("dental", "Send work to the dental laboratory and follow it up"),
    "dental.labcase.work": ("dental", "Work on dental laboratory cases assigned to you"),
    "dental.catalog.manage": ("dental", "Maintain dental procedures and prices, findings, diagnoses and appointment types"),
    "dental.recall.manage": ("dental", "Manage follow-ups and recalls"),
}

ROLES: dict[str, tuple[str, str, list[str]]] = {
    # code: (name, description, default permission codes)
    "system_admin": (
        "System administrator",
        "Technical administration: accounts, roles, security, backups, health. "
        "No patient records, money or clinic configuration.",
        ["users.view", "users.manage", "roles.manage", "sessions.manage", "devices.manage", "audit.view",
         "payments.gateway.manage",
         "backups.manage", "system.health.view", "system.security.manage", "branding.manage"],
    ),
    "clinic_admin": (
        "Clinic administrator",
        "Day-to-day clinic operations: staff, departments, services and fees, catalogues, queue, "
        "reports and announcements. Patient demographics only, no clinical notes.",
        ["users.view", "staff.manage", "departments.manage", "announcements.manage", "audit.operational",
         "devices.manage",
         "settings.manage", "branding.manage", "patients.view", "patients.create", "patients.update", "patients.merge",
         "patients.status",
         "patients.export", "appointments.view", "appointments.manage", "queue.manage",
         "lab.catalog.manage", "medicines.manage", "pharmacy.dispense.override", "inventory.view",
         "inventory.adjust", "billing.view", "billing.discount.approve", "billing.void.approve",
         "reports.operational", "reports.clinical", "reports.financial", "reports.export", "reports.staff",
         "dental.catalog.manage"],
    ),
    "clinic_director": (
        "Clinic director",
        "Executive oversight: financial and operational reports, approvals, policies and announcements. "
        "No technical administration and no clinical notes.",
        ["users.view", "audit.operational", "settings.manage", "announcements.manage", "patients.view",
         "appointments.view", "billing.view", "billing.discount.approve", "billing.void.approve",
         "inventory.view", "reports.operational", "reports.clinical", "reports.financial",
         "reports.export", "reports.staff"],
    ),
    "receptionist": (
        "Receptionist",
        "Registration, appointments, queue and invoicing.",
        ["patients.view", "patients.create", "patients.update", "appointments.view",
         "appointments.manage", "queue.manage", "billing.view", "billing.invoice",
         "reports.operational", "dental.recall.manage"],
    ),
    "doctor": (
        "Doctor",
        "Consultations, diagnoses, prescriptions and laboratory requests.",
        ["patients.view", "patients.create", "patients.update", "patients.status", "appointments.view",
         "appointments.manage", "queue.manage", "triage.record", "clinical.view", "clinical.write",
         "clinical.amend", "prescriptions.create", "lab.request", "lab.view", "pharmacy.view",
         "reports.operational", "reports.clinical"],
    ),
    "nurse": (
        "Nurse",
        "Triage, vital signs and queue.",
        ["patients.view", "patients.create", "patients.update", "appointments.view", "queue.manage",
         "triage.record", "clinical.view", "lab.view"],
    ),
    "lab_technician": (
        "Laboratory technician",
        "Specimens, results and verification.",
        ["patients.view", "lab.view", "lab.result.enter", "lab.result.verify", "lab.catalog.manage",
         "reports.operational"],
    ),
    "pharmacist": (
        "Pharmacist",
        "Dispensing and medicine catalogue.",
        ["patients.view", "pharmacy.view", "pharmacy.dispense", "medicines.manage", "inventory.view",
         "reports.operational"],
    ),
    "cashier": (
        "Cashier",
        "Invoices, payments and receipts.",
        ["patients.view", "appointments.view", "billing.view", "billing.invoice", "billing.payment",
         "reports.financial"],
    ),
    "accountant": (
        "Accountant",
        "Financial oversight: invoices, payments, refunds and financial reports, read only. "
        "Cannot take payments, approve discounts or voids, or see clinical notes.",
        ["billing.view", "inventory.view", "reports.financial", "reports.operational", "reports.export"],
    ),
    "inventory_manager": (
        "Inventory manager",
        "Stock, suppliers and purchases.",
        ["medicines.manage", "inventory.view", "inventory.manage", "inventory.adjust",
         "reports.operational"],
    ),
    "dentist": (
        "Dentist",
        "Dental examinations, chart, diagnoses, treatment plans, procedures, prescriptions and images.",
        ["patients.view", "patients.create", "patients.update", "patients.status", "appointments.view",
         "appointments.manage", "queue.manage", "dental.view", "dental.write", "dental.chart.record", "dental.amend",
         "dental.plan.manage", "dental.procedure.record", "dental.procedure.sign", "prescriptions.create",
         "dental.imaging.view", "dental.imaging.upload", "dental.imaging.manage", "dental.labcase.manage",
         "dental.recall.manage", "pharmacy.view", "reports.operational", "reports.clinical"],
    ),
    "dental_assistant": (
        "Dental assistant",
        "Chairside work: records findings the dentist calls out, prepares procedure records and materials, uploads "
        "images. Cannot sign diagnoses, plans or procedures.",
        ["patients.view", "appointments.view", "queue.manage", "dental.view", "dental.chart.record",
         "dental.procedure.record", "dental.imaging.view", "dental.imaging.upload"],
    ),
    "dental_hygienist": (
        "Dental hygienist",
        "Preventive and periodontal work within the clinic's approved scope: charting, periodontal measurements, "
        "signing own procedures, recalls.",
        ["patients.view", "appointments.view", "queue.manage", "dental.view", "dental.chart.record",
         "dental.procedure.record", "dental.procedure.sign", "dental.imaging.view", "dental.recall.manage"],
    ),
    "dental_technician": (
        "Dental technician",
        "Dental laboratory work assigned to them (crowns, bridges, dentures). Sees the patient's name and MRN only.",
        ["dental.labcase.work"],
    ),
    "imaging_staff": (
        "Imaging staff",
        "Takes and uploads dental images and corrects their details.",
        ["patients.view", "appointments.view", "dental.imaging.view", "dental.imaging.upload",
         "dental.imaging.manage"],
    ),
}

# Permissions that together let someone administer access. The system refuses any change
# that would leave no active user holding all of them.
ADMIN_PERMISSIONS = ("users.manage", "roles.manage")

# A role carrying any of these is "privileged": only holders of users.manage may assign it, and
# holders of staff.manage alone cannot edit, reset or deactivate an account that has one.
PRIVILEGED_PERMISSIONS = frozenset({
    "users.manage", "roles.manage", "sessions.manage", "audit.view", "backups.manage", "payments.gateway.manage",
    "system.health.view", "system.security.manage", "staff.manage",
})

# Senior roles treated as privileged even though their permissions are ordinary: a clinic
# administrator must not be able to reset the director's password and act in their name.
PROTECTED_ROLE_CODES = frozenset({"clinic_director"})


def role_is_privileged(code: str, permission_codes) -> bool:
    return code in PROTECTED_ROLE_CODES or any(p in PRIVILEGED_PERMISSIONS for p in permission_codes)


# Role defaults changed after first release. Migration 0005 applies these to the built-in roles,
# once, so existing installations get the separation of duties too.
ROLE_CHANGES_0005 = {
    "system_admin": {"add": ["system.health.view", "system.security.manage"], "remove": ["settings.manage"]},
    "clinic_admin": {
        "add": ["staff.manage", "departments.manage", "announcements.manage", "audit.operational",
                "patients.create", "patients.update", "appointments.manage", "queue.manage", "medicines.manage",
                "reports.staff"],
        "remove": ["audit.view"],
    },
    "clinic_director": {"add": ["reports.staff"], "remove": []},
}


# Added in migration 0008: the logo permission for the two administrator roles. The accountant role
# itself is created by sync_catalog like any new built-in role.
ROLE_CHANGES_0008 = {
    "system_admin": {"add": ["branding.manage"], "remove": []},
    "clinic_admin": {"add": ["branding.manage"], "remove": []},
}


# Added in migration 0010: who may mark a patient record inactive or deceased.
# Payments by phone (apps/payments): keys are set by the technical administrator.
ROLE_CHANGES_0013 = {"system_admin": {"add": ["payments.gateway.manage"]}}

# Phones for the app (apps/devices): the built-in administrator roles activate and switch them off.
ROLE_CHANGES_0012 = {
    "system_admin": {"add": ["devices.manage"]},
    "clinic_admin": {"add": ["devices.manage"]},
}

# Added in migration 0014 (Dental MRS): dental duties for the shared built-in roles.
ROLE_CHANGES_0014 = {
    "receptionist": {"add": ["dental.recall.manage"]},
    "clinic_admin": {"add": ["dental.catalog.manage"]},
}

ROLE_CHANGES_0010 = {
    "clinic_admin": {"add": ["patients.status"], "remove": []},
    "doctor": {"add": ["patients.status"], "remove": []},
}


def sync_catalog(Permission, Role) -> None:
    """Accepts model classes so it can run inside data migrations (historical models)."""
    for code, (module, description) in PERMISSIONS.items():
        Permission.objects.update_or_create(code=code, defaults={"module": module, "description": description})

    for code, (name, description, perm_codes) in ROLES.items():
        unknown = set(perm_codes) - set(PERMISSIONS)
        if unknown:
            raise ValueError(f"Role {code} references unknown permissions: {sorted(unknown)}")
        role, created = Role.objects.get_or_create(
            code=code, defaults={"name": name, "description": description, "is_system": True}
        )
        if created:
            role.permissions.set(Permission.objects.filter(code__in=perm_codes))
