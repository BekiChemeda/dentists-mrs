/**
 * Treatment plans: a course of treatment across visits. An estimate is never an invoice; an item is completed only
 * by a signed procedure record. After a plan is presented, every change asks for a reason and is kept as a revision.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Printer } from "lucide-react";
import { api } from "../../api/client";
import { useGet } from "../../api/hooks";
import type { Appointment, Paginated } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import {
  Banner,
  Empty,
  ErrorBanner,
  Field,
  Loading,
  Modal,
  Panel,
  ReasonDialog,
  money,
  printElement,
  toast,
} from "../../ui";
import { formatDateTime } from "../../lib/format";
import { REGION_NAMES, allowedSurfaces, orderSurfaces } from "../../lib/teeth";
import { ClinicHeader } from "../common";
import { DentalStatus, useDentalCatalog } from "./common";
import type { DentalDiagnosis, DentalProcedure, PlanItem, TreatmentPlan } from "./types";

function usePlanAction(planId: string) {
  const qc = useQueryClient();
  return (onDone?: () => void) => ({
    onSuccess: (data: TreatmentPlan) => {
      qc.setQueryData(["dental", "plan", planId], data);
      void qc.invalidateQueries({ queryKey: ["dental", "plans"] });
      void qc.invalidateQueries({ queryKey: ["dental", "summary"] });
      toast("Saved");
      onDone?.();
    },
  });
}

export function PlanList({
  patientId,
  encounterId,
  diagnoses = [],
}: {
  patientId: string;
  encounterId?: string;
  diagnoses?: DentalDiagnosis[];
}) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const plans = useGet<TreatmentPlan[]>(["dental", "plans", patientId], `/dental/patients/${patientId}/plans/`);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [reason, setReason] = useState("");
  const [dx, setDx] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () =>
      api.post<TreatmentPlan>(`/dental/patients/${patientId}/plans/`, {
        title,
        clinical_reason: reason,
        encounter_id: encounterId ?? null,
        diagnosis_ids: dx,
      }),
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ["dental", "plans", patientId] });
      setCreating(false);
      setTitle("");
      setReason("");
      setDx([]);
      setOpen(p.id);
    },
  });
  if (plans.isLoading) return <Loading />;
  const list = plans.data ?? [];
  const shown = open ?? list.find((p) => !["completed", "cancelled", "expired", "declined"].includes(p.status))?.id;
  return (
    <div className="stack">
      <ErrorBanner error={plans.error} />
      <div className="row-between">
        <div className="row">
          {list.map((p) => (
            <button
              key={p.id}
              className="btn btn-sm plan-pick"
              aria-pressed={shown === p.id}
              onClick={() => setOpen(p.id)}
            >
              {p.number} · {p.title} <DentalStatus value={p.status} />
            </button>
          ))}
        </div>
        {can("dental.plan.manage") && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden /> {t("dental.new_plan", "New treatment plan")}
          </button>
        )}
      </div>
      {list.length === 0 && <Empty>{t("dental.no_plans", "No treatment plans yet.")}</Empty>}
      {list.length > 0 && !shown && (
        <p className="small muted">
          {t("dental.pick_plan", "All plans are finished. Choose one above to see it, or start a new plan.")}
        </p>
      )}
      {shown && <PlanDetail key={shown} planId={shown} encounterId={encounterId} diagnoses={diagnoses} />}
      <Modal open={creating} title={t("dental.new_plan", "New treatment plan")} onClose={() => setCreating(false)}>
        <form
          className="stack-sm"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <ErrorBanner error={create.error} />
          <Field label={t("dental.plan_title", "Title")} id="f-title" error={create.error}>
            <input id="f-title" value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={150} />
          </Field>
          <Field label={t("dental.clinical_reason", "Clinical reason")} id="f-clinical_reason">
            <textarea id="f-clinical_reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          {diagnoses.length > 0 && (
            <fieldset className="fieldset">
              <legend>{t("dental.linked_diagnoses", "Diagnoses this plan treats")}</legend>
              {diagnoses.map((d) => (
                <label key={d.id} className="check">
                  <input
                    type="checkbox"
                    checked={dx.includes(d.id)}
                    onChange={(e) =>
                      setDx((cur) => (e.target.checked ? [...cur, d.id] : cur.filter((x) => x !== d.id)))
                    }
                  />{" "}
                  {d.code} {d.term_text} ({d.location.label})
                </label>
              ))}
            </fieldset>
          )}
          <div className="form-actions">
            <button type="button" className="btn" onClick={() => setCreating(false)}>
              {t("common.cancel")}
            </button>
            <button className="btn btn-primary" disabled={create.isPending}>
              {t("common.create", "Create")}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function LocationInputs({
  procedure,
  value,
  onChange,
}: {
  procedure: DentalProcedure | undefined;
  value: { scope: string; tooth: string; surfaces: string[]; region: string };
  onChange: (v: { scope: string; tooth: string; surfaces: string[]; region: string }) => void;
}) {
  const { t } = useTranslation();
  if (!procedure) return null;
  const scopes =
    procedure.tooth_requirement === "required"
      ? procedure.surfaces_allowed
        ? ["tooth", "surfaces"]
        : ["tooth"]
      : procedure.tooth_requirement === "none"
        ? ["mouth", "region"]
        : procedure.surfaces_allowed
          ? ["tooth", "surfaces", "region", "mouth"]
          : ["tooth", "region", "mouth"];
  const scope = scopes.includes(value.scope) ? value.scope : scopes[0];
  const tooth = Number(value.tooth);
  return (
    <div className="form-grid">
      <Field label={t("dental.where", "Where")} id="f-scope">
        <select id="f-scope" value={scope} onChange={(e) => onChange({ ...value, scope: e.target.value })}>
          {scopes.map((s) => (
            <option key={s} value={s}>
              {{ tooth: "Whole tooth", surfaces: "Tooth surfaces", region: "Region", mouth: "Whole mouth" }[s]}
            </option>
          ))}
        </select>
      </Field>
      {(scope === "tooth" || scope === "surfaces") && (
        <Field label={t("dental.tooth_fdi", "Tooth number")} id="f-tooth">
          <input
            id="f-tooth"
            inputMode="numeric"
            value={value.tooth}
            onChange={(e) => onChange({ ...value, tooth: e.target.value, surfaces: [] })}
            required
            className="narrow-field"
          />
        </Field>
      )}
      {scope === "surfaces" && tooth > 10 && (
        <div className="field">
          <span>{t("dental.surfaces", "Surfaces")}</span>
          <div className="row">
            {allowedSurfaces(tooth).map((s) => (
              <button
                key={s}
                type="button"
                className="btn btn-sm surface-toggle"
                aria-pressed={value.surfaces.includes(s)}
                onClick={() =>
                  onChange({
                    ...value,
                    surfaces: value.surfaces.includes(s)
                      ? value.surfaces.filter((x) => x !== s)
                      : [...value.surfaces, s],
                  })
                }
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}
      {scope === "region" && (
        <Field label={t("dental.region", "Region")} id="f-region">
          <select id="f-region" value={value.region} onChange={(e) => onChange({ ...value, region: e.target.value })}>
            {Object.entries(REGION_NAMES).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
      )}
    </div>
  );
}

export function locationBody(
  v: { scope: string; tooth: string; surfaces: string[]; region: string },
  p?: DentalProcedure,
) {
  const scopes =
    p?.tooth_requirement === "none"
      ? ["mouth", "region"]
      : p?.tooth_requirement === "required"
        ? ["tooth", "surfaces"]
        : null;
  const scope = scopes && !scopes.includes(v.scope) ? scopes[0] : v.scope;
  return {
    scope,
    tooth: scope === "tooth" || scope === "surfaces" ? Number(v.tooth) || null : null,
    surfaces: scope === "surfaces" ? orderSurfaces(v.surfaces.join("")) : "",
    region: scope === "region" ? v.region : "",
  };
}

export { LocationInputs };

function AddItemForm({
  plan,
  diagnoses,
  onDone,
}: {
  plan: TreatmentPlan;
  diagnoses: DentalDiagnosis[];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const catalog = useDentalCatalog();
  const [procId, setProcId] = useState("");
  const [loc, setLoc] = useState({ scope: "tooth", tooth: "", surfaces: [] as string[], region: "q1" });
  const [fee, setFee] = useState("");
  const [dxId, setDxId] = useState("");
  const [priority, setPriority] = useState("routine");
  const [notes, setNotes] = useState("");
  const [reason, setReason] = useState("");
  const after = usePlanAction(plan.id);
  const proc = catalog.data?.procedures.find((p) => p.id === procId);
  const add = useMutation({
    mutationFn: () =>
      api.post<TreatmentPlan>(`/dental/plans/${plan.id}/items/`, {
        procedure_id: procId,
        ...locationBody(loc, proc),
        estimated_fee: fee === "" ? null : fee,
        diagnosis_id: dxId || null,
        priority,
        notes,
        reason,
      }),
    ...after(onDone),
  });
  const categories = catalog.data?.procedure_categories ?? [];
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        add.mutate();
      }}
    >
      <ErrorBanner error={add.error} />
      <Field label={t("dental.procedure", "Procedure")} id="f-procedure_id" error={add.error}>
        <select
          id="f-procedure_id"
          value={procId}
          onChange={(e) => {
            setProcId(e.target.value);
            setFee("");
          }}
          required
        >
          <option value="">—</option>
          {categories.map(([key, label]) => (
            <optgroup key={key} label={label}>
              {(catalog.data?.procedures ?? [])
                .filter((p) => p.category === key)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} — {money(p.price)} ETB
                  </option>
                ))}
            </optgroup>
          ))}
        </select>
      </Field>
      <LocationInputs procedure={proc} value={loc} onChange={setLoc} />
      <div className="form-grid">
        <Field
          label={t("dental.estimate", "Estimated fee (ETB)")}
          id="f-estimated_fee"
          hint={proc ? `Catalogue: ${money(proc.price)}` : undefined}
        >
          <input
            id="f-estimated_fee"
            inputMode="decimal"
            value={fee}
            onChange={(e) => setFee(e.target.value)}
            placeholder={proc?.price}
          />
        </Field>
        <Field label={t("dental.priority", "Priority")} id="f-priority">
          <select id="f-priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
            {(catalog.data?.plan_item_priorities ?? []).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {diagnoses.length > 0 && (
        <Field label={t("dental.diagnosis", "Diagnosis")} id="f-diagnosis_id">
          <select id="f-diagnosis_id" value={dxId} onChange={(e) => setDxId(e.target.value)}>
            <option value="">—</option>
            {diagnoses.map((d) => (
              <option key={d.id} value={d.id}>
                {d.code} {d.term_text} ({d.location.label})
              </option>
            ))}
          </select>
        </Field>
      )}
      <Field label={t("dental.notes", "Notes")} id="f-notes">
        <input id="f-notes" value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={255} />
      </Field>
      {plan.revision > 0 && (
        <Field
          label={t("dental.change_reason", "Reason for the change (the plan was already presented)")}
          id="f-reason"
          error={add.error}
        >
          <input id="f-reason" value={reason} onChange={(e) => setReason(e.target.value)} required />
        </Field>
      )}
      {proc && (
        <Banner tone="info">
          {t("dental.will_add", "Will add: {{name}}, {{fee}} ETB", {
            name: proc.name,
            fee: money(fee === "" ? proc.price : fee),
          })}
        </Banner>
      )}
      <div className="form-actions">
        <button type="button" className="btn" onClick={onDone}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={add.isPending || !procId}>
          {t("dental.add_item", "Add to plan")}
        </button>
      </div>
    </form>
  );
}

function DecisionForm({ plan, onDone }: { plan: TreatmentPlan; onDone: () => void }) {
  const { t } = useTranslation();
  const open = plan.items.filter((i) => ["proposed", "deferred", "declined", "accepted"].includes(i.status));
  const [choice, setChoice] = useState<Record<string, string>>(
    Object.fromEntries(open.map((i) => [i.id, i.status === "proposed" ? "accepted" : i.status])),
  );
  const [note, setNote] = useState("");
  const after = usePlanAction(plan.id);
  const save = useMutation({
    mutationFn: () => api.post<TreatmentPlan>(`/dental/plans/${plan.id}/decision/`, { decisions: choice, note }),
    ...after(onDone),
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
        {t(
          "dental.decision_hint",
          "Record what the patient decided after the discussion. This is not a consent form: use the clinic's consent process for treatment that needs one.",
        )}
      </Banner>
      <ErrorBanner error={save.error} />
      {open.map((i) => (
        <div key={i.id} className="row-between">
          <span>
            {i.procedure.name} <span className="mono">{i.location.label}</span> — {money(i.estimated_fee)} ETB
          </span>
          <select
            aria-label={`${i.procedure.name} decision`}
            value={choice[i.id]}
            onChange={(e) => setChoice((c) => ({ ...c, [i.id]: e.target.value }))}
          >
            <option value="accepted">{t("dental.status_accepted", "Accepted")}</option>
            <option value="deferred">{t("dental.status_deferred", "Deferred")}</option>
            <option value="declined">{t("dental.status_declined", "Declined")}</option>
          </select>
        </div>
      ))}
      <Field label={t("dental.decision_note", "Note of the discussion")} id="f-note">
        <textarea id="f-note" value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onDone}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={save.isPending}>
          {t("dental.record_decision", "Record decision")}
        </button>
      </div>
    </form>
  );
}

function LinkAppointment({ plan, item, onDone }: { plan: TreatmentPlan; item: PlanItem; onDone: () => void }) {
  const { t } = useTranslation();
  const appts = useGet<Paginated<Appointment>>(
    ["appointments", "patient", plan.patient.id],
    `/appointments/?patient=${plan.patient.id}&date_from=${new Date().toISOString().slice(0, 10)}`,
  );
  const after = usePlanAction(plan.id);
  const link = useMutation({
    mutationFn: (appointmentId: string) =>
      api.post<TreatmentPlan>(`/dental/plan-items/${item.id}/appointments/`, { appointment_id: appointmentId }),
    ...after(onDone),
  });
  const list = (appts.data?.results ?? []).filter((a) => ["scheduled", "confirmed"].includes(a.status));
  return (
    <div className="stack-sm">
      <p className="muted small">
        {t(
          "dental.link_hint",
          "Booking an appointment does not complete the item: only the signed procedure record does.",
        )}
      </p>
      <ErrorBanner error={link.error} />
      {list.length === 0 ? (
        <p>{t("dental.no_upcoming", "No upcoming appointments for this patient. Book one in Appointments first.")}</p>
      ) : (
        list.map((a) => (
          <div key={a.id} className="row-between">
            <span>
              {formatDateTime(a.scheduled_at)} · {a.doctor.full_name}
            </span>
            <button className="btn btn-sm" onClick={() => link.mutate(a.id)} disabled={link.isPending}>
              {t("dental.link", "Plan for this appointment")}
            </button>
          </div>
        ))
      )}
    </div>
  );
}

export function PlanDetail({
  planId,
  diagnoses = [],
}: {
  planId: string;
  encounterId?: string;
  diagnoses?: DentalDiagnosis[];
}) {
  const { t } = useTranslation();
  const priorities = useDentalCatalog().data?.plan_item_priorities ?? [];
  const { can } = useAuth();
  const plan = useGet<TreatmentPlan>(["dental", "plan", planId], `/dental/plans/${planId}/`);
  const revisions = useGet<
    { id: string; revision: number; reason: string; created_by: { full_name: string }; created_at: string }[]
  >(["dental", "plan-revisions", planId, plan.data?.revision ?? 0], `/dental/plans/${planId}/revisions/`);
  const [adding, setAdding] = useState(false);
  const [deciding, setDeciding] = useState(false);
  const [linking, setLinking] = useState<PlanItem | null>(null);
  const [cancelItem, setCancelItem] = useState<PlanItem | null>(null);
  const [feeItem, setFeeItem] = useState<PlanItem | null>(null);
  const [newFee, setNewFee] = useState("");
  const [closing, setClosing] = useState<"cancel" | "expire" | null>(null);
  const after = usePlanAction(planId);
  const present = useMutation({
    mutationFn: () => api.post<TreatmentPlan>(`/dental/plans/${planId}/present/`),
    ...after(),
  });
  const cancel = useMutation({
    mutationFn: (v: { item: PlanItem; reason: string }) =>
      api.post<TreatmentPlan>(`/dental/plan-items/${v.item.id}/${plan.data?.revision ? "cancel" : "remove"}/`, {
        reason: v.reason,
      }),
    ...after(() => setCancelItem(null)),
  });
  const refee = useMutation({
    mutationFn: (v: { item: PlanItem; reason: string }) =>
      api.patch<TreatmentPlan>(`/dental/plan-items/${v.item.id}/`, { estimated_fee: newFee, reason: v.reason }),
    ...after(() => setFeeItem(null)),
  });
  const close = useMutation({
    mutationFn: (v: { action: "cancel" | "expire"; reason: string }) =>
      api.post<TreatmentPlan>(`/dental/plans/${planId}/${v.action}/`, { reason: v.reason }),
    ...after(() => setClosing(null)),
  });
  if (plan.isLoading || !plan.data) return <Loading />;
  const p = plan.data;
  const manage = can("dental.plan.manage") && !["completed", "cancelled", "expired"].includes(p.status);
  const printId = `plan-print-${p.id}`;
  const hasProposed = p.items.some((i) => i.status === "proposed");
  return (
    <Panel
      title={
        <h2>
          {p.number} · {p.title} <DentalStatus value={p.status} />
        </h2>
      }
      actions={
        <>
          <button
            className="btn btn-sm"
            onClick={() => printElement(printId, `${t("dental.estimate_doc", "Treatment estimate")} ${p.number}`)}
          >
            <Printer size={15} aria-hidden /> {t("dental.print_estimate", "Print estimate")}
          </button>
          {manage && (
            <>
              <button className="btn btn-sm" onClick={() => setAdding(true)}>
                <Plus size={15} aria-hidden /> {t("dental.add_item", "Add to plan")}
              </button>
              {["draft", "deferred", "declined", "presented"].includes(p.status) && (
                <button
                  className="btn btn-sm"
                  onClick={() => present.mutate()}
                  disabled={present.isPending || !p.items.length}
                >
                  {p.revision ? t("dental.present_again", "Present again") : t("dental.present", "Present to patient")}
                </button>
              )}
              {p.status !== "draft" &&
                (hasProposed || p.items.some((i) => ["deferred", "declined"].includes(i.status))) && (
                  <button className="btn btn-sm btn-primary" onClick={() => setDeciding(true)}>
                    {t("dental.record_decision", "Record decision")}
                  </button>
                )}
              <button className="btn btn-sm btn-ghost" onClick={() => setClosing("cancel")}>
                {t("dental.cancel_plan", "Cancel plan…")}
              </button>
              {["presented", "deferred"].includes(p.status) && (
                <button className="btn btn-sm btn-ghost" onClick={() => setClosing("expire")}>
                  {t("dental.expire_plan", "Mark expired…")}
                </button>
              )}
            </>
          )}
        </>
      }
    >
      <ErrorBanner error={present.error} />
      <div id={printId} className="stack-sm">
        <div className="print-only">
          <ClinicHeader title={t("dental.estimate_doc", "Treatment estimate")} number={p.number} />
          <p>
            <strong>{p.patient.full_name}</strong> · MRN {p.patient.mrn} ·{" "}
            {formatDateTime(p.presented_at ?? p.created_at)} · {p.created_by.full_name}
          </p>
        </div>
        {p.clinical_reason && <p className="prewrap">{p.clinical_reason}</p>}
        {p.diagnoses.length > 0 && (
          <p className="small">
            {t("dental.for_diagnoses", "For")}:{" "}
            {p.diagnoses.map((d) => `${d.code} ${d.term} (${d.location})`).join("; ")}
          </p>
        )}
        <table className="data">
          <thead>
            <tr>
              <th>#</th>
              <th>{t("dental.procedure", "Procedure")}</th>
              <th>{t("dental.tooth", "Tooth")}</th>
              <th>{t("dental.priority", "Priority")}</th>
              <th>{t("dental.sessions", "Sessions")}</th>
              <th className="num">{t("dental.estimate", "Estimate (ETB)")}</th>
              <th>{t("users.status")}</th>
              <th className="no-print" />
            </tr>
          </thead>
          <tbody>
            {p.items.map((i) => (
              <tr key={i.id} className={i.status === "cancelled" ? "muted" : ""}>
                <td>{i.sequence}</td>
                <td>
                  {i.procedure.name}
                  {i.notes && <div className="small subtle">{i.notes}</div>}
                  {i.appointments.length > 0 && (
                    <div className="small subtle no-print">
                      {t("dental.planned_for", "Planned for")}:{" "}
                      {i.appointments.map((a) => formatDateTime(a.scheduled_at)).join(", ")}
                    </div>
                  )}
                  {i.cancel_reason && <div className="small subtle">{i.cancel_reason}</div>}
                </td>
                <td className="mono">{i.location.label}</td>
                <td>{priorities.find(([k]) => k === i.priority)?.[1] ?? i.priority}</td>
                <td>
                  {i.sessions_done}/{i.sessions_planned}
                </td>
                <td className="num">{money(i.estimated_fee)}</td>
                <td>
                  <DentalStatus value={i.status} />
                </td>
                <td className="num no-print">
                  {manage && !["completed", "cancelled"].includes(i.status) && (
                    <div className="row">
                      {["accepted", "in_progress"].includes(i.status) && (
                        <button className="btn btn-sm btn-ghost" onClick={() => setLinking(i)}>
                          {t("dental.book_appointment", "Book appointment")}
                        </button>
                      )}
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => {
                          setFeeItem(i);
                          setNewFee(i.estimated_fee);
                        }}
                      >
                        {t("dental.change_fee", "Change fee")}
                      </button>
                      {i.sessions_done === 0 && (
                        <button className="btn btn-sm btn-ghost" onClick={() => setCancelItem(i)}>
                          {p.revision ? t("common.cancel") : t("common.remove", "Remove")}
                        </button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={5}>{t("dental.estimated_total", "Estimated total (agreed items, or all proposed)")}</th>
              <th className="num">{money(p.estimated_total)}</th>
              <th colSpan={2} />
            </tr>
          </tfoot>
        </table>
        <p className="small muted">
          {t(
            "dental.estimate_not_invoice",
            "This is an estimate, not an invoice. Charges are made only for treatment actually carried out.",
          )}
        </p>
        {p.decision_note && (
          <p className="small">
            <strong>{t("dental.decision_note", "Note of the discussion")}:</strong>{" "}
            <span className="prewrap">{p.decision_note}</span>
          </p>
        )}
      </div>
      {(revisions.data?.length ?? 0) > 0 && (
        <details className="no-print">
          <summary>{t("dental.revisions", "Revisions ({{n}})", { n: revisions.data?.length })}</summary>
          <ul className="small">
            {revisions.data?.map((r) => (
              <li key={r.id}>
                {t("dental.revision", "Revision")} {r.revision}: {r.reason} — {r.created_by.full_name},{" "}
                {formatDateTime(r.created_at)}
              </li>
            ))}
          </ul>
        </details>
      )}
      <Modal open={adding} title={t("dental.add_item", "Add to plan")} onClose={() => setAdding(false)} wide>
        <AddItemForm plan={p} diagnoses={diagnoses} onDone={() => setAdding(false)} />
      </Modal>
      <Modal open={deciding} title={t("dental.record_decision", "Record decision")} onClose={() => setDeciding(false)}>
        <DecisionForm plan={p} onDone={() => setDeciding(false)} />
      </Modal>
      <Modal open={!!linking} title={t("dental.schedule", "Plan for an appointment")} onClose={() => setLinking(null)}>
        {linking && <LinkAppointment plan={p} item={linking} onDone={() => setLinking(null)} />}
      </Modal>
      <ReasonDialog
        open={!!cancelItem}
        title={t("dental.cancel_item", "Take this item off the plan")}
        label={t("dental.reason", "Reason")}
        confirmLabel={t("common.confirm", "Confirm")}
        onClose={() => setCancelItem(null)}
        onConfirm={(reason) => cancelItem && cancel.mutate({ item: cancelItem, reason })}
        busy={cancel.isPending}
        error={cancel.error}
      />
      <Modal open={!!feeItem} title={t("dental.revise_fee", "Revise the estimate")} onClose={() => setFeeItem(null)}>
        <FeeForm
          value={newFee}
          onChange={setNewFee}
          needsReason={p.revision > 0}
          busy={refee.isPending}
          error={refee.error}
          onCancel={() => setFeeItem(null)}
          onSave={(reason) => feeItem && refee.mutate({ item: feeItem, reason })}
        />
      </Modal>
      <ReasonDialog
        open={!!closing}
        title={
          closing === "expire"
            ? t("dental.expire_plan", "Mark the plan expired")
            : t("dental.cancel_plan", "Cancel the plan")
        }
        label={t("dental.reason", "Reason")}
        confirmLabel={t("common.confirm", "Confirm")}
        onClose={() => setClosing(null)}
        onConfirm={(reason) => closing && close.mutate({ action: closing, reason })}
        busy={close.isPending}
        error={close.error}
        danger
      />
    </Panel>
  );
}

function FeeForm({
  value,
  onChange,
  needsReason,
  busy,
  error,
  onCancel,
  onSave,
}: {
  value: string;
  onChange: (v: string) => void;
  needsReason: boolean;
  busy: boolean;
  error: unknown;
  onCancel: () => void;
  onSave: (reason: string) => void;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        onSave(reason);
      }}
    >
      <ErrorBanner error={error} />
      <Field label={t("dental.estimate", "Estimated fee (ETB)")} id="f-estimated_fee" error={error}>
        <input
          id="f-estimated_fee"
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required
        />
      </Field>
      {needsReason && (
        <Field label={t("dental.change_reason", "Reason for the change")} id="f-reason" error={error}>
          <input id="f-reason" value={reason} onChange={(e) => setReason(e.target.value)} required />
        </Field>
      )}
      <div className="form-actions">
        <button type="button" className="btn" onClick={onCancel}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={busy}>
          {t("common.save", "Save")}
        </button>
      </div>
    </form>
  );
}
