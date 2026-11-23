import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  CalendarPlus,
  GitMerge,
  ListPlus,
  Pencil,
  Plus,
  RotateCcw,
  UserPlus,
  UserX,
  IdCard,
} from "lucide-react";
import { api, queryString } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { Paginated, Patient, PatientBrief, Visit } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime } from "../lib/format";
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
  Segmented,
  Tabs,
  fieldErrors,
  initials,
} from "../ui";
import { AppointmentForm } from "./appointments";
import { DoctorSelect, Ec, PatientPicker, sexAge, todayIso } from "./common";
import { LabTestChecklist } from "./consultation-orders";
import { PatientCard } from "./printouts";
import { AttachmentsPanel } from "./attachments";
import {
  VisitHistory,
  ChangeHistory,
  VitalsHistory,
  ConsultationHistory,
  LabHistory,
  MedicineHistory,
  DiagnosisHistory,
  DocumentHistory,
  AppointmentHistory,
  BillingHistory,
} from "./patient-history";
import { PatientForm } from "./patient-form";
const PAGE = 25;

export function PatientsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [applied, setApplied] = useState("");
  const [page, setPage] = useState(1);
  const [withInactive, setWithInactive] = useState(false);
  const registering = params.get("register") === "1";
  const list = useGet<Paginated<Patient>>(
    ["patients", "list", applied, page, withInactive],
    `/patients/${queryString({ q: applied, page, page_size: PAGE, include_inactive: withInactive ? "true" : undefined })}`,
  );

  return (
    <div className="stack">
      <PageHead
        title={t("nav.patients")}
        sub={
          applied
            ? t("patients.results_for", "Results for “{{q}}”", { q: applied })
            : t("patients.recent", "Most recently registered")
        }
        actions={
          can("patients.create") && (
            <button className="btn btn-primary" onClick={() => setParams({ register: "1" })}>
              <UserPlus size={18} aria-hidden /> {t("patients.register", "Register a new patient")}
            </button>
          )
        }
      />
      <form
        className="filters"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setApplied(q.trim());
        }}
      >
        <div className="field grow" style={{ maxWidth: 520 }}>
          <label htmlFor="pq">{t("patients.search_label", "Name, phone number, MRN or national ID")}</label>
          <input id="pq" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <button className="btn" type="submit">
          {t("common.search")}
        </button>
        <label className="check" style={{ alignSelf: "end", marginBottom: 8 }}>
          <input
            type="checkbox"
            checked={withInactive}
            onChange={(e) => {
              setWithInactive(e.target.checked);
              setPage(1);
            }}
          />
          {t("patients.include_inactive", "Include inactive and deceased records")}
        </label>
      </form>
      <Panel flush>
        <ErrorBanner error={list.error} />
        {list.isLoading ? (
          <Loading />
        ) : list.data?.results.length === 0 ? (
          <Empty>{t("patients.no_match", "No patient matches. Check the spelling or register a new patient.")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("patients.name", "Name")}</th>
                  <th>MRN</th>
                  <th>{t("patients.sex_age", "Sex, age")}</th>
                  <th>{t("patients.phone", "Phone")}</th>
                  <th>{t("patients.city", "City")}</th>
                  <th>{t("patients.registered", "Registered")}</th>
                </tr>
              </thead>
              <tbody>
                {list.data?.results.map((p) => (
                  <tr key={p.id} className="clickable" onClick={() => navigate(`/patients/${p.id}`)}>
                    <td>
                      <Link to={`/patients/${p.id}`} onClick={(e) => e.stopPropagation()}>
                        <strong>{p.full_name}</strong>
                      </Link>
                      {p.is_active === false && (
                        <>
                          {" "}
                          <PatientStatusBadge patient={p} />
                        </>
                      )}
                    </td>
                    <td className="mono">{p.mrn}</td>
                    <td>
                      {sexAge(p, t)}
                      {p.birth_date_estimated && (
                        <span className="subtle"> ({t("patients.estimated", "estimated")})</span>
                      )}
                    </td>
                    <td>{p.phone || "—"}</td>
                    <td>{p.city || "—"}</td>
                    <td className="nowrap">{formatDateTime(p.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {list.data && <Pager page={page} count={list.data.count} pageSize={PAGE} onPage={setPage} />}
      </Panel>
      <Modal
        open={registering}
        wide
        title={t("patients.register", "Register a new patient")}
        onClose={() => setParams({})}
      >
        <PatientForm onSaved={(p) => navigate(`/patients/${p.id}`)} />
      </Modal>
    </div>
  );
}

// ---------------------------------------------------------------------------- chart
type ChartTab =
  | "overview"
  | "visits"
  | "vitals"
  | "consultations"
  | "diagnoses"
  | "labs"
  | "medicines"
  | "documents"
  | "attachments"
  | "appointments"
  | "billing";

export function PatientChart() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as ChartTab) || "overview";
  const patient = useGet<Patient>(["patient", id], `/patients/${id}/`);
  const [editing, setEditing] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const [booking, setBooking] = useState(false);
  const [addingAllergy, setAddingAllergy] = useState(false);
  const [merging, setMerging] = useState(false);
  const [printingCard, setPrintingCard] = useState(false);
  const [statusOpen, setStatusOpen] = useState<"deactivate" | "reactivate" | null>(null);
  const reactivate = useAction(
    (reason: string) => api.post(`/patients/${id}/reactivate/`, { reason }, { ifMatch: patient.data?.row_version }),
    [["patient", id], ["patients"]],
    () => setStatusOpen(null),
    t("patients.reactivated", "Record reactivated"),
  );

  if (patient.isLoading) return <Loading />;
  if (patient.error || !patient.data) return <ErrorBanner error={patient.error} />;
  const p = patient.data;
  const allergies = p.allergies?.filter((a) => a.is_active) ?? [];
  const retired = !!p.merged_into || p.is_active === false;

  const tabs: { key: ChartTab; label: string }[] = [
    { key: "overview", label: t("chart.overview", "Overview") },
    { key: "visits", label: t("chart.visits", "Visits") },
  ];
  if (can("clinical.view", "triage.record")) tabs.push({ key: "vitals", label: t("chart.vitals", "Vital signs") });
  if (can("clinical.view"))
    tabs.push(
      { key: "consultations", label: t("chart.notes", "Evaluation notes") },
      { key: "diagnoses", label: t("chart.diagnoses", "Diagnoses") },
    );
  if (can("lab.view", "lab.result.enter", "clinical.view"))
    tabs.push({ key: "labs", label: t("chart.labs", "Laboratory") });
  if (can("clinical.view", "pharmacy.view")) tabs.push({ key: "medicines", label: t("chart.medicines", "Medicines") });
  if (can("clinical.view")) tabs.push({ key: "documents", label: t("chart.documents", "Referrals & certificates") });
  if (can("clinical.view", "patients.update"))
    tabs.push({ key: "attachments", label: t("chart.attachments", "Attached documents") });
  if (can("appointments.view")) tabs.push({ key: "appointments", label: t("chart.appointments", "Appointments") });
  if (can("billing.view")) tabs.push({ key: "billing", label: t("chart.billing", "Billing") });

  return (
    <div className="stack">
      {p.merged_into && (
        <Banner tone="warn">
          {t(
            "patients.merged_banner",
            "This record was merged into {{name}} ({{mrn}}) on {{when}}. Record everything new there.",
            { name: p.merged_into.full_name, mrn: p.merged_into.mrn, when: formatDateTime(p.merged_at) },
          )}{" "}
          <Link to={`/patients/${p.merged_into.id}`}>{t("patients.open_kept", "Open that record")}</Link>
          {p.merge_reason && (
            <div className="small">
              {t("common.reason", "Reason")}: {p.merge_reason}
            </div>
          )}
        </Banner>
      )}
      {!p.merged_into && p.is_active === false && (
        <Banner tone={p.inactive_kind === "deceased" ? "error" : "warn"}>
          <strong>
            {p.inactive_kind === "deceased"
              ? t("patients.deceased_banner", "Recorded as deceased on {{date}}.", { date: p.date_of_death ?? "" })
              : t("patients.inactive_banner", "Inactive record: {{why}}.", { why: inactiveLabel(p.inactive_kind, t) })}
          </strong>{" "}
          {t("patients.inactive_kept", "The record is kept in full; nothing new can be added.")}
          {p.inactive_note && (
            <div className="small">
              {t("common.reason", "Reason")}: {p.inactive_note}
            </div>
          )}
          {p.inactivated_by_name && (
            <div className="small">
              {t("patients.inactivated_by", "By {{who}}, {{when}}", {
                who: p.inactivated_by_name,
                when: formatDateTime(p.inactivated_at),
              })}
            </div>
          )}
          {can("patients.status") && (
            <div style={{ marginTop: 6 }}>
              <button className="btn btn-sm" onClick={() => setStatusOpen("reactivate")}>
                <RotateCcw size={15} aria-hidden /> {t("patients.reactivate", "Reactivate record…")}
              </button>
            </div>
          )}
        </Banner>
      )}
      {!!p.merged_records?.length && (
        <Banner tone="info">
          {t("patients.has_merged", "Also known under")}{" "}
          {p.merged_records.map((m, i) => (
            <span key={m.id}>
              {i > 0 && ", "}
              <Link to={`/patients/${m.id}`} className="mono">
                {m.mrn}
              </Link>
            </span>
          ))}{" "}
          {t("patients.has_merged_2", "(merged duplicate records).")}
        </Banner>
      )}
      <section className="patient-banner">
        <div className="avatar" aria-hidden>
          {initials(p.full_name)}
        </div>
        <div>
          <h1>{p.full_name}</h1>
          <div className="ids">
            <span>
              MRN <b className="mono">{p.mrn}</b>
            </span>
            <span>
              {sexAge(p, t)}
              {p.birth_date_estimated ? ` (${t("patients.estimated", "estimated")})` : ""}
            </span>
            <span>
              {t("patients.born", "Born")} <b>{p.birth_date}</b>
              <Ec value={p.birth_date} />
            </span>
            {p.blood_group && (
              <span>
                {t("patients.blood", "Blood")} <b>{p.blood_group}</b>
              </span>
            )}
            {p.phone && <span>{p.phone}</span>}
          </div>
          <div className={`alert-strip${allergies.length ? "" : " none"}`}>
            {allergies.length ? <AlertTriangle size={16} aria-hidden /> : null}
            {allergies.length ? (
              <span>
                <strong>{t("patients.allergies", "Allergies")}:</strong>{" "}
                {allergies.map((a) => `${a.substance} (${a.severity})`).join(", ")}
              </span>
            ) : (
              <span>{t("patients.no_allergies", "No known allergies recorded")}</span>
            )}
            {can("patients.update") && (
              <button className="link-btn small" style={{ marginLeft: "auto" }} onClick={() => setAddingAllergy(true)}>
                {t("patients.add_allergy", "Add allergy")}
              </button>
            )}
          </div>
        </div>
        {!retired && (
          <div className="row" style={{ alignSelf: "start" }}>
            {can("queue.manage") && (
              <button className="btn btn-primary" onClick={() => setQueueing(true)}>
                <ListPlus size={18} aria-hidden /> {t("queue.add", "Add to waiting list")}
              </button>
            )}
            {can("appointments.manage") && (
              <button className="btn" onClick={() => setBooking(true)}>
                <CalendarPlus size={18} aria-hidden /> {t("appointments.book", "Book appointment")}
              </button>
            )}
            <button
              className="btn btn-ghost btn-icon"
              onClick={() => setPrintingCard(true)}
              aria-label={t("card.print", "Print patient card")}
              title={t("card.print", "Print patient card")}
            >
              <IdCard size={18} />
            </button>
            {can("patients.update") && (
              <button
                className="btn btn-ghost btn-icon"
                onClick={() => setEditing(true)}
                aria-label={t("patients.edit", "Edit details")}
              >
                <Pencil size={18} />
              </button>
            )}
            {can("patients.status") && (
              <button
                className="btn btn-ghost btn-icon"
                onClick={() => setStatusOpen("deactivate")}
                aria-label={t("patients.deactivate", "Mark inactive or deceased")}
                title={t("patients.deactivate", "Mark inactive or deceased")}
              >
                <UserX size={18} />
              </button>
            )}
            {can("patients.merge") && (
              <button
                className="btn btn-ghost btn-icon"
                onClick={() => setMerging(true)}
                aria-label={t("patients.merge", "Merge a duplicate record into this one")}
                title={t("patients.merge", "Merge a duplicate record into this one")}
              >
                <GitMerge size={18} />
              </button>
            )}
          </div>
        )}
      </section>

      <Tabs tabs={tabs} value={tab} onChange={(k) => setParams({ tab: k })} />
      {tab === "overview" && <Overview patient={p} />}
      {tab === "visits" && <VisitHistory patientId={p.id} />}
      {tab === "vitals" && <VitalsHistory patientId={p.id} />}
      {tab === "consultations" && <ConsultationHistory patientId={p.id} />}
      {tab === "diagnoses" && <DiagnosisHistory patientId={p.id} />}
      {tab === "documents" && <DocumentHistory patientId={p.id} />}
      {tab === "attachments" && <AttachmentsPanel patientId={p.id} />}
      {tab === "appointments" && <AppointmentHistory patientId={p.id} />}
      {tab === "labs" && <LabHistory patientId={p.id} />}
      {tab === "medicines" && <MedicineHistory patientId={p.id} />}
      {tab === "billing" && <BillingHistory patientId={p.id} />}

      <Modal open={printingCard} title={t("card.print", "Print patient card")} onClose={() => setPrintingCard(false)}>
        {printingCard && <PatientCard patient={p} />}
      </Modal>
      <Modal open={editing} wide title={t("patients.edit", "Edit details")} onClose={() => setEditing(false)}>
        <PatientForm
          patient={p}
          onSaved={() => {
            setEditing(false);
            void patient.refetch();
          }}
          onReload={() => {
            setEditing(false);
            void patient.refetch();
          }}
        />
      </Modal>
      <Modal open={queueing} title={t("queue.add", "Add to waiting list")} onClose={() => setQueueing(false)}>
        <WalkInForm patient={p} onDone={() => setQueueing(false)} />
      </Modal>
      <Modal open={booking} title={t("appointments.book", "Book appointment")} onClose={() => setBooking(false)}>
        <AppointmentForm patient={p} onDone={() => setBooking(false)} />
      </Modal>
      <Modal
        open={statusOpen === "deactivate"}
        title={t("patients.deactivate", "Mark inactive or deceased")}
        onClose={() => setStatusOpen(null)}
      >
        {statusOpen === "deactivate" && (
          <DeactivateForm
            patient={p}
            onDone={() => {
              setStatusOpen(null);
              void patient.refetch();
            }}
          />
        )}
      </Modal>
      <ReasonDialog
        open={statusOpen === "reactivate"}
        title={t("patients.reactivate_title", "Reactivate this record?")}
        label={t("patients.reactivate_reason", "Why? e.g. the patient came back, or marked by mistake")}
        confirmLabel={t("patients.reactivate_btn", "Reactivate")}
        onClose={() => setStatusOpen(null)}
        busy={reactivate.isPending}
        error={reactivate.error}
        onConfirm={(reason) => reactivate.mutate(reason)}
      />
      <Modal
        open={merging}
        wide
        title={t("patients.merge_title", "Merge a duplicate into {{name}}", { name: p.full_name })}
        onClose={() => setMerging(false)}
      >
        {merging && (
          <MergeForm
            keep={p}
            onDone={() => {
              setMerging(false);
              void patient.refetch();
            }}
          />
        )}
      </Modal>
      <Modal
        open={addingAllergy}
        title={t("patients.add_allergy", "Add allergy")}
        onClose={() => setAddingAllergy(false)}
      >
        <AllergyForm
          patientId={p.id}
          onDone={() => {
            setAddingAllergy(false);
            void patient.refetch();
          }}
        />
      </Modal>
    </div>
  );
}

function Overview({ patient: p }: { patient: Patient }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [removing, setRemoving] = useState<string | null>(null);
  const remove = useAction(
    (v: { id: string; reason: string }) =>
      api.post(`/patients/${p.id}/allergies/${v.id}/inactivate/`, { reason: v.reason }),
    [["patient", p.id]],
    () => setRemoving(null),
  );
  const address = [
    p.house_number && `House ${p.house_number}`,
    p.kebele && `Kebele ${p.kebele}`,
    p.subcity_woreda,
    p.city,
    p.region,
  ]
    .filter(Boolean)
    .join(", ");
  return (
    <div className="cols-2">
      <Panel title={t("patients.details", "Personal details")}>
        <dl className="facts">
          <dt>{t("patients.address", "Address")}</dt>
          <dd>{address || "—"}</dd>
          <dt>{t("patients.phone", "Phone")}</dt>
          <dd>{[p.phone, p.alt_phone].filter(Boolean).join(", ") || "—"}</dd>
          <dt>{t("patients.national_id", "National ID")}</dt>
          <dd>{p.national_id || "—"}</dd>
          <dt>{t("patients.registered", "Registered")}</dt>
          <dd>{formatDateTime(p.created_at)}</dd>
          <dt>{t("patients.emergency_contact", "Emergency contact")}</dt>
          <dd>
            {p.emergency_contacts?.length
              ? p.emergency_contacts.map((c) => (
                  <div key={c.id}>
                    {c.name}
                    {c.relationship && ` (${c.relationship})`}, {c.phone}
                  </div>
                ))
              : "—"}
          </dd>
        </dl>
        <ChangeHistory patientId={p.id} />
      </Panel>
      <Panel title={t("patients.medical", "Medical background")}>
        <dl className="facts">
          <dt>{t("patients.blood_group", "Blood group")}</dt>
          <dd>{p.blood_group || t("patients.unknown", "Unknown")}</dd>
          <dt>{t("patients.chronic_illness", "Chronic illness")}</dt>
          <dd className="prewrap">{p.known_conditions || "—"}</dd>
          <dt>{t("patients.past_history2", "Past medical & surgical history")}</dt>
          <dd className="prewrap">{p.past_history || "—"}</dd>
          <dt>{t("patients.current_medications", "Current medications")}</dt>
          <dd className="prewrap">{p.current_medications || "—"}</dd>
        </dl>
        {!!p.allergies?.length && (
          <table className="data" style={{ marginTop: 16 }}>
            <thead>
              <tr>
                <th>{t("patients.allergy", "Allergy")}</th>
                <th>{t("patients.reaction", "Reaction")}</th>
                <th>{t("patients.severity", "Severity")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {p.allergies.map((a) => (
                <tr key={a.id} className={a.is_active ? "" : "muted"}>
                  <td>
                    <strong>{a.substance}</strong>
                    {!a.is_active && (
                      <div className="small">
                        {t("patients.removed", "Removed")}: {a.inactive_reason}
                      </div>
                    )}
                  </td>
                  <td>{a.reaction || "—"}</td>
                  <td>{a.severity}</td>
                  <td className="num">
                    {a.is_active && can("patients.update") && (
                      <button className="btn btn-sm btn-ghost" onClick={() => setRemoving(a.id)}>
                        {t("patients.remove", "Remove")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
      <ReasonDialog
        open={removing !== null}
        title={t("patients.remove_allergy", "Remove allergy")}
        label={t("patients.remove_reason", "Why is this allergy no longer valid?")}
        confirmLabel={t("patients.remove", "Remove")}
        busy={remove.isPending}
        error={remove.error}
        onClose={() => setRemoving(null)}
        onConfirm={(reason) => removing && remove.mutate({ id: removing, reason })}
        danger
      />
    </div>
  );
}

function AllergyForm({ patientId, onDone }: { patientId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const [f, setF] = useState({ substance: "", reaction: "", severity: "moderate" });
  const save = useAction(() => api.post(`/patients/${patientId}/allergies/`, f), [], onDone);
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined);
      }}
    >
      <ErrorBanner error={save.error} />
      <Field label={t("patients.allergy", "Substance")} id="a-sub">
        <input id="a-sub" value={f.substance} onChange={(e) => setF({ ...f, substance: e.target.value })} autoFocus />
      </Field>
      <Field label={t("patients.reaction", "Reaction")} id="a-re">
        <input id="a-re" value={f.reaction} onChange={(e) => setF({ ...f, reaction: e.target.value })} />
      </Field>
      <Field label={t("patients.severity", "Severity")} id="a-sev">
        <select id="a-sev" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })}>
          <option value="mild">Mild</option>
          <option value="moderate">Moderate</option>
          <option value="severe">Severe</option>
        </select>
      </Field>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!f.substance || save.isPending}>
          <Plus size={16} /> {t("patients.add_allergy", "Add allergy")}
        </button>
      </div>
    </form>
  );
}

export function WalkInForm({ patient, onDone }: { patient: PatientBrief; onDone: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { moduleOn } = useAuth();
  const labOn = moduleOn("laboratory");
  const [kind, setKind] = useState<"consultation" | "lab_only">("consultation");
  const [doctor, setDoctor] = useState("");
  const [priority, setPriority] = useState("routine");
  const save = useAction(
    () => api.post<Visit>("/visits/", { patient_id: patient.id, doctor_id: doctor || null, priority }),
    [["visits"]],
    () => {
      onDone();
      navigate("/queue");
    },
  );
  return (
    <div className="stack-sm">
      {labOn && (
        <Segmented
          label={t("queue.visit_type", "Visit type")}
          value={kind}
          onChange={setKind}
          options={[
            { key: "consultation", label: t("queue.kind_consult", "See a doctor") },
            { key: "lab_only", label: t("queue.kind_lab", "Laboratory only") },
          ]}
        />
      )}
      {labOn && kind === "lab_only" ? (
        <LabOnlyForm patient={patient} onDone={onDone} />
      ) : (
        <form
          className="stack-sm"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(undefined);
          }}
        >
          <p>
            {t("queue.walk_in_for", "Add {{name}} to today's waiting list as a walk-in.", { name: patient.full_name })}
          </p>
          <ErrorBanner error={save.error} />
          <Field label={t("queue.doctor", "Doctor")} id="w-doc">
            <DoctorSelect
              id="w-doc"
              value={doctor}
              onChange={setDoctor}
              allowNone
              noneLabel={t("queue.first_available", "First available doctor")}
            />
          </Field>
          <Field label={t("queue.priority", "Priority")} id="w-pri">
            <select id="w-pri" value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="routine">Routine</option>
              <option value="urgent">Urgent</option>
              <option value="emergency">Emergency</option>
            </select>
          </Field>
          <div className="form-actions">
            <button className="btn btn-primary" disabled={save.isPending}>
              {t("queue.add", "Add to waiting list")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

/** A patient who came only for tests another clinician requested on paper. */
function LabOnlyForm({ patient, onDone }: { patient: PatientBrief; onDone: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [f, setF] = useState({ requested_by: "", requesting_facility: "", priority: "routine", clinical_notes: "" });
  const save = useAction(
    () => api.post("/lab/walk-in/", { patient_id: patient.id, test_ids: [...selected], ...f }),
    [["visits"], ["lab"]],
    () => {
      onDone();
      navigate("/queue?tab=done");
    },
    t("queue.lab_only_toast", "Sent to the laboratory"),
  );
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined);
      }}
    >
      <p className="small muted">
        {t(
          "queue.lab_only_help",
          "{{name}} goes straight to the laboratory and the cashier, without triage or a doctor here. Copy the request exactly as written.",
          { name: patient.full_name },
        )}
      </p>
      <ErrorBanner error={save.error} />
      <div className="form-grid">
        <Field
          label={t("lab.requested_by", "Requested by (clinician)")}
          id="lw-by"
          error={fieldErrors(save.error, "requested_by")}
        >
          <input
            id="lw-by"
            value={f.requested_by}
            onChange={(e) => setF({ ...f, requested_by: e.target.value })}
            placeholder={t("lab.requested_by_ph", "e.g. Dr. Abebe Kebede")}
          />
        </Field>
        <Field label={t("lab.requesting_facility", "Facility")} id="lw-fac">
          <input
            id="lw-fac"
            value={f.requesting_facility}
            onChange={(e) => setF({ ...f, requesting_facility: e.target.value })}
          />
        </Field>
        <Field label={t("queue.priority", "Priority")} id="lw-p">
          <select id="lw-p" value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}>
            <option value="routine">Routine</option>
            <option value="urgent">Urgent</option>
          </select>
        </Field>
        <Field label={t("lab.clinical_notes", "Clinical notes for the lab")} id="lw-n">
          <input id="lw-n" value={f.clinical_notes} onChange={(e) => setF({ ...f, clinical_notes: e.target.value })} />
        </Field>
      </div>
      <LabTestChecklist selected={selected} onToggle={toggle} />
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!selected.size || !f.requested_by.trim() || save.isPending}>
          {t("queue.send_lab_n", "Send to laboratory ({{n}} test(s))", { n: selected.size })}
        </button>
      </div>
    </form>
  );
}

function MergeForm({ keep, onDone }: { keep: Patient; onDone: () => void }) {
  const { t } = useTranslation();
  const [dupBrief, setDupBrief] = useState<PatientBrief | null>(null);
  const dup = useGet<Patient>(["patient", dupBrief?.id], dupBrief ? `/patients/${dupBrief.id}/` : null);
  const [reason, setReason] = useState("");
  const [checked, setChecked] = useState(false);
  const merge = useAction(
    () => api.post(`/patients/${keep.id}/merge/`, { duplicate_id: dupBrief!.id, reason }),
    [["patient"], ["patients"], ["visits"]],
    onDone,
    t("patients.merged_toast", "Records merged"),
  );
  const rows: [string, (p: Patient) => string][] = [
    ["MRN", (p) => p.mrn],
    [t("patients.name", "Name"), (p) => p.full_name],
    [t("patients.sex", "Sex"), (p) => p.sex],
    [t("patients.born", "Born"), (p) => `${p.birth_date ?? "—"}${p.birth_date_estimated ? " (est.)" : ""}`],
    [t("patients.phone", "Phone"), (p) => [p.phone, p.alt_phone].filter(Boolean).join(", ") || "—"],
    [
      t("patients.address", "Address"),
      (p) => [p.kebele && `Kebele ${p.kebele}`, p.subcity_woreda, p.city].filter(Boolean).join(", ") || "—",
    ],
    [t("patients.national_id", "National ID"), (p) => p.national_id || "—"],
    [t("patients.registered", "Registered"), (p) => formatDateTime(p.created_at)],
  ];
  const d = dup.data;
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        merge.mutate(undefined);
      }}
    >
      <Banner tone="info">
        {t(
          "patients.merge_help",
          "Visits, notes, results, prescriptions, invoices and allergies on the duplicate move to this record. The duplicate keeps its MRN, becomes inactive and points here. This cannot be undone from the screen.",
        )}
      </Banner>
      <ErrorBanner error={merge.error} />
      {!dupBrief ? (
        <PatientPicker value={null} onChange={(v) => v && v.id !== keep.id && setDupBrief(v)} autoFocus />
      ) : (
        <>
          {!d ? (
            <Loading />
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th />
                  <th>{t("patients.keep", "Keep")}</th>
                  <th>{t("patients.duplicate", "Duplicate (retired)")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(([label, f]) => (
                  <tr key={label}>
                    <td className="subtle">{label}</td>
                    <td>
                      <strong>{f(keep)}</strong>
                    </td>
                    <td className={f(keep) !== f(d) ? "flag-H" : ""}>{f(d)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              setDupBrief(null);
              setChecked(false);
            }}
          >
            {t("patients.choose_other", "Choose another record")}
          </button>
          <Field label={t("patients.merge_reason", "Why are these the same person?")} id="mg-r">
            <input
              id="mg-r"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t("patients.merge_ph", "e.g. registered twice; same phone and national ID")}
            />
          </Field>
          <label className="check">
            <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
            <span>
              {t(
                "patients.merge_confirm",
                "I have checked with the patient or their documents that both records are the same person.",
              )}
            </span>
          </label>
          <div className="form-actions">
            <button className="btn btn-danger" disabled={!d || !reason.trim() || !checked || merge.isPending}>
              {t("patients.merge_go", "Merge into {{mrn}}", { mrn: keep.mrn })}
            </button>
          </div>
        </>
      )}
    </form>
  );
}

export function useRegisterParam() {
  const [params] = useSearchParams();
  const [open, setOpen] = useState(params.get("register") === "1");
  useEffect(() => setOpen(params.get("register") === "1"), [params]);
  return open;
}

// ---------------------------------------------------------------------------- record status
type TFn = (key: string, fallback: string, opts?: Record<string, unknown>) => string;

export function inactiveLabel(kind: Patient["inactive_kind"], t: TFn): string {
  if (kind === "deceased") return t("patients.kind_deceased", "deceased");
  if (kind === "moved") return t("patients.kind_moved", "moved away or transferred care");
  return t("patients.kind_other", "other reason");
}

export function PatientStatusBadge({
  patient,
}: {
  patient: Pick<Patient, "is_active" | "inactive_kind" | "date_of_death">;
}) {
  const { t } = useTranslation();
  if (patient.is_active !== false) return null;
  return patient.inactive_kind === "deceased" ? (
    <span className="badge badge-danger">
      {t("patients.badge_deceased", "Deceased")}
      {patient.date_of_death ? ` ${patient.date_of_death}` : ""}
    </span>
  ) : (
    <span className="badge">{t("patients.badge_inactive", "Inactive")}</span>
  );
}

function DeactivateForm({ patient, onDone }: { patient: Patient; onDone: () => void }) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<"moved" | "deceased" | "other">("moved");
  const [note, setNote] = useState("");
  const [died, setDied] = useState(todayIso());
  const [checked, setChecked] = useState(false);
  const save = useAction(
    () =>
      api.post(
        `/patients/${patient.id}/deactivate/`,
        { kind, note, date_of_death: kind === "deceased" ? died : null },
        { ifMatch: patient.row_version },
      ),
    [["patient", patient.id], ["patients"]],
    onDone,
    t("patients.status_saved", "Record status saved"),
  );
  const ready = checked && (kind === "deceased" ? !!died : !!note.trim());
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) save.mutate(undefined);
      }}
    >
      <ErrorBanner error={save.error} onReload={onDone} />
      <p className="muted">
        {t(
          "patients.deactivate_intro",
          "The record and its history are kept. It is hidden from everyday search, nothing new can be added, and future appointments are cancelled. It can be reactivated later.",
        )}
      </p>
      <fieldset className="fieldset">
        <legend>{t("patients.why_inactive", "Why")}</legend>
        {(["moved", "deceased", "other"] as const).map((k) => (
          <label key={k} className="check">
            <input type="radio" name="kind" checked={kind === k} onChange={() => setKind(k)} />
            {k === "moved"
              ? t("patients.kind_moved_long", "Moved away or transferred care elsewhere")
              : k === "deceased"
                ? t("patients.kind_deceased_long", "Deceased")
                : t("patients.kind_other_long", "Other reason")}
          </label>
        ))}
      </fieldset>
      {kind === "deceased" && (
        <Field
          label={t("patients.date_of_death", "Date of death")}
          id="pd-d"
          error={fieldErrors(save.error, "date_of_death")}
          hint={died ? undefined : t("patients.date_required", "Required")}
        >
          <input
            id="pd-d"
            type="date"
            max={todayIso()}
            min={patient.birth_date}
            value={died}
            onChange={(e) => setDied(e.target.value)}
            required
          />
        </Field>
      )}
      <Field
        label={
          kind === "deceased"
            ? t("patients.death_note", "Source of information (optional)")
            : t("patients.inactive_note", "Reason")
        }
        id="pd-n"
        error={fieldErrors(save.error, "note")}
      >
        <input
          id="pd-n"
          value={note}
          maxLength={255}
          onChange={(e) => setNote(e.target.value)}
          placeholder={
            kind === "moved"
              ? t("patients.note_moved_ph", "e.g. moved to Dire Dawa")
              : kind === "deceased"
                ? t("patients.note_death_ph", "e.g. informed by family by phone")
                : ""
          }
        />
      </Field>
      <label className="check">
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
        {t("patients.status_confirm", "I have checked that this is the right patient: {{name}}, MRN {{mrn}}.", {
          name: patient.full_name,
          mrn: patient.mrn,
        })}
      </label>
      <div className="form-actions">
        <button
          className={`btn ${kind === "deceased" ? "btn-danger" : "btn-primary"}`}
          disabled={!ready || save.isPending}
        >
          {kind === "deceased"
            ? t("patients.mark_deceased", "Record as deceased")
            : t("patients.mark_inactive", "Mark inactive")}
        </button>
      </div>
    </form>
  );
}
