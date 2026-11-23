/** Dental pages: patient dental record, examinations list, recalls, laboratory cases and dental catalogue. */
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { api, queryString } from "../../api/client";
import { useGet } from "../../api/hooks";
import type { Paginated, PersonBrief } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import {
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
  Tabs,
  money,
  toast,
} from "../../ui";
import { formatDateTime } from "../../lib/format";
import { ChartView } from "./ChartView";
import { DentalStatus, PENDING_REVIEW_NOTE, useDentalCatalog } from "./common";
import { ImagesPanel } from "./Images";
import { PerioHistory } from "./Perio";
import { PlanList } from "./Plans";
import { ProcedureDetail, ProcedureTable } from "./Procedures";
import { AlertStrip, ProfilePanel } from "./Workspace";
import type {
  DentalProcedure,
  DentalSummary,
  DiagnosisTerm,
  EncounterBrief,
  FindingType,
  LabCase,
  ProcedureRecordBrief,
  Recall,
} from "./types";

// ===========================================================================
// Patient dental record
// ===========================================================================
type RecordTab = "overview" | "chart" | "perio" | "plans" | "procedures" | "images" | "recalls";

export function DentalPatientPage() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const { can, moduleOn } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as RecordTab) || "overview";
  const summary = useGet<DentalSummary>(["dental", "summary", id], `/dental/patients/${id}/summary/`);
  const patient = useGet<{ id: string; mrn: string; full_name: string; sex: string; age: number }>(
    ["patient", id],
    `/patients/${id}/`,
  );
  const procs = useGet<Paginated<ProcedureRecordBrief>>(
    ["dental", "procedures", id],
    tab === "procedures" ? `/dental/procedure-records/?patient=${id}&page_size=100` : null,
  );
  const [openProc, setOpenProc] = useState<string | null>(null);
  const [labCase, setLabCase] = useState(false);
  if (summary.isLoading) return <Loading />;
  if (!summary.data) return <ErrorBanner error={summary.error} />;
  const s = summary.data;
  const name = patient.data?.full_name ?? "";
  const tabs: { key: RecordTab; label: string }[] = [
    { key: "overview", label: t("dental.overview", "Overview") },
    { key: "chart", label: t("dental.tab_chart", "Chart") },
    ...(moduleOn("periodontal") ? [{ key: "perio" as const, label: t("dental.tab_perio", "Periodontal") }] : []),
    { key: "plans", label: t("dental.plans", "Treatment plans") },
    { key: "procedures", label: t("dental.tab_procedures", "Procedures") },
    ...(moduleOn("dental_imaging") && can("dental.imaging.view")
      ? [{ key: "images" as const, label: t("dental.tab_images", "Images") }]
      : []),
    ...(moduleOn("recalls") ? [{ key: "recalls" as const, label: t("dental.recalls", "Recalls") }] : []),
  ];
  return (
    <div className="stack">
      <PageHead
        title={`${t("dental.dental_record", "Dental record")} · ${name}`}
        sub={patient.data && `MRN ${patient.data.mrn} · ${patient.data.sex}, ${patient.data.age}`}
        actions={
          <>
            {can("dental.labcase.manage") && moduleOn("dental_lab") && (
              <button className="btn" onClick={() => setLabCase(true)}>
                {t("dental.new_case", "Laboratory case…")}
              </button>
            )}
            <Link className="btn" to={`/patients/${id}`}>
              {t("dental.patient_record", "Patient record")}
            </Link>
          </>
        }
      />
      <Modal open={labCase} title={t("dental.new_case", "New laboratory case")} onClose={() => setLabCase(false)}>
        {labCase && <NewLabCase patientId={id} onDone={() => setLabCase(false)} />}
      </Modal>
      <AlertStrip summary={s} />
      <Tabs tabs={tabs} value={tab} onChange={(k) => setParams({ tab: k }, { replace: true })} />
      {tab === "overview" && (
        <div className="split">
          <Panel title={t("dental.examinations", "Examinations")}>
            {s.encounters.length === 0 ? (
              <Empty>{t("dental.no_exams", "No dental examinations yet. Start one from the waiting list.")}</Empty>
            ) : (
              <table className="data">
                <tbody>
                  {s.encounters.map((e) => (
                    <tr key={e.id}>
                      <td>{formatDateTime(e.created_at)}</td>
                      <td>
                        {e.chief_complaint || <span className="subtle">—</span>}
                        {e.diagnoses.length > 0 && <div className="small subtle">{e.diagnoses.join("; ")}</div>}
                      </td>
                      <td>{e.dentist.full_name}</td>
                      <td>
                        <DentalStatus value={e.status} />
                      </td>
                      <td className="num">
                        <Link className="btn btn-sm" to={`/dental/encounters/${e.id}`}>
                          {t("common.view", "View")}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
          <div className="stack">
            <Panel title={t("dental.plans", "Treatment plans")}>
              {s.plans.length === 0 ? (
                <p className="muted">{t("dental.no_plans", "No treatment plans yet.")}</p>
              ) : (
                s.plans.map((p) => (
                  <div key={p.id} className="row-between">
                    <span>
                      {p.number} · {p.title} · {money(p.estimated_total)} ETB
                    </span>
                    <DentalStatus value={p.status} />
                  </div>
                ))
              )}
            </Panel>
            <ProfilePanel patientId={id} profile={s.profile} writable={can("dental.write")} />
          </div>
        </div>
      )}
      {tab === "chart" && <ChartView patientId={id} patientName={name} editable={false} encounters={s.encounters} />}
      {tab === "perio" && <PerioHistory patientId={id} />}
      {tab === "plans" && <PlanList patientId={id} />}
      {tab === "procedures" && (
        <Panel title={t("dental.tab_procedures", "Procedures")}>
          {procs.isLoading ? <Loading /> : <ProcedureTable rows={procs.data?.results ?? []} onOpen={setOpenProc} />}
          <Modal
            open={!!openProc}
            title={t("dental.procedure_record", "Procedure record")}
            onClose={() => setOpenProc(null)}
            wide
          >
            {openProc && <ProcedureDetail id={openProc} onClose={() => setOpenProc(null)} />}
          </Modal>
        </Panel>
      )}
      {tab === "images" && <ImagesPanel patientId={id} />}
      {tab === "recalls" && <PatientRecalls patientId={id} />}
    </div>
  );
}

function PatientRecalls({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const q = useGet<Recall[]>(["dental", "recalls", patientId], `/dental/patients/${patientId}/recalls/`);
  if (q.isLoading) return <Loading />;
  return (
    <Panel title={t("dental.recalls", "Recalls")}>
      {!q.data?.length ? (
        <Empty>{t("dental.no_recalls", "No follow-ups or recalls.")}</Empty>
      ) : (
        <table className="data">
          <tbody>
            {q.data.map((r) => (
              <tr key={r.id}>
                <td>{r.due_date}</td>
                <td>
                  {r.kind_label}
                  {r.note && <div className="small subtle">{r.note}</div>}
                </td>
                <td>
                  <DentalStatus value={r.status} />
                </td>
                <td>{r.appointment ? formatDateTime(r.appointment.scheduled_at) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

// ===========================================================================
// My dental examinations
// ===========================================================================
export function DentalEncountersPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState("draft");
  const [page, setPage] = useState(1);
  const q = useGet<Paginated<EncounterBrief & { patient: string }>>(
    ["dental", "encounters", status, page],
    `/dental/encounters/${queryString({ mine: "true", status, page })}`,
  );
  return (
    <div className="stack">
      <PageHead
        title={t("nav.dental_encounters", "My dental examinations")}
        sub={t("dental.encounters_sub", "Start a new examination from the waiting list.")}
        actions={
          <select aria-label={t("users.status")} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="draft">{t("dental.status_draft", "Draft")}</option>
            <option value="signed">{t("dental.status_signed", "Signed")}</option>
            <option value="">{t("common.all", "All")}</option>
          </select>
        }
      />
      <ErrorBanner error={q.error} />
      <Panel flush>
        {q.isLoading ? (
          <Loading />
        ) : !q.data?.results.length ? (
          <Empty>{t("dental.none_here", "Nothing here.")}</Empty>
        ) : (
          <table className="data">
            <tbody>
              {q.data.results.map((e) => (
                <tr key={e.id}>
                  <td>{formatDateTime(e.created_at)}</td>
                  <td>{e.chief_complaint || <span className="subtle">—</span>}</td>
                  <td className="small subtle">{e.diagnoses.join("; ")}</td>
                  <td>
                    <DentalStatus value={e.status} />
                  </td>
                  <td className="num">
                    <Link className="btn btn-sm btn-primary" to={`/dental/encounters/${e.id}`}>
                      {t("common.open", "Open")}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
      {q.data && <Pager page={page} count={q.data.count} pageSize={25} onPage={setPage} />}
    </div>
  );
}

// ===========================================================================
// Recall worklist
// ===========================================================================
export function RecallsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const q = useGet<Paginated<Recall>>(
    ["dental", "recall-list", status, page],
    `/dental/recalls/${queryString({ status, page })}`,
  );
  const [acting, setActing] = useState<{ recall: Recall; kind: "book" | "contact" | "postpone" | "close" } | null>(
    null,
  );
  const refresh = () => void qc.invalidateQueries({ queryKey: ["dental", "recall-list"] });
  const today = new Date().toISOString().slice(0, 10);
  return (
    <div className="stack">
      <PageHead
        title={t("nav.recalls", "Recalls and follow-ups")}
        sub={t(
          "dental.recalls_sub",
          "Patients due for a review or preventive recall. Nothing is sent to patients automatically.",
        )}
        actions={
          <select aria-label={t("users.status")} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("dental.open", "Open (due, booked, postponed)")}</option>
            <option value="completed">{t("dental.status_completed", "Attended")}</option>
            <option value="declined">{t("dental.status_declined", "Declined")}</option>
            <option value="unreachable">{t("dental.status_unreachable", "Unreachable")}</option>
            <option value="cancelled">{t("dental.status_cancelled", "Cancelled")}</option>
          </select>
        }
      />
      <ErrorBanner error={q.error} />
      <Panel flush>
        {q.isLoading ? (
          <Loading />
        ) : !q.data?.results.length ? (
          <Empty>{t("dental.no_recalls", "No follow-ups or recalls.")}</Empty>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>{t("dental.due", "Due")}</th>
                <th>{t("dental.patient", "Patient")}</th>
                <th>{t("dental.phone", "Phone")}</th>
                <th>{t("dental.recall_kind", "Kind")}</th>
                <th>{t("users.status")}</th>
                <th>{t("dental.contacts", "Contact attempts")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {q.data.results.map((r) => (
                <tr key={r.id} className={r.due_date < today && r.status !== "booked" ? "overdue" : ""}>
                  <td>
                    {r.due_date}
                    {r.due_date < today && r.status !== "booked" && (
                      <span className="badge badge-danger">{t("dental.overdue", "overdue")}</span>
                    )}
                  </td>
                  <td>
                    {r.patient.full_name} <span className="mono small">{r.patient.mrn}</span>
                    {r.note && <div className="small subtle">{r.note}</div>}
                  </td>
                  <td className="mono">{r.phone}</td>
                  <td>{r.kind_label}</td>
                  <td>
                    <DentalStatus value={r.status} />
                    {r.appointment && <div className="small">{formatDateTime(r.appointment.scheduled_at)}</div>}
                  </td>
                  <td className="small">
                    {r.contacts.length
                      ? `${r.contacts.length} · ${r.contacts[0].outcome.replace("_", " ")} (${formatDateTime(r.contacts[0].at)})`
                      : "—"}
                  </td>
                  <td className="num">
                    {can("dental.recall.manage") && ["due", "postponed", "booked"].includes(r.status) && (
                      <div className="row">
                        {r.status !== "booked" && (
                          <button
                            className="btn btn-sm btn-primary"
                            onClick={() => setActing({ recall: r, kind: "book" })}
                          >
                            {t("dental.book", "Book…")}
                          </button>
                        )}
                        <button className="btn btn-sm" onClick={() => setActing({ recall: r, kind: "contact" })}>
                          {t("dental.log_contact", "Log call…")}
                        </button>
                        <button
                          className="btn btn-sm btn-ghost"
                          onClick={() => setActing({ recall: r, kind: "postpone" })}
                        >
                          {t("dental.postpone", "Postpone…")}
                        </button>
                        <button
                          className="btn btn-sm btn-ghost"
                          onClick={() => setActing({ recall: r, kind: "close" })}
                        >
                          {t("dental.close", "Close…")}
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
      {q.data && <Pager page={page} count={q.data.count} pageSize={25} onPage={setPage} />}
      <Modal open={!!acting} title={acting?.recall.patient.full_name ?? ""} onClose={() => setActing(null)}>
        {acting && (
          <RecallAction
            recall={acting.recall}
            kind={acting.kind}
            onDone={() => {
              setActing(null);
              refresh();
            }}
          />
        )}
      </Modal>
    </div>
  );
}

function RecallAction({
  recall,
  kind,
  onDone,
}: {
  recall: Recall;
  kind: "book" | "contact" | "postpone" | "close";
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [outcome, setOutcome] = useState("reached");
  const [note, setNote] = useState("");
  const [due, setDue] = useState("");
  const [status, setStatus] = useState("declined");
  const [apptId, setApptId] = useState("");
  const appts = useGet<Paginated<{ id: string; scheduled_at: string; status: string; doctor: PersonBrief }>>(
    ["appointments", "patient", recall.patient.id],
    kind === "book"
      ? `/appointments/?patient=${recall.patient.id}&date_from=${new Date().toISOString().slice(0, 10)}`
      : null,
  );
  const act = useMutation({
    mutationFn: () => {
      if (kind === "book") return api.post(`/dental/recalls/${recall.id}/book/`, { appointment_id: apptId });
      if (kind === "contact") return api.post(`/dental/recalls/${recall.id}/contact/`, { outcome, note });
      if (kind === "postpone")
        return api.post(`/dental/recalls/${recall.id}/status/`, { status: "postponed", due_date: due, reason: note });
      return api.post(`/dental/recalls/${recall.id}/status/`, { status, reason: note });
    },
    onSuccess: () => {
      toast(t("common.saved_toast", "Changes saved"));
      onDone();
    },
  });
  const upcoming = (appts.data?.results ?? []).filter((a) => ["scheduled", "confirmed"].includes(a.status));
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        act.mutate();
      }}
    >
      <ErrorBanner error={act.error} />
      {kind === "book" &&
        (upcoming.length ? (
          <Field label={t("dental.appointment", "Appointment")} id="f-appointment_id">
            <select id="f-appointment_id" value={apptId} onChange={(e) => setApptId(e.target.value)} required>
              <option value="">—</option>
              {upcoming.map((a) => (
                <option key={a.id} value={a.id}>
                  {formatDateTime(a.scheduled_at)} · {a.doctor.full_name}
                </option>
              ))}
            </select>
          </Field>
        ) : (
          <Banner tone="info">
            {t("dental.book_first", "Book the appointment first in Appointments, then link it here.")}{" "}
            <Link to="/appointments">{t("nav.appointments", "Appointments")}</Link>
          </Banner>
        ))}
      {kind === "contact" && (
        <Field label={t("dental.outcome", "What happened")} id="f-outcome">
          <select id="f-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option value="reached">{t("dental.reached", "Spoke to the patient")}</option>
            <option value="no_answer">{t("dental.no_answer", "No answer")}</option>
            <option value="wrong_number">{t("dental.wrong_number", "Wrong or unavailable number")}</option>
            <option value="message_left">{t("dental.message_left", "Message left")}</option>
          </select>
        </Field>
      )}
      {kind === "postpone" && (
        <Field label={t("dental.new_due", "New due date")} id="f-due_date" error={act.error}>
          <input id="f-due_date" type="date" value={due} onChange={(e) => setDue(e.target.value)} required />
        </Field>
      )}
      {kind === "close" && (
        <Field label={t("dental.close_as", "Close as")} id="f-status">
          <select id="f-status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="declined">{t("dental.status_declined", "Declined by the patient")}</option>
            <option value="unreachable">{t("dental.status_unreachable", "Could not be reached")}</option>
            <option value="completed">{t("dental.status_completed", "Attended")}</option>
            <option value="cancelled">{t("dental.status_cancelled", "Cancelled")}</option>
          </select>
        </Field>
      )}
      {kind !== "book" && (
        <Field
          label={kind === "close" ? t("dental.reason", "Reason") : t("dental.note", "Note")}
          id="f-note"
          error={act.error}
        >
          <input
            id="f-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            required={kind === "close" && status !== "completed"}
          />
        </Field>
      )}
      <div className="form-actions">
        <button type="button" className="btn" onClick={onDone}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={act.isPending || (kind === "book" && !apptId)}>
          {t("common.save", "Save")}
        </button>
      </div>
    </form>
  );
}

// ===========================================================================
// Dental laboratory cases
// ===========================================================================
export function LabCasesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const q = useGet<Paginated<LabCase>>(["dental", "lab-cases", status], `/dental/lab-cases/${queryString({ status })}`);
  const [moving, setMoving] = useState<{ c: LabCase; to: string } | null>(null);
  const move = useMutation({
    mutationFn: (v: { c: LabCase; to: string; note: string }) =>
      api.post(`/dental/lab-cases/${v.c.id}/move/`, { status: v.to, note: v.note }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dental", "lab-cases"] });
      setMoving(null);
    },
  });
  const manage = can("dental.labcase.manage");
  const next = (c: LabCase): { to: string; label: string }[] => {
    const out: { to: string; label: string }[] = [];
    if (can("dental.labcase.work")) {
      if (c.status === "requested") out.push({ to: "in_progress", label: t("dental.start_work", "Start work") });
      if (c.status === "in_progress") out.push({ to: "ready", label: t("dental.mark_ready", "Ready for fitting") });
    }
    if (manage) {
      if (c.status === "ready")
        out.push({ to: "delivered", label: t("dental.mark_delivered", "Delivered to patient") });
      if (c.status === "ready") out.push({ to: "in_progress", label: t("dental.send_back", "Send back for changes") });
      if (["requested", "in_progress"].includes(c.status)) out.push({ to: "cancelled", label: t("common.cancel") });
    }
    return out;
  };
  return (
    <div className="stack">
      <PageHead
        title={t("nav.lab_cases", "Dental laboratory cases")}
        sub={
          manage
            ? t(
                "dental.lab_sub",
                "Crowns, bridges and dentures sent to the technician. Create a case from the patient's dental record.",
              )
            : t("dental.lab_sub_tech", "Cases assigned to you.")
        }
        actions={
          <select aria-label={t("users.status")} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("dental.open_cases", "Open")}</option>
            <option value="delivered">{t("dental.status_delivered", "Delivered")}</option>
            <option value="cancelled">{t("dental.status_cancelled", "Cancelled")}</option>
          </select>
        }
      />
      <ErrorBanner error={q.error || move.error} />
      <Panel flush>
        {q.isLoading ? (
          <Loading />
        ) : !q.data?.results.length ? (
          <Empty>{t("dental.no_cases", "No laboratory cases.")}</Empty>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>{t("dental.number", "No.")}</th>
                <th>{t("dental.patient", "Patient")}</th>
                <th>{t("dental.work", "Work")}</th>
                <th>{t("dental.teeth", "Teeth")}</th>
                <th>{t("dental.due", "Due")}</th>
                <th>{t("dental.technician", "Technician")}</th>
                <th>{t("users.status")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {q.data.results.map((c) => (
                <tr key={c.id}>
                  <td className="mono small">{c.number}</td>
                  <td>
                    {c.patient.full_name} <span className="mono small">{c.patient.mrn}</span>
                  </td>
                  <td>
                    {c.case_type_label}
                    {c.shade && ` · ${t("dental.shade", "shade")} ${c.shade}`}
                    <div className="small prewrap">{c.instructions}</div>
                  </td>
                  <td>{c.teeth.join(", ")}</td>
                  <td>{c.due_date ?? "—"}</td>
                  <td>{c.technician?.full_name ?? "—"}</td>
                  <td>
                    <DentalStatus value={c.status} />
                  </td>
                  <td className="num">
                    <div className="row">
                      {next(c).map((n) => (
                        <button
                          key={n.to}
                          className="btn btn-sm"
                          onClick={() =>
                            n.to === "cancelled" ? setMoving({ c, to: n.to }) : move.mutate({ c, to: n.to, note: "" })
                          }
                        >
                          {n.label}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
      <ReasonDialog
        open={!!moving}
        title={t("dental.cancel_case", "Cancel the case")}
        label={t("dental.reason", "Reason")}
        confirmLabel={t("common.confirm", "Confirm")}
        onClose={() => setMoving(null)}
        onConfirm={(note) => moving && move.mutate({ ...moving, note })}
        busy={move.isPending}
        error={move.error}
        danger
      />
    </div>
  );
}

export function NewLabCase({ patientId, onDone }: { patientId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const catalog = useDentalCatalog();
  const techs = useGet<PersonBrief[]>(["dental", "technicians"], "/dental/technicians/");
  const [f, setF] = useState({
    case_type: "crown",
    teeth: "",
    shade: "",
    instructions: "",
    technician_id: "",
    due_date: "",
  });
  const create = useMutation({
    mutationFn: () =>
      api.post(`/dental/patients/${patientId}/lab-cases/`, {
        ...f,
        teeth: f.teeth
          .split(/[\s,]+/)
          .filter(Boolean)
          .map(Number),
        technician_id: f.technician_id || null,
        due_date: f.due_date || null,
      }),
    onSuccess: () => {
      toast(t("dental.case_created", "Laboratory case created"));
      onDone();
    },
  });
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
        <Field label={t("dental.work", "Work")} id="f-case_type">
          <select id="f-case_type" value={f.case_type} onChange={(e) => setF({ ...f, case_type: e.target.value })}>
            {(catalog.data?.lab_case_types ?? []).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("dental.teeth", "Teeth (FDI)")} id="f-teeth" error={create.error}>
          <input id="f-teeth" value={f.teeth} onChange={(e) => setF({ ...f, teeth: e.target.value })} />
        </Field>
        <Field label={t("dental.shade", "Shade")} id="f-shade">
          <input id="f-shade" value={f.shade} onChange={(e) => setF({ ...f, shade: e.target.value })} />
        </Field>
        <Field label={t("dental.due", "Due")} id="f-due_date">
          <input
            id="f-due_date"
            type="date"
            value={f.due_date}
            onChange={(e) => setF({ ...f, due_date: e.target.value })}
          />
        </Field>
        <Field label={t("dental.technician", "Technician")} id="f-technician_id">
          <select
            id="f-technician_id"
            value={f.technician_id}
            onChange={(e) => setF({ ...f, technician_id: e.target.value })}
          >
            <option value="">—</option>
            {(techs.data ?? []).map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field
        label={t("dental.instructions", "Instructions for the technician")}
        id="f-instructions"
        error={create.error}
      >
        <textarea
          id="f-instructions"
          value={f.instructions}
          onChange={(e) => setF({ ...f, instructions: e.target.value })}
          required
        />
      </Field>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onDone}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={create.isPending}>
          {t("common.create", "Create")}
        </button>
      </div>
    </form>
  );
}

// ===========================================================================
// Dental catalogue (procedures and prices, findings, diagnoses, appointment types)
// ===========================================================================
type CatTab = "procedures" | "findings" | "diagnoses" | "types";

export function DentalCataloguePage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<CatTab>("procedures");
  return (
    <div className="stack">
      <PageHead
        title={t("nav.dental_catalogue", "Dental catalogue")}
        sub={t("dental.catalogue_sub", "Procedures and prices, chart findings, diagnoses and appointment types.")}
      />
      <Banner tone="warn">{t("dental.pending_review", PENDING_REVIEW_NOTE)}</Banner>
      <Tabs
        tabs={[
          { key: "procedures", label: t("dental.procedures_prices", "Procedures and prices") },
          { key: "findings", label: t("dental.chart_findings", "Chart findings") },
          { key: "diagnoses", label: t("dental.diagnoses", "Diagnoses") },
          { key: "types", label: t("dental.appointment_types", "Appointment types") },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "procedures" && <ProcedureCatalogue />}
      {tab === "findings" && <FindingCatalogue />}
      {tab === "diagnoses" && <DiagnosisCatalogue />}
      {tab === "types" && <AppointmentTypes />}
    </div>
  );
}

function ProcedureCatalogue() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useGet<DentalProcedure[]>(["dental", "procedures-all"], "/dental/procedures/?all=1");
  const catalog = useDentalCatalog();
  const [editing, setEditing] = useState<DentalProcedure | "new" | null>(null);
  const cats = Object.fromEntries(catalog.data?.procedure_categories ?? []);
  return (
    <Panel
      flush
      actions={
        <button className="btn btn-sm btn-primary" onClick={() => setEditing("new")}>
          <Plus size={15} aria-hidden /> {t("dental.new_procedure", "New procedure")}
        </button>
      }
      title={t("dental.procedures_prices", "Procedures and prices")}
    >
      {q.isLoading ? (
        <Loading />
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>{t("dental.code", "Code")}</th>
              <th>{t("dental.name", "Name")}</th>
              <th>{t("dental.category", "Category")}</th>
              <th className="num">{t("dental.price", "Price (ETB)")}</th>
              <th>{t("dental.billing", "Billing")}</th>
              <th>{t("users.status")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(q.data ?? []).map((p) => (
              <tr key={p.id} className={p.is_active ? "" : "muted"}>
                <td className="mono small">{p.code}</td>
                <td>{p.name}</td>
                <td>{cats[p.category] ?? p.category}</td>
                <td className="num">{money(p.price)}</td>
                <td className="small">
                  {p.billing_mode === "per_session"
                    ? t("dental.per_session", "Per session")
                    : t("dental.on_completion", "On completion")}
                </td>
                <td>{p.is_active ? t("common.active") : t("common.inactive")}</td>
                <td className="num">
                  <button className="btn btn-sm" onClick={() => setEditing(p)}>
                    {t("users.edit")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Modal
        open={!!editing}
        title={
          editing === "new" ? t("dental.new_procedure", "New procedure") : t("dental.edit_procedure", "Edit procedure")
        }
        onClose={() => setEditing(null)}
        wide
      >
        {editing && (
          <ProcedureForm
            proc={editing === "new" ? null : editing}
            categories={catalog.data?.procedure_categories ?? []}
            recallKinds={catalog.data?.recall_kinds ?? []}
            onDone={() => {
              setEditing(null);
              void qc.invalidateQueries({ queryKey: ["dental"] });
            }}
          />
        )}
      </Modal>
    </Panel>
  );
}

function ProcedureForm({
  proc,
  categories,
  recallKinds,
  onDone,
}: {
  proc: DentalProcedure | null;
  categories: [string, string][];
  recallKinds: [string, string][];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [f, setF] = useState({
    code: proc?.code ?? "",
    name: proc?.name ?? "",
    category: proc?.category ?? "restorative",
    description: proc?.description ?? "",
    default_minutes: String(proc?.default_minutes ?? 30),
    price: proc?.price ?? "0",
    tax_rate: proc?.tax_rate ?? "0",
    is_active: proc?.is_active ?? true,
    tooth_requirement: proc?.tooth_requirement ?? "optional",
    surfaces_allowed: proc?.surfaces_allowed ?? false,
    consumes_stock: proc?.consumes_stock ?? false,
    typical_sessions: String(proc?.typical_sessions ?? 1),
    billing_mode: proc?.billing_mode ?? "on_completion",
    follow_up_kind: proc?.follow_up_kind ?? "",
    follow_up_days: proc?.follow_up_days == null ? "" : String(proc.follow_up_days),
    performer_roles: (proc?.performer_roles ?? []).join(", "),
  });
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...f,
        default_minutes: Number(f.default_minutes),
        typical_sessions: Number(f.typical_sessions),
        follow_up_days: f.follow_up_days === "" ? null : Number(f.follow_up_days),
        performer_roles: f.performer_roles.split(/[\s,]+/).filter(Boolean),
      };
      return proc
        ? api.patch(`/dental/procedures/${proc.id}/`, body, { ifMatch: proc.row_version })
        : api.post("/dental/procedures/", body);
    },
    onSuccess: () => {
      toast(t("common.saved_toast", "Changes saved"));
      onDone();
    },
  });
  const input = (k: keyof typeof f, label: string, type = "text") => (
    <Field label={label} id={`f-${k}`} error={save.error}>
      <input
        id={`f-${k}`}
        type={type}
        value={String(f[k])}
        onChange={(e) => setF({ ...f, [k]: e.target.value })}
        disabled={k === "code" && !!proc}
      />
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
        {input("code", t("dental.code", "Code"))}
        {input("name", t("dental.name", "Name"))}
        <Field label={t("dental.category", "Category")} id="f-category">
          <select id="f-category" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
            {categories.map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        {input("price", t("dental.price", "Price (ETB)"), "number")}
        {input("default_minutes", t("dental.minutes", "Default minutes"), "number")}
        {input("typical_sessions", t("dental.sessions", "Typical sessions"), "number")}
        <Field label={t("dental.tooth_req", "Tooth")} id="f-tooth_requirement">
          <select
            id="f-tooth_requirement"
            value={f.tooth_requirement}
            onChange={(e) => setF({ ...f, tooth_requirement: e.target.value as typeof f.tooth_requirement })}
          >
            <option value="required">{t("dental.tooth_required", "A tooth must be chosen")}</option>
            <option value="optional">{t("dental.tooth_optional", "Tooth optional")}</option>
            <option value="none">{t("dental.tooth_none", "Not tooth-specific")}</option>
          </select>
        </Field>
        <Field label={t("dental.billing", "Billing")} id="f-billing_mode">
          <select
            id="f-billing_mode"
            value={f.billing_mode}
            onChange={(e) => setF({ ...f, billing_mode: e.target.value as typeof f.billing_mode })}
          >
            <option value="on_completion">{t("dental.on_completion", "Charged once, when completed")}</option>
            <option value="per_session">{t("dental.per_session", "Charged for every session")}</option>
          </select>
        </Field>
        <Field label={t("dental.follow_up_kind", "Follow-up")} id="f-follow_up_kind">
          <select
            id="f-follow_up_kind"
            value={f.follow_up_kind}
            onChange={(e) => setF({ ...f, follow_up_kind: e.target.value })}
          >
            <option value="">—</option>
            {recallKinds.map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        {input("follow_up_days", t("dental.follow_up_days", "Follow-up after (days)"), "number")}
        {input(
          "performer_roles",
          t("dental.performer_roles", "Only these roles may perform it (role codes, optional)"),
        )}
      </div>
      <div className="row">
        <label className="check">
          <input
            type="checkbox"
            checked={f.surfaces_allowed}
            onChange={(e) => setF({ ...f, surfaces_allowed: e.target.checked })}
          />{" "}
          {t("dental.surfaces_allowed", "Surfaces can be chosen")}
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={f.consumes_stock}
            onChange={(e) => setF({ ...f, consumes_stock: e.target.checked })}
          />{" "}
          {t("dental.consumes_stock", "Uses stock materials")}
        </label>
        <label className="check">
          <input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />{" "}
          {t("common.active")}
        </label>
      </div>
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

function FindingCatalogue() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useGet<FindingType[]>(["dental", "finding-types"], "/dental/finding-types/");
  const toggle = useMutation({
    mutationFn: (ft: FindingType) =>
      api.patch(`/dental/finding-types/${ft.id}/`, { is_active: !ft.is_active }, { ifMatch: ft.row_version }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["dental"] }),
  });
  return (
    <Panel flush title={t("dental.chart_findings", "Chart findings")}>
      <ErrorBanner error={toggle.error} />
      {q.isLoading ? (
        <Loading />
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>{t("dental.symbol", "Symbol")}</th>
              <th>{t("dental.name", "Name")}</th>
              <th>{t("dental.kind", "Kind")}</th>
              <th>{t("dental.applies_to", "Applies to")}</th>
              <th>{t("users.status")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(q.data ?? []).map((ft) => (
              <tr key={ft.id} className={ft.is_active ? "" : "muted"}>
                <td>
                  <span className={`sym sym-${ft.kind}`}>{ft.symbol}</span>
                </td>
                <td>{ft.name}</td>
                <td>{ft.kind}</td>
                <td>{ft.applies_to}</td>
                <td>{ft.is_active ? t("common.active") : t("common.inactive")}</td>
                <td className="num">
                  <button className="btn btn-sm" onClick={() => toggle.mutate(ft)}>
                    {ft.is_active ? t("dental.stop_using", "Stop using") : t("dental.use", "Use")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function DiagnosisCatalogue() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const terms = useGet<DiagnosisTerm[]>(
    ["dental", "terms-all", q],
    `/dental/diagnosis-terms/${queryString({ q, all: "1" })}`,
  );
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ code: "", term: "", category: "", source_version: "WHO ICD-10 (2019)" });
  const add = useMutation({
    mutationFn: () => api.post("/dental/diagnosis-terms/", { ...f, code_system: "ICD-10" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dental"] });
      setAdding(false);
    },
  });
  const toggle = useMutation({
    mutationFn: (d: DiagnosisTerm) =>
      api.patch(`/dental/diagnosis-terms/${d.id}/`, { is_active: !d.is_active }, { ifMatch: d.row_version }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["dental"] }),
  });
  return (
    <Panel
      flush
      title={t("dental.diagnoses", "Diagnoses (ICD-10)")}
      actions={
        <>
          <input
            aria-label={t("dental.search", "Search")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="K04…"
          />
          <button className="btn btn-sm btn-primary" onClick={() => setAdding(true)}>
            <Plus size={15} aria-hidden /> {t("dental.add_code", "Add an ICD-10 code")}
          </button>
        </>
      }
    >
      <ErrorBanner error={toggle.error} />
      <table className="data">
        <tbody>
          {(terms.data ?? []).map((d) => (
            <tr key={d.id} className={d.is_active ? "" : "muted"}>
              <td className="mono">{d.code}</td>
              <td>{d.term}</td>
              <td className="small subtle">{d.category}</td>
              <td className="num">
                <button className="btn btn-sm" onClick={() => toggle.mutate(d)}>
                  {d.is_active ? t("dental.stop_using", "Stop using") : t("dental.use", "Use")}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Modal open={adding} title={t("dental.add_code", "Add an ICD-10 code")} onClose={() => setAdding(false)}>
        <form
          className="stack-sm"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <p className="small muted">
            {t("dental.add_code_hint", "Use the exact code and title from the WHO ICD-10 list. Do not invent codes.")}
          </p>
          <ErrorBanner error={add.error} />
          {(["code", "term", "category", "source_version"] as const).map((k) => (
            <Field key={k} label={k} id={`f-${k}`} error={add.error}>
              <input
                id={`f-${k}`}
                value={f[k]}
                onChange={(e) => setF({ ...f, [k]: e.target.value })}
                required={k !== "category"}
              />
            </Field>
          ))}
          <div className="form-actions">
            <button className="btn btn-primary" disabled={add.isPending}>
              {t("common.save", "Save")}
            </button>
          </div>
        </form>
      </Modal>
    </Panel>
  );
}

interface AppointmentTypeRow {
  id: string;
  code: string;
  name: string;
  category: string;
  default_minutes: number;
  default_room: { id: string; name: string } | null;
  is_active: boolean;
  sort_order: number;
  row_version: number;
}

function AppointmentTypes() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useGet<AppointmentTypeRow[]>(["appointment-types", "all"], "/appointment-types/?all=1");
  const rooms = useGet<{ id: string; name: string; is_active: boolean }[]>(["rooms"], "/rooms/");
  const [editing, setEditing] = useState<AppointmentTypeRow | "new" | null>(null);
  const [f, setF] = useState({
    code: "",
    name: "",
    category: "procedure",
    default_minutes: "30",
    default_room_id: "",
    is_active: true,
  });
  const open = (row: AppointmentTypeRow | "new") => {
    setEditing(row);
    setF(
      row === "new"
        ? { code: "", name: "", category: "procedure", default_minutes: "30", default_room_id: "", is_active: true }
        : {
            code: row.code,
            name: row.name,
            category: row.category,
            default_minutes: String(row.default_minutes),
            default_room_id: row.default_room?.id ?? "",
            is_active: row.is_active,
          },
    );
  };
  const save = useMutation({
    mutationFn: () => {
      const body = { ...f, default_minutes: Number(f.default_minutes), default_room_id: f.default_room_id || null };
      return editing && editing !== "new"
        ? api.patch(`/appointment-types/${editing.id}/`, body, { ifMatch: editing.row_version })
        : api.post("/appointment-types/", body);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["appointment-types"] });
      setEditing(null);
    },
  });
  const roomList = Array.isArray(rooms.data) ? rooms.data : [];
  return (
    <Panel
      flush
      title={t("dental.appointment_types", "Appointment types")}
      actions={
        <button className="btn btn-sm btn-primary" onClick={() => open("new")}>
          <Plus size={15} aria-hidden /> {t("dental.new_type", "New type")}
        </button>
      }
    >
      <table className="data">
        <tbody>
          {(q.data ?? []).map((row) => (
            <tr key={row.id} className={row.is_active ? "" : "muted"}>
              <td>{row.name}</td>
              <td>{row.category}</td>
              <td>{row.default_minutes} min</td>
              <td>{row.default_room?.name ?? "—"}</td>
              <td className="num">
                <button className="btn btn-sm" onClick={() => open(row)}>
                  {t("users.edit")}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Modal open={!!editing} title={t("dental.appointment_type", "Appointment type")} onClose={() => setEditing(null)}>
        <form
          className="stack-sm"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <ErrorBanner error={save.error} />
          <div className="form-grid">
            <Field label={t("dental.code", "Code")} id="f-code" error={save.error}>
              <input
                id="f-code"
                value={f.code}
                disabled={editing !== "new"}
                onChange={(e) => setF({ ...f, code: e.target.value })}
                required
              />
            </Field>
            <Field label={t("dental.name", "Name")} id="f-name" error={save.error}>
              <input id="f-name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
            </Field>
            <Field label={t("dental.category", "Category")} id="f-category">
              <select id="f-category" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
                <option value="consultation">{t("dental.consultation", "Consultation or examination")}</option>
                <option value="procedure">{t("dental.procedure_cat", "Planned procedure")}</option>
                <option value="review">{t("dental.review", "Follow-up or review")}</option>
                <option value="imaging">{t("dental.imaging", "Imaging")}</option>
              </select>
            </Field>
            <Field label={t("dental.minutes", "Default minutes")} id="f-default_minutes" error={save.error}>
              <input
                id="f-default_minutes"
                type="number"
                value={f.default_minutes}
                onChange={(e) => setF({ ...f, default_minutes: e.target.value })}
              />
            </Field>
            <Field label={t("dental.chair", "Default chair or room")} id="f-default_room_id">
              <select
                id="f-default_room_id"
                value={f.default_room_id}
                onChange={(e) => setF({ ...f, default_room_id: e.target.value })}
              >
                <option value="">—</option>
                {roomList.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <label className="check">
            <input
              type="checkbox"
              checked={f.is_active}
              onChange={(e) => setF({ ...f, is_active: e.target.checked })}
            />{" "}
            {t("common.active")}
          </label>
          <div className="form-actions">
            <button className="btn btn-primary" disabled={save.isPending}>
              {t("common.save", "Save")}
            </button>
          </div>
        </form>
      </Modal>
    </Panel>
  );
}
