/**
 * Orthodontics: the assessment in an examination, the treatment course (case) with its visits, retention, progress
 * photos, and payment: a package price paid in instalments, or a charge per visit. Starter vocabulary pending
 * clinical review.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { api, queryString } from "../../api/client";
import { useGet } from "../../api/hooks";
import type { Paginated, PersonBrief } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import {
  Badge,
  Banner,
  Empty,
  ErrorBanner,
  Field,
  Loading,
  Modal,
  PageHead,
  Pager,
  Panel,
  ReasonDialog,
  Segmented,
  money,
  toast,
  type BadgeTone,
} from "../../ui";
import { formatDateTime, formatDay } from "../../lib/format";
import { useDentalCatalog } from "./common";
import type { DentalImage } from "./types";
import { useUnsavedGuard } from "../../lib/unsaved";

// ---------------------------------------------------------------------------------------------------------- types
export interface OrthoAssessment {
  id: string;
  encounter: string;
  encounter_status: string;
  recorded_by: PersonBrief;
  created_at: string;
  version: number;
  [field: string]: unknown;
}

interface OrthoVisit {
  id: string;
  visit_date: string;
  kind: string;
  kind_label: string;
  upper_wire: string;
  lower_wire: string;
  elastics: string;
  aligner_number: number | null;
  breakages: string;
  oral_hygiene: string;
  compliance: string;
  notes: string;
  next_interval_weeks: number | null;
  performed_by: PersonBrief;
  created_at: string;
  charge: string | null;
  no_charge_reason: string;
  extra_charge: string;
  extra_charge_reason: string;
  status: "recorded" | "entered_in_error";
  void_reason: string;
}

interface Instalment {
  id: string;
  sequence: number;
  label: string;
  due_date: string;
  amount: string;
  state: "scheduled" | "due" | "overdue" | "invoiced" | "part_paid" | "paid" | "cancelled";
  status: string;
  cancelled_reason: string;
  invoice: { id: string; number: string; status: string } | null;
}

interface OrthoCaseBrief {
  id: string;
  number: string;
  patient: { id: string; mrn: string; full_name: string };
  orthodontist: PersonBrief;
  appliance: string;
  appliance_label: string;
  arches: string;
  status: "planned" | "active" | "retention" | "completed" | "discontinued";
  status_label: string;
  started_on: string | null;
  debonded_on: string | null;
  closed_on: string | null;
  expected_months: number | null;
  months_in_treatment: number | null;
  billing_mode: "package" | "per_visit";
  billing_label: string;
  package_price: string | null;
  per_visit_price: string | null;
  last_visit: { date: string; kind: string } | null;
}

interface OrthoCase extends OrthoCaseBrief {
  version: number;
  objectives: string;
  notes: string;
  closed_reason: string;
  retainer_upper: string;
  retainer_lower: string;
  retention_review_months: number | null;
  deposit: string;
  assessment: OrthoAssessment | null;
  plan: { id: string; number: string; title: string } | null;
  visits: OrthoVisit[];
  instalments: Instalment[];
  billing_summary: Record<string, string | null>;
  events: { action: string; note: string; by: string; at: string }[];
}

interface OrthoCatalog {
  appliances: [string, string][];
  arches: [string, string][];
  billing_modes: [string, string][];
  retainers: [string, string][];
  visit_kinds: [string, string][];
  angle: [string, string][];
  incisor: [string, string][];
  severity: [string, string][];
  skeletal: [string, string][];
  profile: [string, string][];
  hygiene: [string, string][];
}

function useOrthoCatalog(): OrthoCatalog | undefined {
  const catalog = useDentalCatalog();
  return (catalog.data as unknown as { ortho?: OrthoCatalog } | undefined)?.ortho;
}

const OPEN = ["planned", "active", "retention"];
const STATUS_TONE: Record<string, BadgeTone> = {
  planned: "wait",
  active: "ok",
  retention: "info",
  completed: "muted",
  discontinued: "muted",
};
const INSTALMENT: Record<Instalment["state"], [string, BadgeTone]> = {
  scheduled: ["Scheduled", "muted"],
  due: ["Due today", "wait"],
  overdue: ["Overdue", "danger"],
  invoiced: ["Invoiced, unpaid", "info"],
  part_paid: ["Part paid", "info"],
  paid: ["Paid", "ok"],
  cancelled: ["Cancelled", "muted"],
};
// Which visits can be recorded in each state (the server enforces the same).
const KINDS_WHEN: Record<string, string[]> = {
  planned: ["records", "bonding", "aligner", "other"],
  active: ["adjustment", "aligner", "emergency", "debond", "retainer_fit", "records", "bonding", "other"],
  retention: ["retention_review", "retainer_fit", "emergency", "records", "other"],
};
// In per-visit cases, these are charged unless the dentist says why not; fittings and removals are usually
// separate procedures from the catalogue.
const CHARGED_BY_DEFAULT = ["adjustment", "aligner", "emergency", "retention_review"];

function invalidate(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ["dental", "ortho"] });
  void qc.invalidateQueries({ queryKey: ["dental", "summary"] });
}

// ---------------------------------------------------------------------------------------------------------- assessment
const ASSESSMENT_CHOICES: [string, string, keyof OrthoCatalog][] = [
  ["molar_right", "Molar relationship, right", "angle"],
  ["molar_left", "Molar relationship, left", "angle"],
  ["canine_right", "Canine relationship, right", "angle"],
  ["canine_left", "Canine relationship, left", "angle"],
  ["incisor_relationship", "Incisor relationship", "incisor"],
  ["crowding_upper", "Crowding, upper", "severity"],
  ["crowding_lower", "Crowding, lower", "severity"],
  ["spacing_upper", "Spacing, upper", "severity"],
  ["spacing_lower", "Spacing, lower", "severity"],
  ["skeletal_pattern", "Skeletal pattern", "skeletal"],
  ["facial_profile", "Facial profile", "profile"],
  ["oral_hygiene", "Oral hygiene", "hygiene"],
];
const ASSESSMENT_SHORT_TEXT: [string, string, string?][] = [
  ["midline_upper", "Upper midline", "e.g. 2 mm to the right"],
  ["midline_lower", "Lower midline"],
  ["crossbite", "Crossbite (teeth)", "e.g. 12, 22 anterior crossbite"],
  ["extractions_planned", "Extractions planned", "e.g. 14, 24, 34, 44"],
  ["habits", "Habits", "e.g. thumb sucking, tongue thrust"],
  ["tmj", "Temporomandibular joint"],
];
const ASSESSMENT_LONG_TEXT: [string, string][] = [
  ["other_findings", "Other findings (impacted, missing, rotated teeth)"],
  ["problem_list", "Problem list"],
  ["objectives", "Treatment objectives"],
  ["treatment_options", "Treatment options discussed"],
  ["notes", "Notes"],
];
const ALL_ASSESSMENT_FIELDS = [
  ...ASSESSMENT_CHOICES.map(([k]) => k),
  "overjet_mm",
  "overbite_mm",
  ...ASSESSMENT_SHORT_TEXT.map(([k]) => k),
  ...ASSESSMENT_LONG_TEXT.map(([k]) => k),
];

const EVENT_LABELS: Record<string, string> = {
  create: "Case opened",
  start: "Treatment started",
  retention: "Moved to retention",
  complete: "Case completed",
  discontinue: "Case discontinued",
  billing_change: "Payment method changed",
  instalment_forward: "Instalment brought forward",
  visit_void: "Visit marked as entered in error",
  update: "Case details changed",
};

function eventLabel(action: string, t: (k: string, d: string) => string): string {
  const d = EVENT_LABELS[action];
  return d ? t(`dental.ortho_event_${action}`, d) : action.replace(/_/g, " ");
}

export function OrthoAssessmentForm({ encounterId, editable }: { encounterId: string; editable: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const ortho = useOrthoCatalog();
  const key = ["dental", "ortho", "assessment", encounterId];
  const current = useGet<OrthoAssessment | null>(key, `/dental/encounters/${encounterId}/ortho-assessment/`);
  const [f, setF] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  useUnsavedGuard(`ortho-assessment-${encounterId}`, dirty);
  useEffect(() => {
    if (dirty || current.data === undefined) return;
    const data = current.data ?? ({} as OrthoAssessment);
    setF(Object.fromEntries(ALL_ASSESSMENT_FIELDS.map((k) => [k, data[k] == null ? "" : String(data[k])])));
  }, [current.data, dirty]);
  const save = useMutation({
    mutationFn: () =>
      api.put<OrthoAssessment>(`/dental/encounters/${encounterId}/ortho-assessment/`, {
        ...(current.data ? { row_version: current.data.version } : {}),
        ...f,
      }),
    onSuccess: (data) => {
      qc.setQueryData(key, data);
      setDirty(false);
      invalidate(qc);
      toast(t("dental.ortho_assessment_saved", "Orthodontic assessment saved"));
    },
  });
  if (current.isLoading || !ortho) return <Loading />;
  const set = (k: string, v: string) => {
    setDirty(true);
    setF((c) => ({ ...c, [k]: v }));
  };
  const ro = !editable;
  return (
    <Panel
      title={t("dental.ortho_assessment", "Orthodontic assessment")}
      actions={
        current.data ? <span className="small muted">{`${current.data.recorded_by.full_name}`}</span> : undefined
      }
    >
      <div className="stack">
        <ErrorBanner error={save.error} onReload={() => setDirty(false)} />
        <div className="form-grid">
          {ASSESSMENT_CHOICES.map(([k, label, list]) => (
            <Field key={k} label={t(`dental.ortho_${k}`, label)} id={`oa-${k}`} error={save.error}>
              <select id={`oa-${k}`} value={f[k] ?? ""} disabled={ro} onChange={(e) => set(k, e.target.value)}>
                <option value="">—</option>
                {ortho[list].map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
          ))}
          <Field
            label={t("dental.ortho_overjet", "Overjet (mm)")}
            id="oa-overjet_mm"
            hint={t("dental.ortho_overjet_hint", "Negative for a reverse overjet")}
            error={save.error}
          >
            <input
              id="oa-overjet_mm"
              inputMode="decimal"
              value={f.overjet_mm ?? ""}
              disabled={ro}
              onChange={(e) => set("overjet_mm", e.target.value)}
            />
          </Field>
          <Field
            label={t("dental.ortho_overbite", "Overbite (mm)")}
            id="oa-overbite_mm"
            hint={t("dental.ortho_overbite_hint", "Negative for an open bite")}
            error={save.error}
          >
            <input
              id="oa-overbite_mm"
              inputMode="decimal"
              value={f.overbite_mm ?? ""}
              disabled={ro}
              onChange={(e) => set("overbite_mm", e.target.value)}
            />
          </Field>
          {ASSESSMENT_SHORT_TEXT.map(([k, label, hint]) => (
            <Field key={k} label={t(`dental.ortho_${k}`, label)} id={`oa-${k}`} hint={hint}>
              <input id={`oa-${k}`} value={f[k] ?? ""} disabled={ro} onChange={(e) => set(k, e.target.value)} />
            </Field>
          ))}
        </div>
        {ASSESSMENT_LONG_TEXT.map(([k, label]) => (
          <Field key={k} label={t(`dental.ortho_${k}`, label)} id={`oa-${k}`}>
            <textarea id={`oa-${k}`} value={f[k] ?? ""} disabled={ro} onChange={(e) => set(k, e.target.value)} />
          </Field>
        ))}
        {editable && (
          <div className="action-bar">
            <span className="small muted">
              {dirty ? t("consult.unsaved", "Unsaved changes") : t("consult.saved", "All changes saved")}
            </span>
            <button className="btn btn-primary" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
              {t("dental.ortho_save_assessment", "Save assessment")}
            </button>
          </div>
        )}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------------------------------------- case panel
/** The patient's orthodontic treatment: the open case in full, earlier cases below. */
export function OrthoPanel({ patientId, encounterId }: { patientId: string; encounterId?: string }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const data = useGet<{ cases: OrthoCase[]; assessments: OrthoAssessment[] }>(
    ["dental", "ortho", "patient", patientId],
    `/dental/patients/${patientId}/ortho/`,
  );
  const [creating, setCreating] = useState(false);
  if (data.isLoading) return <Loading />;
  if (data.error) return <ErrorBanner error={data.error} />;
  const cases = data.data?.cases ?? [];
  const open = cases.find((c) => OPEN.includes(c.status));
  const closed = cases.filter((c) => c !== open);
  return (
    <div className="stack">
      {!open && (
        <Panel title={t("dental.ortho_treatment", "Orthodontic treatment")}>
          <Empty>
            {t("dental.ortho_none", "No orthodontic treatment in progress.")}
            {can("dental.ortho.manage") && (
              <div style={{ marginTop: 12 }}>
                <button className="btn btn-primary" onClick={() => setCreating(true)}>
                  <Plus size={16} /> {t("dental.ortho_new_case", "Start orthodontic case")}
                </button>
              </div>
            )}
          </Empty>
        </Panel>
      )}
      {open && <OrthoCaseDetail c={open} encounterId={encounterId} patientId={patientId} />}
      {closed.length > 0 && (
        <Panel title={t("dental.ortho_earlier", "Earlier orthodontic cases")}>
          <table className="data">
            <tbody>
              {closed.map((c) => (
                <tr key={c.id}>
                  <td className="mono nowrap">{c.number}</td>
                  <td>{c.appliance_label}</td>
                  <td>
                    {c.started_on ? formatDay(c.started_on) : "—"} → {c.closed_on ? formatDay(c.closed_on) : "—"}
                  </td>
                  <td>
                    <Badge tone={STATUS_TONE[c.status]}>{c.status_label}</Badge>
                  </td>
                  <td className="small muted">{c.closed_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
      <Modal
        open={creating}
        title={t("dental.ortho_new_case", "Start orthodontic case")}
        onClose={() => setCreating(false)}
        wide
      >
        {creating && (
          <NewCaseForm
            patientId={patientId}
            assessments={data.data?.assessments ?? []}
            onDone={() => setCreating(false)}
          />
        )}
      </Modal>
    </div>
  );
}

function OrthoCaseDetail({ c, encounterId, patientId }: { c: OrthoCase; encounterId?: string; patientId: string }) {
  const { t } = useTranslation();
  const { can, moduleOn } = useAuth();
  const qc = useQueryClient();
  const manage = can("dental.ortho.manage");
  const ortho = useOrthoCatalog();
  const [dialog, setDialog] = useState<
    null | "visit" | "billing" | "details" | "discontinue" | "complete" | "retention"
  >(null);
  const [removedOn, setRemovedOn] = useState(today());
  const [voiding, setVoiding] = useState<OrthoVisit | null>(null);
  const act = useMutation({
    mutationFn: ({ action, reason, on_date }: { action: string; reason?: string; on_date?: string }) =>
      api.post<OrthoCase>(`/dental/ortho/cases/${c.id}/${action}/`, { reason: reason ?? "", on_date }),
    onSuccess: () => {
      invalidate(qc);
      setDialog(null);
      toast("Saved");
    },
  });
  const voidVisit = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api.post<OrthoCase>(`/dental/ortho/visits/${id}/void/`, { reason }),
    onSuccess: () => {
      invalidate(qc);
      setVoiding(null);
    },
  });
  const forward = useMutation({
    mutationFn: (id: string) => api.post<OrthoCase>(`/dental/ortho/instalments/${id}/bring-forward/`, {}),
    onSuccess: () => {
      invalidate(qc);
      toast(t("dental.ortho_brought_forward", "Due today: the cashier can now collect it"));
    },
  });
  const isOpen = OPEN.includes(c.status);
  const months =
    c.months_in_treatment == null
      ? "—"
      : `${c.months_in_treatment}${c.expected_months ? ` / ${c.expected_months}` : ""} ${t("dental.months", "months")}`;
  return (
    <div className="stack">
      <Panel
        title={`${t("dental.ortho_case", "Orthodontic case")} ${c.number}`}
        actions={
          <div className="row">
            <Badge tone={STATUS_TONE[c.status]}>{c.status_label}</Badge>
            {manage && isOpen && (
              <>
                <button className="btn btn-primary btn-sm" onClick={() => setDialog("visit")}>
                  {t("dental.ortho_record_visit", "Record orthodontic visit")}
                </button>
                {c.status === "planned" && (
                  <button className="btn btn-sm" onClick={() => act.mutate({ action: "start" })}>
                    {t("dental.ortho_start", "Start treatment")}
                  </button>
                )}
                {c.status === "active" && (
                  <button className="btn btn-sm" onClick={() => setDialog("retention")}>
                    {t("dental.ortho_to_retention", "Move to retention")}
                  </button>
                )}
                {c.status !== "planned" && (
                  <button className="btn btn-sm" onClick={() => setDialog("complete")}>
                    {t("dental.ortho_complete", "Complete case")}
                  </button>
                )}
                <button className="btn btn-sm" onClick={() => setDialog("details")}>
                  {t("dental.ortho_edit", "Edit details")}
                </button>
                <button className="btn btn-sm" onClick={() => setDialog("billing")}>
                  {t("dental.ortho_change_billing", "Change price or payment")}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => setDialog("discontinue")}>
                  {t("dental.ortho_discontinue", "Discontinue…")}
                </button>
              </>
            )}
          </div>
        }
      >
        <ErrorBanner error={act.error} />
        <dl className="facts">
          <dt>{t("dental.ortho_appliance", "Appliance")}</dt>
          <dd>
            {c.appliance_label} · {labelOf(ortho?.arches, c.arches)}
          </dd>
          <dt>{t("dental.ortho_orthodontist", "Dentist")}</dt>
          <dd>{c.orthodontist.full_name}</dd>
          <dt>{t("dental.ortho_started", "Started")}</dt>
          <dd>{c.started_on ? formatDay(c.started_on) : t("dental.ortho_not_started", "Not started")}</dd>
          <dt>{t("dental.ortho_in_treatment", "In treatment")}</dt>
          <dd>{months}</dd>
          {c.debonded_on && (
            <>
              <dt>{t("dental.ortho_debonded", "Braces removed")}</dt>
              <dd>{formatDay(c.debonded_on)}</dd>
            </>
          )}
          {(c.retainer_upper || c.retainer_lower) && (
            <>
              <dt>{t("dental.ortho_retainers", "Retainers")}</dt>
              <dd>
                {t("dental.upper", "Upper")}: {labelOf(ortho?.retainers, c.retainer_upper)} ·{" "}
                {t("dental.lower", "Lower")}: {labelOf(ortho?.retainers, c.retainer_lower)}
              </dd>
            </>
          )}
          <dt>{t("dental.ortho_last_visit", "Last visit")}</dt>
          <dd>{c.last_visit ? `${formatDay(c.last_visit.date)} · ${c.last_visit.kind}` : "—"}</dd>
          {c.objectives && (
            <>
              <dt>{t("dental.ortho_objectives", "Objectives")}</dt>
              <dd className="prewrap">{c.objectives}</dd>
            </>
          )}
          {c.closed_reason && (
            <>
              <dt>{t("dental.ortho_closed_reason", "Reason")}</dt>
              <dd>{c.closed_reason}</dd>
            </>
          )}
        </dl>
      </Panel>

      <OrthoPayment c={c} onForward={(id) => forward.mutate(id)} busy={forward.isPending} error={forward.error} />

      <Panel title={t("dental.ortho_visits", "Orthodontic visits")}>
        {c.visits.length === 0 ? (
          <Empty>{t("dental.ortho_no_visits", "No visits recorded yet.")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("common.date", "Date")}</th>
                  <th>{t("dental.ortho_visit_kind", "What was done")}</th>
                  <th>{t("dental.ortho_wires", "Wires (upper / lower)")}</th>
                  <th>{t("dental.ortho_elastics", "Elastics")}</th>
                  <th>{t("dental.ortho_hygiene_short", "Hygiene / wear")}</th>
                  <th>{t("dental.ortho_notes", "Notes")}</th>
                  <th>{t("dental.ortho_charged", "Charged")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {c.visits.map((v) => (
                  <tr key={v.id} className={v.status === "entered_in_error" ? "struck" : undefined}>
                    <td>
                      {formatDay(v.visit_date)}
                      <div className="small muted">{v.performed_by.full_name}</div>
                    </td>
                    <td>
                      {v.kind_label}
                      {v.aligner_number ? ` · ${t("dental.ortho_aligner", "aligner")} ${v.aligner_number}` : ""}
                      {v.next_interval_weeks ? (
                        <div className="small muted">
                          {t("dental.ortho_next_in", "Next in {{n}} weeks", { n: v.next_interval_weeks })}
                        </div>
                      ) : null}
                    </td>
                    <td className="mono small">
                      {v.upper_wire || "—"} / {v.lower_wire || "—"}
                    </td>
                    <td className="small">{v.elastics || "—"}</td>
                    <td className="small">
                      {labelOf(ortho?.hygiene, v.oral_hygiene)} / {labelOf(ortho?.hygiene, v.compliance)}
                    </td>
                    <td className="small">
                      {v.breakages && (
                        <div>
                          <strong>{t("dental.ortho_breakages", "Breakages")}:</strong> {v.breakages}
                        </div>
                      )}
                      {v.notes}
                      {v.status === "entered_in_error" && (
                        <div className="image-withdrawn">
                          {t("dental.entered_in_error", "Entered in error")}: {v.void_reason}
                        </div>
                      )}
                    </td>
                    <td className="small">
                      {v.status === "entered_in_error"
                        ? t("dental.not_charged_error", "Not charged (entered in error)")
                        : v.charge
                          ? `${money(v.charge)}`
                          : v.no_charge_reason
                            ? `— (${v.no_charge_reason})`
                            : "—"}
                      {v.status !== "entered_in_error" && Number(v.extra_charge) > 0 && (
                        <div>
                          + {money(v.extra_charge)} ({v.extra_charge_reason})
                        </div>
                      )}
                    </td>
                    <td>
                      {v.status === "recorded" && (can("dental.amend") || manage) && (
                        <button className="btn btn-ghost btn-sm" onClick={() => setVoiding(v)}>
                          {t("dental.entered_in_error_btn", "Entered in error…")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {moduleOn("dental_imaging") && can("dental.imaging.view") && (
        <ProgressPhotos patientId={patientId} since={c.started_on ?? c.closed_on ?? null} />
      )}

      {c.events.length > 0 && (
        <details>
          <summary>{t("dental.ortho_history", "Case history")}</summary>
          <ul className="plain-list small">
            {c.events.map((e, i) => (
              <li key={i}>
                {formatDateTime(e.at)} · {e.by} · <strong>{eventLabel(e.action, t)}</strong>
                {e.note ? ` — ${e.note}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}

      <Modal
        open={dialog === "visit"}
        title={t("dental.ortho_record_visit", "Record orthodontic visit")}
        onClose={() => setDialog(null)}
        wide
      >
        {dialog === "visit" && <VisitForm c={c} encounterId={encounterId} onDone={() => setDialog(null)} />}
      </Modal>
      <Modal
        open={dialog === "billing"}
        title={t("dental.ortho_change_billing", "Change price or payment")}
        onClose={() => setDialog(null)}
        wide
      >
        {dialog === "billing" && <BillingForm c={c} onDone={() => setDialog(null)} />}
      </Modal>
      <Modal open={dialog === "details"} title={t("dental.ortho_edit", "Edit details")} onClose={() => setDialog(null)}>
        {dialog === "details" && <DetailsForm c={c} onDone={() => setDialog(null)} />}
      </Modal>
      <ReasonDialog
        open={dialog === "discontinue"}
        title={t("dental.ortho_discontinue_title", "Discontinue orthodontic treatment")}
        label={t(
          "dental.ortho_discontinue_label",
          "Reason. Instalments not yet invoiced are cancelled; invoices already issued stay as they are.",
        )}
        confirmLabel={t("dental.ortho_discontinue_confirm", "Discontinue")}
        danger
        busy={act.isPending}
        error={act.error}
        onClose={() => setDialog(null)}
        onConfirm={(reason) => act.mutate({ action: "discontinue", reason })}
      />
      <ReasonDialog
        open={dialog === "complete"}
        title={t("dental.ortho_complete_title", "Complete orthodontic case")}
        label={t("dental.ortho_complete_label", "Outcome note")}
        confirmLabel={t("dental.ortho_complete", "Complete case")}
        busy={act.isPending}
        error={act.error}
        onClose={() => setDialog(null)}
        onConfirm={(reason) => act.mutate({ action: "complete", reason })}
      />
      <Modal
        open={dialog === "retention"}
        title={t("dental.ortho_to_retention", "Move to retention")}
        onClose={() => setDialog(null)}
      >
        <form
          className="stack-sm"
          onSubmit={(e) => {
            e.preventDefault();
            act.mutate({ action: "retention", on_date: removedOn });
          }}
        >
          <p className="muted">
            {t(
              "dental.ortho_retention_hint",
              "Use this when the braces have come off. If you are recording the removal visit now, use Record orthodontic visit and choose Braces removed instead.",
            )}
          </p>
          <ErrorBanner error={act.error} />
          <Field label={t("dental.ortho_removed_on", "Braces removed on")} id="f-removed_on">
            <input
              id="f-removed_on"
              type="date"
              value={removedOn}
              max={today()}
              min={c.started_on ?? undefined}
              onChange={(e) => setRemovedOn(e.target.value)}
              required
            />
          </Field>
          <div className="form-actions">
            <button type="button" className="btn" onClick={() => setDialog(null)}>
              {t("common.cancel")}
            </button>
            <button className="btn btn-primary" disabled={act.isPending || !removedOn}>
              {t("dental.ortho_to_retention", "Move to retention")}
            </button>
          </div>
        </form>
      </Modal>
      <ReasonDialog
        open={voiding !== null}
        title={t("dental.ortho_void_title", "Visit entered in error")}
        label={t("dental.reason", "Reason")}
        confirmLabel={t("dental.entered_in_error", "Entered in error")}
        danger
        busy={voidVisit.isPending}
        error={voidVisit.error}
        onClose={() => setVoiding(null)}
        onConfirm={(reason) => voiding && voidVisit.mutate({ id: voiding.id, reason })}
      />
    </div>
  );
}

function labelOf(list: [string, string][] | undefined, value: string): string {
  if (!value) return "—";
  return list?.find(([v]) => v === value)?.[1] ?? value;
}

function OrthoPayment({
  c,
  onForward,
  busy,
  error,
}: {
  c: OrthoCase;
  onForward: (id: string) => void;
  busy: boolean;
  error: unknown;
}) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const s = c.billing_summary;
  if (c.billing_mode === "per_visit")
    return (
      <Panel title={t("dental.ortho_payment", "Payment")}>
        <dl className="facts">
          <dt>{t("dental.ortho_billing", "Charged")}</dt>
          <dd>{c.billing_label}</dd>
          <dt>{t("dental.ortho_per_visit_price", "Price per visit")}</dt>
          <dd>{money(c.per_visit_price)} ETB</dd>
          <dt>{t("dental.ortho_charged_so_far", "Charged on visits so far")}</dt>
          <dd>{money(s.visits_charged)} ETB</dd>
          {Number(s.invoiced_instalments) > 0 && (
            <>
              <dt>{t("dental.ortho_earlier_instalments", "Earlier package instalments invoiced")}</dt>
              <dd>{money(s.invoiced_instalments)} ETB</dd>
            </>
          )}
        </dl>
        <p className="small muted">
          {t(
            "dental.ortho_per_visit_hint",
            "Each orthodontic visit is added to the patient's invoice for that visit. Fitting and removing braces, records and retainers are charged as procedures from the catalogue.",
          )}
        </p>
      </Panel>
    );
  const live = c.instalments.filter((i) => i.status === "scheduled");
  const cancelled = c.instalments.filter((i) => i.status === "cancelled");
  return (
    <Panel title={t("dental.ortho_payment", "Payment")}>
      <div className="stack-sm">
        <ErrorBanner error={error} />
        <div className="figures">
          <div className="figure">
            <b>{money(s.package_price)}</b>
            <span>{t("dental.ortho_package", "Package price (ETB)")}</span>
          </div>
          <div className="figure">
            <b>{money(s.paid)}</b>
            <span>{t("dental.ortho_paid", "Paid")}</span>
          </div>
          <div className="figure">
            <b>{money((Number(s.invoiced) - Number(s.paid)).toFixed(2))}</b>
            <span>{t("dental.ortho_invoiced_unpaid", "Invoiced, not yet paid")}</span>
          </div>
          <div className="figure">
            <b>{money(s.scheduled)}</b>
            <span>{t("dental.ortho_still_scheduled", "Still to be invoiced")}</span>
          </div>
          <div className={`figure${Number(s.overdue) > 0 ? " attention" : ""}`}>
            <b>{money(s.overdue)}</b>
            <span>{t("dental.ortho_overdue", "Overdue, not invoiced")}</span>
          </div>
        </div>
        <table className="data">
          <thead>
            <tr>
              <th>{t("dental.ortho_instalment", "Instalment")}</th>
              <th>{t("dental.ortho_due", "Due")}</th>
              <th className="num">{t("dental.amount", "Amount (ETB)")}</th>
              <th>{t("common.status", "Status")}</th>
              <th>{t("dental.ortho_invoice", "Invoice")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {live.map((i) => (
              <tr key={i.id}>
                <td>{i.label}</td>
                <td>{formatDay(i.due_date)}</td>
                <td className="num">{money(i.amount)}</td>
                <td>
                  <Badge tone={INSTALMENT[i.state][1]}>{t(`dental.inst_${i.state}`, INSTALMENT[i.state][0])}</Badge>
                </td>
                <td className="mono small">{i.invoice?.number ?? ""}</td>
                <td>
                  {i.state === "scheduled" && (can("dental.ortho.manage") || can("billing.invoice")) && (
                    <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onForward(i.id)}>
                      {t("dental.ortho_bring_forward", "Take payment today")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="small muted">
          {t(
            "dental.ortho_package_hint",
            "The cashier collects instalments that are due when making the patient's invoice (with or without a visit). Orthodontic visits are not charged separately; an extra charge (e.g. a lost retainer) is added to the visit.",
          )}
        </p>
        {cancelled.length > 0 && (
          <details>
            <summary className="small">
              {t("dental.ortho_cancelled_instalments", "Cancelled instalments ({{n}})", { n: cancelled.length })}
            </summary>
            <ul className="plain-list small">
              {cancelled.map((i) => (
                <li key={i.id}>
                  {i.label} · {formatDay(i.due_date)} · {money(i.amount)} — {i.cancelled_reason}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------------------------------------- forms
function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function today(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

/** Package price, deposit and instalments, with a preview of the schedule. Used to create and to change a case. */
function PackageFields({
  f,
  set,
  error,
  allowDeposit,
  alreadyInvoiced = 0,
}: {
  f: Record<string, string>;
  set: (k: string, v: string) => void;
  error: unknown;
  allowDeposit: boolean;
  alreadyInvoiced?: number;
}) {
  const { t } = useTranslation();
  const price = Number(f.package_price || 0);
  const deposit = allowDeposit ? Number(f.deposit || 0) : 0;
  const count = Math.max(1, Number(f.instalment_count || 1));
  const interval = Number(f.instalment_interval_days || 30);
  const rest = price - alreadyInvoiced - deposit;
  const each = rest > 0 ? Math.floor((rest / count) * 100) / 100 : 0;
  const first = f.first_payment_date || today();
  return (
    <>
      <div className="form-grid">
        <Field label={t("dental.ortho_package", "Package price (ETB)")} id="f-package_price" error={error}>
          <input
            id="f-package_price"
            inputMode="decimal"
            value={f.package_price ?? ""}
            onChange={(e) => set("package_price", e.target.value)}
            required
          />
        </Field>
        {allowDeposit && (
          <Field label={t("dental.ortho_deposit", "Deposit (ETB)")} id="f-deposit" error={error}>
            <input
              id="f-deposit"
              inputMode="decimal"
              value={f.deposit ?? ""}
              onChange={(e) => set("deposit", e.target.value)}
            />
          </Field>
        )}
        <Field label={t("dental.ortho_count", "Number of instalments")} id="f-instalment_count" error={error}>
          <input
            id="f-instalment_count"
            type="number"
            min={1}
            max={60}
            value={f.instalment_count ?? ""}
            onChange={(e) => set("instalment_count", e.target.value)}
          />
        </Field>
        <Field label={t("dental.ortho_interval", "Every (days)")} id="f-instalment_interval_days" error={error}>
          <input
            id="f-instalment_interval_days"
            type="number"
            min={7}
            max={92}
            value={f.instalment_interval_days ?? ""}
            onChange={(e) => set("instalment_interval_days", e.target.value)}
          />
        </Field>
        <Field label={t("dental.ortho_first_payment", "First payment")} id="f-first_payment_date" error={error}>
          <input
            id="f-first_payment_date"
            type="date"
            value={f.first_payment_date ?? ""}
            onChange={(e) => set("first_payment_date", e.target.value)}
          />
        </Field>
      </div>
      {price > 0 && rest >= 0 && (
        <Banner tone="info">
          {alreadyInvoiced > 0 &&
            `${t("dental.ortho_already_invoiced", "Already invoiced")}: ${money(alreadyInvoiced.toFixed(2))} ETB. `}
          {deposit > 0 &&
            `${t("dental.ortho_deposit_short", "Deposit")} ${money(deposit.toFixed(2))} ETB (${formatDay(first)}), `}
          {rest > 0 &&
            t("dental.ortho_schedule_preview", "{{count}} × about {{each}} ETB every {{interval}} days from {{from}}", {
              count,
              each: money(each.toFixed(2)),
              interval,
              from: formatDay(deposit > 0 ? addDays(first, interval) : first),
            })}
        </Banner>
      )}
    </>
  );
}

function NewCaseForm({
  patientId,
  assessments,
  onDone,
}: {
  patientId: string;
  assessments: OrthoAssessment[];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const ortho = useOrthoCatalog();
  const [f, setF] = useState<Record<string, string>>({
    appliance: "fixed_metal",
    arches: "both",
    billing_mode: "package",
    instalment_count: "12",
    instalment_interval_days: "30",
    first_payment_date: today(),
    assessment_id: assessments[0]?.id ?? "",
    objectives: String(assessments[0]?.objectives ?? ""),
  });
  const set = (k: string, v: string) => setF((c) => ({ ...c, [k]: v }));
  // The latest assessment may arrive after the form opens (just saved in this examination).
  const latest = assessments[0];
  useEffect(() => {
    if (!latest) return;
    setF((c) =>
      c.assessment_id
        ? c
        : { ...c, assessment_id: latest.id, objectives: c.objectives || String(latest.objectives ?? "") },
    );
  }, [latest]);
  const create = useMutation({
    mutationFn: () =>
      api.post<OrthoCase>(`/dental/patients/${patientId}/ortho/cases/`, {
        ...f,
        assessment_id: f.assessment_id || null,
        expected_months: f.expected_months || null,
      }),
    onSuccess: () => {
      invalidate(qc);
      toast(t("dental.ortho_case_created", "Orthodontic case created"));
      onDone();
    },
  });
  if (!ortho) return <Loading />;
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <ErrorBanner error={create.error} />
      <div className="form-grid">
        <Field label={t("dental.ortho_appliance", "Appliance")} id="f-appliance" error={create.error}>
          <select id="f-appliance" value={f.appliance} onChange={(e) => set("appliance", e.target.value)}>
            {ortho.appliances.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("dental.ortho_arches", "Arches")} id="f-arches">
          <select id="f-arches" value={f.arches} onChange={(e) => set("arches", e.target.value)}>
            {ortho.arches.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label={t("dental.ortho_expected", "Expected length (months)")}
          id="f-expected_months"
          error={create.error}
        >
          <input
            id="f-expected_months"
            type="number"
            min={1}
            max={96}
            value={f.expected_months ?? ""}
            onChange={(e) => set("expected_months", e.target.value)}
          />
        </Field>
        <Field label={t("dental.ortho_assessment", "Orthodontic assessment")} id="f-assessment_id">
          <select id="f-assessment_id" value={f.assessment_id} onChange={(e) => set("assessment_id", e.target.value)}>
            <option value="">{t("dental.none_option", "None")}</option>
            {assessments.map((a) => (
              <option key={a.id} value={a.id}>
                {formatDateTime(a.created_at)} · {a.recorded_by.full_name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label={t("dental.ortho_objectives", "Objectives")} id="f-objectives">
        <textarea id="f-objectives" value={f.objectives ?? ""} onChange={(e) => set("objectives", e.target.value)} />
      </Field>
      <fieldset className="stack-sm form-group">
        <legend>{t("dental.ortho_how_charged", "How is the treatment charged?")}</legend>
        <Segmented
          label={t("dental.ortho_how_charged", "How is the treatment charged?")}
          value={f.billing_mode as "package" | "per_visit"}
          onChange={(v) => set("billing_mode", v)}
          options={[
            { key: "package", label: t("dental.ortho_package_mode", "Package, paid in instalments") },
            { key: "per_visit", label: t("dental.ortho_per_visit_mode", "Charged per visit") },
          ]}
        />
        {f.billing_mode === "package" ? (
          <PackageFields f={f} set={set} error={create.error} allowDeposit />
        ) : (
          <div className="form-grid">
            <Field
              label={t("dental.ortho_per_visit_price", "Price per visit")}
              id="f-per_visit_price"
              error={create.error}
            >
              <input
                id="f-per_visit_price"
                inputMode="decimal"
                value={f.per_visit_price ?? ""}
                onChange={(e) => set("per_visit_price", e.target.value)}
                required
              />
            </Field>
          </div>
        )}
      </fieldset>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onDone}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={create.isPending}>
          {t("dental.ortho_create", "Create case")}
        </button>
      </div>
    </form>
  );
}

function BillingForm({ c, onDone }: { c: OrthoCase; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const invoiced = c.instalments
    .filter((i) => i.status === "scheduled" && i.invoice)
    .reduce((sum, i) => sum + Number(i.amount), 0);
  // Start from the case's current schedule: the instalments not yet invoiced, at their current spacing.
  const open = c.instalments
    .filter((i) => i.status === "scheduled" && !i.invoice)
    .sort((a, b) => a.due_date.localeCompare(b.due_date));
  const gap =
    open.length > 1 ? Math.round((Date.parse(open[1].due_date) - Date.parse(open[0].due_date)) / 86_400_000) : 30;
  const [f, setF] = useState<Record<string, string>>({
    billing_mode: c.billing_mode,
    package_price: c.package_price ?? "",
    per_visit_price: c.per_visit_price ?? "",
    instalment_count: String(open.length || 6),
    instalment_interval_days: String(gap > 0 ? gap : 30),
    first_payment_date: open[0] && open[0].due_date > today() ? open[0].due_date : today(),
    reason: "",
  });
  const set = (k: string, v: string) => setF((x) => ({ ...x, [k]: v }));
  const save = useMutation({
    mutationFn: () => api.post<OrthoCase>(`/dental/ortho/cases/${c.id}/billing/`, { ...f, row_version: c.version }),
    onSuccess: () => {
      invalidate(qc);
      toast("Saved");
      onDone();
    },
  });
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <Banner tone="info">
        {c.billing_mode === "package"
          ? t(
              "dental.ortho_billing_change_hint",
              "What has already been invoiced stays as it is. Instalments not yet invoiced are replaced by the schedule below.",
            )
          : t(
              "dental.ortho_billing_change_hint_visit",
              "Visits already charged keep their price. The new price applies to visits recorded from now on.",
            )}
      </Banner>
      <ErrorBanner error={save.error} />
      <Segmented
        label={t("dental.ortho_how_charged", "How is the treatment charged?")}
        value={f.billing_mode as "package" | "per_visit"}
        onChange={(v) => set("billing_mode", v)}
        options={[
          { key: "package", label: t("dental.ortho_package_mode", "Package, paid in instalments") },
          { key: "per_visit", label: t("dental.ortho_per_visit_mode", "Charged per visit") },
        ]}
      />
      {f.billing_mode === "package" ? (
        <PackageFields f={f} set={set} error={save.error} allowDeposit={invoiced === 0} alreadyInvoiced={invoiced} />
      ) : (
        <Field label={t("dental.ortho_per_visit_price", "Price per visit")} id="f-per_visit_price" error={save.error}>
          <input
            id="f-per_visit_price"
            inputMode="decimal"
            value={f.per_visit_price}
            onChange={(e) => set("per_visit_price", e.target.value)}
            required
          />
        </Field>
      )}
      <Field label={t("dental.reason", "Reason")} id="f-reason" error={save.error}>
        <textarea id="f-reason" value={f.reason} onChange={(e) => set("reason", e.target.value)} required />
      </Field>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onDone}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={save.isPending || !f.reason.trim()}>
          {t("dental.ortho_save_billing", "Save")}
        </button>
      </div>
    </form>
  );
}

function DetailsForm({ c, onDone }: { c: OrthoCase; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const ortho = useOrthoCatalog();
  const [f, setF] = useState<Record<string, string>>({
    appliance: c.appliance,
    arches: c.arches,
    expected_months: c.expected_months ? String(c.expected_months) : "",
    objectives: c.objectives,
    notes: c.notes,
    retainer_upper: c.retainer_upper,
    retainer_lower: c.retainer_lower,
    retention_review_months: c.retention_review_months ? String(c.retention_review_months) : "",
  });
  const set = (k: string, v: string) => setF((x) => ({ ...x, [k]: v }));
  const save = useMutation({
    mutationFn: () =>
      api.patch<OrthoCase>(`/dental/ortho/cases/${c.id}/`, {
        ...f,
        row_version: c.version,
        expected_months: f.expected_months || null,
        retention_review_months: f.retention_review_months || null,
      }),
    onSuccess: () => {
      invalidate(qc);
      toast("Saved");
      onDone();
    },
  });
  if (!ortho) return <Loading />;
  const select = (k: string, label: string, list: [string, string][], blank = false) => (
    <Field label={label} id={`d-${k}`} error={save.error}>
      <select id={`d-${k}`} value={f[k]} onChange={(e) => set(k, e.target.value)}>
        {blank && <option value="">—</option>}
        {list.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </Field>
  );
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <ErrorBanner error={save.error} onReload={onDone} />
      <div className="form-grid">
        {select("appliance", t("dental.ortho_appliance", "Appliance"), ortho.appliances)}
        {select("arches", t("dental.ortho_arches", "Arches"), ortho.arches)}
        <Field label={t("dental.ortho_expected", "Expected length (months)")} id="d-expected_months">
          <input
            id="d-expected_months"
            type="number"
            min={1}
            max={96}
            value={f.expected_months}
            onChange={(e) => set("expected_months", e.target.value)}
          />
        </Field>
        {select("retainer_upper", t("dental.ortho_retainer_upper", "Upper retainer"), ortho.retainers, true)}
        {select("retainer_lower", t("dental.ortho_retainer_lower", "Lower retainer"), ortho.retainers, true)}
        <Field
          label={t("dental.ortho_retention_review", "Retention reviews every (months)")}
          id="d-retention_review_months"
        >
          <input
            id="d-retention_review_months"
            type="number"
            min={1}
            max={60}
            value={f.retention_review_months}
            onChange={(e) => set("retention_review_months", e.target.value)}
          />
        </Field>
      </div>
      <Field label={t("dental.ortho_objectives", "Objectives")} id="d-objectives">
        <textarea id="d-objectives" value={f.objectives} onChange={(e) => set("objectives", e.target.value)} />
      </Field>
      <Field label={t("dental.ortho_notes", "Notes")} id="d-notes">
        <textarea id="d-notes" value={f.notes} onChange={(e) => set("notes", e.target.value)} />
      </Field>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onDone}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={save.isPending}>
          {t("common.save", "Save")}
        </button>
      </div>
    </form>
  );
}

function VisitForm({ c, encounterId, onDone }: { c: OrthoCase; encounterId?: string; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const ortho = useOrthoCatalog();
  const allowed = KINDS_WHEN[c.status] ?? [];
  const firstKind = c.status === "planned" ? (c.appliance === "aligners" ? "aligner" : "bonding") : allowed[0];
  const lastWires = c.visits.find((v) => v.status === "recorded" && (v.upper_wire || v.lower_wire));
  const [f, setF] = useState<Record<string, string>>({
    kind: firstKind,
    upper_wire: lastWires?.upper_wire ?? "",
    lower_wire: lastWires?.lower_wire ?? "",
    next_interval_weeks: c.status === "retention" ? "12" : "4",
    extra_charge: "",
  });
  const [charge, setCharge] = useState(CHARGED_BY_DEFAULT.includes(firstKind));
  const set = (k: string, v: string) => setF((x) => ({ ...x, [k]: v }));
  const save = useMutation({
    mutationFn: () =>
      api.post(`/dental/ortho/cases/${c.id}/visits/`, {
        ...f,
        ...(encounterId ? { encounter_id: encounterId } : {}),
        aligner_number: f.aligner_number || null,
        next_interval_weeks: f.next_interval_weeks || null,
        extra_charge: f.extra_charge || null,
        charge_this_visit: charge,
      }),
    onSuccess: () => {
      invalidate(qc);
      toast(t("dental.ortho_visit_saved", "Orthodontic visit recorded"));
      onDone();
    },
  });
  if (!ortho) return <Loading />;
  const kinds = ortho.visit_kinds.filter(([v]) => allowed.includes(v));
  const fixed = !["aligners", "removable", "functional"].includes(c.appliance);
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <ErrorBanner error={save.error} />
      <div className="form-grid">
        <Field label={t("dental.ortho_visit_kind", "What was done")} id="f-kind" error={save.error}>
          <select
            id="f-kind"
            value={f.kind}
            onChange={(e) => {
              set("kind", e.target.value);
              setCharge(CHARGED_BY_DEFAULT.includes(e.target.value));
            }}
          >
            {kinds.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        {fixed && (
          <>
            <Field label={t("dental.ortho_upper_wire", "Upper archwire")} id="f-upper_wire" hint="e.g. 0.016 NiTi">
              <input id="f-upper_wire" value={f.upper_wire} onChange={(e) => set("upper_wire", e.target.value)} />
            </Field>
            <Field label={t("dental.ortho_lower_wire", "Lower archwire")} id="f-lower_wire">
              <input id="f-lower_wire" value={f.lower_wire} onChange={(e) => set("lower_wire", e.target.value)} />
            </Field>
          </>
        )}
        {(c.appliance === "aligners" || f.kind === "aligner") && (
          <Field label={t("dental.ortho_aligner_number", "Aligner number")} id="f-aligner_number" error={save.error}>
            <input
              id="f-aligner_number"
              type="number"
              min={1}
              value={f.aligner_number ?? ""}
              onChange={(e) => set("aligner_number", e.target.value)}
            />
          </Field>
        )}
        <Field label={t("dental.ortho_elastics", "Elastics")} id="f-elastics" hint="e.g. Class II, 3/16, 4.5 oz">
          <input id="f-elastics" value={f.elastics ?? ""} onChange={(e) => set("elastics", e.target.value)} />
        </Field>
        <Field label={t("dental.ortho_hygiene", "Oral hygiene")} id="f-oral_hygiene">
          <select
            id="f-oral_hygiene"
            value={f.oral_hygiene ?? ""}
            onChange={(e) => set("oral_hygiene", e.target.value)}
          >
            <option value="">—</option>
            {ortho.hygiene.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("dental.ortho_compliance", "Wear and cooperation")} id="f-compliance">
          <select id="f-compliance" value={f.compliance ?? ""} onChange={(e) => set("compliance", e.target.value)}>
            <option value="">—</option>
            {ortho.hygiene.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label={t("dental.ortho_next_weeks", "Next visit in (weeks)")}
          id="f-next_interval_weeks"
          hint={t("dental.ortho_next_hint", "Added to the recall list")}
          error={save.error}
        >
          <input
            id="f-next_interval_weeks"
            type="number"
            min={1}
            max={52}
            value={f.next_interval_weeks}
            onChange={(e) => set("next_interval_weeks", e.target.value)}
          />
        </Field>
        {f.kind === "retainer_fit" && (
          <>
            <Field label={t("dental.ortho_retainer_upper", "Upper retainer")} id="f-retainer_upper">
              <select
                id="f-retainer_upper"
                value={f.retainer_upper ?? ""}
                onChange={(e) => set("retainer_upper", e.target.value)}
              >
                <option value="">—</option>
                {ortho.retainers.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("dental.ortho_retainer_lower", "Lower retainer")} id="f-retainer_lower">
              <select
                id="f-retainer_lower"
                value={f.retainer_lower ?? ""}
                onChange={(e) => set("retainer_lower", e.target.value)}
              >
                <option value="">—</option>
                {ortho.retainers.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
          </>
        )}
      </div>
      <Field label={t("dental.ortho_breakages", "Breakages")} id="f-breakages" hint="e.g. 21 bracket debonded">
        <input id="f-breakages" value={f.breakages ?? ""} onChange={(e) => set("breakages", e.target.value)} />
      </Field>
      <Field label={t("dental.ortho_notes", "Notes")} id="f-notes">
        <textarea id="f-notes" value={f.notes ?? ""} onChange={(e) => set("notes", e.target.value)} />
      </Field>
      <fieldset className="stack-sm form-group">
        <legend>{t("dental.ortho_charges", "Charges")}</legend>
        {c.billing_mode === "per_visit" ? (
          <>
            <label className="check">
              <input type="checkbox" checked={charge} onChange={(e) => setCharge(e.target.checked)} />{" "}
              {t("dental.ortho_charge_visit", "Charge this visit ({{price}} ETB)", { price: money(c.per_visit_price) })}
            </label>
            {!charge && (
              <Field
                label={t("dental.ortho_no_charge_reason", "Why is it not charged?")}
                id="f-no_charge_reason"
                error={save.error}
              >
                <input
                  id="f-no_charge_reason"
                  value={f.no_charge_reason ?? ""}
                  onChange={(e) => set("no_charge_reason", e.target.value)}
                />
              </Field>
            )}
          </>
        ) : (
          <p className="small muted">
            {t("dental.ortho_package_no_charge", "Covered by the package price; no visit charge.")}
          </p>
        )}
        <div className="form-grid">
          <Field label={t("dental.ortho_extra", "Extra charge (ETB)")} id="f-extra_charge" error={save.error}>
            <input
              id="f-extra_charge"
              inputMode="decimal"
              value={f.extra_charge}
              onChange={(e) => set("extra_charge", e.target.value)}
            />
          </Field>
          <Field
            label={t("dental.ortho_extra_reason", "For")}
            id="f-extra_charge_reason"
            hint="e.g. lost retainer"
            error={save.error}
          >
            <input
              id="f-extra_charge_reason"
              value={f.extra_charge_reason ?? ""}
              onChange={(e) => set("extra_charge_reason", e.target.value)}
            />
          </Field>
        </div>
      </fieldset>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onDone}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={save.isPending}>
          {t("dental.ortho_record_visit_short", "Record visit")}
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------------------------------------- photos
const PHOTO_KINDS = ["intraoral_photo", "extraoral_photo", "cephalometric", "panoramic"];

/** Photographs and orthodontic radiographs from two dates side by side, to see progress. */
function ProgressPhotos({ patientId, since }: { patientId: string; since: string | null }) {
  const { t } = useTranslation();
  const images = useGet<DentalImage[]>(["dental", "images", patientId, false], `/dental/patients/${patientId}/images/`);
  const byDate = useMemo(() => {
    const groups = new Map<string, DentalImage[]>();
    for (const img of images.data ?? []) {
      if (img.status !== "active" || !PHOTO_KINDS.includes(img.kind)) continue;
      const day = (img.captured_at ?? img.uploaded_at).slice(0, 10);
      groups.set(day, [...(groups.get(day) ?? []), img]);
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [images.data]);
  const dates = byDate.map(([d]) => d);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  useEffect(() => {
    if (dates.length && !a) {
      setA((since && dates.find((d) => d >= since)) || dates[0]);
      setB(dates[dates.length - 1]);
    }
  }, [dates, a, since]);
  if (images.isLoading) return null;
  const column = (day: string) => (
    <div className="stack-sm">
      {(byDate.find(([d]) => d === day)?.[1] ?? []).map((img) => (
        <figure key={img.id} className="image-card" style={{ cursor: "default" }}>
          <img src={`/api/v1/dental/images/${img.id}/file/?preview=1`} alt={img.description || img.kind_label} />
          <figcaption className="small">
            {img.kind_label}
            {img.description ? ` · ${img.description}` : ""}
          </figcaption>
        </figure>
      ))}
    </div>
  );
  return (
    <Panel title={t("dental.ortho_progress", "Progress photos")}>
      {dates.length < 2 ? (
        <p className="small muted">
          {t(
            "dental.ortho_progress_hint",
            "Upload intraoral or extraoral photographs (Images tab) at the start and during treatment to compare them here.",
          )}
        </p>
      ) : (
        <div className="stack-sm">
          <div className="form-grid">
            <Field label={t("dental.compare_from", "Earlier")} id="pp-a">
              <select id="pp-a" value={a} onChange={(e) => setA(e.target.value)}>
                {dates.map((d) => (
                  <option key={d} value={d}>
                    {formatDay(d)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("dental.compare_to", "Later")} id="pp-b">
              <select id="pp-b" value={b} onChange={(e) => setB(e.target.value)}>
                {dates.map((d) => (
                  <option key={d} value={d}>
                    {formatDay(d)}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="form-grid">
            {column(a)}
            {column(b)}
          </div>
        </div>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------------------------------------- list page
export function OrthoCasesPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState("");
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(1);
  const list = useGet<Paginated<OrthoCaseBrief>>(
    ["dental", "ortho", "cases", status, mine, page],
    `/dental/ortho/cases/${queryString({ status: status || undefined, mine: mine ? 1 : undefined, page })}`,
  );
  return (
    <div className="stack">
      <PageHead
        title={t("nav.ortho", "Orthodontics")}
        sub={t("dental.ortho_list_sub", "Patients in orthodontic treatment or retention.")}
        actions={
          <div className="row">
            <label className="check">
              <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />{" "}
              {t("dental.ortho_mine", "My patients")}
            </label>
            <select
              aria-label={t("common.status", "Status")}
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">{t("dental.ortho_open", "Open (planned, active, retention)")}</option>
              <option value="planned">{t("dental.ortho_planned", "Planned")}</option>
              <option value="active">{t("dental.ortho_active", "Active treatment")}</option>
              <option value="retention">{t("dental.ortho_retention", "Retention")}</option>
              <option value="completed">{t("dental.ortho_completed", "Completed")}</option>
              <option value="discontinued">{t("dental.ortho_discontinued", "Discontinued")}</option>
            </select>
          </div>
        }
      />
      <Panel>
        {list.isLoading ? (
          <Loading />
        ) : !list.data?.results.length ? (
          <Empty>{t("dental.ortho_list_empty", "No orthodontic cases here.")}</Empty>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>{t("common.patient", "Patient")}</th>
                <th>{t("dental.ortho_case", "Case")}</th>
                <th>{t("common.status", "Status")}</th>
                <th>{t("dental.ortho_appliance", "Appliance")}</th>
                <th>{t("dental.ortho_months", "Months (done / planned)")}</th>
                <th>{t("dental.ortho_last_visit", "Last visit")}</th>
                <th>{t("dental.ortho_billing", "Charged")}</th>
              </tr>
            </thead>
            <tbody>
              {list.data.results.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link to={`/dental/patients/${c.patient.id}?tab=ortho`}>{c.patient.full_name}</Link>{" "}
                    <span className="mono small">{c.patient.mrn}</span>
                  </td>
                  <td className="mono nowrap">{c.number}</td>
                  <td>
                    <Badge tone={STATUS_TONE[c.status]}>{c.status_label}</Badge>
                  </td>
                  <td>{c.appliance_label}</td>
                  <td>
                    {c.months_in_treatment == null
                      ? "—"
                      : `${c.months_in_treatment}${c.expected_months ? ` / ${c.expected_months}` : ""}`}
                  </td>
                  <td>{c.last_visit ? `${formatDay(c.last_visit.date)} · ${c.last_visit.kind}` : "—"}</td>
                  <td className="small">{c.billing_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <ErrorBanner error={list.error} />
        {list.data && <Pager page={page} count={list.data.count} pageSize={25} onPage={setPage} />}
      </Panel>
    </div>
  );
}
