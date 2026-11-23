import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AlertTriangle, CalendarPlus, FileSignature, Printer, Save, Stethoscope } from "lucide-react";
import { ApiError, api } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import {
  NOTE_FIELDS,
  type Encounter,
  type EncounterSummary,
  type LabOrder,
  type NoteField,
  type Paginated,
  type Patient,
  type Visit,
  type Vitals,
  type ClinicalSummary,
  type Prescription,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import {
  FLAG_LABEL,
  GENERAL_APPEARANCE,
  NOTE_GROUPS,
  NOTE_LABELS,
  SHORT_NOTE_FIELDS,
  StateBadge,
  generalAppearanceLabel,
  useTriageLabel,
} from "../labels";
import { formatDateTime } from "../lib/format";
import {
  Badge,
  Banner,
  ConfirmDialog,
  Empty,
  ErrorBanner,
  Loading,
  Modal,
  PageHead,
  Panel,
  Tabs,
  initials,
  toast,
} from "../ui";
import { AppointmentForm } from "./appointments";
import { sexAge, waitLabel } from "./common";
import { ConsultationSummary } from "./printouts";
import { DocumentsPanel, ReferredHere, PrescriptionDoc } from "./clinical-documents";
import { DiagnosesPanel, LabPanel, AmendForm, PrescriptionForm, LabOrderForm } from "./consultation-orders";
export function ConsultationsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const waiting = useGet<Visit[]>(
    ["visits", "doctor-waiting"],
    `/visits/?status=waiting_doctor,waiting_triage&doctor=${user?.id}`,
    { refetchInterval: 20_000 },
  );
  const drafts = useGet<Paginated<EncounterSummary>>(
    ["encounters", "mine", "draft"],
    "/encounters/?mine=true&status=draft",
  );
  const recent = useGet<Paginated<EncounterSummary>>(
    ["encounters", "mine", "signed"],
    "/encounters/?mine=true&status=signed&page_size=10",
  );
  const start = useAction(
    (visitId: string) => api.post<Encounter>(`/visits/${visitId}/encounters/`),
    [["visits"]],
    (enc) => navigate(`/consultations/${enc.id}`),
  );

  return (
    <div className="stack">
      <PageHead
        title={t("nav.consultations")}
        sub={t("consult.sub2", "Your waiting patients and unsigned evaluation notes.")}
      />
      <ErrorBanner error={start.error} />
      <div className="split">
        <Panel title={t("consult.waiting", "Waiting for you")} flush>
          {waiting.isLoading ? (
            <Loading />
          ) : !waiting.data?.length ? (
            <Empty>{t("consult.none_waiting", "No one is waiting for you.")}</Empty>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>{t("queue.ticket", "Ticket")}</th>
                    <th>{t("patients.patient", "Patient")}</th>
                    <th>{t("queue.waiting", "Waiting")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {waiting.data.map((v) => (
                    <tr key={v.id}>
                      <td>
                        <span className="token" style={{ fontSize: "1.8rem", border: 0 }}>
                          {v.queue_number}
                        </span>
                      </td>
                      <td>
                        <strong>{v.patient.full_name}</strong>
                        <div className="small muted">
                          {sexAge(v.patient, t)}
                          {v.has_vitals ? "" : `, ${t("consult.no_vitals", "no vitals yet")}`}
                        </div>
                        {v.priority !== "routine" && <StateBadge set="priority" value={v.priority} />}
                      </td>
                      <td>{waitLabel(v.waiting_minutes)}</td>
                      <td className="num">
                        <button
                          className="btn btn-sm btn-primary"
                          disabled={start.isPending}
                          onClick={() => start.mutate(v.id)}
                        >
                          <Stethoscope size={15} aria-hidden /> {t("queue.manage", "Manage")}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <div className="stack">
          <Panel title={t("consult.unsigned", "Unsigned notes")} flush>
            {!drafts.data?.results.length ? (
              <Empty>{t("consult.none_unsigned", "All your notes are signed.")}</Empty>
            ) : (
              <div>
                {drafts.data.results.map((e) => (
                  <Link key={e.id} to={`/consultations/${e.id}`} className="notice unread">
                    <strong>{e.chief_complaint || t("consult.untitled", "Note started")} </strong>
                    <div className="small subtle">{formatDateTime(e.created_at)}</div>
                  </Link>
                ))}
              </div>
            )}
          </Panel>
          <Panel title={t("consult.recent", "Recently signed")} flush>
            {!recent.data?.results.length ? (
              <Empty>{t("consult.none_recent", "None yet.")}</Empty>
            ) : (
              <div>
                {recent.data.results.map((e) => (
                  <Link key={e.id} to={`/consultations/${e.id}`} className="notice">
                    <strong>{e.diagnoses[0] ?? e.chief_complaint}</strong>
                    <div className="small subtle">{formatDateTime(e.signed_at)}</div>
                  </Link>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------- visit page
type VisitTab = "note" | "investigations" | "prescription" | "documents";
const EXAM_FIELDS: NoteField[] = [
  "exam_heent",
  "exam_lgs",
  "exam_resp",
  "exam_cvs",
  "exam_abd",
  "exam_gus",
  "exam_cns",
];
const EXAM_HINTS: Record<string, string> = {
  exam_heent: "Head, eyes, ears, nose, throat",
  exam_lgs: "Lymph glandular system",
  exam_resp: "Respiratory system",
  exam_cvs: "Cardiovascular system",
  exam_abd: "Abdomen",
  exam_gus: "Genitourinary system",
  exam_cns: "Central nervous system",
};
// Sections of the earlier note layout. Shown only when an older note has text in them.
const LEGACY_FIELDS: NoteField[] = [
  "surgical_history",
  "physical_examination",
  "systems_examination",
  "assessment",
  "differential_diagnosis",
];

export function ConsultationWorkspace() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const { user, can } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as VisitTab) || "note";
  const enc = useGet<Encounter>(["encounter", id], `/encounters/${id}/`);
  const visit = useGet<Visit>(["visits", enc.data?.visit], enc.data ? `/visits/${enc.data.visit}/` : null);
  const labs = useGet<Paginated<LabOrder>>(["lab", "encounter", id], `/lab/orders/?encounter=${id}`, {
    refetchInterval: 30_000,
  });
  const [notes, setNotes] = useState<Partial<Record<NoteField, string>>>({});
  const [followUp, setFollowUp] = useState("");
  const [printRx, setPrintRx] = useState<Prescription | null>(null);
  const [printSummary, setPrintSummary] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [signError, setSignError] = useState<unknown>(null);
  const [confirmSign, setConfirmSign] = useState(false);
  const [busy, setBusy] = useState(false);
  const [amending, setAmending] = useState<NoteField | null>(null);
  const [bookingFollowUp, setBookingFollowUp] = useState(false);

  useEffect(() => {
    if (enc.data && !dirty) {
      setNotes(Object.fromEntries(NOTE_FIELDS.map((f) => [f, enc.data[f] ?? ""])));
      setFollowUp(enc.data.follow_up_date ?? "");
    }
  }, [enc.data, dirty]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (dirty) e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (enc.isLoading) return <Loading />;
  if (!enc.data) return <ErrorBanner error={enc.error} />;
  const e = enc.data;
  const mine = e.doctor.id === user?.id;
  const editable = e.status === "draft" && mine;
  const visitOpen = !!visit.data && !["completed", "cancelled"].includes(visit.data.status);
  // Investigations and prescriptions can be sent before or after signing, while the visit is open.
  const canOrder = mine && visitOpen;
  const labCount = labs.data?.results.reduce((n, o) => n + o.items.length, 0) ?? 0;
  const rxCount = e.prescriptions.reduce((n, rx) => n + rx.items.length, 0);
  const goTab = (k: VisitTab) => setParams({ tab: k });

  const save = async () => {
    setBusy(true);
    setSaveError(null);
    try {
      await api.patch(`/encounters/${e.id}/`, { version: e.version, ...notes, follow_up_date: followUp || null });
      setDirty(false);
      await enc.refetch();
      return true;
    } catch (err) {
      setSaveError(err);
      return false;
    } finally {
      setBusy(false);
    }
  };
  const sign = async () => {
    setSignError(null);
    if (dirty && !(await save())) return;
    setConfirmSign(true);
  };
  const doSign = async () => {
    try {
      await api.post(`/encounters/${e.id}/sign/`);
      await enc.refetch();
      void visit.refetch();
      toast(t("consult.signed_toast", "Evaluation note signed"));
    } catch (err) {
      setSignError(err);
    }
  };
  const change = (field: NoteField, value: string) => {
    setNotes({ ...notes, [field]: value });
    setDirty(true);
  };
  const latestAmendment = (field: string) => [...e.amendments].reverse().find((a) => a.field_name === field);
  const shown = (field: NoteField) => {
    const amendment = latestAmendment(field);
    const value = field === "general_appearance" ? generalAppearanceLabel(e[field]) : e[field];
    return (
      <>
        <p className="prewrap">{value || <span className="subtle">—</span>}</p>
        {amendment && (
          <div className="amended small">
            <strong>
              {t("consult.amended_by", "Amended by {{who}}, {{when}}", {
                who: amendment.author.full_name,
                when: formatDateTime(amendment.created_at),
              })}
            </strong>
            <p className="prewrap">{amendment.amended_text}</p>
            <p className="subtle">
              {t("consult.reason", "Reason")}: {amendment.reason}
            </p>
          </div>
        )}
      </>
    );
  };
  const amendButton = (field: NoteField) =>
    e.status === "signed" &&
    can("clinical.amend") &&
    mine && (
      <button className="btn btn-sm btn-ghost" onClick={() => setAmending(field)}>
        {t("consult.amend", "Amend")}
      </button>
    );
  const noteField = (field: NoteField, hint?: string) => {
    const short = SHORT_NOTE_FIELDS.has(field);
    const label = t(`note.${field}`, NOTE_LABELS[field]);
    return (
      <div className="note-section" key={field}>
        {editable ? (
          <>
            <label htmlFor={`n-${field}`}>
              {label}
              {(field === "chief_complaint" || field === "plan") && (
                <span className="subtle small"> ({t("consult.required_to_sign", "required to sign")})</span>
              )}
            </label>
            {field === "general_appearance" ? (
              <select id={`n-${field}`} value={notes[field] ?? ""} onChange={(ev) => change(field, ev.target.value)}>
                <option value="">{t("common.not_recorded", "Not recorded")}</option>
                {GENERAL_APPEARANCE.map((g) => (
                  <option key={g.key} value={g.key}>
                    {t(`ga.${g.key}`, g.label)}
                  </option>
                ))}
              </select>
            ) : short ? (
              <input
                id={`n-${field}`}
                value={notes[field] ?? ""}
                maxLength={60}
                placeholder={t("consult.duration_ph", "e.g. 3 days")}
                onChange={(ev) => change(field, ev.target.value)}
              />
            ) : (
              <textarea
                id={`n-${field}`}
                rows={["history_present_illness", "plan"].includes(field) ? 3 : 2}
                value={notes[field] ?? ""}
                placeholder={hint}
                onChange={(ev) => change(field, ev.target.value)}
              />
            )}
          </>
        ) : (
          <>
            <div className="row-between">
              <span className="label" style={{ fontWeight: 700 }}>
                {label}
              </span>
              {!short && amendButton(field)}
            </div>
            {shown(field)}
          </>
        )}
      </div>
    );
  };
  const examRow = (field: NoteField) => (
    <div className="exam-row" key={field}>
      <label htmlFor={`n-${field}`} title={EXAM_HINTS[field]}>
        {NOTE_LABELS[field]}
      </label>
      {editable ? (
        <input
          id={`n-${field}`}
          value={notes[field] ?? ""}
          placeholder={t(`exam_hint.${field}`, EXAM_HINTS[field])}
          onChange={(ev) => change(field, ev.target.value)}
        />
      ) : (
        <div>{shown(field)}</div>
      )}
      {!editable && <div>{amendButton(field)}</div>}
    </div>
  );
  const legacy = LEGACY_FIELDS.filter((f) => (e[f] ?? "").trim());

  return (
    <div className="stack">
      <ConfirmDialog
        open={confirmSign}
        onClose={() => setConfirmSign(false)}
        onConfirm={() => void doSign()}
        title={t("consult.sign_title", "Sign the evaluation note?")}
        confirmLabel={t("consult.sign_note", "Sign note")}
        body={t(
          "consult.confirm_sign3",
          "After signing, the note can only be corrected by an amendment. You can still send investigations and a prescription from their pages while the visit is open.",
        )}
      />
      <section className="patient-banner">
        <div className="avatar" aria-hidden>
          {initials(e.patient.full_name)}
        </div>
        <div>
          <h1>{e.patient.full_name}</h1>
          <div className="ids">
            <span className="mono">{e.patient.mrn}</span>
            <span>{sexAge(e.patient, t)}</span>
            <span>Dr. {e.doctor.full_name}</span>
            <span>{formatDateTime(e.created_at)}</span>
          </div>
          <PatientAllergies patientId={e.patient.id} />
        </div>
        <div className="row" style={{ alignSelf: "start" }}>
          {e.status === "signed" ? (
            <Badge tone="ok">{t("consult.signed_at", "Signed {{when}}", { when: formatDateTime(e.signed_at) })}</Badge>
          ) : (
            <Badge tone="wait">{t("consult.draft", "Draft, not signed")}</Badge>
          )}
          {e.status === "signed" && (
            <button type="button" className="btn btn-ghost" onClick={() => setPrintSummary(true)}>
              <Printer size={16} aria-hidden /> {t("summary.print", "Summary for the patient")}
            </button>
          )}
          <Link className="btn btn-ghost" to={`/patients/${e.patient.id}`}>
            {t("consult.open_chart", "Full chart")}
          </Link>
        </div>
      </section>

      {visit.data && <ReferredHere visitId={visit.data.id} encounterId={e.id} />}

      <Tabs
        tabs={
          [
            { key: "note", label: t("visit.tab_note", "Evaluation note") },
            { key: "investigations", label: t("visit.tab_investigations", "Investigations"), count: labCount },
            { key: "prescription", label: t("visit.tab_prescription", "Prescription"), count: rxCount },
            { key: "documents", label: t("visit.tab_documents", "Referral & certificates") },
          ] as { key: VisitTab; label: string; count?: number }[]
        }
        value={tab}
        onChange={goTab}
      />

      {saveError instanceof ApiError && saveError.status === 409 && (
        <Banner tone="warn">
          {saveError.message}{" "}
          <button
            className="link-btn"
            onClick={() => {
              setDirty(false);
              void enc.refetch();
            }}
          >
            {t("consult.reload", "Reload note")}
          </button>
        </Banner>
      )}
      {!!saveError && !(saveError instanceof ApiError && saveError.status === 409) && <ErrorBanner error={saveError} />}
      {!!signError && <ErrorBanner error={signError} />}

      <div className="workspace">
        <div className="stack">
          {tab === "note" && (
            <>
              {e.status === "signed" && mine && visitOpen && (
                <Banner tone="ok">
                  {t(
                    "consult.signed_next",
                    "Signed. Send investigations or a prescription from their pages if needed.",
                  )}{" "}
                  <button className="link-btn" onClick={() => goTab("investigations")}>
                    {t("visit.tab_investigations", "Investigations")}
                  </button>
                  {" · "}
                  <button className="link-btn" onClick={() => goTab("prescription")}>
                    {t("visit.tab_prescription", "Prescription")}
                  </button>
                </Banner>
              )}
              <Panel
                title={t("consult.evaluation_note", "Evaluation note")}
                actions={
                  editable && (
                    <span className="small subtle">
                      {dirty ? t("consult.unsaved", "Unsaved changes") : t("consult.saved", "All changes saved")}
                    </span>
                  )
                }
              >
                {NOTE_GROUPS.map((g) => (
                  <div className="note-group" key={g.title}>
                    <h3 className="note-group-title">{t(`note.group.${g.title}`, g.title)}</h3>
                    <div
                      className={
                        g.fields.length === 2 && g.fields.some((f) => SHORT_NOTE_FIELDS.has(f)) ? "note-row" : undefined
                      }
                    >
                      {g.fields.map((f) => noteField(f as NoteField, g.hint?.[f]))}
                    </div>
                    {g.title.startsWith("4.") && (
                      <>
                        <h4 className="note-sub">{t("consult.system_findings", "System-specific findings")}</h4>
                        <div className="exam-grid">{EXAM_FIELDS.map(examRow)}</div>
                      </>
                    )}
                  </div>
                ))}
                {legacy.length > 0 && (
                  <div className="note-group">
                    <h3 className="note-group-title">{t("consult.legacy", "From the earlier note layout")}</h3>
                    {legacy.map((f) => (
                      <div className="note-section" key={f}>
                        <span className="label" style={{ fontWeight: 700 }}>
                          {NOTE_LABELS[f]}
                        </span>
                        {shown(f)}
                      </div>
                    ))}
                  </div>
                )}
              </Panel>
              <DiagnosesPanel encounter={e} editable={editable} onChange={() => void enc.refetch()} />
              <Panel title={t("note.group.6. Treatment plan", "6. Treatment plan")}>
                {["plan", "non_drug_treatment", "follow_up_instructions"].map((f) => noteField(f as NoteField))}
                <div className="note-section">
                  <label htmlFor="n-fu">{t("consult.follow_up_date", "Follow-up date")}</label>
                  <div className="row">
                    {editable ? (
                      <input
                        id="n-fu"
                        type="date"
                        value={followUp}
                        onChange={(ev) => {
                          setFollowUp(ev.target.value);
                          setDirty(true);
                        }}
                      />
                    ) : (
                      <span>{e.follow_up_date ?? "—"}</span>
                    )}
                    {can("appointments.manage") && mine && (
                      <button type="button" className="btn btn-sm" onClick={() => setBookingFollowUp(true)}>
                        <CalendarPlus size={15} aria-hidden />{" "}
                        {t("consult.book_follow_up", "Book follow-up appointment")}
                      </button>
                    )}
                  </div>
                </div>
              </Panel>
              {editable && (
                <div className="action-bar">
                  <button className="btn" onClick={() => void save()} disabled={busy || !dirty}>
                    <Save size={16} aria-hidden /> {t("consult.save_draft", "Save draft")}
                  </button>
                  <button className="btn btn-primary" onClick={() => void sign()} disabled={busy}>
                    <FileSignature size={16} aria-hidden /> {t("consult.sign_note", "Sign note")}
                  </button>
                </div>
              )}
            </>
          )}

          {tab === "investigations" && (
            <>
              <LabPanel orders={labs.data?.results ?? []} loading={labs.isLoading} />
              {canOrder && can("lab.request") && (
                <Panel title={t("consult.order_labs", "Request laboratory tests")}>
                  <LabOrderForm encounterId={e.id} onDone={() => void labs.refetch()} />
                </Panel>
              )}
            </>
          )}

          {tab === "prescription" && (
            <>
              <Panel title={t("consult.prescriptions", "Prescriptions")}>
                {e.prescriptions.length === 0 ? (
                  <p className="subtle">{t("consult.no_rx", "No medicines prescribed.")}</p>
                ) : (
                  e.prescriptions.map((rx) => (
                    <div key={rx.id} className="stack-sm" style={{ marginBottom: 12 }}>
                      <div className="row">
                        <StateBadge set="rx" value={rx.status} />
                        {rx.number && <span className="mono small">{rx.number}</span>}
                        {rx.notes && <span className="small muted">{rx.notes}</span>}
                        {rx.status !== "cancelled" && (
                          <button
                            type="button"
                            className="btn btn-sm"
                            style={{ marginLeft: "auto" }}
                            onClick={() => setPrintRx(rx)}
                          >
                            <Printer size={14} aria-hidden /> {t("common.view_print", "View / print")}
                          </button>
                        )}
                      </div>
                      <table className="data">
                        <tbody>
                          {rx.items.map((i) => (
                            <tr key={i.id}>
                              <td>
                                <strong>{i.drug_name}</strong>
                              </td>
                              <td>
                                {i.dose}, {i.route}, {i.frequency}
                                {i.duration_days ? `, ${i.duration_days} days` : ""}
                                {i.instructions && <div className="small muted">{i.instructions}</div>}
                              </td>
                              <td className="num">
                                {Number(i.quantity)} {i.unit}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ))
                )}
              </Panel>
              {canOrder &&
                can("prescriptions.create") &&
                (e.diagnoses.length === 0 ? (
                  <Banner tone="warn">
                    {t("rx.needs_dx", "Add the physician diagnosis in the evaluation note before prescribing.")}{" "}
                    <button className="link-btn" onClick={() => goTab("note")}>
                      {t("visit.tab_note", "Evaluation note")}
                    </button>
                  </Banner>
                ) : (
                  <Panel title={t("consult.prescribe", "Prescribe")}>
                    <PrescriptionForm
                      key={e.prescriptions.length}
                      encounterId={e.id}
                      onDone={() => void enc.refetch()}
                    />
                  </Panel>
                ))}
            </>
          )}

          {tab === "documents" && (
            <DocumentsPanel
              encounter={e}
              mine={mine && can("clinical.write")}
              visitOpen={visitOpen}
              visitDepartment={visit.data?.department ?? ""}
            />
          )}
        </div>

        <aside className="stack side-sticky">
          <VitalsSummary visitId={e.visit} />
          <ClinicalContext patientId={e.patient.id} />
          <PreviousConsultations patientId={e.patient.id} currentId={e.id} />
        </aside>
      </div>

      <Modal
        open={amending !== null}
        title={t("consult.amend_title", "Amend: {{section}}", { section: amending ? NOTE_LABELS[amending] : "" })}
        onClose={() => setAmending(null)}
      >
        {amending && (
          <AmendForm
            encounter={e}
            field={amending}
            onDone={() => {
              setAmending(null);
              void enc.refetch();
            }}
          />
        )}
      </Modal>
      <Modal
        open={printSummary}
        wide
        title={t("summary.title", "Consultation summary")}
        onClose={() => setPrintSummary(false)}
      >
        {printSummary && enc.data && <ConsultationSummary encounter={enc.data} labs={labs.data?.results ?? []} />}
      </Modal>
      <Modal
        open={printRx !== null}
        wide
        title={t("rx.document_title", "Prescription")}
        onClose={() => setPrintRx(null)}
      >
        {printRx && <PrescriptionDoc rx={printRx} allergies={e.allergy_notes} />}
      </Modal>
      <Modal
        open={bookingFollowUp}
        title={t("consult.book_follow_up", "Book follow-up appointment")}
        onClose={() => setBookingFollowUp(false)}
      >
        {bookingFollowUp && (
          <AppointmentForm
            patient={e.patient}
            encounterId={e.id}
            defaultDoctor={e.doctor.id}
            defaultDate={followUp || undefined}
            defaultReason={t("consult.follow_up_reason", "Follow-up")}
            onDone={() => setBookingFollowUp(false)}
          />
        )}
      </Modal>
    </div>
  );
}

function PatientAllergies({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const p = useGet<Patient>(["patient", patientId], `/patients/${patientId}/`);
  const allergies = p.data?.allergies?.filter((a) => a.is_active) ?? [];
  if (!p.data) return null;
  return (
    <div className={`alert-strip${allergies.length ? "" : " none"}`}>
      {allergies.length > 0 && <AlertTriangle size={16} aria-hidden />}
      {allergies.length ? (
        <span>
          <strong>{t("patients.allergies", "Allergies")}:</strong>{" "}
          {allergies.map((a) => `${a.substance} (${a.severity})`).join(", ")}
        </span>
      ) : (
        <span>{t("patients.no_allergies", "No known allergies recorded")}</span>
      )}
    </div>
  );
}

function VitalsSummary({ visitId }: { visitId: string }) {
  const { t } = useTranslation();
  const triageLabel = useTriageLabel();
  const q = useGet<Paginated<Vitals>>(["vitals", "visit", visitId], `/visits/${visitId}/vitals/`);
  const v = q.data?.results[0];
  const flags = v?.interpretation.flags ?? {};
  const level = (...keys: string[]) => keys.map((k) => flags[k]?.level).find(Boolean);
  const cell = (label: string, value: string | number | null | undefined, ...keys: string[]) => {
    const l = level(...keys);
    const title = keys
      .map((k) => flags[k]?.text)
      .filter(Boolean)
      .join("; ");
    return (
      <div
        className={`vital${l === "critical" ? " abnormal" : l === "abnormal" ? " abnormal-amber" : ""}`}
        title={title || undefined}
      >
        <b>{value ?? "—"}</b>
        <span>{label}</span>
      </div>
    );
  };
  const news = v?.interpretation.news2;
  return (
    <Panel title={t("consult.triage", "Triage")}>
      {!v ? (
        <p className="subtle">{t("consult.no_vitals_recorded", "Not recorded for this visit.")}</p>
      ) : (
        <div className="stack-sm">
          {(v.chief_complaint || v.symptoms || v.triage_to) && (
            <dl className="facts small">
              {v.triage_to && (
                <>
                  <dt>{t("triage.triage_to", "Triage to")}</dt>
                  <dd>
                    <strong>{triageLabel(v.triage_to)}</strong>
                  </dd>
                </>
              )}
              {v.chief_complaint && (
                <>
                  <dt>{t("triage.complaint", "Main complaint")}</dt>
                  <dd>
                    {v.chief_complaint}
                    {v.complaint_duration && `, ${v.complaint_duration}`}
                  </dd>
                </>
              )}
              {v.general_appearance && (
                <>
                  <dt>{t("triage.general_appearance", "General appearance")}</dt>
                  <dd>{generalAppearanceLabel(v.general_appearance)}</dd>
                </>
              )}
              {v.symptoms && (
                <>
                  <dt>{t("triage.symptoms", "Symptoms")}</dt>
                  <dd>{v.symptoms}</dd>
                </>
              )}
              {v.current_medications && (
                <>
                  <dt>{t("triage.meds", "Medications")}</dt>
                  <dd>{v.current_medications}</dd>
                </>
              )}
              {v.observations && (
                <>
                  <dt>{t("triage.observations", "Observed")}</dt>
                  <dd>{v.observations}</dd>
                </>
              )}
              {v.notes && (
                <>
                  <dt>{t("vitals.notes", "Notes")}</dt>
                  <dd>{v.notes}</dd>
                </>
              )}
            </dl>
          )}
          <div className="vitals-grid">
            {cell("BP mmHg", v.systolic ? `${v.systolic}/${v.diastolic ?? "–"}` : null, "systolic", "diastolic")}
            {cell("Temp °C", v.temperature_c, "temperature_c")}
            {cell("Pulse", v.heart_rate, "heart_rate")}
            {cell("Resp /min", v.respiratory_rate, "respiratory_rate")}
            {cell("SpO₂ %", v.spo2, "spo2")}
            {cell("BMI", v.bmi)}
            {cell("Weight kg", v.weight_kg)}
            {cell("Height cm", v.height_cm)}
            {cell("Pain", v.pain_score)}
          </div>
          {Object.keys(flags).length > 0 && (
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
              {Object.entries(flags).map(([k, f]) => (
                <li key={k} className={f.level === "critical" ? "flag-H" : ""}>
                  {f.text}
                </li>
              ))}
            </ul>
          )}
          {news && (
            <p className="small">
              <strong>NEWS2 {news.total}</strong>
              {news.complete ? `, ${news.risk} risk` : ` (${t("triage.incomplete", "incomplete")})`}
            </p>
          )}
          <p className="small subtle">
            {v.allergies_confirmed ? t("consult.allergies_checked", "Allergies checked at triage. ") : ""}
            {v.recorded_by.full_name}, {formatDateTime(v.recorded_at)}
            {q.data &&
              q.data.count > 1 &&
              `, ${t("consult.more_vitals", "{{n}} measurements today", { n: q.data.count })}`}
          </p>
        </div>
      )}
    </Panel>
  );
}

function PreviousConsultations({ patientId, currentId }: { patientId: string; currentId: string }) {
  const { t } = useTranslation();
  const q = useGet<Paginated<EncounterSummary>>(
    ["encounters", "patient", patientId],
    `/encounters/?patient=${patientId}&page_size=6`,
  );
  const rows = q.data?.results.filter((e) => e.id !== currentId) ?? [];
  return (
    <Panel title={t("consult.history", "Previous consultations")}>
      {rows.length === 0 ? (
        <p className="subtle">{t("consult.first_visit", "No earlier consultations.")}</p>
      ) : (
        <ol className="timeline">
          {rows.map((e) => (
            <li key={e.id}>
              <Link to={`/consultations/${e.id}`}>
                <strong>{formatDateTime(e.signed_at ?? e.created_at)}</strong>
              </Link>
              <div className="small">{e.diagnoses.join("; ") || e.chief_complaint}</div>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

/** Everything the doctor should see beside the note without leaving the page. */
function ClinicalContext({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const q = useGet<ClinicalSummary>(
    ["patient", patientId, "clinical-summary"],
    `/patients/${patientId}/clinical-summary/`,
  );
  const s = q.data;
  if (!s) return null;
  return (
    <Panel title={t("consult.context", "Patient history")}>
      <dl className="facts small">
        <dt>{t("patients.chronic_illness", "Chronic illness")}</dt>
        <dd className="prewrap">{s.known_conditions || "—"}</dd>
        <dt>{t("patients.past_history_short", "History")}</dt>
        <dd className="prewrap">{s.past_history || "—"}</dd>
        <dt>{t("patients.current_medications", "Current medicines")}</dt>
        <dd className="prewrap">{s.current_medications || "—"}</dd>
        <dt>{t("consult.visits", "Visits")}</dt>
        <dd>
          {s.visit_count}
          {s.last_visit && `, ${t("consult.last", "last")} ${s.last_visit}`}
        </dd>
      </dl>
      {s.diagnoses.length > 0 && (
        <>
          <h3 className="side-sub">{t("consult.prev_dx", "Previous diagnoses")}</h3>
          <ul className="side-list">
            {s.diagnoses.map((d, i) => (
              <li key={i}>
                {d.code && <span className="mono">{d.code} </span>}
                {d.description}
                {d.certainty === "provisional" && (
                  <span className="subtle"> ({t("consult.provisional", "provisional")})</span>
                )}
                <span className="subtle"> {formatDateTime(d.date).split(",")[0]}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {s.results.length > 0 && (
        <>
          <h3 className="side-sub">{t("consult.prev_results", "Recent laboratory results")}</h3>
          <ul className="side-list">
            {s.results.map((r, i) => (
              <li key={i} className={r.flag && r.flag !== "N" ? "flag-H" : undefined}>
                {r.test}: {r.result} {r.unit}
                {r.flag && r.flag !== "N" ? ` (${FLAG_LABEL[r.flag]})` : ""}
                <span className="subtle"> {formatDateTime(r.date).split(",")[0]}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {s.recent_prescriptions.length > 0 && (
        <>
          <h3 className="side-sub">{t("consult.prev_rx", "Recent prescriptions")}</h3>
          <ul className="side-list">
            {s.recent_prescriptions.map((r, i) => (
              <li key={i}>
                {r.drug}, {r.dose} {r.frequency}
                {r.days ? `, ${r.days} d` : ""}
                <span className="subtle"> {formatDateTime(r.date).split(",")[0]}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}
