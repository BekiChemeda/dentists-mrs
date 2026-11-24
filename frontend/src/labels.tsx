/** Display labels and badge tones for domain states, in one place so every screen agrees. */
import { useTranslation } from "react-i18next";
import { useGet } from "./api/hooks";
import type { Department } from "./api/types";
import { Badge, type BadgeTone } from "./ui";

const VISIT: Record<string, [string, BadgeTone]> = {
  waiting_triage: ["Waiting for triage", "wait"],
  waiting_doctor: ["Waiting for doctors", "wait"],
  in_consultation: ["Being managed", "info"],
  after_consult: ["After consultation", "info"],
  completed: ["Completed", "ok"],
  cancelled: ["Cancelled", "muted"],
};
const OUTCOME: Record<string, [string, BadgeTone]> = {
  completed: ["Care completed", "ok"],
  follow_up: ["Follow-up booked", "ok"],
  referred: ["Referred", "info"],
  left_early: ["Left before completion", "wait"],
};
const APPOINTMENT: Record<string, [string, BadgeTone]> = {
  scheduled: ["Scheduled", "muted"],
  confirmed: ["Confirmed", "info"],
  arrived: ["Arrived", "wait"],
  in_consultation: ["In consultation", "info"],
  completed: ["Completed", "ok"],
  cancelled: ["Cancelled", "muted"],
  no_show: ["No-show", "danger"],
};
const PRIORITY: Record<string, [string, BadgeTone]> = {
  routine: ["Routine", "muted"],
  urgent: ["Urgent", "wait"],
  emergency: ["Emergency", "danger"],
};
const LAB_ITEM: Record<string, [string, BadgeTone]> = {
  ordered: ["Awaiting specimen", "wait"],
  collected: ["Specimen collected", "info"],
  resulted: ["Awaiting verification", "wait"],
  verified: ["Verified", "ok"],
  cancelled: ["Cancelled", "muted"],
};
const LAB_ORDER: Record<string, [string, BadgeTone]> = {
  ordered: ["Ordered", "wait"],
  in_progress: ["In progress", "info"],
  completed: ["Completed", "ok"],
  cancelled: ["Cancelled", "muted"],
};
const RX: Record<string, [string, BadgeTone]> = {
  active: ["To dispense", "wait"],
  partial: ["Partly dispensed", "info"],
  dispensed: ["Dispensed", "ok"],
  not_collected: ["Not collected", "muted"],
  cancelled: ["Cancelled", "muted"],
  external: ["Printed for an outside pharmacy", "info"],
};
const INVOICE: Record<string, [string, BadgeTone]> = {
  draft: ["Draft", "muted"],
  issued: ["Unpaid", "wait"],
  partial: ["Partly paid", "info"],
  paid: ["Paid", "ok"],
  void: ["Void", "danger"],
};
const APPROVAL: Record<string, [string, BadgeTone]> = {
  pending: ["Waiting for decision", "wait"],
  approved: ["Approved, not yet used", "ok"],
  rejected: ["Rejected", "danger"],
  used: ["Used", "muted"],
  cancelled: ["Withdrawn", "muted"],
};

const SETS = {
  visit: VISIT,
  outcome: OUTCOME,
  appointment: APPOINTMENT,
  priority: PRIORITY,
  labItem: LAB_ITEM,
  labOrder: LAB_ORDER,
  rx: RX,
  invoice: INVOICE,
  approval: APPROVAL,
};

/** Plain-text label for a state (for <option> elements, where a badge cannot go). */
export function useStateLabel(): (set: keyof typeof SETS, value: string) => string {
  const { t } = useTranslation();
  return (set, value) => t(`state.${set}.${value}`, SETS[set][value]?.[0] ?? value);
}

export function StateBadge({ set, value }: { set: keyof typeof SETS; value: string }) {
  const { t } = useTranslation();
  const [label, tone] = SETS[set][value] ?? [value, "muted" as BadgeTone];
  return <Badge tone={tone}>{t(`state.${set}.${value}`, label)}</Badge>;
}

export const PAYMENT_METHODS: { key: string; label: string }[] = [
  { key: "cash", label: "Cash" },
  { key: "telebirr", label: "telebirr" },
  { key: "cbe_birr", label: "CBE Birr" },
  { key: "mpesa", label: "M-Pesa" },
  { key: "ebirr", label: "E-birr" },
  { key: "bank_transfer", label: "Bank transfer" },
  { key: "card", label: "Card" },
  { key: "insurance", label: "Insurance / credit" },
];

export const NOTE_LABELS: Record<string, string> = {
  chief_complaint: "Main complaint",
  complaint_duration: "Duration",
  history_present_illness: "History of present illness",
  past_medical_history: "Past medical & surgical history",
  surgical_history: "Previous operations",
  family_history: "Family history",
  medication_history: "Medication history",
  allergy_notes: "Allergy history",
  general_appearance: "General appearance",
  physical_examination: "Examination findings",
  systems_examination: "System-specific findings",
  assessment: "Clinical assessment",
  differential_diagnosis: "Differential diagnoses",
  plan: "Treatment plan",
  non_drug_treatment: "Advice and non-drug treatment",
  follow_up_instructions: "Follow-up instructions",
  exam_heent: "HEENT",
  exam_lgs: "LGS",
  exam_resp: "RESP",
  exam_cvs: "CVS",
  exam_abd: "ABD",
  exam_gus: "GUS",
  exam_cns: "CNS",
};

export const GENERAL_APPEARANCE: { key: string; label: string }[] = [
  { key: "acute_sick", label: "Acute sick looking" },
  { key: "chronic_sick", label: "Chronic sick looking" },
  { key: "acute_on_chronic", label: "Acute on chronic sick looking" },
];
export const generalAppearanceLabel = (v: string) => GENERAL_APPEARANCE.find((g) => g.key === v)?.label ?? v;

/**
 * Triage destinations are departments managed by the clinic administrator. This hook returns a
 * code → name lookup (codes are kept on records, so renamed departments still display).
 */
export function useTriageLabel(): (code: string) => string {
  const q = useGet<Department[]>(["departments", "all"], "/departments/", { staleTime: 300_000 });
  return (code: string) => q.data?.find((d) => d.code === code)?.name ?? code;
}

/** Active departments that receive patients from triage, in clinic order. */
export function useTriageDestinations(): Department[] {
  const q = useGet<Department[]>(["departments", "all"], "/departments/", { staleTime: 300_000 });
  return (q.data ?? []).filter((d) => d.receives_triage && d.is_active);
}

/** Prescription frequencies, as clinicians write them. Must match the server's list. */
export const FREQUENCIES = ["Daily", "BID", "TID", "QID", "STAT", "PRN", "Nocte", "Weekly"];

/** The code clinicians write, with plain words so nobody has to guess. */
export const FREQUENCY_LABELS: Record<string, string> = {
  Daily: "Once a day",
  BID: "BID: twice a day",
  TID: "TID: three times a day",
  QID: "QID: four times a day",
  STAT: "STAT: once, immediately",
  PRN: "PRN: when needed",
  Nocte: "Nocte: at night",
  Weekly: "Once a week",
};

/** A quantity without trailing zeros: "15.000" becomes "15", "2.500" becomes "2.5". */
export function qty(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  return Number.isFinite(n) ? String(n) : String(v);
}

/** The evaluation note in the order it is written. Signing needs the complaint, a diagnosis and the plan. */
export const NOTE_GROUPS: { title: string; fields: string[]; hint?: Record<string, string> }[] = [
  { title: "1. Presenting complaint", fields: ["chief_complaint", "complaint_duration"] },
  {
    title: "2. History of present illness",
    fields: ["history_present_illness"],
    hint: { history_present_illness: "Onset, location, severity, progression, associated symptoms, relevant history" },
  },
  {
    title: "3. Past medical & surgical history",
    fields: ["past_medical_history", "family_history", "medication_history", "allergy_notes"],
  },
  { title: "4. Physical examination", fields: ["general_appearance"] },
];
// 5. Physician diagnosis (ICD-10) and 6. Treatment plan follow as their own sections on the visit page.
export const SHORT_NOTE_FIELDS = new Set(["complaint_duration"]);

export const FLAG_LABEL: Record<string, string> = {
  H: "High",
  L: "Low",
  A: "Abnormal",
  N: "Normal",
  HH: "Critically high",
  LL: "Critically low",
  AA: "Critical",
  "": "",
};
export const isCriticalFlag = (f: string) => f === "LL" || f === "HH" || f === "AA";
