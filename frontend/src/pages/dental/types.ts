/** Shapes returned by /api/v1/dental/. */
import type { PatientBrief, PersonBrief } from "../../api/types";

export interface Location {
  scope: "tooth" | "surfaces" | "region" | "mouth";
  tooth: number | null;
  surfaces: string;
  region: string;
  label: string;
}

export interface FindingType {
  id: string;
  code: string;
  name: string;
  kind: "state" | "condition" | "existing";
  applies_to: "tooth" | "surface" | "either" | "area";
  symbol: string;
  color: string;
  description?: string;
  is_active?: boolean;
  sort_order?: number;
  review_status?: string;
  row_version?: number;
}

export interface Finding {
  id: string;
  encounter: string;
  encounter_signed_at: string | null;
  location: Location;
  finding_type: Pick<FindingType, "id" | "code" | "name" | "kind" | "symbol" | "color">;
  is_existing_work: boolean;
  note: string;
  diagnosis: { id: string; code: string; term: string } | null;
  procedure: string | null;
  recorded_by: PersonBrief;
  recorded_at: string;
  resolved_at: string | null;
  resolved_in: string | null;
  resolved_by: PersonBrief | null;
  resolution_note: string;
  voided_at: string | null;
  voided_by: PersonBrief | null;
  void_reason: string;
}

export interface DentalProcedure {
  id: string;
  code: string;
  name: string;
  category: string;
  description: string;
  default_minutes: number;
  price: string;
  tax_rate: string;
  is_active: boolean;
  tooth_requirement: "required" | "optional" | "none";
  surfaces_allowed: boolean;
  consumes_stock: boolean;
  typical_sessions: number;
  billing_mode: "on_completion" | "per_session";
  follow_up_kind: string;
  follow_up_days: number | null;
  performer_roles: string[];
  review_status: string;
  default_materials: { item_id: string; item: string; unit: string; quantity: string }[];
  row_version: number;
}

export interface DentalCatalog {
  finding_types: FindingType[];
  procedures: DentalProcedure[];
  procedure_categories: [string, string][];
  risk_questions: [string, string][];
  risk_answers: string[];
  surfaces: Record<string, string>;
  regions: Record<string, string>;
  scopes: Record<string, string>;
  perio_sites: string[];
  image_kinds: [string, string][];
  recall_kinds: [string, string][];
  lab_case_types: [string, string][];
  plan_item_priorities: [string, string][];
  roles?: [string, string][];
}

export interface DiagnosisTerm {
  id: string;
  code_system: string;
  code: string;
  term: string;
  category: string;
  source_version: string;
  is_active: boolean;
  review_status: string;
  row_version: number;
}

export interface DentalDiagnosis {
  id: string;
  encounter: string;
  code_system: string;
  code: string;
  term_text: string;
  source_version: string;
  certainty: "suspected" | "confirmed";
  status: "active" | "historical" | "resolved";
  notes: string;
  location: Location;
  recorded_by: PersonBrief;
  created_at: string;
  resolved_at: string | null;
  resolution_note: string;
}

export interface RiskReview {
  id: string;
  encounter: string | null;
  reviewed_by: PersonBrief;
  reviewed_at: string;
  answers: Record<string, { answer: string; detail: string }>;
  allergies_reviewed: boolean;
  medications_reviewed: boolean;
  notes: string;
  changed_since_previous: boolean | null;
}

export interface DentalProfile {
  id: string;
  previous_treatment: string;
  extraction_history: string;
  root_canal_history: string;
  orthodontic_history: string;
  prosthesis_history: string;
  oral_hygiene: string;
  tobacco_use: "" | "never" | "former" | "current";
  tobacco_notes: string;
  other_habits: string;
  anxiety_notes: string;
  communication_notes: string;
  updated_by: PersonBrief | null;
  updated_at: string;
  row_version: number;
}

export interface ProcedureRecordBrief {
  id: string;
  number: string;
  patient: string;
  visit: string;
  encounter: string;
  plan_item: string | null;
  procedure: { id: string; code: string; name: string; category: string; billing_mode: string };
  location: Location;
  performed_by: PersonBrief;
  session_number: number;
  status: "draft" | "completed" | "session_completed" | "not_performed";
  signed_at: string | null;
  price: string | null;
  created_at: string;
}

export interface ProcedureRecord extends ProcedureRecordBrief {
  assisted_by: PersonBrief | null;
  started_at: string | null;
  completed_at: string | null;
  findings_before: string;
  findings_after: string;
  notes: string;
  anaesthesia: string;
  complications: string;
  post_op_instructions: string;
  follow_up_recommendation: string;
  follow_up_days: number | null;
  not_performed_reason: string;
  signed_by: PersonBrief | null;
  version: number;
  materials: { id: string; item_id: string; item: string; unit: string; quantity: string; note: string }[];
  amendments: {
    id: string;
    field_name: string;
    original_text: string;
    amended_text: string;
    reason: string;
    author: PersonBrief;
    created_at: string;
  }[];
  billed: { invoice_id: string; invoice_number: string; status: string } | null;
  charge: {
    price: string;
    estimate: string | null;
    expected_total: string | null;
    billing_mode: string;
    warning: "no_price" | "differs_from_estimate" | null;
  } | null;
}

export interface DentalEncounter {
  id: string;
  visit: string;
  visit_status: string;
  patient: PatientBrief;
  dentist: PersonBrief;
  status: "draft" | "signed";
  version: number;
  signed_at: string | null;
  created_at: string;
  risk_review: RiskReview | null;
  diagnoses: DentalDiagnosis[];
  findings: Finding[];
  amendments: {
    id: string;
    field_name: string;
    original_text: string;
    amended_text: string;
    reason: string;
    author: PersonBrief;
    created_at: string;
  }[];
  procedures: ProcedureRecordBrief[];
  prescriptions: {
    id: string;
    number: string;
    status: string;
    items: {
      drug_name: string;
      dose: string;
      frequency: string;
      duration_days: number | null;
      quantity: string;
      instructions: string;
    }[];
  }[];
  has_periodontal: boolean;
  pain_present: boolean | null;
  pain_teeth: number[];
  pain_severity: number | null;
  pain_pattern: "" | "continuous" | "intermittent";
  pain_sensitivity: string[];
  mouth_opening_mm: number | null;
  follow_up_date: string | null;
  [note: string]: unknown;
}

export interface EncounterBrief {
  id: string;
  visit: string;
  patient: string;
  dentist: PersonBrief;
  status: "draft" | "signed";
  chief_complaint: string;
  signed_at: string | null;
  created_at: string;
  diagnoses: string[];
}

export interface PlanItem {
  id: string;
  sequence: number;
  procedure: { id: string; code: string; name: string; category: string };
  location: Location;
  diagnosis: { id: string; code: string; term: string } | null;
  priority: string;
  sessions_planned: number;
  sessions_done: number;
  estimated_minutes: number;
  estimated_fee: string;
  assigned_dentist: PersonBrief | null;
  notes: string;
  status: "proposed" | "accepted" | "deferred" | "declined" | "in_progress" | "completed" | "cancelled";
  decision_at: string | null;
  cancel_reason: string;
  appointments: { id: string; scheduled_at: string; status: string }[];
}

export interface TreatmentPlan {
  id: string;
  number: string;
  patient: PatientBrief;
  created_by: PersonBrief;
  encounter: string | null;
  title: string;
  clinical_reason: string;
  diagnoses: { id: string; code: string; term: string; location: string }[];
  status: string;
  revision: number;
  review_date: string | null;
  presented_at: string | null;
  decision_at: string | null;
  decision_note: string;
  cancel_reason: string;
  notes: string;
  created_at: string;
  updated_at: string;
  estimated_total: string;
  items: PlanItem[];
  row_version: number;
}

export interface PlanBrief {
  id: string;
  number: string;
  title: string;
  status: string;
  created_by: PersonBrief;
  created_at: string;
  presented_at: string | null;
  review_date: string | null;
  estimated_total: string;
  item_counts: Record<string, number>;
}

export interface PerioSite {
  probing_depth_mm: number | null;
  gingival_margin_mm: number | null;
  cal_mm?: number | null;
  bleeding: boolean | null;
  plaque: boolean | null;
  suppuration: boolean | null;
  not_measured: boolean;
  not_measured_reason: string;
}

export interface PerioTooth {
  tooth: number;
  missing: boolean;
  excluded: boolean;
  exclusion_reason: string;
  implant: boolean;
  mobility: number | null;
  furcation: number | null;
  notes: string;
  furcation_applies?: boolean;
  sites: Record<string, PerioSite>;
}

export interface PerioExam {
  id: string;
  patient: string;
  encounter: string;
  encounter_status: string;
  examiner: PersonBrief;
  protocol: string;
  notes: string;
  version: number;
  created_at: string;
  teeth: PerioTooth[];
  summary: {
    teeth_charted: number;
    teeth_missing: number;
    teeth_excluded: number;
    sites_with_values: number;
    sites_not_measured: number;
    sites_possible: number;
    bleeding: { positive: number; assessed: number; percent: number | null };
    plaque: { positive: number; assessed: number; percent: number | null };
    suppuration: { positive: number; assessed: number; percent: number | null };
    pd_4_or_more: number;
    pd_6_or_more: number;
    deepest_pd: number | null;
    formula: string;
  };
}

export interface DentalImage {
  id: string;
  patient: string;
  encounter: string | null;
  kind: string;
  kind_label: string;
  captured_at: string | null;
  uploaded_at: string;
  uploaded_by: PersonBrief;
  referring_dentist: PersonBrief | null;
  teeth: number[];
  region: string;
  description: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
  width: number;
  height: number;
  status: "active" | "withdrawn";
  withdrawn_reason: string;
  replaces: string | null;
  changes: { field: string; old: string; new: string; reason: string; by: string; at: string }[];
}

export interface Recall {
  id: string;
  patient: { id: string; mrn: string; full_name: string };
  phone: string;
  kind: string;
  kind_label: string;
  due_date: string;
  note: string;
  status: string;
  appointment: { id: string; scheduled_at: string; status: string } | null;
  closed_reason: string;
  contacts: { outcome: string; note: string; by: string; at: string }[];
  created_at: string;
}

export interface LabCase {
  id: string;
  number: string;
  patient: { id: string; mrn: string; full_name: string };
  plan_item: string | null;
  case_type: string;
  case_type_label: string;
  teeth: number[];
  shade: string;
  instructions: string;
  technician: PersonBrief | null;
  due_date: string | null;
  status: "requested" | "in_progress" | "ready" | "delivered" | "cancelled";
  requested_by: PersonBrief;
  delivered_at: string | null;
  created_at: string;
  events: { status: string; note: string; by: string; at: string }[];
}

export interface DentalSummary {
  profile: DentalProfile;
  risk_review: RiskReview | null;
  shared_history: {
    allergies: { substance: string; severity: string; reaction: string }[];
    known_conditions: string;
    past_history: string;
    current_medications: string;
  };
  encounters: EncounterBrief[];
  plans: PlanBrief[];
  open_recalls: Recall[];
}
