/** History tabs of the patient chart: visits, vital signs, notes, results, medicines, documents, appointments, billing. */
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type {
  Appointment,
  Certificate,
  EncounterSummary,
  InternalReferral,
  Invoice,
  LabOrder,
  Paginated,
  Payment,
  Prescription,
  Referral,
  Visit,
  VisitEvent,
  Vitals,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { FLAG_LABEL, PAYMENT_METHODS, StateBadge, useTriageLabel } from "../labels";
import { formatDateTime } from "../lib/format";
import { Empty, Loading, Modal, Panel, ReasonDialog, money, qty } from "../ui";
import { CriticalNote, timeOf, todayIso } from "./common";
import { CertificateDoc, ReferralLetter } from "./clinical-documents";
import { LabTrends, VitalsTrends } from "./trends";
import { CompleteVisitDialog } from "./complete-visit";

export function VisitHistory({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const q = useGet<Paginated<Visit>>(["visits", "patient", patientId], `/visits/?patient=${patientId}&page_size=50`);
  const [open, setOpen] = useState<string | null>(null);
  const [completing, setCompleting] = useState<Visit | null>(null);
  const [reopening, setReopening] = useState<Visit | null>(null);
  const reopen = useAction(
    (v: { id: string; reason: string }) => api.post(`/visits/${v.id}/reopen/`, { reason: v.reason }),
    [["visits"]],
    () => setReopening(null),
    t("visit.reopened_toast", "Visit reopened"),
  );
  if (q.isLoading) return <Loading />;
  if (!q.data?.results.length) return <Empty>{t("chart.no_visits", "No visits yet.")}</Empty>;
  const today = todayIso();
  return (
    <Panel flush>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>{t("common.date", "Date")}</th>
              <th>{t("queue.ticket", "Ticket")}</th>
              <th>{t("queue.type", "Type")}</th>
              <th>{t("queue.doctor", "Doctor")}</th>
              <th>{t("common.status", "Status")}</th>
              <th>{t("visit.outcome_short", "Outcome")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {q.data.results.map((v) => (
              <Fragment key={v.id}>
                <tr>
                  <td className="nowrap">{v.visit_date}</td>
                  <td>{v.queue_number}</td>
                  <td>
                    {v.kind === "walk_in"
                      ? t("queue.walk_in_short", "Walk-in")
                      : t("queue.appointment_short", "Appointment")}
                  </td>
                  <td>{v.assigned_doctor ? `Dr. ${v.assigned_doctor.full_name}` : "—"}</td>
                  <td>
                    <StateBadge set="visit" value={v.status} />
                    {v.cancel_reason && <div className="small subtle">{v.cancel_reason}</div>}
                  </td>
                  <td>
                    {v.outcome ? <StateBadge set="outcome" value={v.outcome} /> : "—"}
                    {v.completion_note && <div className="small subtle">{v.completion_note}</div>}
                  </td>
                  <td className="num">
                    <div className="row" style={{ justifyContent: "flex-end", gap: 6 }}>
                      {v.status === "after_consult" && can("queue.manage", "clinical.write") && (
                        <button className="btn btn-sm btn-primary" onClick={() => setCompleting(v)}>
                          {t("visit.complete", "Complete visit")}
                        </button>
                      )}
                      {v.status === "completed" && v.visit_date === today && can("queue.manage", "clinical.write") && (
                        <button className="btn btn-sm" onClick={() => setReopening(v)}>
                          {t("visit.reopen", "Reopen")}
                        </button>
                      )}
                      <button
                        className="btn btn-sm btn-ghost"
                        aria-expanded={open === v.id}
                        onClick={() => setOpen(open === v.id ? null : v.id)}
                      >
                        {open === v.id
                          ? t("visit.hide_timeline", "Hide timeline")
                          : t("visit.show_timeline", "Timeline")}
                      </button>
                    </div>
                  </td>
                </tr>
                {open === v.id && (
                  <tr className="timeline-row">
                    <td colSpan={7}>
                      <VisitTimeline visitId={v.id} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <CompleteVisitDialog visit={completing} onClose={() => setCompleting(null)} />
      <ReasonDialog
        open={reopening !== null}
        title={t("visit.reopen_title", "Reopen visit")}
        label={t("visit.reopen_reason", "Why is the visit being reopened?")}
        confirmLabel={t("visit.reopen", "Reopen")}
        busy={reopen.isPending}
        error={reopen.error}
        onClose={() => setReopening(null)}
        onConfirm={(reason) => reopening && reopen.mutate({ id: reopening.id, reason })}
      />
    </Panel>
  );
}

const FIELD_LABELS: Record<string, string> = {
  first_name: "Given name",
  middle_name: "Father's name",
  last_name: "Grandfather's name",
  sex: "Sex",
  birth_date: "Date of birth",
  birth_date_estimated: "Birth date estimated",
  phone: "Phone",
  alt_phone: "Second phone",
  region: "Region",
  city: "City",
  subcity_woreda: "Sub-city / woreda",
  kebele: "Kebele",
  house_number: "House number",
  national_id: "National ID",
  blood_group: "Blood group",
  known_conditions: "Chronic illness",
  past_history: "Past medical & surgical history",
  current_medications: "Current medications",
  emergency_contacts: "Emergency contacts",
};

export function ChangeHistory({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const q = useGet<
    { id: number; field: string; old_value: string; new_value: string; changed_at: string; changed_by: string }[]
  >(["patient", patientId, "history"], open ? `/patients/${patientId}/history/` : null);
  return (
    <div style={{ marginTop: 14 }}>
      <button type="button" className="link-btn small" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? t("patients.hide_history", "Hide change history") : t("patients.show_history", "Show change history")}
      </button>
      {open &&
        (q.isLoading ? (
          <Loading />
        ) : !q.data?.length ? (
          <p className="small subtle">{t("patients.no_changes", "No changes since registration.")}</p>
        ) : (
          <table className="data" style={{ marginTop: 8 }}>
            <thead>
              <tr>
                <th>{t("common.when", "When")}</th>
                <th>{t("patients.field", "Field")}</th>
                <th>{t("patients.before", "Before")}</th>
                <th>{t("patients.after", "After")}</th>
                <th>{t("common.by", "By")}</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((c) => (
                <tr key={c.id}>
                  <td className="nowrap small">{formatDateTime(c.changed_at)}</td>
                  <td>{t(`patients.f.${c.field}`, FIELD_LABELS[c.field] ?? c.field)}</td>
                  <td className="small muted">{c.old_value || "—"}</td>
                  <td className="small">{c.new_value || "—"}</td>
                  <td className="small">{c.changed_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
    </div>
  );
}

export function VisitTimeline({ visitId }: { visitId: string }) {
  const { t } = useTranslation();
  const q = useGet<VisitEvent[]>(["visits", visitId, "timeline"], `/visits/${visitId}/timeline/`);
  if (q.isLoading) return <Loading />;
  if (!q.data?.length)
    return <p className="subtle small">{t("visit.no_events", "No events recorded for this visit.")}</p>;
  return (
    <ol className="timeline compact">
      {q.data.map((e) => (
        <li key={e.id}>
          <span className="mono small subtle">{timeOf(e.at)}</span> {e.summary}
          {e.actor && <span className="small subtle">, {e.actor.full_name}</span>}
        </li>
      ))}
    </ol>
  );
}

export function VitalsHistory({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const triageLabel = useTriageLabel();
  const q = useGet<Paginated<Vitals>>(["vitals", patientId], `/vitals/?patient=${patientId}&page_size=50`);
  if (q.isLoading) return <Loading />;
  if (!q.data?.results.length) return <Empty>{t("chart.no_vitals", "No vital signs recorded.")}</Empty>;
  return (
    <div className="stack">
      <VitalsTrends vitals={q.data.results} />
      <Panel flush>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>{t("common.when", "When")}</th>
                <th className="num">BP</th>
                <th className="num">Temp °C</th>
                <th className="num">Pulse</th>
                <th className="num">RR</th>
                <th className="num">SpO₂</th>
                <th className="num">Weight kg</th>
                <th className="num">BMI</th>
                <th className="num">Pain</th>
                <th>{t("triage.triage_to", "Triage to")}</th>
                <th>{t("common.by", "By")}</th>
              </tr>
            </thead>
            <tbody>
              {q.data.results.map((v) => (
                <tr key={v.id}>
                  <td className="nowrap">{formatDateTime(v.recorded_at)}</td>
                  <td className="num">{v.systolic ? `${v.systolic}/${v.diastolic ?? "–"}` : "—"}</td>
                  <td className="num">{v.temperature_c ?? "—"}</td>
                  <td className="num">{v.heart_rate ?? "—"}</td>
                  <td className="num">{v.respiratory_rate ?? "—"}</td>
                  <td className="num">{v.spo2 ?? "—"}</td>
                  <td className="num">{v.weight_kg ?? "—"}</td>
                  <td className="num">{v.bmi ?? "—"}</td>
                  <td className="num">{v.pain_score ?? "—"}</td>
                  <td>
                    {v.triage_to ? triageLabel(v.triage_to) : "—"}
                    {v.chief_complaint && <div className="small subtle">{v.chief_complaint}</div>}
                  </td>
                  <td>{v.recorded_by.full_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

export function ConsultationHistory({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const q = useGet<Paginated<EncounterSummary>>(
    ["encounters", "patient", patientId],
    `/encounters/?patient=${patientId}&page_size=50`,
  );
  if (q.isLoading) return <Loading />;
  if (!q.data?.results.length) return <Empty>{t("chart.no_consultations", "No consultations yet.")}</Empty>;
  return (
    <Panel>
      <ol className="timeline">
        {q.data.results.map((e) => (
          <li key={e.id}>
            <div className="row-between">
              <Link to={`/consultations/${e.id}`}>
                <strong>{formatDateTime(e.signed_at ?? e.created_at)}</strong>
              </Link>
              {e.status === "draft" ? (
                <StateBadge set="visit" value="in_consultation" />
              ) : (
                <span className="small muted">Dr. {e.doctor.full_name}</span>
              )}
            </div>
            <p>
              {e.chief_complaint || <span className="subtle">{t("chart.no_complaint", "No complaint recorded")}</span>}
            </p>
            {e.diagnoses.length > 0 && <p className="small muted">{e.diagnoses.join("; ")}</p>}
          </li>
        ))}
      </ol>
    </Panel>
  );
}

export function LabHistory({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const q = useGet<Paginated<LabOrder>>(
    ["lab", "patient", patientId],
    `/lab/orders/?patient=${patientId}&page_size=50`,
  );
  if (q.isLoading) return <Loading />;
  if (!q.data?.results.length) return <Empty>{t("chart.no_labs", "No laboratory tests yet.")}</Empty>;
  return (
    <div className="stack">
      <LabTrends orders={q.data.results} />
      <Panel flush>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>{t("common.date", "Date")}</th>
                <th>{t("lab.test", "Test")}</th>
                <th>{t("lab.result", "Result")}</th>
                <th>{t("lab.reference", "Reference")}</th>
                <th>{t("common.status", "Status")}</th>
              </tr>
            </thead>
            <tbody>
              {q.data.results.flatMap((o) =>
                o.items.map((i) => (
                  <tr key={i.id}>
                    <td className="nowrap">
                      {formatDateTime(o.created_at)}
                      <div className="small subtle mono">{o.accession_number}</div>
                    </td>
                    <td>{i.test.name}</td>
                    <td>
                      {i.display_result ? (
                        <span className={`flag-${i.flag}`}>
                          {i.display_result} {i.unit} {i.flag && i.flag !== "N" && `(${FLAG_LABEL[i.flag]})`}
                        </span>
                      ) : (
                        "—"
                      )}
                      {i.amendments.length > 0 && (
                        <div className="small subtle">
                          {t("lab.corrected", "Corrected")}:{" "}
                          {i.amendments
                            .map((a) => `${a.previous_numeric ?? a.previous_text} → (${a.reason})`)
                            .join("; ")}
                        </div>
                      )}
                      {i.repeat_of && (
                        <div className="small subtle">
                          {t("lab.repeat", "Repeat")}: {i.repeat_reason}
                        </div>
                      )}
                      <CriticalNote item={i} />
                    </td>
                    <td className="small muted">
                      {i.ref_low !== null || i.ref_high !== null
                        ? `${i.ref_low !== null ? qty(i.ref_low) : ""}–${i.ref_high !== null ? qty(i.ref_high) : ""} ${i.unit}`
                        : i.ref_text || "—"}
                    </td>
                    <td>
                      <StateBadge set="labItem" value={i.status} />
                      {i.verified_by && <div className="small subtle">{i.verified_by.full_name}</div>}
                    </td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

export function MedicineHistory({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const q = useGet<Paginated<Prescription>>(
    ["prescriptions", "patient", patientId],
    `/prescriptions/?patient=${patientId}&page_size=50`,
  );
  if (q.isLoading) return <Loading />;
  if (!q.data?.results.length) return <Empty>{t("chart.no_rx", "No prescriptions yet.")}</Empty>;
  return (
    <Panel flush>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>{t("common.date", "Date")}</th>
              <th>{t("rx.medicine", "Medicine")}</th>
              <th>{t("rx.directions", "Directions")}</th>
              <th className="num">{t("rx.dispensed", "Dispensed")}</th>
              <th>{t("common.status", "Status")}</th>
            </tr>
          </thead>
          <tbody>
            {q.data.results.flatMap((rx) =>
              rx.items.map((i, n) => (
                <tr key={i.id}>
                  <td className="nowrap">
                    {n === 0 ? formatDateTime(rx.created_at) : ""}
                    {n === 0 && <div className="small subtle">Dr. {rx.prescriber.full_name}</div>}
                  </td>
                  <td>
                    <strong>{i.drug_name}</strong>
                  </td>
                  <td>
                    {i.dose}, {i.frequency}
                    {i.duration_days ? `, ${i.duration_days} days` : ""}
                    {i.instructions && <div className="small muted">{i.instructions}</div>}
                  </td>
                  <td className="num">
                    {Number(i.quantity_dispensed)} / {Number(i.quantity)}
                  </td>
                  <td>{n === 0 && <StateBadge set="rx" value={rx.status} />}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

type PatientDiagnosis = {
  id: string;
  date: string;
  code: string;
  description: string;
  kind: string;
  certainty: string;
  doctor: string;
  encounter: string;
  signed: boolean;
};

export function DiagnosisHistory({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const q = useGet<PatientDiagnosis[]>(["diagnoses", "patient", patientId], `/patients/${patientId}/diagnoses/`);
  if (q.isLoading) return <Loading />;
  if (!q.data?.length) return <Empty>{t("chart.no_dx", "No diagnoses recorded yet.")}</Empty>;
  return (
    <Panel flush>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>{t("common.date", "Date")}</th>
              <th>ICD-10</th>
              <th>{t("consult.dx", "Diagnosis")}</th>
              <th>{t("chart.dx_type", "Type")}</th>
              <th>{t("chart.doctor", "Doctor")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {q.data.map((d) => (
              <tr key={d.id}>
                <td className="nowrap">{formatDateTime(d.date)}</td>
                <td className="mono">{d.code || "—"}</td>
                <td>
                  <strong>{d.description}</strong>
                </td>
                <td>
                  {d.kind}
                  {d.certainty === "provisional" && (
                    <div className="small flag-H">{t("chart.provisional", "Provisional")}</div>
                  )}
                </td>
                <td>Dr. {d.doctor}</td>
                <td className="num">
                  <Link className="btn btn-sm btn-ghost" to={`/consultations/${d.encounter}`}>
                    {t("chart.open_note", "Open note")}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export function DocumentHistory({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const q = useGet<{ referrals: Referral[]; certificates: Certificate[]; internal_referrals?: InternalReferral[] }>(
    ["documents", "patient", patientId],
    `/patients/${patientId}/documents/`,
  );
  const [view, setView] = useState<
    { kind: "referral"; doc: Referral } | { kind: "certificate"; doc: Certificate } | null
  >(null);
  if (q.isLoading) return <Loading />;
  const rows = [
    ...(q.data?.referrals ?? []).map((r) => ({
      id: r.id,
      date: r.created_at,
      number: r.number,
      cancelled: r.status === "cancelled",
      title: t("consult.referral", "Referral"),
      detail: `${r.to_facility}${r.to_department ? `, ${r.to_department}` : ""}`,
      open: () => setView({ kind: "referral", doc: r }),
    })),
    ...(q.data?.certificates ?? []).map((c) => ({
      id: c.id,
      date: c.created_at,
      number: c.number,
      cancelled: c.is_cancelled,
      title: t("consult.certificate", "Medical certificate"),
      detail: c.days ? `${c.start_date} → ${c.end_date} (${c.days} ${t("common.days", "days")})` : c.kind,
      open: () => setView({ kind: "certificate", doc: c }),
    })),
    ...(q.data?.internal_referrals ?? []).map((r) => ({
      id: r.id,
      date: r.created_at,
      number: "",
      cancelled: r.status === "cancelled",
      title: t("consult.internal_referral", "Referred within the clinic"),
      detail: `${r.from_department_name || "—"} → ${r.to_department_name} (Dr. ${r.referred_by}): ${r.reason}${r.seen_by ? `. ${t("consult.internal_seen_short", "Seen by Dr. {{who}}", { who: r.seen_by })}` : ""}`,
      open: null as null | (() => void),
    })),
  ].sort((a, b) => b.date.localeCompare(a.date));
  if (!rows.length) return <Empty>{t("chart.no_docs", "No referrals or certificates yet.")}</Empty>;
  return (
    <Panel flush>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>{t("common.date", "Date")}</th>
              <th>{t("chart.document", "Document")}</th>
              <th>{t("chart.details", "Details")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={r.cancelled ? "muted" : ""}>
                <td className="nowrap">{formatDateTime(r.date)}</td>
                <td>
                  <strong>{r.title}</strong> <span className="mono small">{r.number}</span>
                  {r.cancelled && <div className="small">{t("common.cancelled", "Cancelled")}</div>}
                </td>
                <td>{r.detail}</td>
                <td className="num">
                  {r.open && (
                    <button className="btn btn-sm" onClick={r.open}>
                      {t("common.view_print", "View / print")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Modal
        open={view !== null}
        wide
        title={
          view?.kind === "referral"
            ? t("consult.referral_letter", "Referral letter")
            : t("consult.certificate", "Medical certificate")
        }
        onClose={() => setView(null)}
      >
        {view?.kind === "referral" && <ReferralLetter referral={view.doc} />}
        {view?.kind === "certificate" && <CertificateDoc cert={view.doc} />}
      </Modal>
    </Panel>
  );
}

export function AppointmentHistory({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const q = useGet<Paginated<Appointment>>(
    ["appointments", "patient", patientId],
    `/appointments/?patient=${patientId}&page_size=50`,
  );
  if (q.isLoading) return <Loading />;
  if (!q.data?.results.length) return <Empty>{t("chart.no_appointments", "No appointments yet.")}</Empty>;
  const today = todayIso();
  return (
    <Panel flush>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>{t("common.date", "Date")}</th>
              <th>{t("chart.doctor", "Doctor")}</th>
              <th>{t("appt.reason", "Reason")}</th>
              <th>{t("common.status", "Status")}</th>
            </tr>
          </thead>
          <tbody>
            {[...q.data.results]
              .sort((a, b) => b.scheduled_at.localeCompare(a.scheduled_at))
              .map((a) => (
                <tr key={a.id}>
                  <td className="nowrap">
                    <strong>{formatDateTime(a.scheduled_at)}</strong>
                    {a.scheduled_date >= today && !["cancelled", "no_show", "completed"].includes(a.status) && (
                      <div className="small">
                        <span className="badge badge-info">{t("chart.upcoming", "Upcoming")}</span>
                      </div>
                    )}
                  </td>
                  <td>Dr. {a.doctor.full_name}</td>
                  <td>
                    {a.reason || "—"}
                    {a.source_encounter && (
                      <div className="small subtle">
                        {t("chart.follow_up_from", "Follow-up booked from a consultation")}
                      </div>
                    )}
                  </td>
                  <td>
                    <StateBadge set="appointment" value={a.status} />
                    {a.cancel_reason && <div className="small subtle">{a.cancel_reason}</div>}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export function BillingHistory({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const q = useGet<Paginated<Invoice>>(
    ["invoices", "patient", patientId],
    `/billing/invoices/?patient=${patientId}&page_size=50`,
  );
  const pays = useGet<Paginated<Payment>>(
    ["payments", "patient", patientId],
    `/billing/payments/?patient=${patientId}&page_size=50`,
  );
  if (q.isLoading) return <Loading />;
  if (!q.data?.results.length) return <Empty>{t("chart.no_invoices", "No invoices yet.")}</Empty>;
  return (
    <div className="stack">
      {!!pays.data?.results.length && (
        <Panel flush title={t("chart.payments", "Payments")}>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("billing.receipt", "Receipt")}</th>
                  <th>{t("common.date", "Date")}</th>
                  <th>{t("billing.method", "Method")}</th>
                  <th className="num">{t("billing.amount", "Amount")}</th>
                  <th className="num">{t("billing.refunded", "Refunded")}</th>
                </tr>
              </thead>
              <tbody>
                {pays.data.results.map((p) => (
                  <tr key={p.id}>
                    <td className="mono">
                      {p.receipt_number}
                      <div className="small subtle">{p.invoice_number}</div>
                    </td>
                    <td>{formatDateTime(p.received_at)}</td>
                    <td>
                      {PAYMENT_METHODS.find((m) => m.key === p.method)?.label}
                      {p.reference && <div className="small subtle mono">{p.reference}</div>}
                    </td>
                    <td className="num">{money(p.amount)}</td>
                    <td className="num">{Number(p.refunded) > 0 ? `−${money(p.refunded ?? "0")}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
      <Panel flush title={t("chart.invoices", "Invoices")}>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>{t("billing.invoice", "Invoice")}</th>
                <th>{t("common.date", "Date")}</th>
                <th className="num">{t("billing.total", "Total")}</th>
                <th className="num">{t("billing.balance", "Balance")}</th>
                <th>{t("common.status", "Status")}</th>
              </tr>
            </thead>
            <tbody>
              {q.data.results.map((i) => (
                <tr key={i.id}>
                  <td>
                    <Link to={`/billing/invoices/${i.id}`} className="mono">
                      {i.number}
                    </Link>
                  </td>
                  <td>{formatDateTime(i.created_at)}</td>
                  <td className="num">{money(i.total)}</td>
                  <td className="num">{money(i.balance)}</td>
                  <td>
                    <StateBadge set="invoice" value={i.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
