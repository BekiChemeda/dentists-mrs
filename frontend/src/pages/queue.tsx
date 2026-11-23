import { useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CheckCheck, HeartPulse, Megaphone, Stethoscope, UserPlus } from "lucide-react";
import { api } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { Encounter, PatientBrief, Visit } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { StateBadge, useTriageDestinations, useTriageLabel } from "../labels";
import {
  Badge,
  Banner,
  Empty,
  ErrorBanner,
  Field,
  Loading,
  Menu,
  Modal,
  PageHead,
  Panel,
  ReasonDialog,
  Segmented,
  Tabs,
  toast,
} from "../ui";
import { DoctorSelect, PatientPicker, timeOf, waitLabel } from "./common";
import { WalkInForm } from "./patients";
import { MyRoomPicker } from "./setup";
import { VitalsForm } from "./vitals";
import { CompleteVisitDialog } from "./complete-visit";
type QueueAction = { kind: "skip" | "remove" | "reassign" | "complete"; visit: Visit } | null;

type QueueTab = "triage" | "doctor" | "managed" | "done";

const sexShort = (sex: string) => (sex === "female" ? "F" : sex === "male" ? "M" : "");

/** Diagnosis once the doctor has recorded one; until then the triage complaint, shown as such. */
function DiagnosisCell({ v }: { v: Visit }) {
  const { t } = useTranslation();
  if (v.kind === "lab_only") return <span className="badge badge-info">{t("queue.kind_lab", "Laboratory only")}</span>;
  if (v.diagnoses.length) {
    return (
      <>
        {v.diagnoses.map((d, i) => (
          <div key={i}>
            {d.code && <span className="mono">{d.code} </span>}
            {d.description}
          </div>
        ))}
      </>
    );
  }
  if (v.triage?.chief_complaint) {
    return (
      <span className="muted">
        {t("queue.complaint", "Complaint")}: {v.triage.chief_complaint}
        {v.triage.complaint_duration && `, ${v.triage.complaint_duration}`}
      </span>
    );
  }
  return <span className="subtle">—</span>;
}

export function QueuePage() {
  const { t } = useTranslation();
  const triageLabel = useTriageLabel();
  const { can, user, moduleOn } = useAuth();
  const [params, setParams] = useSearchParams();
  // Dentists see patients like doctors do; their examination is the dental workspace.
  const dentist = can("dental.write") && !can("clinical.write");
  const clinician = can("clinical.write", "dental.write");
  const [scope, setScope] = useState<"all" | "mine">(clinician && !can("queue.manage") ? "mine" : "all");
  // Today's visits, open and completed, so the last tab can show who has finished.
  const q = useGet<Visit[]>(
    ["visits", "today", scope],
    `/visits/${scope === "mine" && user ? `?doctor=${user.id}` : ""}`,
    { refetchInterval: 20_000 },
  );
  const stale = useGet<Visit[]>(
    ["visits", "stale"],
    can("queue.manage", "clinical.write", "dental.write") ? "/visits/?stale=1" : null,
  );
  const [walkIn, setWalkIn] = useState(false);
  const [walkPatient, setWalkPatient] = useState<PatientBrief | null>(null);
  const [vitalsFor, setVitalsFor] = useState<Visit | null>(null);
  const [action, setAction] = useState<QueueAction>(null);
  const navigate = useNavigate();

  const triageOn = moduleOn("triage");
  const defaultTab: QueueTab = !triageOn || (clinician && !can("triage.record")) ? "doctor" : "triage";
  const asked = params.get("tab") as QueueTab | null;
  const tab = asked && !(asked === "triage" && !triageOn) ? asked : defaultTab;

  const update = useAction(
    (v: { id: string; body: Record<string, unknown> }) => api.patch(`/visits/${v.id}/`, v.body),
    [["visits"]],
    () => setAction(null),
  );
  const act = useAction(
    (v: { id: string; action: string; body?: Record<string, unknown> }) =>
      api.post<Visit>(`/visits/${v.id}/${v.action}/`, v.body ?? {}),
    [["visits"]],
    () => setAction(null),
    false,
  );
  const callNext = useAction(
    (stage: "triage" | "doctor") =>
      api.post<{ visit: Visit | null; message?: string }>("/visits/call-next/", { stage }),
    [["visits"]],
    (r) =>
      toast(
        r.visit
          ? t("queue.called_toast", "Called {{n}}: {{name}}", {
              n: r.visit.queue_number,
              name: r.visit.patient.full_name,
            })
          : t("queue.nobody", "Nobody is waiting."),
      ),
    false,
  );
  const start = useAction(
    (visitId: string) =>
      api.post<Encounter>(dentist ? `/dental/visits/${visitId}/encounters/` : `/visits/${visitId}/encounters/`),
    [["visits"]],
    (enc) => navigate(dentist ? `/dental/encounters/${enc.id}?tab=history` : `/consultations/${enc.id}`),
    false,
  );

  // "My department": doctors in OPD 1 see the patients triaged to OPD 1 first. Triage itself is unfiltered.
  const destinations = useTriageDestinations();
  const [deptChoice, setDeptChoice] = useState<string | null>(null);
  const myDept =
    user?.department && destinations.some((d) => d.code === user.department?.code) ? user.department.code : "";
  const deptFilter = deptChoice ?? myDept;
  // A patient not yet sent to any department (no triage, as in most dental clinics) is everyone's, and a
  // patient booked with this clinician always shows on their list.
  const visits = (q.data ?? []).filter((v) => {
    const sentTo = v.department || v.triage?.triage_to;
    return (
      !deptFilter ||
      v.status === "waiting_triage" ||
      !sentTo ||
      sentTo === deptFilter ||
      v.assigned_doctor?.id === user?.id
    );
  });
  const byTab: Record<QueueTab, Visit[]> = {
    triage: visits.filter((v) => v.status === "waiting_triage"),
    doctor: visits.filter((v) => v.status === "waiting_doctor"),
    managed: visits.filter((v) => v.status === "in_consultation"),
    done: [...visits.filter((v) => v.status === "after_consult"), ...visits.filter((v) => v.status === "completed")],
  };
  const tabs: { key: QueueTab; label: string; count: number }[] = [
    ...(triageOn
      ? [{ key: "triage" as const, label: t("queue.lane_triage", "Waiting for triage"), count: byTab.triage.length }]
      : []),
    { key: "doctor", label: t("queue.lane_doctor", "Waiting for doctors"), count: byTab.doctor.length },
    { key: "managed", label: t("queue.lane_consult", "Being managed"), count: byTab.managed.length },
    { key: "done", label: t("queue.lane_after", "Completed visits"), count: byTab.done.length },
  ];
  const rows = byTab[tab];
  const callStage =
    tab === "triage" && can("triage.record") ? "triage" : tab === "doctor" && clinician ? "doctor" : null;
  const canHandle = can("queue.manage", "triage.record", "clinical.write", "dental.write");
  // The clinician's own consultation or dental examination on this visit: the newest one they wrote.
  const myEncounter = (v: Visit) =>
    dentist
      ? [...(v.dental_encounters ?? [])].reverse().find((e) => e.dentist_id === user?.id)
      : [...v.encounters].reverse().find((e) => e.doctor_id === user?.id);
  const workspace = (id: string) => (dentist ? `/dental/encounters/${id}` : `/consultations/${id}`);

  const moreMenu = (v: Visit) => {
    const waiting = v.status === "waiting_triage" || v.status === "waiting_doctor";
    const items = [
      {
        label: t("queue.call", "Call"),
        onSelect: () => act.mutate({ id: v.id, action: "call" }),
        hidden: !waiting || !!v.called_at,
      },
      {
        label: t("queue.skip", "Skip…"),
        onSelect: () => setAction({ kind: "skip", visit: v }),
        hidden: !waiting || !!v.skipped_at,
      },
      {
        label: t("queue.return", "Return to queue"),
        onSelect: () => act.mutate({ id: v.id, action: "return" }),
        hidden: !waiting || !v.skipped_at,
      },
      {
        label: t("queue.reassign", "Assign doctor…"),
        onSelect: () => setAction({ kind: "reassign", visit: v }),
        hidden: !waiting || !can("queue.manage"),
      },
      {
        label: t("queue.send_doctor", "Send to doctor without triage"),
        hidden: v.status !== "waiting_triage" || !can("queue.manage"),
        onSelect: () => update.mutate({ id: v.id, body: { status: "waiting_doctor" } }),
      },
      ...(["routine", "urgent", "emergency"] as const)
        .filter((p) => waiting && p !== v.priority && can("queue.manage", "triage.record"))
        .map((p) => ({
          label: t("queue.set_priority", "Set priority: {{p}}", { p }),
          onSelect: () => update.mutate({ id: v.id, body: { priority: p } }),
        })),
      {
        label: t("consult.review", "Review consultation"),
        hidden: v.status !== "after_consult" || !clinician,
        onSelect: () => start.mutate(v.id),
      },
      { label: t("queue.open_chart", "Open patient chart"), onSelect: () => navigate(`/patients/${v.patient.id}`) },
      {
        label: t("queue.remove", "Remove from queue…"),
        danger: true,
        hidden: !waiting || !can("queue.manage"),
        onSelect: () => setAction({ kind: "remove", visit: v }),
      },
    ];
    return canHandle ? (
      <Menu label={t("queue.more", "More actions for {{name}}", { name: v.patient.full_name })} items={items} />
    ) : null;
  };

  const primary = (v: Visit) => {
    const mineOrFree = !v.assigned_doctor || v.assigned_doctor.id === user?.id;
    const mine = myEncounter(v);
    if (v.status === "waiting_triage" && can("triage.record")) {
      return (
        <button className="btn btn-sm btn-primary" onClick={() => setVitalsFor(v)}>
          <HeartPulse size={15} aria-hidden /> {t("queue.triage", "Triage")}
        </button>
      );
    }
    if ((v.status === "waiting_doctor" || v.status === "waiting_triage") && clinician && mineOrFree) {
      return (
        <button className="btn btn-sm btn-primary" disabled={start.isPending} onClick={() => start.mutate(v.id)}>
          <Stethoscope size={15} aria-hidden /> {t("queue.manage", "Manage")}
        </button>
      );
    }
    if (v.status === "in_consultation" && clinician && v.assigned_doctor?.id === user?.id) {
      return (
        <button className="btn btn-sm btn-primary" onClick={() => start.mutate(v.id)}>
          <Stethoscope size={15} aria-hidden /> {t("queue.manage", "Manage")}
        </button>
      );
    }
    if (v.status === "after_consult" && can("queue.manage")) {
      return (
        <button className="btn btn-sm btn-primary" onClick={() => setAction({ kind: "complete", visit: v })}>
          <CheckCheck size={15} aria-hidden /> {t("visit.complete", "Complete visit")}
        </button>
      );
    }
    if (v.status === "after_consult" && mine) {
      return (
        <Link className="btn btn-sm btn-primary" to={workspace(mine.id)}>
          <Stethoscope size={15} aria-hidden /> {t("queue.manage", "Manage")}
        </Link>
      );
    }
    if (v.status === "completed") {
      return (
        <Link className="btn btn-sm" to={`/patients/${v.patient.id}?tab=visits`}>
          {t("common.view", "View")}
        </Link>
      );
    }
    return null;
  };

  const nameCell = (v: Visit) => (
    <td>
      <Link to={`/patients/${v.patient.id}`}>
        <strong>{v.patient.full_name}</strong>
      </Link>
      <div className="row small" style={{ gap: 6, marginTop: 2 }}>
        <span className="subtle">{t("queue.ticket_n", "Ticket {{n}}", { n: v.queue_number })}</span>
        {v.priority !== "routine" && <StateBadge set="priority" value={v.priority} />}
        {v.called_at && (
          <span className="badge badge-info">
            {v.called_room
              ? t("queue.called_to", "Called to {{room}} {{time}}", { room: v.called_room, time: timeOf(v.called_at) })
              : t("queue.called", "Called {{time}}", { time: timeOf(v.called_at) })}
          </span>
        )}
        {v.skipped_at && (
          <span className="badge badge-muted" title={v.skip_reason}>
            {t("queue.skipped", "Skipped")}
          </span>
        )}
      </div>
    </td>
  );
  const common = (v: Visit, i: number) => (
    <>
      <td className="num-left">{i + 1}</td>
      {nameCell(v)}
      <td className="mono">{v.patient.mrn}</td>
      <td>{v.patient.age}</td>
      <td>{sexShort(v.patient.sex)}</td>
    </>
  );
  const head = (extra: string[]) => (
    <thead>
      <tr>
        <th>{t("queue.sn", "S/N")}</th>
        <th>{t("queue.name", "Name")}</th>
        <th>{t("queue.mrn", "MRN")}</th>
        <th>{t("queue.age", "Age")}</th>
        <th>{t("queue.sex", "Sex")}</th>
        {extra.map((h) => (
          <th key={h}>{h}</th>
        ))}
        <th className="num">{t("queue.action", "Action")}</th>
      </tr>
    </thead>
  );
  const actions = (v: Visit) => (
    <td className="num">
      <div className="row" style={{ gap: 6, justifyContent: "flex-end", flexWrap: "nowrap" }}>
        {primary(v)}
        {moreMenu(v)}
      </div>
    </td>
  );

  return (
    <div className="stack">
      <PageHead
        title={t("nav.queue")}
        sub={t("queue.sub", "Patients in the clinic today. Emergencies and urgent cases are listed first.")}
        actions={
          <>
            {can("clinical.write") && <MyRoomPicker />}
            {can("clinical.write") && can("queue.manage") && (
              <Segmented
                label={t("queue.scope", "Show")}
                value={scope}
                onChange={setScope}
                options={[
                  { key: "all", label: t("queue.all", "Everyone") },
                  { key: "mine", label: t("queue.mine", "My patients") },
                ]}
              />
            )}
            {can("queue.manage") && (
              <button className="btn btn-primary" onClick={() => setWalkIn(true)}>
                <UserPlus size={18} aria-hidden /> {t("queue.walk_in", "Add walk-in")}
              </button>
            )}
          </>
        }
      />
      <ErrorBanner error={q.error ?? update.error ?? start.error ?? callNext.error ?? (action ? null : act.error)} />
      {!!stale.data?.length && (
        <Banner tone="warn">
          {t(
            "queue.stale",
            "{{n}} visit(s) from earlier days are still open. Complete or close them so reports stay correct.",
            { n: stale.data.length },
          )}{" "}
          {stale.data.slice(0, 5).map((v) => (
            <button
              key={v.id}
              type="button"
              className="link-btn"
              style={{ marginRight: 10 }}
              onClick={() => setAction({ kind: v.status === "after_consult" ? "complete" : "remove", visit: v })}
            >
              {v.patient.full_name} ({v.visit_date})
            </button>
          ))}
        </Banner>
      )}
      <div className="row-between">
        <Tabs tabs={tabs} value={tab} onChange={(k) => setParams({ tab: k })} />
        {destinations.length > 0 && (
          <label className="row small" style={{ gap: 6 }}>
            {t("queue.sent_to", "Sent to")}
            <select
              value={deptFilter}
              onChange={(e) => setDeptChoice(e.target.value)}
              aria-label={t("queue.sent_to", "Sent to")}
            >
              <option value="">{t("queue.all_departments", "All departments")}</option>
              {destinations.map((d) => (
                <option key={d.code} value={d.code}>
                  {d.name}
                  {d.code === myDept ? ` (${t("queue.my_department", "my department")})` : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        {callStage && rows.length > 0 && (
          <button
            type="button"
            className="btn btn-sm"
            disabled={callNext.isPending}
            onClick={() => callNext.mutate(callStage)}
          >
            <Megaphone size={14} aria-hidden /> {t("queue.call_next", "Call next")}
          </button>
        )}
      </div>
      <Panel flush>
        {q.isLoading ? (
          <Loading />
        ) : rows.length === 0 ? (
          <Empty>{t("queue.lane_empty", "Nobody here.")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data waiting-list">
              {tab === "triage" && (
                <>
                  {head([t("queue.address", "Address"), t("queue.waiting", "Waiting")])}
                  <tbody>
                    {rows.map((v, i) => (
                      <tr key={v.id} className={`prio-${v.priority}`}>
                        {common(v, i)}
                        <td>{v.patient.address || <span className="subtle">—</span>}</td>
                        <td>{waitLabel(v.waiting_minutes)}</td>
                        {actions(v)}
                      </tr>
                    ))}
                  </tbody>
                </>
              )}
              {tab === "doctor" && (
                <>
                  {head([
                    t("queue.triage_time", "Triage time"),
                    t("queue.sent_to", "Sent to"),
                    t("queue.diagnosis", "Diagnosis"),
                  ])}
                  <tbody>
                    {rows.map((v, i) => (
                      <tr key={v.id} className={`prio-${v.priority}`}>
                        {common(v, i)}
                        <td>
                          {v.triage ? (
                            timeOf(v.triage.recorded_at)
                          ) : (
                            <span className="subtle">{t("queue.not_triaged", "Not triaged")}</span>
                          )}
                        </td>
                        <td>
                          {v.department || v.triage?.triage_to
                            ? triageLabel(v.department || v.triage?.triage_to || "")
                            : "—"}
                          {v.internal_referral && (
                            <div className="small referral-note" title={v.internal_referral.reason}>
                              {t("queue.referred_from", "Referred from {{from}} by Dr. {{who}}", {
                                from: triageLabel(v.internal_referral.from_department),
                                who: v.internal_referral.referred_by,
                              })}
                            </div>
                          )}
                        </td>
                        <td className="dx-cell">
                          <DiagnosisCell v={v} />
                        </td>
                        {actions(v)}
                      </tr>
                    ))}
                  </tbody>
                </>
              )}
              {tab === "managed" && (
                <>
                  {head([t("queue.doctor", "Doctor"), t("queue.since", "Since"), t("queue.diagnosis", "Diagnosis")])}
                  <tbody>
                    {rows.map((v, i) => (
                      <tr key={v.id} className={`prio-${v.priority}`}>
                        {common(v, i)}
                        <td>{v.assigned_doctor ? `Dr. ${v.assigned_doctor.full_name}` : "—"}</td>
                        <td>{v.consultation_started_at ? timeOf(v.consultation_started_at) : "—"}</td>
                        <td className="dx-cell">
                          <DiagnosisCell v={v} />
                        </td>
                        {actions(v)}
                      </tr>
                    ))}
                  </tbody>
                </>
              )}
              {tab === "done" && (
                <>
                  {head([t("queue.doctor", "Doctor"), t("queue.diagnosis", "Diagnosis"), t("queue.status", "Status")])}
                  <tbody>
                    {rows.map((v, i) => (
                      <tr key={v.id}>
                        {common(v, i)}
                        <td>{v.assigned_doctor ? `Dr. ${v.assigned_doctor.full_name}` : "—"}</td>
                        <td className="dx-cell">
                          <DiagnosisCell v={v} />
                        </td>
                        <td>
                          {v.status === "completed" ? (
                            <StateBadge set="outcome" value={v.outcome || "completed"} />
                          ) : (
                            <Badge tone="wait">{t("queue.finishing", "Lab, pharmacy or payment")}</Badge>
                          )}
                        </td>
                        {actions(v)}
                      </tr>
                    ))}
                  </tbody>
                </>
              )}
            </table>
          </div>
        )}
      </Panel>

      <Modal
        open={walkIn}
        title={t("queue.walk_in", "Add walk-in")}
        onClose={() => {
          setWalkIn(false);
          setWalkPatient(null);
        }}
      >
        {walkPatient ? (
          <WalkInForm
            patient={walkPatient}
            onDone={() => {
              setWalkIn(false);
              setWalkPatient(null);
            }}
          />
        ) : (
          <PatientPicker value={null} onChange={setWalkPatient} autoFocus />
        )}
      </Modal>
      <Modal
        open={vitalsFor !== null}
        title={t("triage.record", "Record vital signs")}
        onClose={() => setVitalsFor(null)}
        wide
      >
        {vitalsFor && <VitalsForm visit={vitalsFor} onDone={() => setVitalsFor(null)} />}
      </Modal>
      <ReasonDialog
        open={action?.kind === "remove"}
        title={t("queue.remove_title", "Remove from queue")}
        label={t("queue.remove_reason", "Why is this patient leaving the queue?")}
        confirmLabel={t("queue.remove_confirm", "Remove")}
        busy={update.isPending}
        error={update.error}
        danger
        onClose={() => setAction(null)}
        onConfirm={(reason) => action && update.mutate({ id: action.visit.id, body: { status: "cancelled", reason } })}
      />
      <ReasonDialog
        open={action?.kind === "skip"}
        title={t("queue.skip_title", "Skip this patient")}
        label={t("queue.skip_reason", "Why is this patient being skipped? They stay in the queue, at the end.")}
        confirmLabel={t("queue.skip_confirm", "Skip")}
        busy={act.isPending}
        error={act.error}
        onClose={() => setAction(null)}
        onConfirm={(reason) => action && act.mutate({ id: action.visit.id, action: "skip", body: { reason } })}
      />
      <Modal
        open={action?.kind === "reassign"}
        title={t("queue.reassign_title", "Assign a doctor")}
        onClose={() => setAction(null)}
      >
        {action?.kind === "reassign" && (
          <ReassignForm
            visit={action.visit}
            busy={update.isPending}
            error={update.error}
            onSave={(doctorId) => update.mutate({ id: action.visit.id, body: { doctor_id: doctorId || null } })}
            onCancel={() => setAction(null)}
          />
        )}
      </Modal>
      <CompleteVisitDialog visit={action?.kind === "complete" ? action.visit : null} onClose={() => setAction(null)} />
    </div>
  );
}

function ReassignForm({
  visit,
  onSave,
  onCancel,
  busy,
  error,
}: {
  visit: Visit;
  onSave: (doctorId: string) => void;
  onCancel: () => void;
  busy: boolean;
  error: unknown;
}) {
  const { t } = useTranslation();
  const [doctor, setDoctor] = useState(visit.assigned_doctor?.id ?? "");
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        onSave(doctor);
      }}
    >
      <p>
        <strong>{visit.patient.full_name}</strong>, {t("queue.ticket_n", "Ticket {{n}}", { n: visit.queue_number })}
      </p>
      <ErrorBanner error={error} />
      <Field label={t("queue.doctor", "Doctor")} id="ra-doc">
        <DoctorSelect
          id="ra-doc"
          value={doctor}
          onChange={setDoctor}
          allowNone
          noneLabel={t("queue.any_doctor", "Any doctor")}
        />
      </Field>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onCancel}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={busy}>
          {t("queue.assign", "Assign")}
        </button>
      </div>
    </form>
  );
}

/** The triage list is the first tab of the waiting list. */
export function TriagePage() {
  return <Navigate to="/queue?tab=triage" replace />;
}
