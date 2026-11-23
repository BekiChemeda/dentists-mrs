/** Small helpers shared by the dental screens. */
import { useTranslation } from "react-i18next";
import { useGet } from "../../api/hooks";
import type { PersonBrief } from "../../api/types";
import { Badge, type BadgeTone } from "../../ui";
import type { DentalCatalog } from "./types";

export function useDentalCatalog() {
  return useGet<DentalCatalog>(["dental", "catalog"], "/dental/catalog/", { staleTime: 5 * 60_000 });
}

export function useClinicians() {
  return useGet<{ clinicians: PersonBrief[]; assistants: PersonBrief[] }>(
    ["dental", "clinicians"],
    "/dental/clinicians/",
    { staleTime: 5 * 60_000 },
  );
}

const TONES: Record<string, BadgeTone> = {
  draft: "wait",
  signed: "ok",
  presented: "info",
  accepted: "ok",
  partially_accepted: "ok",
  deferred: "wait",
  declined: "muted",
  in_progress: "info",
  completed: "ok",
  cancelled: "muted",
  expired: "muted",
  proposed: "wait",
  session_completed: "info",
  not_performed: "muted",
  due: "wait",
  booked: "info",
  postponed: "wait",
  unreachable: "danger",
  requested: "wait",
  ready: "ok",
  delivered: "ok",
  active: "ok",
  withdrawn: "muted",
};

const LABELS: Record<string, string> = {
  draft: "Draft",
  signed: "Signed",
  presented: "Presented",
  accepted: "Accepted",
  partially_accepted: "Partially accepted",
  deferred: "Deferred",
  declined: "Declined",
  in_progress: "In progress",
  completed: "Completed",
  cancelled: "Cancelled",
  expired: "Expired",
  proposed: "Awaiting decision",
  session_completed: "Session done",
  not_performed: "Not performed",
  due: "Due",
  booked: "Booked",
  postponed: "Postponed",
  unreachable: "Unreachable",
  requested: "Requested",
  ready: "Ready",
  delivered: "Delivered",
  active: "Active",
  withdrawn: "Withdrawn",
};

export function DentalStatus({ value }: { value: string }) {
  const { t } = useTranslation();
  return <Badge tone={TONES[value] ?? "muted"}>{t(`dental.status_${value}`, LABELS[value] ?? value)}</Badge>;
}

export const NOTE_GROUPS: { title: string; fields: [string, string, "short" | "long"][] }[] = [
  {
    title: "Complaint",
    fields: [
      ["chief_complaint", "Chief complaint", "long"],
      ["history_of_complaint", "History of the present complaint", "long"],
      ["patient_description", "In the patient's own words", "long"],
    ],
  },
  {
    title: "Pain",
    fields: [
      ["pain_location", "Location or region", "short"],
      ["pain_onset", "Onset", "short"],
      ["pain_duration", "Duration", "short"],
      ["pain_triggers", "Triggers", "short"],
      ["pain_relief", "Relieving factors", "short"],
      ["swelling", "Swelling or associated symptoms", "short"],
    ],
  },
  {
    title: "History reviewed today",
    fields: [
      ["medical_history_review", "Medical history", "long"],
      ["dental_history_review", "Dental history", "long"],
    ],
  },
  {
    title: "Extraoral examination",
    fields: [
      ["extraoral_symmetry", "Facial symmetry", "short"],
      ["extraoral_swelling", "Swelling", "short"],
      ["extraoral_lymph_nodes", "Lymph nodes", "short"],
      ["extraoral_jaw_movement", "Jaw movement", "short"],
      ["extraoral_tmj", "Temporomandibular joint", "short"],
      ["extraoral_other", "Other extraoral findings", "long"],
    ],
  },
  {
    title: "Intraoral examination",
    fields: [
      ["intraoral_mucosa", "Oral mucosa", "short"],
      ["intraoral_tongue", "Tongue", "short"],
      ["intraoral_floor_of_mouth", "Floor of mouth", "short"],
      ["intraoral_palate", "Palate", "short"],
      ["intraoral_gingiva", "Gingiva", "short"],
      ["intraoral_saliva", "Saliva and dryness", "short"],
      ["intraoral_occlusion", "Occlusion and bite", "short"],
      ["intraoral_soft_tissue", "Soft tissue lesions", "long"],
      ["intraoral_other", "Other intraoral findings", "long"],
    ],
  },
  {
    title: "Assessment and plan",
    fields: [
      ["assessment", "Diagnostic assessment", "long"],
      ["proposed_treatment", "Proposed treatment", "long"],
      ["discussion_notes", "Discussion with the patient", "long"],
      ["consent_notes", "Consent notes", "long"],
      ["follow_up_instructions", "Follow-up instructions", "long"],
    ],
  },
];

export const NOTE_LABEL: Record<string, string> = Object.fromEntries(
  NOTE_GROUPS.flatMap((g) => g.fields.map(([k, label]) => [k, label])),
);

export const PROCEDURE_TEXT_FIELDS: [string, string][] = [
  ["findings_before", "Findings before"],
  ["notes", "Procedure notes"],
  ["anaesthesia", "Anaesthesia (as given)"],
  ["findings_after", "Findings after"],
  ["complications", "Complications or unexpected events"],
  ["post_op_instructions", "Post-procedure instructions"],
  ["follow_up_recommendation", "Follow-up recommendation"],
];

export const PENDING_REVIEW_NOTE =
  "Starter list — pending clinical review. Names, symbols and prices must be checked by the clinic's dentists.";
