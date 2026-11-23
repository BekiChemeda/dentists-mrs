/**
 * Navigation and dashboard selection. Pure functions so they can be unit-tested.
 * Hiding a link is a convenience only: the backend enforces every permission.
 */

export type NavGroup = "work" | "departments" | "management" | "admin";

export interface NavItem {
  key: string;
  path: string;
  /** User needs at least one of these permissions. Empty = everyone signed in. */
  anyOf: string[];
  group: NavGroup;
  /** Hidden when the system administrator switches this module off. */
  module?: string;
}

export const NAV_ITEMS: NavItem[] = [
  { key: "dashboard", path: "/", anyOf: [], group: "work" },
  { key: "patients", path: "/patients", anyOf: ["patients.view"], group: "work" },
  {
    key: "queue",
    path: "/queue",
    anyOf: ["queue.manage", "triage.record", "clinical.write", "dental.write"],
    group: "work",
  },
  { key: "appointments", path: "/appointments", anyOf: ["appointments.view"], group: "work" },
  { key: "calendar", path: "/calendar", anyOf: ["appointments.view"], group: "work" },
  { key: "triage", path: "/triage", anyOf: ["triage.record"], group: "work", module: "triage" },
  { key: "consultations", path: "/consultations", anyOf: ["clinical.write"], group: "work" },
  { key: "dental_encounters", path: "/dental/encounters", anyOf: ["dental.write"], group: "work" },
  { key: "recalls", path: "/dental/recalls", anyOf: ["dental.recall.manage"], group: "work", module: "recalls" },
  { key: "ortho", path: "/dental/ortho", anyOf: ["dental.ortho.manage"], group: "work", module: "orthodontics" },
  {
    key: "lab_cases",
    path: "/dental/lab-cases",
    anyOf: ["dental.labcase.manage", "dental.labcase.work"],
    group: "departments",
    module: "dental_lab",
  },
  { key: "laboratory", path: "/laboratory", anyOf: ["lab.view", "lab.result.enter"], group: "departments" },
  { key: "pharmacy", path: "/pharmacy", anyOf: ["pharmacy.dispense", "pharmacy.view"], group: "departments" },
  { key: "inventory", path: "/inventory", anyOf: ["inventory.view"], group: "departments" },
  { key: "billing", path: "/billing", anyOf: ["billing.view"], group: "departments" },
  {
    key: "approvals",
    path: "/approvals",
    anyOf: [
      "pharmacy.dispense",
      "billing.invoice",
      "billing.payment",
      "pharmacy.dispense.override",
      "billing.discount.approve",
      "billing.void.approve",
    ],
    group: "management",
  },
  {
    key: "reports",
    path: "/reports",
    anyOf: ["reports.operational", "reports.clinical", "reports.financial", "reports.staff"],
    group: "management",
  },
  {
    key: "catalogue",
    path: "/catalogue",
    anyOf: ["settings.manage", "lab.catalog.manage", "medicines.manage"],
    group: "management",
  },
  { key: "dental_catalogue", path: "/dental/catalogue", anyOf: ["dental.catalog.manage"], group: "management" },
  { key: "announcements", path: "/announcements", anyOf: ["announcements.manage"], group: "management" },
  { key: "departments", path: "/admin/departments", anyOf: ["departments.manage"], group: "management" },
  { key: "clinic", path: "/admin/clinic", anyOf: ["settings.manage", "branding.manage"], group: "management" },
  { key: "users", path: "/admin/users", anyOf: ["users.view"], group: "admin" },
  { key: "roles", path: "/admin/roles", anyOf: ["users.view"], group: "admin" },
  { key: "phones", path: "/admin/phones", anyOf: ["devices.manage", "system.security.manage"], group: "admin" },
  { key: "audit", path: "/admin/audit", anyOf: ["audit.view", "audit.operational"], group: "admin" },
  { key: "system", path: "/admin/system", anyOf: ["system.health.view", "system.security.manage"], group: "admin" },
];

export function hasAny(permissions: readonly string[], required: readonly string[]): boolean {
  return required.length === 0 || required.some((code) => permissions.includes(code));
}

export function visibleNavItems(permissions: readonly string[], modulesOff: readonly string[] = []): NavItem[] {
  return NAV_ITEMS.filter(
    (item) => hasAny(permissions, item.anyOf) && !(item.module && modulesOff.includes(item.module)),
  );
}

export type DashboardKind =
  | "system_admin"
  | "clinic_admin"
  | "clinic_director"
  | "doctor"
  | "dentist"
  | "dental_hygienist"
  | "dental_assistant"
  | "dental_technician"
  | "imaging_staff"
  | "nurse"
  | "receptionist"
  | "lab_technician"
  | "pharmacist"
  | "cashier"
  | "inventory_manager"
  | "accountant"
  | "general";

/** When a user holds several roles, the first match in this order decides the home dashboard. */
const DASHBOARD_PRIORITY: DashboardKind[] = [
  "doctor",
  "dentist",
  "dental_hygienist",
  "dental_assistant",
  "dental_technician",
  "imaging_staff",
  "nurse",
  "lab_technician",
  "pharmacist",
  "receptionist",
  "cashier",
  "inventory_manager",
  "accountant",
  "clinic_admin",
  "clinic_director",
  "system_admin",
];

export function dashboardFor(roleCodes: readonly string[]): DashboardKind {
  return DASHBOARD_PRIORITY.find((kind) => roleCodes.includes(kind)) ?? "general";
}
