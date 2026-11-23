export interface RoleSummary {
  id: string;
  code: string;
  name: string;
  /** Carries administrative rights; only a system administrator can assign it. */
  privileged?: boolean;
}

export interface Department {
  /** Version for edit-conflict protection; send it back when saving. */
  row_version?: number;
  id: string;
  code: string;
  name: string;
  receives_triage: boolean;
  is_active: boolean;
  sort_order: number;
  staff_count?: number;
}

export interface Announcement {
  /** Version for edit-conflict protection; send it back when saving. */
  row_version?: number;
  id: string;
  title: string;
  body: string;
  level: "info" | "important";
  role_ids: string[];
  department_id: string | null;
  department_name: string | null;
  starts_on: string;
  ends_on: string | null;
  is_active: boolean;
  created_by_name: string;
  created_at: string;
}

export interface SecuritySettings {
  /** Version for edit-conflict protection; send it back when saving. */
  row_version?: number;
  password_min_length: number;
  login_max_failures: number;
  login_lockout_minutes: number;
  session_idle_minutes: number;
  maintenance_mode: boolean;
  maintenance_message: string;
  mfa_required_for: "off" | "admins" | "all";
  dormant_account_days: number;
  floor: { password_min_length: number };
  limits: Record<string, [number, number]>;
  session_absolute_hours: number;
}

export interface EmailSettingsData {
  /** Version for edit-conflict protection; send it back when saving. */
  row_version?: number;
  enabled: boolean;
  provider: "cpanel" | "brevo" | "custom";
  host: string;
  port: number;
  security: "ssl" | "starttls";
  username: string;
  password_set: boolean;
  from_email: string;
  from_name: string;
  reply_to: string;
  site_url: string;
  configured: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  presets: Record<string, { host: string; port: number; security: "ssl" | "starttls" }>;
  outbox: { queued: number; failed_7d: number; oldest_queued_at: string | null };
}

export interface OutboundEmailRow {
  id: number;
  to_email: string;
  kind: string;
  subject: string;
  status: "queued" | "sent" | "failed";
  attempts: number;
  next_attempt_at: string;
  last_error: string;
  created_at: string;
  sent_at: string | null;
}

export interface OffsiteRun {
  id: number;
  started_at: string;
  finished_at: string;
  status: "success" | "failure";
  snapshot_id: string;
  bytes_added: number | null;
  dump_file: string;
  target: string;
  message: string;
}

export interface OffsiteStatus {
  enabled: boolean;
  interval_hours: number;
  last_success_at: string | null;
  last_attempt_at: string | null;
  last_status: "success" | "failure" | null;
  last_message: string;
  target: string;
  next_due_at: string | null;
  overdue: boolean;
}

export interface ErrorEvent {
  id: number;
  occurred_at: string;
  request_id: string;
  method: string;
  path: string;
  exception_type: string;
  message: string;
  user_id: string | null;
}

interface Usage {
  total: number;
  percent_used: number | null;
}
export interface SystemHealth {
  checked_at: string;
  status: "ok" | "warning" | "error";
  warnings: string[];
  version: string | null;
  python: string;
  django: string;
  debug: boolean;
  https: boolean;
  app_uptime_seconds: number;
  host_uptime_seconds: number | null;
  load: { "1m": number; "5m": number; "15m": number; cpus: number | null } | null;
  memory: (Usage & { available: number }) | null;
  disk: (Usage & { used: number; free: number; path: string }) | null;
  backup_disk: (Usage & { used: number; free: number; path: string }) | null;
  database: {
    status: string;
    latency_ms?: number;
    vendor?: string;
    server_version?: number | null;
    size_bytes?: number | null;
    pending_migrations: string[];
  };
  backup: {
    configured: boolean;
    found?: boolean;
    directory?: string;
    file?: string;
    taken_at?: string;
    size_bytes?: number;
    age_hours?: number;
    count?: number;
    stale?: boolean;
  };
  errors_24h: number;
  sessions_active: number;
  failed_logins_24h: number;
  locked_accounts: number;
  maintenance_mode: boolean;
  offsite: OffsiteStatus;
}

export interface User {
  /** Version for edit-conflict protection; send it back when saving. */
  row_version?: number;
  id: string;
  username: string;
  first_name: string;
  last_name: string;
  full_name: string;
  email: string;
  phone: string;
  job_title: string;
  registration_number: string;
  department: { id: string; code: string; name: string } | null;
  start_date: string | null;
  mfa_enabled: boolean;
  is_active: boolean;
  is_locked: boolean;
  must_change_password: boolean;
  roles: RoleSummary[];
  last_login: string | null;
  created_at: string;
}

export interface CurrentUser extends User {
  permissions: string[];
  mfa_setup_required: boolean;
  email_alerts: "off" | "important" | "all";
  /** Modules the system administrator has switched off for this clinic. */
  modules_off?: string[];
  /** The room this person works in today; shown to patients when they are called. */
  room?: { id: string; name: string } | null;
}

export interface Room {
  id: string;
  name: string;
  department_id: string | null;
  department_name: string;
  is_active: boolean;
  sort_order: number;
  row_version?: number;
}

export interface ClinicModule {
  key: string;
  name: string;
  description: string;
  when_off: string;
  enabled: boolean;
  /** Set when the module is off only because a module it needs is off. */
  off_because_of: string[];
  requires: string[];
  needed_by: string[];
  permissions: string[];
}

export interface PermissionLayout {
  actions: { key: string; label: string }[];
  areas: {
    key: string;
    name: string;
    module: string | null;
    module_on: boolean;
    permissions: { code: string; action: string; label: string; privileged: boolean }[];
  }[];
}

export interface Role extends RoleSummary {
  /** Version for edit-conflict protection; send it back when saving. */
  row_version?: number;
  description: string;
  is_system: boolean;
  permission_codes: string[];
  user_count: number;
  privileged: boolean;
}

export interface Permission {
  code: string;
  module: string;
  description: string;
}

export interface AuditEvent {
  id: string;
  occurred_at: string;
  actor: string | null;
  actor_username: string;
  action: string;
  object_type: string;
  object_id: string;
  outcome: "success" | "failure" | "denied";
  ip_address: string | null;
  user_agent: string;
  request_id: string;
  details: Record<string, unknown>;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface SessionInfo {
  id: string;
  created_at: string;
  last_seen_at: string;
  ip_address: string | null;
  user_agent: string;
  is_current: boolean;
}

// ---------------------------------------------------------------- clinical modules
export interface PersonBrief {
  id: string;
  full_name: string;
  username: string;
}

export interface PatientBrief {
  id: string;
  mrn: string;
  full_name: string;
  sex: "female" | "male";
  birth_date: string;
  age: number;
  phone: string;
  address?: string;
}

export interface Allergy {
  id: string;
  substance: string;
  reaction: string;
  severity: "mild" | "moderate" | "severe";
  is_active: boolean;
  inactive_reason: string;
  created_at: string;
  recorded_by_name: string;
}

export interface Patient extends PatientBrief {
  /** Version for edit-conflict protection; send it back when saving. */
  row_version?: number;
  /** Why an unmerged record is inactive. */
  inactive_kind?: "" | "moved" | "deceased" | "other";
  inactive_note?: string;
  date_of_death?: string | null;
  inactivated_at?: string | null;
  inactivated_by_name?: string | null;
  first_name: string;
  middle_name: string;
  last_name: string;
  birth_date_estimated: boolean;
  city: string;
  created_at: string;
  alt_phone?: string;
  region?: string;
  subcity_woreda?: string;
  kebele?: string;
  house_number?: string;
  national_id?: string;
  blood_group?: string;
  known_conditions?: string;
  past_history?: string;
  current_medications?: string;
  emergency_contacts?: { id: string; name: string; relationship: string; phone: string }[];
  allergies?: Allergy[];
  is_active?: boolean;
  merged_into?: { id: string; mrn: string; full_name: string } | null;
  merged_at?: string | null;
  merge_reason?: string;
  merged_records?: { id: string; mrn: string; full_name: string; merged_at: string }[];
}

export type VisitStatus =
  "waiting_triage" | "waiting_doctor" | "in_consultation" | "after_consult" | "completed" | "cancelled";
export type Priority = "routine" | "urgent" | "emergency";

export interface Visit {
  id: string;
  patient: PatientBrief;
  visit_date: string;
  queue_number: number;
  kind: "walk_in" | "appointment" | "lab_only";
  status: VisitStatus;
  priority: Priority;
  assigned_doctor: PersonBrief | null;
  arrived_at: string;
  consultation_started_at: string | null;
  completed_at: string | null;
  completed_by: PersonBrief | null;
  outcome: "" | VisitOutcome;
  completion_note: string;
  cancel_reason: string;
  called_at: string | null;
  called_by: PersonBrief | null;
  /** Room the patient was called to, when the caller had chosen one. */
  called_room?: string | null;
  skipped_at: string | null;
  skip_reason: string;
  waiting_minutes: number | null;
  has_vitals: boolean;
  triage: {
    recorded_at: string;
    chief_complaint: string;
    complaint_duration: string;
    triage_to: TriageDestination | "";
    general_appearance: GeneralAppearance | "";
  } | null;
  diagnoses: { code: string; description: string }[];
  encounters: { id: string; doctor_id: string; status: "draft" | "signed" }[];
  dental_encounters?: { id: string; dentist_id: string; status: "draft" | "signed" }[];
  /** Department code where the patient is now (set at triage, changed by an internal referral). */
  department?: string;
  internal_referral?: {
    id: string;
    from_department: string;
    urgency: string;
    reason: string;
    referred_by: string;
    created_at: string;
  } | null;
  appointment: string | null;
}

export type GeneralAppearance = "acute_sick" | "chronic_sick" | "acute_on_chronic";
export type TriageDestination = "adult_eopd" | "pediatric_eopd" | "opd1" | "opd2" | "labour_ward";

export type VisitOutcome = "completed" | "referred" | "left_early" | "follow_up";

export interface VisitEvent {
  id: number;
  at: string;
  actor: PersonBrief | null;
  kind: string;
  summary: string;
}

export interface Outstanding {
  draft_notes: string[];
  lab_pending: string[];
  medicines_pending: string[];
  unbilled: string[];
  balance_due: string;
  open_invoices: string[];
  any: boolean;
  blocking: boolean;
}

export interface Appointment {
  id: string;
  patient: PatientBrief;
  doctor: PersonBrief;
  scheduled_at: string;
  scheduled_date: string;
  duration_minutes: number;
  reason: string;
  notes: string;
  service: { id: string; name: string } | null;
  status: "scheduled" | "confirmed" | "arrived" | "completed" | "cancelled" | "no_show";
  display_status: string;
  confirmed_at: string | null;
  reschedule_count: number;
  cancel_reason: string;
  visit_id: string | null;
  visit_status: VisitStatus | null;
  source_encounter: string | null;
}

export interface Vitals {
  id: string;
  visit: string;
  recorded_at: string;
  recorded_by: PersonBrief;
  systolic: number | null;
  diastolic: number | null;
  temperature_c: string | null;
  heart_rate: number | null;
  respiratory_rate: number | null;
  spo2: number | null;
  weight_kg: string | null;
  height_cm: string | null;
  bmi: string | null;
  pain_score: number | null;
  consciousness: "" | "alert" | "confusion" | "voice" | "pain" | "unresponsive";
  on_oxygen: boolean | null;
  chief_complaint: string;
  complaint_duration: string;
  general_appearance: GeneralAppearance | "";
  triage_to: TriageDestination | "";
  symptoms: string;
  allergies_confirmed: boolean | null;
  current_medications: string;
  observations: string;
  notes: string;
  interpretation: VitalsReading;
}

export interface VitalsReading {
  reference: string;
  flags: Record<string, { level: "abnormal" | "critical"; text: string }>;
  news2: { total: number; complete: boolean; risk: string | null } | null;
  worst: "normal" | "abnormal" | "critical";
}

export interface Icd {
  code: string;
  title: string;
  is_common: boolean;
}

export interface Diagnosis {
  id: string;
  icd: Icd | null;
  description: string;
  kind: "primary" | "secondary";
  certainty: "confirmed" | "provisional";
  created_at: string;
}

export interface Amendment {
  id: string;
  field_name: string;
  original_text: string;
  amended_text: string;
  reason: string;
  author: PersonBrief;
  created_at: string;
}

export interface RxItem {
  id: string;
  item: string | null;
  drug_name: string;
  strength: string;
  dosage_form: string;
  dose: string;
  route: string;
  frequency: string;
  duration_days: number | null;
  quantity: string;
  quantity_dispensed: string;
  remaining: string;
  instructions: string;
  warnings: string;
  allergy_override_reason: string;
  unit: string;
}

export interface Prescription {
  id: string;
  encounter: string;
  visit_id: string;
  patient: PatientBrief;
  prescriber: PersonBrief;
  /** Printed on the prescription, e.g. RX-2026-00042. */
  number?: string;
  prescriber_details?: Clinician;
  status: "active" | "partial" | "dispensed" | "not_collected" | "cancelled" | "external";
  notes: string;
  cancel_reason: string;
  controlled_class: string;
  special_form_serial: string;
  patient_weight_kg: string | null;
  created_at: string;
  items: RxItem[];
}

export const NOTE_FIELDS = [
  "chief_complaint",
  "complaint_duration",
  "history_present_illness",
  "past_medical_history",
  "surgical_history",
  "family_history",
  "medication_history",
  "allergy_notes",
  "general_appearance",
  "physical_examination",
  "systems_examination",
  "assessment",
  "differential_diagnosis",
  "plan",
  "non_drug_treatment",
  "follow_up_instructions",
  "exam_heent",
  "exam_lgs",
  "exam_resp",
  "exam_cvs",
  "exam_abd",
  "exam_gus",
  "exam_cns",
] as const;
export type NoteField = (typeof NOTE_FIELDS)[number];

export type Encounter = {
  id: string;
  visit: string;
  patient: PatientBrief;
  doctor: PersonBrief;
  doctor_details?: Clinician;
  status: "draft" | "signed";
  version: number;
  follow_up_date: string | null;
  signed_at: string | null;
  created_at: string;
  updated_at: string;
  diagnoses: Diagnosis[];
  amendments: Amendment[];
  prescriptions: Prescription[];
} & Record<NoteField, string>;

export interface EncounterSummary {
  id: string;
  visit: string;
  doctor: PersonBrief;
  status: "draft" | "signed";
  chief_complaint: string;
  signed_at: string | null;
  created_at: string;
  diagnoses: string[];
}

export interface LabTest {
  /** Version for edit-conflict protection; send it back when saving. */
  row_version?: number;
  id: string;
  code: string;
  name: string;
  category: string;
  specimen_type: string;
  result_type: "numeric" | "qualitative" | "choice" | "text";
  unit: string;
  ref_low: string | null;
  ref_high: string | null;
  ref_text: string;
  choices: string;
  normal_choice: string;
  critical_low: string | null;
  critical_high: string | null;
  critical_choices: string;
  price: string;
  is_active: boolean;
  ranges: LabRange[];
  answers: string[];
}

export interface LabRange {
  id?: number;
  sex: "" | "female" | "male";
  age_min_days: number;
  age_max_days: number | null;
  ref_low: string | null;
  ref_high: string | null;
  ref_text: string;
  critical_low: string | null;
  critical_high: string | null;
}

export type LabFlag = "" | "N" | "L" | "H" | "A" | "LL" | "HH" | "AA";

export interface LabItem {
  id: string;
  test: LabTest;
  status: "ordered" | "collected" | "resulted" | "verified" | "cancelled";
  price: string;
  is_chargeable: boolean;
  repeat_of: string | null;
  repeat_reason: string;
  specimen_type: string;
  specimen_label: string;
  collected_at: string | null;
  collected_by: PersonBrief | null;
  result_numeric: string | null;
  result_text: string;
  display_result: string;
  unit: string;
  ref_low: string | null;
  ref_high: string | null;
  ref_text: string;
  critical_low: string | null;
  critical_high: string | null;
  flag: LabFlag;
  is_critical: boolean;
  result_comment: string;
  entered_by: PersonBrief | null;
  entered_at: string | null;
  verified_by: PersonBrief | null;
  verified_at: string | null;
  cancel_reason: string;
  critical_reported_to: string;
  critical_reported_at: string | null;
  critical_reported_by: PersonBrief | null;
  critical_acknowledged_at: string | null;
  critical_acknowledged_by: PersonBrief | null;
  amendments: {
    id: string;
    previous_numeric: string | null;
    previous_text: string;
    previous_flag: string;
    reason: string;
    author: PersonBrief;
    created_at: string;
  }[];
}

export interface LabOrder {
  id: string;
  accession_number: string;
  patient: PatientBrief;
  visit: string;
  encounter: string | null;
  ordered_by: PersonBrief;
  priority: "routine" | "urgent";
  status: "ordered" | "in_progress" | "completed" | "cancelled";
  clinical_notes: string;
  external_requester?: string;
  external_facility?: string;
  created_at: string;
  items: LabItem[];
}

export interface StockItem {
  /** Version for edit-conflict protection; send it back when saving. */
  row_version?: number;
  id: string;
  code: string;
  name: string;
  generic_name: string;
  brand_name: string;
  category: string;
  pack_unit?: string;
  units_per_pack?: string | null;
  dosage_form: string;
  strength: string;
  unit: string;
  route: string;
  therapeutic_category: string;
  controlled_class: "" | "psychotropic" | "narcotic";
  allergy_groups: string;
  warnings: string;
  default_supplier: string | null;
  reorder_level: string;
  selling_price: string;
  is_active: boolean;
  on_hand: string | null;
  usable: string | null;
  is_low: boolean;
  batches?: Batch[];
}

export interface Batch {
  id: string;
  item: string;
  item_code: string;
  item_name: string;
  unit: string;
  batch_number: string;
  expiry_date: string | null;
  unit_cost: string;
  supplier_name: string;
  on_hand: string;
  created_at: string;
}

export interface Supplier {
  /** Version for edit-conflict protection; send it back when saving. */
  row_version?: number;
  id: string;
  name: string;
  contact_person: string;
  phone: string;
  email: string;
  address: string;
  tin: string;
  is_active: boolean;
}

export interface Movement {
  id: string;
  item: string;
  item_name: string;
  batch: string;
  batch_number: string;
  kind: "receipt" | "dispense" | "adjustment" | "expired";
  quantity: string;
  reason: string;
  reference_type: string;
  is_override: boolean;
  created_by: PersonBrief;
  created_at: string;
}

export interface Purchase {
  id: string;
  supplier: Supplier;
  supplier_invoice_no: string;
  purchase_date: string;
  notes: string;
  total_cost: string;
  received_by: PersonBrief;
  line_count: number;
  created_at: string;
}

export interface Dispensation {
  id: string;
  prescription_id: string;
  patient: PatientBrief;
  item_name: string;
  unit: string;
  quantity: string;
  unit_price: string;
  override_approval: string | null;
  dispensed_by: PersonBrief;
  dispensed_at: string;
}

export interface Approval {
  id: string;
  kind: "dispense_override" | "discount" | "invoice_void" | "refund";
  kind_label: string;
  status: "pending" | "approved" | "rejected" | "used" | "cancelled";
  object_type: string;
  object_id: string;
  summary: string;
  amount: string | null;
  quantity: string | null;
  reason: string;
  requested_by: PersonBrief;
  decided_by: PersonBrief | null;
  decided_at: string | null;
  decision_note: string;
  created_at: string;
  can_decide: boolean;
}

export interface ServicePrice {
  /** Version for edit-conflict protection; send it back when saving. */
  row_version?: number;
  id: string;
  code: string;
  name: string;
  category: "consultation" | "procedure" | "other";
  price: string;
  tax_rate: string;
  is_active: boolean;
}

export interface InvoiceLine {
  id: string;
  kind: string;
  description: string;
  quantity: string;
  unit_price: string;
  line_total: string;
  tax_rate: string;
  source_type: string;
  is_void: boolean;
}

export interface Payment {
  id: string;
  receipt_number: string;
  invoice: string;
  invoice_number: string;
  patient_name: string;
  amount: string;
  method: "cash" | "telebirr" | "cbe_birr" | "bank_transfer" | "card" | "insurance";
  reference: string;
  received_by: PersonBrief;
  received_at: string;
  refunded?: string;
  refundable?: string;
}

export interface Refund {
  id: string;
  number: string;
  payment: string;
  receipt_number: string;
  amount: string;
  method: Payment["method"];
  reference: string;
  reason: string;
  approved_by: string;
  refunded_by: string;
  refunded_at: string;
}

export interface Invoice {
  id: string;
  number: string;
  patient: PatientBrief;
  visit: string | null;
  visit_date?: string | null;
  status: "draft" | "issued" | "partial" | "paid" | "void";
  subtotal?: string;
  discount_amount?: string;
  tax_amount?: string;
  total: string;
  amount_paid: string;
  balance: string;
  void_reason?: string;
  issued_at: string | null;
  created_at: string;
  lines?: InvoiceLine[];
  payments?: Payment[];
  refunds?: Refund[];
  new_payment?: Payment;
}

export interface Notice {
  id: string;
  kind: string;
  title: string;
  body: string;
  link: string;
  created_at: string;
  read_at: string | null;
}

export interface ReportInfo {
  key: string;
  title: string;
  description: string;
  uses_dates: boolean;
  /** Can be limited to one department (never the financial reports). */
  by_department?: boolean;
}

export interface ReportResult extends ReportInfo {
  department?: string;
  department_name?: string;
  date_from: string;
  date_to: string;
  generated_at: string;
  columns: { key: string; label: string; kind: "text" | "number" | "money" | "date" }[];
  rows: Record<string, string | number | null>[];
  can_export: boolean;
}

export interface Clinician {
  id: string;
  full_name: string;
  job_title: string;
  registration_number: string;
}

export interface Referral {
  id: string;
  number: string;
  encounter: string;
  patient: PatientBrief;
  to_facility: string;
  to_department: string;
  urgency: "routine" | "urgent" | "emergency";
  reason: string;
  clinical_summary: string;
  treatment_given: string;
  status: "issued" | "cancelled";
  cancel_reason: string;
  referred_by: Clinician;
  created_at: string;
  visit_date: string;
}

export interface Certificate {
  id: string;
  number: string;
  encounter: string;
  patient: PatientBrief;
  kind: "sick_leave" | "fitness" | "attendance";
  start_date: string | null;
  end_date: string | null;
  days: number | null;
  include_diagnosis: boolean;
  diagnosis_text: string;
  remarks: string;
  is_cancelled: boolean;
  cancel_reason: string;
  issued_by: Clinician;
  created_at: string;
}

export interface ClinicSettings {
  facility_name: string;
  facility_level: string;
  license_number: string;
  address: string;
  phone: string;
  tin: string;
  lab_billing_point: "ordered" | "collected" | "verified";
  show_ethiopian_calendar: boolean;
  row_version?: number;
  has_logo?: boolean;
  logo_version?: string | null;
  /** Short footers printed at the bottom of each kind of document. */
  note_patient_card?: string;
  note_prescription?: string;
  note_consultation?: string;
  note_referral?: string;
  note_lab_report?: string;
  note_certificate?: string;
  /** Waiting list: highlight patients waiting longer than this (minutes). */
  wait_alert_minutes?: number;
  /** Reception may send a patient straight to the doctor without triage. */
  allow_skip_triage?: boolean;
  /** Close a finished visit this many minutes after signing; 0 = staff close visits. */
  auto_complete_minutes?: number;
  /** Opening hours by weekday ("mon".."sun"); null = closed that day; empty object = no limit. */
  opening_hours?: Record<string, { open: string; close: string } | null>;
  setup_checklist_hidden?: boolean;
}

export interface ClinicalSummary {
  known_conditions: string;
  past_history: string;
  current_medications: string;
  allergies: { substance: string; severity: string; reaction: string }[];
  diagnoses: { code: string; description: string; certainty: string; date: string }[];
  results: { test: string; result: string; unit: string; flag: string; date: string }[];
  recent_prescriptions: {
    drug: string;
    dose: string;
    frequency: string;
    days: number | null;
    date: string;
    status: string;
  }[];
  visit_count: number;
  last_visit: string | null;
}

export interface InternalReferral {
  id: string;
  visit: string;
  patient: string;
  from_encounter: string;
  from_department: string;
  from_department_name: string;
  to_department: string;
  to_department_name: string;
  to_doctor: { id: string; full_name: string } | null;
  urgency: "routine" | "urgent" | "emergency";
  reason: string;
  status: "pending" | "seen" | "cancelled";
  referred_by: string;
  seen_by: string | null;
  seen_at: string | null;
  cancel_reason: string;
  created_at: string;
}
