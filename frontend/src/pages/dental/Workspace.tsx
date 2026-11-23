/**
 * The dentist's workspace for one examination: history, complaint and examination, chart, periodontal chart,
 * diagnoses, treatment plan, procedures, prescriptions, images and signing. Draft, signed and amended states are
 * always visible in the header.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Printer } from "lucide-react";
import { api, queryString } from "../../api/client";
import { useGet } from "../../api/hooks";
import type { Paginated, StockItem } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { Banner, ErrorBanner, Field, Loading, Modal, PageHead, Panel, Tabs, printElement, toast } from "../../ui";
import { formatDateTime } from "../../lib/format";
import { ClinicHeader } from "../common";
import { FREQUENCIES } from "../../labels";
import { ChartView } from "./ChartView";
import { DentalStatus, NOTE_GROUPS, NOTE_LABEL, useDentalCatalog } from "./common";
import { ImagesPanel } from "./Images";
import { PerioChart } from "./Perio";
import { PlanList, LocationInputs, locationBody } from "./Plans";
import { AmendReason, EncounterProcedures } from "./Procedures";
import type { DentalEncounter, DentalSummary, DiagnosisTerm, RiskReview } from "./types";

type Tab = "history" | "exam" | "chart" | "perio" | "diagnoses" | "plan" | "procedures" | "rx" | "images" | "sign";

export function DentalWorkspace() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const { can, user, moduleOn } = useAuth();
  const [params, setParams] = useSearchParams();
  const enc = useGet<DentalEncounter>(["dental", "encounter", id], `/dental/encounters/${id}/`);
  const summary = useGet<DentalSummary>(
    ["dental", "summary", enc.data?.patient.id],
    enc.data ? `/dental/patients/${enc.data.patient.id}/summary/` : null,
  );
  const tab = (params.get("tab") as Tab) || "history";
  const setTab = (k: Tab) => setParams({ tab: k }, { replace: true });
  const [examDirty, setExamDirty] = useState(false);
  if (enc.isLoading) return <Loading />;
  if (!enc.data) return <ErrorBanner error={enc.error} />;
  const e = enc.data;
  const mine = e.dentist.id === user?.id;
  const open = e.status === "draft" && !["completed", "cancelled"].includes(e.visit_status);
  const writable = open && mine && can("dental.write");
  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: "history", label: t("dental.tab_history", "History") },
    {
      key: "exam",
      label: `${t("dental.tab_exam", "Complaint & examination")}${examDirty ? " •" : ""}`,
    },
    { key: "chart", label: t("dental.tab_chart", "Chart"), count: e.findings.length },
    ...(moduleOn("periodontal") ? [{ key: "perio" as const, label: t("dental.tab_perio", "Periodontal") }] : []),
    { key: "diagnoses", label: t("dental.tab_diagnoses", "Diagnoses"), count: e.diagnoses.length },
    { key: "plan", label: t("dental.tab_plan", "Treatment plan") },
    { key: "procedures", label: t("dental.tab_procedures", "Procedures"), count: e.procedures.length },
    { key: "rx", label: t("dental.tab_rx", "Prescriptions"), count: e.prescriptions.length },
    ...(moduleOn("dental_imaging") && can("dental.imaging.view")
      ? [{ key: "images" as const, label: t("dental.tab_images", "Images") }]
      : []),
    { key: "sign", label: e.status === "draft" ? t("dental.tab_sign", "Sign") : t("dental.tab_summary", "Summary") },
  ];
  return (
    <div className="stack">
      <PageHead
        title={`${t("dental.examination", "Dental examination")} · ${e.patient.full_name}`}
        sub={
          <span>
            MRN {e.patient.mrn} · {e.patient.sex}, {e.patient.age} · Dr. {e.dentist.full_name} ·{" "}
            {formatDateTime(e.created_at)} <DentalStatus value={e.status} />
            {e.amendments.length > 0 && (
              <span className="badge badge-info">
                {t("dental.amended_n", "Amended ({{n}})", { n: e.amendments.length })}
              </span>
            )}
          </span>
        }
        actions={
          <Link className="btn" to={`/dental/patients/${e.patient.id}`}>
            {t("dental.dental_record", "Dental record")}
          </Link>
        }
      />
      <AlertStrip summary={summary.data} />
      {e.status === "draft" && !mine && (
        <Banner tone="info">
          {t(
            "dental.not_mine",
            "This examination is being written by Dr. {{who}}. You can record chart findings and procedures; only the author can edit the notes and sign.",
            {
              who: e.dentist.full_name,
            },
          )}
        </Banner>
      )}
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "history" && <HistoryTab encounter={e} summary={summary.data} writable={writable} />}
      {/* Kept mounted so unsaved typing survives a look at another tab. */}
      <div hidden={tab !== "exam"}>
        <ExamTab encounter={e} writable={writable} onDirty={setExamDirty} />
      </div>
      {tab === "chart" && (
        <ChartView
          patientId={e.patient.id}
          patientName={e.patient.full_name}
          encounterId={e.id}
          editable={open}
          diagnoses={e.diagnoses}
          encounters={summary.data?.encounters ?? []}
          defaultDentition={e.patient.age < 13 ? "mixed" : undefined}
        />
      )}
      {tab === "perio" && (
        <PerioChart encounterId={e.id} patientId={e.patient.id} editable={open && can("dental.chart.record")} />
      )}
      {tab === "diagnoses" && <DiagnosesTab encounter={e} writable={writable} />}
      {tab === "plan" && <PlanList patientId={e.patient.id} encounterId={e.id} diagnoses={e.diagnoses} />}
      {tab === "procedures" && <EncounterProcedures encounter={e} />}
      {tab === "rx" && <PrescriptionsTab encounter={e} writable={writable && can("prescriptions.create")} />}
      {tab === "images" && <ImagesPanel patientId={e.patient.id} encounterId={e.id} />}
      {tab === "sign" && <SignTab encounter={e} writable={writable} unsaved={examDirty} />}
    </div>
  );
}

function AlertStrip({ summary }: { summary?: DentalSummary }) {
  const { t } = useTranslation();
  if (!summary) return null;
  const a = summary.shared_history.allergies;
  const yes = summary.risk_review
    ? Object.entries(summary.risk_review.answers).filter(([, v]) => v.answer === "yes")
    : [];
  return (
    <div className={`alert-strip${a.length || yes.length ? "" : " muted"}`} role="note">
      <strong>{t("dental.alerts", "Alerts")}:</strong>{" "}
      {a.length
        ? a.map((x) => `${x.substance} (${x.severity})`).join(", ")
        : t("dental.no_allergies", "No allergies recorded")}
      {yes.length > 0 && ` · ${yes.map(([k, v]) => `${k.replace("_", " ")}: ${v.detail}`).join("; ")}`}
      {!summary.risk_review && ` · ${t("dental.no_review", "No medical history review yet")}`}
      {summary.risk_review &&
        ` · ${t("dental.reviewed", "Reviewed")} ${formatDateTime(summary.risk_review.reviewed_at)}`}
    </div>
  );
}

// ---------------------------------------------------------------------------
function HistoryTab({
  encounter,
  summary,
  writable,
}: {
  encounter: DentalEncounter;
  summary?: DentalSummary;
  writable: boolean;
}) {
  const { t } = useTranslation();
  const catalog = useDentalCatalog();
  const qc = useQueryClient();
  const last = summary?.risk_review;
  const [answers, setAnswers] = useState<Record<string, { answer: string; detail: string }>>({});
  const [allergies, setAllergies] = useState(false);
  const [meds, setMeds] = useState(false);
  const [notes, setNotes] = useState("");
  useEffect(() => {
    if (last) setAnswers(last.answers);
  }, [last?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = useMutation({
    mutationFn: () =>
      api.post<RiskReview>(`/dental/patients/${encounter.patient.id}/risk-reviews/`, {
        answers,
        allergies_reviewed: allergies,
        medications_reviewed: meds,
        notes,
        encounter_id: encounter.id,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dental"] });
      toast(t("dental.review_saved", "Medical history review recorded"));
      setNotes("");
    },
  });
  const sh = summary?.shared_history;
  return (
    <div className="split">
      <Panel title={t("dental.risk_review", "Medical history review before treatment")}>
        <div className="stack">
          {last && (
            <p className="small muted">
              {t("dental.last_review", "Last review by {{who}}, {{when}}", {
                who: last.reviewed_by.full_name,
                when: formatDateTime(last.reviewed_at),
              })}
              {last.changed_since_previous === true && ` · ${t("dental.changed", "changed since the review before")}`}
            </p>
          )}
          <Banner tone="info">
            {t(
              "dental.review_hint",
              "A record of what was reviewed. The system does not decide whether treatment is safe.",
            )}
          </Banner>
          <ErrorBanner error={save.error} />
          <div className="stack-sm">
            {(catalog.data?.risk_questions ?? []).map(([key, label]) => {
              const a = answers[key] ?? { answer: "", detail: "" };
              return (
                <div key={key} className="note-row">
                  <span>{label}</span>
                  <select
                    aria-label={label}
                    disabled={!writable}
                    value={a.answer}
                    onChange={(ev) => setAnswers((c) => ({ ...c, [key]: { ...a, answer: ev.target.value } }))}
                  >
                    <option value="">—</option>
                    <option value="no">{t("common.no", "No")}</option>
                    <option value="yes">{t("common.yes", "Yes")}</option>
                    <option value="unknown">{t("dental.unknown", "Unknown")}</option>
                    <option value="not_applicable">{t("dental.na", "Not applicable")}</option>
                  </select>
                  {(a.answer === "yes" || a.detail) && (
                    <input
                      aria-label={`${label} — detail`}
                      disabled={!writable}
                      value={a.detail}
                      placeholder={t("dental.detail", "Detail")}
                      onChange={(ev) => setAnswers((c) => ({ ...c, [key]: { ...a, detail: ev.target.value } }))}
                    />
                  )}
                </div>
              );
            })}
            {writable && (
              <>
                <label className="check">
                  <input type="checkbox" checked={allergies} onChange={(e) => setAllergies(e.target.checked)} />{" "}
                  {t("dental.allergies_checked", "Allergies checked with the patient")}
                </label>
                <label className="check">
                  <input type="checkbox" checked={meds} onChange={(e) => setMeds(e.target.checked)} />{" "}
                  {t("dental.meds_checked", "Current medicines checked with the patient")}
                </label>
                <Field label={t("dental.notes", "Notes")} id="f-review-notes">
                  <textarea id="f-review-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
                </Field>
                <div className="form-actions">
                  <button className="btn btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
                    {t("dental.record_review", "Record review")}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </Panel>
      <div className="stack">
        <Panel title={t("dental.shared_history", "From the patient record")}>
          {sh ? (
            <dl className="facts">
              <dt>{t("dental.allergies", "Allergies")}</dt>
              <dd>
                {sh.allergies.length
                  ? sh.allergies
                      .map((a) => `${a.substance} (${a.severity}${a.reaction ? `: ${a.reaction}` : ""})`)
                      .join("; ")
                  : "—"}
              </dd>
              <dt>{t("dental.conditions", "Known conditions")}</dt>
              <dd className="prewrap">{sh.known_conditions || "—"}</dd>
              <dt>{t("dental.past_history", "Past history")}</dt>
              <dd className="prewrap">{sh.past_history || "—"}</dd>
              <dt>{t("dental.current_meds", "Current medicines")}</dt>
              <dd className="prewrap">{sh.current_medications || "—"}</dd>
            </dl>
          ) : (
            <Loading />
          )}
          <p className="small muted">{t("dental.shared_hint", "Edit these in the patient's record (Patients).")}</p>
        </Panel>
        {summary && <ProfilePanel patientId={encounter.patient.id} profile={summary.profile} writable={writable} />}
      </div>
    </div>
  );
}

const PROFILE_FIELDS: [string, string][] = [
  ["previous_treatment", "Previous dental treatment"],
  ["extraction_history", "Extractions"],
  ["root_canal_history", "Root canal treatment"],
  ["orthodontic_history", "Orthodontic treatment"],
  ["prosthesis_history", "Dentures, crowns, bridges, implants"],
  ["oral_hygiene", "Oral hygiene habits"],
  ["other_habits", "Other relevant habits (e.g. khat chewing, bruxism)"],
  ["anxiety_notes", "Dental anxiety"],
  ["communication_notes", "Communication needs"],
];

export function ProfilePanel({
  patientId,
  profile,
  writable,
}: {
  patientId: string;
  profile: DentalSummary["profile"];
  writable: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [f, setF] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState(false);
  useEffect(() => setF(profile as unknown as Record<string, string>), [profile]);
  const save = useMutation({
    mutationFn: () => api.patch(`/dental/patients/${patientId}/profile/`, f, { ifMatch: profile.row_version }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dental", "summary"] });
      setEditing(false);
      toast(t("common.saved_toast", "Changes saved"));
    },
  });
  return (
    <Panel
      title={t("dental.profile", "Dental history")}
      actions={
        writable &&
        !editing && (
          <button className="btn btn-sm" onClick={() => setEditing(true)}>
            {t("users.edit", "Edit")}
          </button>
        )
      }
    >
      <ErrorBanner error={save.error} />
      {editing ? (
        <form
          className="stack-sm"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          {PROFILE_FIELDS.map(([k, label]) => (
            <Field key={k} label={label} id={`f-${k}`}>
              <textarea
                id={`f-${k}`}
                rows={2}
                value={f[k] ?? ""}
                onChange={(e) => setF((c) => ({ ...c, [k]: e.target.value }))}
              />
            </Field>
          ))}
          <div className="form-grid">
            <Field label={t("dental.tobacco", "Tobacco use")} id="f-tobacco_use">
              <select
                id="f-tobacco_use"
                value={f.tobacco_use ?? ""}
                onChange={(e) => setF((c) => ({ ...c, tobacco_use: e.target.value }))}
              >
                <option value="">{t("dental.not_asked", "Not asked")}</option>
                <option value="never">{t("dental.never", "Never")}</option>
                <option value="former">{t("dental.former", "Former")}</option>
                <option value="current">{t("dental.current", "Current")}</option>
              </select>
            </Field>
            <Field label={t("dental.tobacco_notes", "Tobacco notes")} id="f-tobacco_notes">
              <input
                id="f-tobacco_notes"
                value={f.tobacco_notes ?? ""}
                onChange={(e) => setF((c) => ({ ...c, tobacco_notes: e.target.value }))}
              />
            </Field>
          </div>
          <div className="form-actions">
            <button type="button" className="btn" onClick={() => setEditing(false)}>
              {t("common.cancel")}
            </button>
            <button className="btn btn-primary" disabled={save.isPending}>
              {t("common.save", "Save")}
            </button>
          </div>
        </form>
      ) : (
        <dl className="facts">
          {PROFILE_FIELDS.map(([k, label]) => (
            <div key={k} style={{ display: "contents" }}>
              <dt>{label}</dt>
              <dd className="prewrap">{(profile as unknown as Record<string, string>)[k] || "—"}</dd>
            </div>
          ))}
          <dt>{t("dental.tobacco", "Tobacco use")}</dt>
          <dd>
            {profile.tobacco_use || "—"} {profile.tobacco_notes}
          </dd>
        </dl>
      )}
      {profile.updated_by && (
        <p className="small subtle">
          {t("dental.updated_by", "Last changed by {{who}}, {{when}}", {
            who: profile.updated_by.full_name,
            when: formatDateTime(profile.updated_at),
          })}
        </p>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
function ExamTab({
  encounter,
  writable,
  onDirty,
}: {
  encounter: DentalEncounter;
  writable: boolean;
  onDirty: (dirty: boolean) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const initial = useMemo(() => {
    const out: Record<string, string> = {};
    for (const g of NOTE_GROUPS) for (const [k] of g.fields) out[k] = String(encounter[k] ?? "");
    return out;
  }, [encounter]);
  const [f, setF] = useState(initial);
  const [pain, setPain] = useState({
    pain_present: encounter.pain_present,
    pain_teeth: encounter.pain_teeth.join(", "),
    pain_severity: encounter.pain_severity == null ? "" : String(encounter.pain_severity),
    pain_pattern: encounter.pain_pattern,
    pain_sensitivity: encounter.pain_sensitivity,
    mouth_opening_mm: encounter.mouth_opening_mm == null ? "" : String(encounter.mouth_opening_mm),
  });
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (!dirty) setF(initial);
  }, [initial, dirty]);
  useEffect(() => {
    onDirty(dirty);
    const warn = (ev: BeforeUnloadEvent) => {
      if (dirty) ev.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, onDirty]);
  const save = useMutation({
    mutationFn: () =>
      api.patch<DentalEncounter>(`/dental/encounters/${encounter.id}/`, {
        version: encounter.version,
        ...f,
        pain_present: pain.pain_present,
        pain_teeth: pain.pain_teeth
          .split(/[\s,]+/)
          .filter(Boolean)
          .map(Number),
        pain_severity: pain.pain_severity === "" ? null : Number(pain.pain_severity),
        pain_pattern: pain.pain_pattern,
        pain_sensitivity: pain.pain_sensitivity,
        mouth_opening_mm: pain.mouth_opening_mm === "" ? null : Number(pain.mouth_opening_mm),
      }),
    onSuccess: (data) => {
      qc.setQueryData(["dental", "encounter", encounter.id], data);
      setDirty(false);
      toast(t("common.saved_toast", "Changes saved"));
    },
  });
  const set = (k: string, v: string) => {
    setDirty(true);
    setF((c) => ({ ...c, [k]: v }));
  };
  const amendments = (k: string) => encounter.amendments.filter((a) => a.field_name === k);
  return (
    <div className="stack">
      <ErrorBanner error={save.error} onReload={() => setDirty(false)} />
      {NOTE_GROUPS.map((g) => (
        <Panel key={g.title} title={t(`dental.group_${g.title}`, g.title)}>
          {g.title === "Pain" && (
            <div className="form-grid">
              <Field label={t("dental.pain_present", "Pain present")} id="f-pain_present">
                <select
                  id="f-pain_present"
                  disabled={!writable}
                  value={pain.pain_present == null ? "" : pain.pain_present ? "yes" : "no"}
                  onChange={(e) => {
                    setDirty(true);
                    setPain((p) => ({ ...p, pain_present: e.target.value === "" ? null : e.target.value === "yes" }));
                  }}
                >
                  <option value="">—</option>
                  <option value="yes">{t("common.yes", "Yes")}</option>
                  <option value="no">{t("common.no", "No")}</option>
                </select>
              </Field>
              <Field label={t("dental.pain_teeth", "Affected teeth (FDI)")} id="f-pain_teeth" error={save.error}>
                <input
                  id="f-pain_teeth"
                  disabled={!writable}
                  value={pain.pain_teeth}
                  onChange={(e) => {
                    setDirty(true);
                    setPain((p) => ({ ...p, pain_teeth: e.target.value }));
                  }}
                />
              </Field>
              <Field label={t("dental.pain_severity", "Severity (0–10)")} id="f-pain_severity" error={save.error}>
                <input
                  id="f-pain_severity"
                  type="number"
                  min={0}
                  max={10}
                  disabled={!writable}
                  value={pain.pain_severity}
                  onChange={(e) => {
                    setDirty(true);
                    setPain((p) => ({ ...p, pain_severity: e.target.value }));
                  }}
                />
              </Field>
              <Field label={t("dental.pain_pattern", "Pattern")} id="f-pain_pattern">
                <select
                  id="f-pain_pattern"
                  disabled={!writable}
                  value={pain.pain_pattern}
                  onChange={(e) => {
                    setDirty(true);
                    setPain((p) => ({ ...p, pain_pattern: e.target.value as typeof p.pain_pattern }));
                  }}
                >
                  <option value="">—</option>
                  <option value="continuous">{t("dental.continuous", "Continuous")}</option>
                  <option value="intermittent">{t("dental.intermittent", "Intermittent")}</option>
                </select>
              </Field>
              <fieldset className="fieldset span-all">
                <legend>{t("dental.sensitivity", "Sensitive to")}</legend>
                {["hot", "cold", "sweet", "biting"].map((s) => (
                  <label key={s} className="check">
                    <input
                      type="checkbox"
                      disabled={!writable}
                      checked={pain.pain_sensitivity.includes(s)}
                      onChange={(e) => {
                        setDirty(true);
                        setPain((p) => ({
                          ...p,
                          pain_sensitivity: e.target.checked
                            ? [...p.pain_sensitivity, s]
                            : p.pain_sensitivity.filter((x) => x !== s),
                        }));
                      }}
                    />{" "}
                    {s}
                  </label>
                ))}
              </fieldset>
            </div>
          )}
          {g.title === "Extraoral examination" && (
            <Field label={t("dental.mouth_opening", "Mouth opening (mm)")} id="f-mouth_opening_mm" error={save.error}>
              <input
                id="f-mouth_opening_mm"
                type="number"
                min={0}
                max={90}
                className="narrow-field"
                disabled={!writable}
                value={pain.mouth_opening_mm}
                onChange={(e) => {
                  setDirty(true);
                  setPain((p) => ({ ...p, mouth_opening_mm: e.target.value }));
                }}
              />
            </Field>
          )}
          <div className={g.fields.every(([, , s]) => s === "short") ? "form-grid" : "stack-sm"}>
            {g.fields.map(([k, label, size]) => (
              <Field key={k} label={t(`dental.f_${k}`, label)} id={`f-${k}`} error={save.error}>
                {writable ? (
                  size === "short" ? (
                    <input id={`f-${k}`} value={f[k]} onChange={(e) => set(k, e.target.value)} maxLength={255} />
                  ) : (
                    <textarea id={`f-${k}`} value={f[k]} onChange={(e) => set(k, e.target.value)} rows={3} />
                  )
                ) : (
                  <div className="prewrap">
                    {amendments(k).length
                      ? amendments(k)[amendments(k).length - 1].amended_text
                      : f[k] || <span className="subtle">—</span>}
                    {amendments(k).length > 0 && <div className="small amended">{t("dental.amended", "Amended")}</div>}
                  </div>
                )}
              </Field>
            ))}
          </div>
        </Panel>
      ))}
      {writable && (
        <div className="action-bar">
          <span className="small muted">
            {dirty ? t("consult.unsaved", "Unsaved changes") : t("consult.saved", "All changes saved")}
          </span>
          <button className="btn btn-primary" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
            {t("common.save", "Save")}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
function DiagnosesTab({ encounter, writable }: { encounter: DentalEncounter; writable: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const terms = useGet<DiagnosisTerm[]>(["dental", "terms", q], `/dental/diagnosis-terms/${queryString({ q })}`);
  const [termId, setTermId] = useState("");
  const [loc, setLoc] = useState({ scope: "tooth", tooth: "", surfaces: [] as string[], region: "q1" });
  const [certainty, setCertainty] = useState("confirmed");
  const [notes, setNotes] = useState("");
  const refresh = () => void qc.invalidateQueries({ queryKey: ["dental", "encounter", encounter.id] });
  const add = useMutation({
    mutationFn: () =>
      api.post(`/dental/encounters/${encounter.id}/diagnoses/`, {
        term_id: termId,
        ...locationBody(loc),
        certainty,
        notes,
      }),
    onSuccess: () => {
      refresh();
      setNotes("");
      toast(t("dental.dx_added", "Diagnosis added"));
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.post(`/dental/diagnoses/${id}/remove/`),
    onSuccess: refresh,
  });
  const anyProc = { tooth_requirement: "optional", surfaces_allowed: true } as Parameters<
    typeof LocationInputs
  >[0]["procedure"];
  return (
    <div className="split">
      <Panel title={t("dental.tab_diagnoses", "Diagnoses")}>
        <ErrorBanner error={remove.error} />
        {encounter.diagnoses.length === 0 ? (
          <p className="muted">{t("dental.no_dx", "No diagnoses recorded in this examination.")}</p>
        ) : (
          <table className="data">
            <tbody>
              {encounter.diagnoses.map((d) => (
                <tr key={d.id}>
                  <td className="mono">{d.code}</td>
                  <td>
                    {d.term_text}
                    {d.notes && <div className="small subtle">{d.notes}</div>}
                  </td>
                  <td className="mono">{d.location.label}</td>
                  <td>
                    {d.certainty} · {d.status}
                  </td>
                  <td className="num">
                    {writable && (
                      <button className="btn btn-sm btn-ghost" onClick={() => remove.mutate(d.id)}>
                        {t("common.remove", "Remove")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="small subtle">
          {t("dental.dx_codes", "Codes: WHO ICD-10 (starter list pending clinical review).")}
        </p>
      </Panel>
      {writable && (
        <Panel title={t("dental.add_dx", "Add a diagnosis")}>
          <form
            className="stack-sm"
            onSubmit={(e) => {
              e.preventDefault();
              add.mutate();
            }}
          >
            <ErrorBanner error={add.error} />
            <Field label={t("dental.search", "Search")} id="f-q">
              <input id="f-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="K02, caries, pulpitis…" />
            </Field>
            <Field label={t("dental.diagnosis", "Diagnosis")} id="f-term_id" error={add.error}>
              <select id="f-term_id" value={termId} onChange={(e) => setTermId(e.target.value)} required size={6}>
                {(terms.data ?? []).map((tm) => (
                  <option key={tm.id} value={tm.id}>
                    {tm.code} {tm.term}
                  </option>
                ))}
              </select>
            </Field>
            <LocationInputs procedure={anyProc} value={loc} onChange={setLoc} />
            <Field label={t("dental.certainty", "Certainty")} id="f-certainty">
              <select id="f-certainty" value={certainty} onChange={(e) => setCertainty(e.target.value)}>
                <option value="confirmed">{t("dental.confirmed", "Confirmed")}</option>
                <option value="suspected">{t("dental.suspected", "Suspected")}</option>
              </select>
            </Field>
            <Field label={t("dental.notes", "Notes")} id="f-dx-notes">
              <input id="f-dx-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </Field>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={add.isPending || !termId}>
                {t("dental.add_dx", "Add diagnosis")}
              </button>
            </div>
          </form>
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
interface RxLine {
  item_id: string | null;
  drug_name: string;
  dose: string;
  frequency: string;
  duration_days: string;
  quantity: string;
  instructions: string;
  allergy_override_reason: string;
}
const EMPTY_LINE: RxLine = {
  item_id: null,
  drug_name: "",
  dose: "",
  frequency: "TID",
  duration_days: "",
  quantity: "",
  instructions: "",
  allergy_override_reason: "",
};

function PrescriptionsTab({ encounter, writable }: { encounter: DentalEncounter; writable: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [lines, setLines] = useState<RxLine[]>([{ ...EMPTY_LINE }]);
  const [search, setSearch] = useState("");
  const [focus, setFocus] = useState(0);
  const meds = useGet<Paginated<StockItem>>(
    ["items", "rx-search", search],
    writable && search.length >= 2
      ? `/inventory/items/${queryString({ category: "medicine", active: "true", q: search, page_size: 8 })}`
      : null,
  );
  const send = useMutation({
    mutationFn: () =>
      api.post(`/dental/encounters/${encounter.id}/prescriptions/`, {
        items: lines.map((l) => ({
          ...l,
          duration_days: l.duration_days ? Number(l.duration_days) : null,
        })),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dental", "encounter", encounter.id] });
      setLines([{ ...EMPTY_LINE }]);
      toast(t("dental.rx_saved", "Prescription saved"));
    },
  });
  const set = (i: number, patch: Partial<RxLine>) =>
    setLines((c) => c.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const printId = `rx-print-${encounter.id}`;
  return (
    <div className="stack">
      <Panel
        title={t("dental.tab_rx", "Prescriptions")}
        actions={
          encounter.prescriptions.length > 0 && (
            <button
              className="btn btn-sm"
              onClick={() => printElement(printId, t("dental.prescription", "Prescription"))}
            >
              <Printer size={15} aria-hidden /> {t("common.print", "Print")}
            </button>
          )
        }
      >
        {encounter.prescriptions.length === 0 ? (
          <p className="muted">{t("dental.no_rx", "No prescriptions in this examination.")}</p>
        ) : (
          <div id={printId}>
            <div className="print-only">
              <ClinicHeader title={t("dental.prescription", "Prescription")} />
              <p>
                <strong>{encounter.patient.full_name}</strong> · MRN {encounter.patient.mrn} · Dr.{" "}
                {encounter.dentist.full_name}
              </p>
            </div>
            {encounter.prescriptions.map((rx) => (
              <div key={rx.id} className="stack-sm">
                <strong>
                  {rx.number} <DentalStatus value={rx.status === "external" ? "printed" : rx.status} />
                </strong>
                <ul>
                  {rx.items.map((it, i) => (
                    <li key={i}>
                      {it.drug_name} — {it.dose} {it.frequency}
                      {it.duration_days ? ` × ${it.duration_days} days` : ""} ({it.quantity}) {it.instructions}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </Panel>
      {writable && (
        <Panel title={t("dental.new_rx", "New prescription")}>
          <Banner tone="info">
            {t(
              "dental.rx_hint",
              "The dentist decides the medicine and dose; the system checks the catalogue and the patient's recorded allergies. Narcotic and psychotropic medicines use the official special prescription form.",
            )}
          </Banner>
          <ErrorBanner error={send.error} />
          {lines.map((l, i) => (
            <div key={i} className="form-grid-4 fieldset">
              <Field label={t("dental.medicine", "Medicine")} id={`f-drug-${i}`}>
                <input
                  id={`f-drug-${i}`}
                  value={l.drug_name}
                  onFocus={() => setFocus(i)}
                  onChange={(e) => {
                    set(i, { drug_name: e.target.value, item_id: null });
                    setSearch(e.target.value);
                    setFocus(i);
                  }}
                />
                {focus === i &&
                  (meds.data?.results ?? []).map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      className="btn btn-sm"
                      onClick={() => {
                        set(i, { item_id: m.id, drug_name: `${m.name} ${m.strength}`.trim() });
                        setSearch("");
                      }}
                    >
                      {m.name} {m.strength}
                    </button>
                  ))}
              </Field>
              <Field label={t("dental.dose", "Dose")} id={`f-dose-${i}`}>
                <input id={`f-dose-${i}`} value={l.dose} onChange={(e) => set(i, { dose: e.target.value })} required />
              </Field>
              <Field label={t("dental.frequency", "Frequency")} id={`f-freq-${i}`}>
                <select id={`f-freq-${i}`} value={l.frequency} onChange={(e) => set(i, { frequency: e.target.value })}>
                  {FREQUENCIES.map((fq) => (
                    <option key={fq}>{fq}</option>
                  ))}
                </select>
              </Field>
              <Field label={t("dental.days", "Days")} id={`f-days-${i}`}>
                <input
                  id={`f-days-${i}`}
                  inputMode="numeric"
                  value={l.duration_days}
                  onChange={(e) => set(i, { duration_days: e.target.value })}
                />
              </Field>
              <Field label={t("dental.quantity", "Quantity")} id={`f-qty-${i}`}>
                <input
                  id={`f-qty-${i}`}
                  inputMode="decimal"
                  value={l.quantity}
                  onChange={(e) => set(i, { quantity: e.target.value })}
                  required
                />
              </Field>
              <Field label={t("dental.instructions", "Instructions")} id={`f-ins-${i}`}>
                <input
                  id={`f-ins-${i}`}
                  value={l.instructions}
                  onChange={(e) => set(i, { instructions: e.target.value })}
                />
              </Field>
              {send.error instanceof Error && "details" in send.error && (
                <Field
                  label={t("dental.allergy_override", "Reason to continue despite the allergy (if warned)")}
                  id={`f-ovr-${i}`}
                >
                  <input
                    id={`f-ovr-${i}`}
                    value={l.allergy_override_reason}
                    onChange={(e) => set(i, { allergy_override_reason: e.target.value })}
                  />
                </Field>
              )}
            </div>
          ))}
          <div className="form-actions">
            <button type="button" className="btn" onClick={() => setLines((c) => [...c, { ...EMPTY_LINE }])}>
              {t("dental.add_line", "Add a medicine")}
            </button>
            <button className="btn btn-primary" onClick={() => send.mutate()} disabled={send.isPending}>
              {t("dental.save_rx", "Save prescription")}
            </button>
          </div>
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
function SignTab({
  encounter,
  writable,
  unsaved,
}: {
  encounter: DentalEncounter;
  writable: boolean;
  unsaved: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { can } = useAuth();
  const [amendField, setAmendField] = useState<string | null>(null);
  const [amendText, setAmendText] = useState("");
  const sign = useMutation({
    mutationFn: () => api.post<DentalEncounter>(`/dental/encounters/${encounter.id}/sign/`),
    onSuccess: (data) => {
      qc.setQueryData(["dental", "encounter", encounter.id], data);
      void qc.invalidateQueries({ queryKey: ["visits"] });
      toast(t("dental.signed", "Examination signed"));
    },
  });
  const amend = useMutation({
    mutationFn: (reason: string) =>
      api.post<DentalEncounter>(`/dental/encounters/${encounter.id}/amendments/`, {
        field_name: amendField,
        text: amendText,
        reason,
      }),
    onSuccess: (data) => {
      qc.setQueryData(["dental", "encounter", encounter.id], data);
      setAmendField(null);
    },
  });
  const drafts = encounter.procedures.filter((p) => p.status === "draft");
  const printId = `exam-print-${encounter.id}`;
  const value = (k: string) => {
    const a = encounter.amendments.filter((x) => x.field_name === k);
    return a.length ? a[a.length - 1].amended_text : String(encounter[k] ?? "");
  };
  return (
    <div className="stack">
      {encounter.status === "draft" ? (
        <Panel title={t("dental.sign_exam", "Sign the examination")}>
          <ErrorBanner error={sign.error} />
          <ul className="checklist">
            <li className={value("chief_complaint") ? "check-done" : ""}>
              {t("dental.ck_complaint", "Chief complaint recorded")}
            </li>
            <li className={encounter.diagnoses.length || value("assessment") ? "check-done" : ""}>
              {t("dental.ck_dx", "A diagnosis or an assessment")}
            </li>
            <li className={encounter.risk_review ? "check-done" : ""}>
              {t("dental.ck_review", "Medical history reviewed (recommended)")}
            </li>
          </ul>
          {unsaved && (
            <Banner tone="warn">
              {t(
                "dental.unsaved_exam",
                "The complaint and examination page has unsaved changes. Save them before signing.",
              )}
            </Banner>
          )}
          {drafts.length > 0 && (
            <Banner tone="warn">
              {t(
                "dental.unsigned_procs",
                "{{n}} procedure record(s) are still unsigned. They must be signed before the visit can be closed.",
                {
                  n: drafts.length,
                },
              )}
            </Banner>
          )}
          <p className="small muted">
            {t("dental.sign_hint", "After signing, nothing can be changed except by an amendment with a reason.")}
          </p>
          {writable && (
            <div className="form-actions">
              <button className="btn btn-primary" onClick={() => sign.mutate()} disabled={sign.isPending || unsaved}>
                {t("dental.sign", "Sign")}
              </button>
            </div>
          )}
        </Panel>
      ) : (
        <Panel
          title={t("dental.exam_report", "Examination report")}
          actions={
            <button
              className="btn btn-sm"
              onClick={() => printElement(printId, t("dental.exam_report", "Examination report"))}
            >
              <Printer size={15} aria-hidden /> {t("common.print", "Print")}
            </button>
          }
        >
          <div id={printId} className="doc stack-sm">
            <ClinicHeader title={t("dental.exam_report", "Dental examination report")} />
            <p>
              <strong>{encounter.patient.full_name}</strong> · MRN {encounter.patient.mrn} · {encounter.patient.sex},{" "}
              {encounter.patient.age} · Dr. {encounter.dentist.full_name} · {t("dental.signed_at", "Signed")}{" "}
              {formatDateTime(encounter.signed_at)}
            </p>
            {NOTE_GROUPS.flatMap((g) => g.fields)
              .filter(([k]) => value(k))
              .map(([k]) => (
                <div key={k} className="note-section">
                  <strong>{NOTE_LABEL[k]}</strong>
                  <div className="prewrap">{value(k)}</div>
                  {can("dental.amend") && (
                    <button
                      className="btn btn-sm btn-ghost no-print"
                      onClick={() => {
                        setAmendField(k);
                        setAmendText(value(k));
                      }}
                    >
                      {t("dental.amend", "Amend…")}
                    </button>
                  )}
                </div>
              ))}
            {encounter.diagnoses.length > 0 && (
              <div className="note-section">
                <strong>{t("dental.tab_diagnoses", "Diagnoses")}</strong>
                <ul>
                  {encounter.diagnoses.map((d) => (
                    <li key={d.id}>
                      {d.code} {d.term_text} — {d.location.label} ({d.certainty})
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {encounter.findings.length > 0 && (
              <div className="note-section">
                <strong>{t("dental.findings_recorded", "Chart findings recorded")}</strong>
                <ul>
                  {encounter.findings.map((f) => (
                    <li key={f.id} className={f.voided_at ? "struck" : ""}>
                      {f.location.label}: {f.finding_type.name} {f.note && `— ${f.note}`}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {encounter.amendments.length > 0 && (
              <div className="note-section small">
                <strong>{t("dental.amendments", "Amendments")}</strong>
                <ul>
                  {encounter.amendments.map((a) => (
                    <li key={a.id}>
                      {NOTE_LABEL[a.field_name] ?? a.field_name}: “{a.original_text}” → “{a.amended_text}” — {a.reason}{" "}
                      ({a.author.full_name}, {formatDateTime(a.created_at)})
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Panel>
      )}
      <FollowUpPanel encounter={encounter} />
      <Modal
        open={!!amendField}
        title={`${t("dental.amend", "Amend")}: ${NOTE_LABEL[amendField ?? ""] ?? ""}`}
        onClose={() => setAmendField(null)}
      >
        <div className="stack-sm">
          <textarea
            aria-label={t("dental.corrected_text", "Corrected text")}
            rows={4}
            value={amendText}
            onChange={(e) => setAmendText(e.target.value)}
          />
          <AmendReason
            busy={amend.isPending}
            error={amend.error}
            onCancel={() => setAmendField(null)}
            onSave={(r) => amend.mutate(r)}
          />
        </div>
      </Modal>
    </div>
  );
}

function FollowUpPanel({ encounter }: { encounter: DentalEncounter }) {
  const { t } = useTranslation();
  const { can, moduleOn } = useAuth();
  const catalog = useDentalCatalog();
  const qc = useQueryClient();
  const [kind, setKind] = useState("post_op");
  const [due, setDue] = useState("");
  const [note, setNote] = useState("");
  const add = useMutation({
    mutationFn: () =>
      api.post(`/dental/patients/${encounter.patient.id}/recalls/`, {
        kind,
        due_date: due,
        note,
        encounter_id: encounter.id,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dental"] });
      toast(t("dental.recall_added", "Follow-up added to the recall list"));
      setDue("");
      setNote("");
    },
  });
  if (!moduleOn("recalls") || !can("dental.write", "dental.recall.manage")) return null;
  return (
    <Panel title={t("dental.follow_up", "Follow-up / recall")}>
      <ErrorBanner error={add.error} />
      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
      >
        <Field label={t("dental.recall_kind", "Kind")} id="f-kind">
          <select id="f-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
            {(catalog.data?.recall_kinds ?? []).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("dental.due", "Due")} id="f-due_date" error={add.error}>
          <input id="f-due_date" type="date" value={due} onChange={(e) => setDue(e.target.value)} required />
        </Field>
        <Field label={t("dental.note", "Note")} id="f-recall-note">
          <input id="f-recall-note" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <div className="form-actions span-all">
          <button className="btn" disabled={add.isPending || !due}>
            {t("dental.add_recall", "Add to recall list")}
          </button>
        </div>
      </form>
    </Panel>
  );
}
