/** Referrals, certificates and prescriptions: the forms that issue them and the printed documents. */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FileText, Printer, Send } from "lucide-react";
import { api } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import {
  type Encounter,
  type Certificate,
  type Clinician,
  type InternalReferral,
  type Prescription,
  type Referral,
} from "../api/types";
import { useTriageDestinations } from "../labels";
import { formatDateTime } from "../lib/format";
import { Banner, ErrorBanner, Field, Modal, Panel, ReasonDialog, printElement } from "../ui";
import { ClinicHeader, DocFooter, DoctorSelect, Ec, EcRange, sexAge } from "./common";

const URGENCY = [
  { key: "routine", label: "Routine" },
  { key: "urgent", label: "Urgent" },
  { key: "emergency", label: "Emergency" },
];
const CERT_KINDS = [
  { key: "sick_leave", label: "Sick leave" },
  { key: "fitness", label: "Fitness to work or study" },
  { key: "attendance", label: "Attendance" },
];

export function DocumentsPanel({
  encounter: e,
  mine,
  visitOpen,
  visitDepartment,
}: {
  encounter: Encounter;
  mine: boolean;
  visitOpen: boolean;
  visitDepartment: string;
}) {
  const { t } = useTranslation();
  const refs = useGet<Referral[]>(["encounter", e.id, "referrals"], `/encounters/${e.id}/referrals/`);
  const internal = useGet<InternalReferral[]>(
    ["encounter", e.id, "internal"],
    `/encounters/${e.id}/internal-referrals/`,
  );
  const certs = useGet<Certificate[]>(["encounter", e.id, "certificates"], `/encounters/${e.id}/certificates/`);
  const [form, setForm] = useState<"referral" | "internal" | "certificate" | null>(null);
  const [view, setView] = useState<
    { kind: "referral"; doc: Referral } | { kind: "certificate"; doc: Certificate } | null
  >(null);
  const [cancelling, setCancelling] = useState<{
    kind: "referrals" | "certificates" | "internal-referrals";
    id: string;
  } | null>(null);
  const cancel = useAction(
    (v: { kind: string; id: string; reason: string }) => api.post(`/${v.kind}/${v.id}/cancel/`, { reason: v.reason }),
    [["encounter", e.id]],
    () => setCancelling(null),
    t("consult.doc_cancelled", "Document cancelled"),
  );
  const none = !refs.data?.length && !certs.data?.length && !internal.data?.length;
  return (
    <Panel
      title={t("consult.documents", "Referral and certificates")}
      actions={
        mine && (
          <>
            {visitOpen && (
              <button className="btn btn-sm" onClick={() => setForm("internal")}>
                <Send size={15} aria-hidden /> {t("consult.refer_internal", "Refer within the clinic")}
              </button>
            )}
            <button className="btn btn-sm" onClick={() => setForm("referral")}>
              <Send size={15} aria-hidden /> {t("consult.refer", "Refer to another facility")}
            </button>
            <button className="btn btn-sm" onClick={() => setForm("certificate")}>
              <FileText size={15} aria-hidden /> {t("consult.certificate", "Certificate")}
            </button>
          </>
        )
      }
    >
      {none ? (
        <p className="subtle">{t("consult.no_docs", "No referral or certificate for this consultation.")}</p>
      ) : (
        <table className="data">
          <tbody>
            {internal.data?.map((r) => (
              <tr key={r.id} className={r.status === "cancelled" ? "muted" : ""}>
                <td>
                  <strong>{t("consult.internal_referral", "Referred within the clinic")}</strong>
                  <div className="small">
                    {r.to_department_name}
                    {r.to_doctor && `, Dr. ${r.to_doctor.full_name}`} ({r.urgency}): {r.reason}
                  </div>
                  <div className="small subtle">
                    {r.status === "seen"
                      ? t("consult.internal_seen", "Seen by Dr. {{who}}, {{when}}", {
                          who: r.seen_by ?? "",
                          when: formatDateTime(r.seen_at),
                        })
                      : r.status === "cancelled"
                        ? `${t("common.cancelled", "Cancelled")}: ${r.cancel_reason}`
                        : t("consult.internal_waiting", "Waiting to be seen")}
                  </div>
                </td>
                <td className="num">
                  {mine && r.status === "pending" && (
                    <button
                      className="btn btn-sm btn-ghost"
                      onClick={() => setCancelling({ kind: "internal-referrals", id: r.id })}
                    >
                      {t("common.cancel")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {refs.data?.map((r) => (
              <tr key={r.id} className={r.status === "cancelled" ? "muted" : ""}>
                <td>
                  <strong>{t("consult.referral", "Referral")}</strong> <span className="mono small">{r.number}</span>
                  <div className="small">
                    {r.to_facility}
                    {r.to_department && `, ${r.to_department}`} ({r.urgency})
                  </div>
                  {r.status === "cancelled" && (
                    <div className="small">
                      {t("common.cancelled", "Cancelled")}: {r.cancel_reason}
                    </div>
                  )}
                </td>
                <td className="num">
                  <div className="row" style={{ justifyContent: "flex-end", gap: 6 }}>
                    <button className="btn btn-sm" onClick={() => setView({ kind: "referral", doc: r })}>
                      <Printer size={14} aria-hidden /> {t("common.view_print", "View / print")}
                    </button>
                    {mine && r.status === "issued" && (
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => setCancelling({ kind: "referrals", id: r.id })}
                      >
                        {t("common.cancel")}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {certs.data?.map((c) => (
              <tr key={c.id} className={c.is_cancelled ? "muted" : ""}>
                <td>
                  <strong>
                    {t(`consult.cert.${c.kind}`, CERT_KINDS.find((k) => k.key === c.kind)?.label ?? c.kind)}
                  </strong>{" "}
                  <span className="mono small">{c.number}</span>
                  {c.days && (
                    <div className="small">
                      {c.start_date} → {c.end_date} ({c.days} {t("common.days", "days")})
                    </div>
                  )}
                  {c.is_cancelled && (
                    <div className="small">
                      {t("common.cancelled", "Cancelled")}: {c.cancel_reason}
                    </div>
                  )}
                </td>
                <td className="num">
                  <div className="row" style={{ justifyContent: "flex-end", gap: 6 }}>
                    <button className="btn btn-sm" onClick={() => setView({ kind: "certificate", doc: c })}>
                      <Printer size={14} aria-hidden /> {t("common.view_print", "View / print")}
                    </button>
                    {mine && !c.is_cancelled && (
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => setCancelling({ kind: "certificates", id: c.id })}
                      >
                        {t("common.cancel")}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Modal
        open={form === "referral"}
        title={t("consult.refer_title", "Refer the patient")}
        onClose={() => setForm(null)}
      >
        {form === "referral" && (
          <ReferralForm
            encounter={e}
            onDone={(r) => {
              setForm(null);
              setView({ kind: "referral", doc: r });
            }}
          />
        )}
      </Modal>
      <Modal
        open={form === "internal"}
        title={t("consult.refer_internal", "Refer within the clinic")}
        onClose={() => setForm(null)}
      >
        {form === "internal" && (
          <InternalReferralForm
            encounter={e}
            currentDepartment={visitDepartment}
            onDone={() => {
              setForm(null);
              void internal.refetch();
            }}
          />
        )}
      </Modal>
      <Modal
        open={form === "certificate"}
        title={t("consult.cert_title", "Medical certificate")}
        onClose={() => setForm(null)}
      >
        {form === "certificate" && (
          <CertificateForm
            encounter={e}
            onDone={(c) => {
              setForm(null);
              setView({ kind: "certificate", doc: c });
            }}
          />
        )}
      </Modal>
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
        {view?.kind === "referral" && <ReferralLetter referral={view.doc} encounter={e} />}
        {view?.kind === "certificate" && <CertificateDoc cert={view.doc} />}
      </Modal>
      <ReasonDialog
        open={cancelling !== null}
        title={t("consult.cancel_doc", "Cancel document")}
        label={t("common.reason", "Reason")}
        confirmLabel={t("consult.cancel_doc_confirm", "Cancel document")}
        danger
        busy={cancel.isPending}
        error={cancel.error}
        onClose={() => setCancelling(null)}
        onConfirm={(reason) => cancelling && cancel.mutate({ ...cancelling, reason })}
      />
    </Panel>
  );
}

function InternalReferralForm({
  encounter: e,
  currentDepartment,
  onDone,
}: {
  encounter: Encounter;
  currentDepartment: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const destinations = useTriageDestinations().filter((d) => d.code !== currentDepartment);
  const [f, setF] = useState({ to_department: "", to_doctor_id: "", urgency: "routine", reason: "" });
  const save = useAction(
    () => api.post(`/encounters/${e.id}/internal-referrals/`, { ...f, to_doctor_id: f.to_doctor_id || null }),
    [["encounter", e.id], ["visits"]],
    onDone,
    t("consult.internal_saved", "Patient sent to the department's waiting list"),
  );
  return (
    <form
      className="stack-sm"
      onSubmit={(ev) => {
        ev.preventDefault();
        save.mutate(undefined);
      }}
    >
      <ErrorBanner error={save.error} />
      <p className="muted small">
        {t(
          "consult.internal_intro",
          "The patient moves to that department's waiting list in this same visit. Your note stays yours: sign it when you are done.",
        )}
      </p>
      <div className="form-grid">
        <Field label={t("consult.to_department_internal", "Department")} id="ir-d" error={save.error}>
          <select
            id="ir-d"
            value={f.to_department}
            onChange={(ev) => setF({ ...f, to_department: ev.target.value })}
            required
            autoFocus
          >
            <option value="">{t("common.choose", "Choose…")}</option>
            {destinations.map((d) => (
              <option key={d.code} value={d.code}>
                {d.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("consult.to_doctor", "Doctor (optional)")} id="ir-doc">
          <DoctorSelect
            id="ir-doc"
            value={f.to_doctor_id}
            onChange={(v) => setF({ ...f, to_doctor_id: v })}
            allowNone
            noneLabel={t("consult.any_doctor_dept", "Any doctor in that department")}
          />
        </Field>
        <Field label={t("consult.urgency", "Urgency")} id="ir-u">
          <select id="ir-u" value={f.urgency} onChange={(ev) => setF({ ...f, urgency: ev.target.value })}>
            {URGENCY.map((u) => (
              <option key={u.key} value={u.key}>
                {t(`state.priority.${u.key}`, u.label)}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label={t("consult.referral_reason", "Reason for referral")} id="ir-r">
        <textarea id="ir-r" value={f.reason} onChange={(ev) => setF({ ...f, reason: ev.target.value })} required />
      </Field>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={save.isPending || !f.to_department || !f.reason.trim()}>
          {t("consult.send_internal", "Send to department")}
        </button>
      </div>
    </form>
  );
}

/** For the receiving doctor: why this patient was sent here. */
export function ReferredHere({ visitId, encounterId }: { visitId: string; encounterId: string }) {
  const { t } = useTranslation();
  const q = useGet<InternalReferral[]>(["visits", visitId, "internal"], `/visits/${visitId}/internal-referrals/`);
  // Shown to the receiving doctor only: the referring doctor's own consultation is the referral's source.
  const r = q.data?.find((x) => x.status !== "cancelled" && x.from_encounter !== encounterId);
  if (!r) return null;
  return (
    <Banner tone="info">
      <strong>
        {t("consult.referred_here", "Referred from {{from}} by Dr. {{who}}", {
          from: r.from_department_name || "—",
          who: r.referred_by,
        })}
      </strong>{" "}
      ({r.urgency}, {formatDateTime(r.created_at)}): {r.reason}
    </Banner>
  );
}

function ReferralForm({ encounter: e, onDone }: { encounter: Encounter; onDone: (r: Referral) => void }) {
  const { t } = useTranslation();
  const dx = e.diagnoses.map((d) => d.description).join("; ");
  const [f, setF] = useState({
    to_facility: "",
    to_department: "",
    urgency: "routine",
    reason: "",
    clinical_summary: [
      e.chief_complaint && `Complaint: ${e.chief_complaint}`,
      dx && `Diagnosis: ${dx}`,
      e.plan && `Plan: ${e.plan}`,
    ]
      .filter(Boolean)
      .join("\n"),
    treatment_given: e.prescriptions
      .flatMap((rx) => rx.items.map((i) => `${i.drug_name} ${i.dose} ${i.frequency}`))
      .join("; "),
  });
  const set = (k: keyof typeof f) => (ev: { target: { value: string } }) => setF({ ...f, [k]: ev.target.value });
  const save = useAction(
    () => api.post<Referral>(`/encounters/${e.id}/referrals/`, f),
    [["encounter", e.id], ["visits"]],
    onDone,
    t("consult.referral_saved", "Referral issued"),
  );
  return (
    <form
      className="stack-sm"
      onSubmit={(ev) => {
        ev.preventDefault();
        save.mutate(undefined);
      }}
    >
      <ErrorBanner error={save.error} />
      <div className="form-grid">
        <Field label={t("consult.to_facility", "Referred to (facility)")} id="rf-f" error={save.error}>
          <input id="rf-f" value={f.to_facility} onChange={set("to_facility")} required autoFocus />
        </Field>
        <Field label={t("consult.to_department", "Department or service")} id="rf-d">
          <input id="rf-d" value={f.to_department} onChange={set("to_department")} />
        </Field>
        <Field label={t("consult.urgency", "Urgency")} id="rf-u">
          <select id="rf-u" value={f.urgency} onChange={set("urgency")}>
            {URGENCY.map((u) => (
              <option key={u.key} value={u.key}>
                {t(`state.priority.${u.key}`, u.label)}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label={t("consult.referral_reason", "Reason for referral")} id="rf-r">
        <textarea id="rf-r" value={f.reason} onChange={set("reason")} required />
      </Field>
      <Field
        label={t("consult.clinical_summary", "Clinical summary")}
        id="rf-s"
        hint={t("consult.summary_hint", "Pre-filled from this note; edit as needed.")}
      >
        <textarea id="rf-s" value={f.clinical_summary} onChange={set("clinical_summary")} rows={4} />
      </Field>
      <Field label={t("consult.treatment_given", "Treatment given")} id="rf-t">
        <textarea id="rf-t" value={f.treatment_given} onChange={set("treatment_given")} />
      </Field>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={save.isPending || !f.to_facility.trim() || !f.reason.trim()}>
          {t("consult.issue_referral", "Issue referral")}
        </button>
      </div>
    </form>
  );
}

function CertificateForm({ encounter: e, onDone }: { encounter: Encounter; onDone: (c: Certificate) => void }) {
  const { t } = useTranslation();
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Addis_Ababa" }).format(new Date());
  const [f, setF] = useState({
    kind: "sick_leave",
    start_date: today,
    end_date: today,
    include_diagnosis: false,
    diagnosis_text: e.diagnoses[0]?.description ?? "",
    remarks: "",
  });
  const save = useAction(
    () =>
      api.post<Certificate>(`/encounters/${e.id}/certificates/`, {
        ...f,
        start_date: f.kind === "attendance" ? null : f.start_date || null,
        end_date: f.kind === "attendance" ? null : f.end_date || null,
      }),
    [["encounter", e.id]],
    onDone,
    t("consult.cert_saved", "Certificate issued"),
  );
  return (
    <form
      className="stack-sm"
      onSubmit={(ev) => {
        ev.preventDefault();
        save.mutate(undefined);
      }}
    >
      <ErrorBanner error={save.error} />
      <Field label={t("consult.cert_kind", "Type")} id="ct-k">
        <select id="ct-k" value={f.kind} onChange={(ev) => setF({ ...f, kind: ev.target.value })}>
          {CERT_KINDS.map((k) => (
            <option key={k.key} value={k.key}>
              {t(`consult.cert.${k.key}`, k.label)}
            </option>
          ))}
        </select>
      </Field>
      {f.kind !== "attendance" && (
        <div className="form-grid">
          <Field label={t("consult.from", "From")} id="ct-s">
            <input
              id="ct-s"
              type="date"
              value={f.start_date}
              onChange={(ev) => setF({ ...f, start_date: ev.target.value })}
            />
          </Field>
          <Field label={t("consult.to", "To (inclusive)")} id="ct-e">
            <input
              id="ct-e"
              type="date"
              min={f.start_date}
              value={f.end_date}
              onChange={(ev) => setF({ ...f, end_date: ev.target.value })}
            />
          </Field>
        </div>
      )}
      <label className="check">
        <input
          type="checkbox"
          checked={f.include_diagnosis}
          onChange={(ev) => setF({ ...f, include_diagnosis: ev.target.checked })}
        />
        <span>
          {t(
            "consult.include_dx",
            "Print the diagnosis on the certificate. Only with the patient's agreement: employers do not need it.",
          )}
        </span>
      </label>
      {f.include_diagnosis && (
        <Field label={t("consult.dx_text", "Diagnosis as printed")} id="ct-d">
          <input
            id="ct-d"
            value={f.diagnosis_text}
            onChange={(ev) => setF({ ...f, diagnosis_text: ev.target.value })}
          />
        </Field>
      )}
      <Field label={t("consult.remarks", "Remarks")} id="ct-r">
        <textarea id="ct-r" value={f.remarks} onChange={(ev) => setF({ ...f, remarks: ev.target.value })} />
      </Field>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={save.isPending}>
          {t("consult.issue_cert", "Issue certificate")}
        </button>
      </div>
    </form>
  );
}

function Signature({ who }: { who: Clinician }) {
  const { t } = useTranslation();
  return (
    <div className="doc-sign">
      <div>
        {who.full_name}
        {who.job_title && `, ${who.job_title}`}
      </div>
      <div className="small">
        {t("consult.reg_no", "Registration no.")} {who.registration_number || "________"}
      </div>
      <div className="doc-sign-line">{t("consult.signature_stamp", "Signature and stamp")}</div>
    </div>
  );
}

/** Printable prescription. When the clinic has no pharmacy module the patient takes this to an outside pharmacy. */
export function PrescriptionDoc({ rx, allergies }: { rx: Prescription; allergies?: string }) {
  const { t } = useTranslation();
  const who: Clinician = rx.prescriber_details ?? {
    id: rx.prescriber.id,
    full_name: rx.prescriber.full_name,
    job_title: "",
    registration_number: "",
  };
  return (
    <div className="stack-sm">
      <article className="doc" id="prescription-doc">
        <ClinicHeader title={t("rx.document_title", "Prescription")} number={rx.number} />
        <dl className="facts">
          <dt>{t("common.date", "Date")}</dt>
          <dd>
            {formatDateTime(rx.created_at)}
            <Ec value={rx.created_at} />
          </dd>
          <dt>{t("patients.patient", "Patient")}</dt>
          <dd>
            {rx.patient.full_name}, {sexAge(rx.patient, t)}, MRN <span className="mono">{rx.patient.mrn}</span>
          </dd>
          {rx.patient_weight_kg && (
            <>
              <dt>{t("rx.weight", "Weight")}</dt>
              <dd>{Number(rx.patient_weight_kg)} kg</dd>
            </>
          )}
          <dt>{t("patients.allergies", "Allergies")}</dt>
          <dd>{allergies?.trim() || t("rx.no_known_allergies", "None recorded")}</dd>
        </dl>
        <table className="data rx-table">
          <thead>
            <tr>
              <th>{t("rx.medicine", "Medicine")}</th>
              <th>{t("rx.how_to_take", "How to take")}</th>
              <th className="num">{t("rx.quantity", "Quantity")}</th>
            </tr>
          </thead>
          <tbody>
            {rx.items.map((i) => (
              <tr key={i.id}>
                <td>
                  <strong>{i.drug_name}</strong>
                  {(i.strength || i.dosage_form) && (
                    <div className="small">{[i.strength, i.dosage_form].filter(Boolean).join(" ")}</div>
                  )}
                </td>
                <td>
                  {i.dose}, {i.route}, {i.frequency}
                  {i.duration_days ? `, ${i.duration_days} ${t("rx.days", "days")}` : ""}
                  {i.instructions && <div className="small">{i.instructions}</div>}
                </td>
                <td className="num">
                  {Number(i.quantity)} {i.unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rx.notes && <p className="prewrap">{rx.notes}</p>}
        {rx.controlled_class && (
          <p className="small">
            {t(
              "rx.controlled_note",
              "Controlled medicine: valid only with the special prescription form, serial {{serial}}.",
              { serial: rx.special_form_serial || "________" },
            )}
          </p>
        )}
        <Signature who={who} />
        <DocFooter kind="note_prescription" />
      </article>
      <div className="form-actions">
        <button
          className="btn btn-primary"
          onClick={() => printElement("prescription-doc", rx.number || "prescription")}
        >
          <Printer size={16} aria-hidden /> {t("common.print", "Print")}
        </button>
      </div>
    </div>
  );
}

export function ReferralLetter({ referral: r, encounter: e }: { referral: Referral; encounter?: Encounter }) {
  const { t } = useTranslation();
  return (
    <div className="stack-sm">
      <article className="doc" id="referral-doc">
        <ClinicHeader title={t("consult.referral_letter", "Referral letter")} number={r.number} />
        <dl className="facts">
          <dt>{t("common.date", "Date")}</dt>
          <dd>
            {formatDateTime(r.created_at)}
            <Ec value={r.created_at} />
          </dd>
          <dt>{t("consult.to", "To")}</dt>
          <dd>
            <strong>{r.to_facility}</strong>
            {r.to_department && `, ${r.to_department}`}
          </dd>
          <dt>{t("consult.urgency", "Urgency")}</dt>
          <dd>{r.urgency}</dd>
          <dt>{t("patients.patient", "Patient")}</dt>
          <dd>
            {r.patient.full_name}, {sexAge(r.patient, t)}, MRN <span className="mono">{r.patient.mrn}</span>
            {r.patient.phone && `, ${r.patient.phone}`}
          </dd>
        </dl>
        <h3>{t("consult.referral_reason", "Reason for referral")}</h3>
        <p className="prewrap">{r.reason}</p>
        {r.clinical_summary && (
          <>
            <h3>{t("consult.clinical_summary", "Clinical summary")}</h3>
            <p className="prewrap">{r.clinical_summary}</p>
          </>
        )}
        {r.treatment_given && (
          <>
            <h3>{t("consult.treatment_given", "Treatment given")}</h3>
            <p className="prewrap">{r.treatment_given}</p>
          </>
        )}
        {e?.allergy_notes && (
          <>
            <h3>{t("patients.allergies", "Allergies")}</h3>
            <p>{e.allergy_notes}</p>
          </>
        )}
        <Signature who={r.referred_by} />
        <DocFooter kind="note_referral" />
        {r.status === "cancelled" && (
          <p className="flag-H">
            {t("consult.doc_is_cancelled", "CANCELLED")}: {r.cancel_reason}
          </p>
        )}
      </article>
      <div className="form-actions">
        <button className="btn btn-primary" onClick={() => printElement("referral-doc", r.number)}>
          <Printer size={16} aria-hidden /> {t("common.print", "Print")}
        </button>
      </div>
    </div>
  );
}

export function CertificateDoc({ cert: c }: { cert: Certificate }) {
  const { t } = useTranslation();
  const kind = CERT_KINDS.find((k) => k.key === c.kind)?.label ?? c.kind;
  return (
    <div className="stack-sm">
      <article className="doc" id="certificate-doc">
        <ClinicHeader title={t(`consult.cert.${c.kind}`, kind)} number={c.number} />
        <p>
          {t("consult.cert_body_1", "This is to certify that")} <strong>{c.patient.full_name}</strong> (
          {sexAge(c.patient, t)}, MRN <span className="mono">{c.patient.mrn}</span>){" "}
          {t("consult.cert_body_2", "was seen at this facility on {{date}}.", {
            date: formatDateTime(c.created_at).split(",")[0],
          })}
          <Ec value={c.created_at} />
        </p>
        {c.kind === "sick_leave" && c.days && (
          <p>
            {t(
              "consult.cert_sick",
              "On medical grounds the patient needs rest from {{from}} to {{to}} inclusive ({{n}} days).",
              { from: c.start_date, to: c.end_date, n: c.days },
            )}
            {c.start_date && c.end_date && <EcRange from={c.start_date} to={c.end_date} />}
          </p>
        )}
        {c.kind === "fitness" && (
          <p>
            {t("consult.cert_fit", "On examination the patient is fit to resume work or study{{from}}.", {
              from: c.start_date ? ` from ${c.start_date}` : "",
            })}
          </p>
        )}
        {c.include_diagnosis && c.diagnosis_text && (
          <p>
            {t("consult.dx", "Diagnosis")}: {c.diagnosis_text}
          </p>
        )}
        {c.remarks && <p className="prewrap">{c.remarks}</p>}
        <Signature who={c.issued_by} />
        <DocFooter kind="note_certificate" />
        {c.is_cancelled && (
          <p className="flag-H">
            {t("consult.doc_is_cancelled", "CANCELLED")}: {c.cancel_reason}
          </p>
        )}
      </article>
      <div className="form-actions">
        <button className="btn btn-primary" onClick={() => printElement("certificate-doc", c.number)}>
          <Printer size={16} aria-hidden /> {t("common.print", "Print")}
        </button>
      </div>
    </div>
  );
}
