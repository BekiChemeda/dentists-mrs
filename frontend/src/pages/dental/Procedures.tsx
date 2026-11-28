/**
 * Procedure records: what was actually done. Planned, booked, performed and billed are separate records; signing
 * copies the price, deducts the materials from stock and updates the plan item.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useIsMutating, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Printer } from "lucide-react";
import { api, queryString } from "../../api/client";
import { useGet } from "../../api/hooks";
import type { Paginated, StockItem } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import {
  Banner,
  ErrorBanner,
  Field,
  Loading,
  Modal,
  Panel,
  ReasonDialog,
  money,
  printElement,
  qty,
  toast,
} from "../../ui";
import { formatDateTime } from "../../lib/format";
import { ClinicHeader } from "../common";
import { DentalStatus, PROCEDURE_TEXT_FIELDS, useClinicians, useDentalCatalog } from "./common";
import { LocationInputs, locationBody } from "./Plans";
import type { DentalEncounter, ProcedureRecord, ProcedureRecordBrief, TreatmentPlan } from "./types";
import { useUnsavedGuard } from "../../lib/unsaved";

export function EncounterProcedures({ encounter }: { encounter: DentalEncounter }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const editable = encounter.status === "draft" && !["completed", "cancelled"].includes(encounter.visit_status);
  return (
    <Panel
      title={t("dental.procedures", "Procedures this visit")}
      actions={
        editable &&
        can("dental.procedure.record") && (
          <button className="btn btn-sm btn-primary" onClick={() => setCreating(true)}>
            <Plus size={15} aria-hidden /> {t("dental.record_procedure", "Record a procedure")}
          </button>
        )
      }
    >
      {encounter.procedures.length === 0 ? (
        <p className="muted">{t("dental.no_procedures", "No procedures recorded in this examination.")}</p>
      ) : (
        <ProcedureTable rows={encounter.procedures} onOpen={setOpen} />
      )}
      <Modal
        open={creating}
        title={t("dental.record_procedure", "Record a procedure")}
        onClose={() => setCreating(false)}
        wide
      >
        {creating && (
          <NewProcedureForm
            encounter={encounter}
            onDone={(id) => {
              setCreating(false);
              if (id) setOpen(id);
            }}
          />
        )}
      </Modal>
      <Modal open={!!open} title={t("dental.procedure_record", "Procedure record")} onClose={() => setOpen(null)} wide>
        {open && <ProcedureDetail id={open} onClose={() => setOpen(null)} />}
      </Modal>
    </Panel>
  );
}

export function ProcedureTable({ rows, onOpen }: { rows: ProcedureRecordBrief[]; onOpen: (id: string) => void }) {
  const { t } = useTranslation();
  return (
    <table className="data">
      <thead>
        <tr>
          <th>{t("dental.number", "No.")}</th>
          <th>{t("dental.procedure", "Procedure")}</th>
          <th>{t("dental.tooth", "Tooth")}</th>
          <th>{t("dental.session", "Session")}</th>
          <th>{t("dental.performed_by", "Performed by")}</th>
          <th>{t("users.status")}</th>
          <th className="num">{t("dental.price", "Price")}</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}>
            <td className="mono small">{r.number}</td>
            <td>{r.procedure.name}</td>
            <td className="mono">{r.location.label}</td>
            <td>{r.session_number}</td>
            <td>{r.performed_by.full_name}</td>
            <td>
              <DentalStatus value={r.status} />
            </td>
            <td className="num">{r.price == null ? "—" : money(r.price)}</td>
            <td className="num">
              <button className="btn btn-sm" onClick={() => onOpen(r.id)}>
                {r.status === "draft" ? t("dental.continue_note", "Continue writing") : t("common.view", "View")}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function NewProcedureForm({ encounter, onDone }: { encounter: DentalEncounter; onDone: (id?: string) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { can, user } = useAuth();
  const catalog = useDentalCatalog();
  const clinicians = useClinicians();
  const plans = useGet<TreatmentPlan[]>(
    ["dental", "plans", encounter.patient.id],
    `/dental/patients/${encounter.patient.id}/plans/`,
  );
  const openItems = (plans.data ?? []).flatMap((p) =>
    p.items.filter((i) => ["accepted", "in_progress"].includes(i.status)).map((i) => ({ plan: p, item: i })),
  );
  const [mode, setMode] = useState<"plan" | "catalogue">("plan");
  const [itemId, setItemId] = useState("");
  const [procId, setProcId] = useState("");
  const [loc, setLoc] = useState({ scope: "tooth", tooth: "", surfaces: [] as string[], region: "q1" });
  const [performer, setPerformer] = useState(can("dental.procedure.sign") ? (user?.id ?? "") : encounter.dentist.id);
  const [assistant, setAssistant] = useState("");
  useEffect(() => {
    if (!plans.isLoading && openItems.length === 0) setMode("catalogue");
  }, [plans.isLoading, openItems.length]);
  const proc = catalog.data?.procedures.find((p) => p.id === procId);
  const create = useMutation({
    mutationFn: () =>
      api.post<ProcedureRecord>(`/dental/encounters/${encounter.id}/procedures/`, {
        ...(mode === "plan" ? { plan_item_id: itemId } : { procedure_id: procId, ...locationBody(loc, proc) }),
        performed_by_id: performer || null,
        assisted_by_id: assistant || null,
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["dental", "encounter", encounter.id] });
      onDone(r.id);
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
      <div className="row">
        <label className="check">
          <input
            type="radio"
            checked={mode === "plan"}
            disabled={openItems.length === 0}
            onChange={() => setMode("plan")}
          />{" "}
          {t("dental.from_plan", "From the treatment plan")}
        </label>
        <label className="check">
          <input type="radio" checked={mode === "catalogue"} onChange={() => setMode("catalogue")} />{" "}
          {t("dental.not_planned", "Not planned (e.g. emergency, examination, radiograph)")}
        </label>
      </div>
      {mode === "plan" ? (
        <Field label={t("dental.plan_item", "Plan item")} id="f-plan_item_id">
          <select id="f-plan_item_id" value={itemId} onChange={(e) => setItemId(e.target.value)} required>
            <option value="">—</option>
            {openItems.map(({ plan, item }) => (
              <option key={item.id} value={item.id}>
                {plan.number}: {item.procedure.name} {item.location.label} ({item.sessions_done}/{item.sessions_planned}
                )
              </option>
            ))}
          </select>
        </Field>
      ) : (
        <>
          <Field label={t("dental.procedure", "Procedure")} id="f-procedure_id" error={create.error}>
            <select id="f-procedure_id" value={procId} onChange={(e) => setProcId(e.target.value)} required>
              <option value="">—</option>
              {(catalog.data?.procedure_categories ?? []).map(([key, label]) => (
                <optgroup key={key} label={label}>
                  {(catalog.data?.procedures ?? [])
                    .filter((p) => p.category === key)
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </Field>
          <LocationInputs procedure={proc} value={loc} onChange={setLoc} />
        </>
      )}
      <div className="form-grid">
        <Field label={t("dental.performed_by", "Performed by")} id="f-performed_by_id" error={create.error}>
          <select id="f-performed_by_id" value={performer} onChange={(e) => setPerformer(e.target.value)}>
            {(clinicians.data?.clinicians ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.full_name}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("dental.assisted_by", "Assisted by")} id="f-assisted_by_id">
          <select id="f-assisted_by_id" value={assistant} onChange={(e) => setAssistant(e.target.value)}>
            <option value="">—</option>
            {[...(clinicians.data?.assistants ?? []), ...(clinicians.data?.clinicians ?? [])].map((c) => (
              <option key={c.id} value={c.id}>
                {c.full_name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="form-actions">
        <button type="button" className="btn" onClick={() => onDone()}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={create.isPending}>
          {t("dental.start_record", "Start the record")}
        </button>
      </div>
    </form>
  );
}

function MaterialsEditor({ record, editable }: { record: ProcedureRecord; editable: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [rows, setRows] = useState(
    record.materials.map((m) => ({
      item_id: m.item_id,
      item: m.item,
      unit: m.unit,
      quantity: String(Number(m.quantity)),
    })),
  );
  const [search, setSearch] = useState("");
  const found = useGet<Paginated<StockItem>>(
    ["items", "dental-search", search],
    editable && search.length >= 2
      ? `/inventory/items/${queryString({ q: search, active: "true", page_size: 8 })}`
      : null,
  );
  const save = useMutation({
    mutationKey: ["dental", "materials", record.id],
    mutationFn: () =>
      api.put<ProcedureRecord>(`/dental/procedure-records/${record.id}/materials/`, {
        materials: rows.map((r) => ({ item_id: r.item_id, quantity: r.quantity })),
      }),
    onSuccess: (r) => {
      qc.setQueryData(["dental", "procedure", record.id], r);
      toast(t("dental.materials_saved", "Materials saved"));
    },
  });
  return (
    <fieldset className="fieldset stack-sm">
      <legend>{t("dental.materials", "Materials used")}</legend>
      <p className="small muted">
        {t(
          "dental.materials_hint",
          "Stock is taken (earliest expiry first) only when the record is signed. Instruments are never consumed.",
        )}
      </p>
      <ErrorBanner error={save.error} />
      {rows.length === 0 && <p className="muted small">{t("dental.no_materials", "None listed.")}</p>}
      {rows.map((r, i) => (
        <div key={r.item_id} className="row">
          <span className="grow">{r.item}</span>
          {editable ? (
            <input
              aria-label={`${r.item} quantity`}
              className="narrow-field"
              inputMode="decimal"
              value={r.quantity}
              onChange={(e) => setRows((cur) => cur.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)))}
            />
          ) : (
            <span>{qty(r.quantity)}</span>
          )}
          <span className="small subtle">{r.unit}</span>
          {editable && (
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={() => setRows((cur) => cur.filter((_, j) => j !== i))}
            >
              {t("common.remove", "Remove")}
            </button>
          )}
        </div>
      ))}
      {editable && (
        <>
          <input
            aria-label={t("dental.find_material", "Find a stock item")}
            placeholder={t("dental.find_material", "Find a stock item")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {(found.data?.results ?? [])
            .filter((it) => it.category !== "instrument" && !rows.some((r) => r.item_id === it.id))
            .map((it) => (
              <button
                key={it.id}
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  setRows((cur) => [...cur, { item_id: it.id, item: it.name, unit: it.unit, quantity: "1" }]);
                  setSearch("");
                }}
              >
                + {it.name} {it.strength}
              </button>
            ))}
          <div className="form-actions">
            <button type="button" className="btn btn-sm" onClick={() => save.mutate()} disabled={save.isPending}>
              {t("dental.save_materials", "Save materials")}
            </button>
          </div>
        </>
      )}
    </fieldset>
  );
}

export function ProcedureDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { can, user } = useAuth();
  const rec = useGet<ProcedureRecord>(["dental", "procedure", id], `/dental/procedure-records/${id}/`);
  const [text, setText] = useState<Record<string, string>>({});
  const [outcome, setOutcome] = useState<"completed" | "session_completed" | "not_performed">("completed");
  const [reason, setReason] = useState("");
  const [confirmCharge, setConfirmCharge] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [amending, setAmending] = useState<string | null>(null);
  const [amendText, setAmendText] = useState("");
  // Fields typed since the last save. A newer version from the server (e.g. after saving materials) refreshes
  // only the fields the user has not touched, so unsaved typing is never thrown away.
  const dirty = useRef(new Set<string>());
  const [hasEdits, setHasEdits] = useState(false);
  useUnsavedGuard(`procedure-${id}`, hasEdits);
  useEffect(() => {
    if (rec.data) {
      const server = rec.data as unknown as Record<string, string>;
      setText((cur) =>
        Object.fromEntries(
          PROCEDURE_TEXT_FIELDS.map(([k]) => [k, dirty.current.has(k) ? (cur[k] ?? "") : String(server[k] ?? "")]),
        ),
      );
    }
  }, [rec.data?.version]); // eslint-disable-line react-hooks/exhaustive-deps
  const refresh = (r?: ProcedureRecord) => {
    if (r) qc.setQueryData(["dental", "procedure", id], r);
    void qc.invalidateQueries({ queryKey: ["dental", "encounter"] });
    void qc.invalidateQueries({ queryKey: ["dental", "plan"] });
    void qc.invalidateQueries({ queryKey: ["dental", "plans"] });
  };
  // Saving materials changes the record's version: wait for it, then send the newest version we have.
  const materialsSaving = useIsMutating({ mutationKey: ["dental", "materials", id] }) > 0;
  const save = useMutation({
    mutationFn: () =>
      api.patch<ProcedureRecord>(`/dental/procedure-records/${id}/`, {
        version: qc.getQueryData<ProcedureRecord>(["dental", "procedure", id])?.version ?? rec.data?.version,
        ...text,
      }),
    onSuccess: (r) => {
      dirty.current.clear();
      setHasEdits(false);
      refresh(r);
      toast(t("common.saved_toast", "Changes saved"));
    },
  });
  const sign = useMutation({
    mutationFn: async () => {
      await save.mutateAsync();
      return api.post<ProcedureRecord>(`/dental/procedure-records/${id}/sign/`, {
        outcome,
        reason,
        confirm_charge: confirmCharge,
      });
    },
    onSuccess: (r) => {
      refresh(r);
      toast(t("dental.signed_toast", "Procedure record signed"));
    },
  });
  const discard = useMutation({
    mutationFn: (why: string) => api.post(`/dental/procedure-records/${id}/discard/`, { reason: why }),
    onSuccess: () => {
      refresh();
      onClose();
    },
  });
  const amend = useMutation({
    mutationFn: (why: string) =>
      api.post<ProcedureRecord>(`/dental/procedure-records/${id}/amendments/`, {
        field_name: amending,
        text: amendText,
        reason: why,
      }),
    onSuccess: (r) => {
      refresh(r);
      setAmending(null);
    },
  });
  if (rec.isLoading || !rec.data) return <Loading />;
  const r = rec.data;
  const draft = r.status === "draft";
  const editable = draft && can("dental.procedure.record");
  const canSign = draft && can("dental.procedure.sign") && r.performed_by.id === user?.id;
  // Signing this outcome charges the patient (a per-session procedure charges every session).
  const charged =
    outcome === "completed" || (outcome === "session_completed" && r.charge?.billing_mode === "per_session");
  const needsConfirm = charged && !!r.charge?.warning;
  const printId = `proc-print-${r.id}`;
  return (
    <div className="stack-sm">
      <div className="row-between">
        <div>
          <strong>{r.procedure.name}</strong> <span className="mono">{r.location.label}</span> · {r.number} ·{" "}
          {t("dental.session", "Session")} {r.session_number} <DentalStatus value={r.status} />
          <div className="small subtle">
            {t("dental.performed_by", "Performed by")} {r.performed_by.full_name}
            {r.assisted_by && ` · ${t("dental.assisted_by", "Assisted by")} ${r.assisted_by.full_name}`}
            {r.signed_at && ` · ${t("dental.signed_at", "Signed")} ${formatDateTime(r.signed_at)}`}
            {r.price != null && ` · ${money(r.price)} ETB`}
            {r.billed && ` · ${t("dental.billed_on", "Billed on")} ${r.billed.invoice_number}`}
          </div>
        </div>
        {!draft && (
          <button
            className="btn btn-sm"
            onClick={() => printElement(printId, `${t("dental.procedure_report", "Procedure report")} ${r.number}`)}
          >
            <Printer size={15} aria-hidden /> {t("common.print", "Print")}
          </button>
        )}
      </div>
      <ErrorBanner error={save.error || sign.error} />
      {draft && !canSign && (
        <Banner tone="info">
          {t("dental.sign_by_performer", "{{who}} must sign this record.", { who: r.performed_by.full_name })}
        </Banner>
      )}
      <div id={printId} className="stack-sm">
        <div className="print-only">
          <ClinicHeader title={t("dental.procedure_report", "Procedure report")} number={r.number} />
        </div>
        {PROCEDURE_TEXT_FIELDS.map(([k, label]) => {
          const amendments = r.amendments.filter((a) => a.field_name === k);
          const shown = amendments.length ? amendments[amendments.length - 1].amended_text : text[k];
          return (
            <Field key={k} label={t(`dental.f_${k}`, label)} id={`f-${k}`}>
              {editable ? (
                <textarea
                  id={`f-${k}`}
                  value={text[k] ?? ""}
                  onChange={(e) => {
                    dirty.current.add(k);
                    setHasEdits(true);
                    setText((c) => ({ ...c, [k]: e.target.value }));
                  }}
                  rows={2}
                />
              ) : (
                <div className="prewrap">
                  {shown || <span className="subtle">—</span>}
                  {amendments.length > 0 && (
                    <div className="small amended">
                      {t("dental.amended", "Amended")}:{" "}
                      {amendments
                        .map((a) => `${a.reason} (${a.author.full_name}, ${formatDateTime(a.created_at)})`)
                        .join("; ")}
                    </div>
                  )}
                  {!draft && can("dental.amend") && (
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost no-print"
                      onClick={() => {
                        setAmending(k);
                        setAmendText(shown ?? "");
                      }}
                    >
                      {t("dental.amend", "Amend…")}
                    </button>
                  )}
                </div>
              )}
            </Field>
          );
        })}
        {!draft && r.not_performed_reason && (
          <p>
            <strong>{t("dental.not_performed_reason", "Not performed")}:</strong> {r.not_performed_reason}
          </p>
        )}
      </div>
      <MaterialsEditor key={r.version} record={r} editable={editable} />
      {editable && (
        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={() => setDiscarding(true)}>
            {t("dental.discard", "Discard draft…")}
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => save.mutate()}
            disabled={save.isPending || materialsSaving}
          >
            {t("common.save", "Save")}
          </button>
        </div>
      )}
      {canSign && (
        <fieldset className="fieldset stack-sm">
          <legend>{t("dental.sign_record", "Sign the record")}</legend>
          <div className="row">
            {(["completed", "session_completed", "not_performed"] as const).map((o) => (
              <label key={o} className="check">
                <input type="radio" checked={outcome === o} onChange={() => setOutcome(o)} />{" "}
                {
                  {
                    completed: t("dental.outcome_completed", "Procedure completed"),
                    session_completed: t("dental.outcome_session", "This session done, more needed"),
                    not_performed: t("dental.outcome_not", "Not performed"),
                  }[o]
                }
              </label>
            ))}
          </div>
          {charged && r.charge && (
            <div className="stack-sm">
              <div className="small">
                {t("dental.charge_line", "Charge on signing: {{price}} ETB (catalogue price)", {
                  price: money(r.charge.price),
                })}
                {r.charge.estimate != null &&
                  ` · ${t("dental.accepted_estimate", "Accepted estimate: {{estimate}} ETB", {
                    estimate: money(r.charge.estimate),
                  })}`}
              </div>
              {r.charge.warning && (
                <Banner tone="warn">
                  {r.charge.warning === "no_price"
                    ? t(
                        "dental.charge_no_price",
                        "This procedure has no price in the catalogue, so it will be billed at 0 ETB and cannot be corrected after signing. Ask the clinic administrator to set the price, or confirm that it is free of charge.",
                      )
                    : t(
                        "dental.charge_differs",
                        "The invoice will use the catalogue price ({{total}} ETB), not the estimate the patient accepted ({{estimate}} ETB).",
                        {
                          total: money(r.charge.expected_total ?? r.charge.price),
                          estimate: money(r.charge.estimate ?? "0"),
                        },
                      )}
                </Banner>
              )}
              {needsConfirm && (
                <label className="check">
                  <input type="checkbox" checked={confirmCharge} onChange={(e) => setConfirmCharge(e.target.checked)} />{" "}
                  {r.charge.warning === "no_price"
                    ? t("dental.confirm_free", "I confirm this procedure is free of charge")
                    : t("dental.confirm_price", "I confirm the charge of {{total}} ETB", {
                        total: money(r.charge.expected_total ?? r.charge.price),
                      })}
                </label>
              )}
            </div>
          )}
          {outcome === "not_performed" && (
            <Field label={t("dental.reason", "Reason")} id="f-reason" error={sign.error}>
              <input id="f-reason" value={reason} onChange={(e) => setReason(e.target.value)} required />
            </Field>
          )}
          <div className="form-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={
                sign.isPending ||
                materialsSaving ||
                (outcome === "not_performed" && !reason.trim()) ||
                (needsConfirm && !confirmCharge)
              }
              onClick={() => sign.mutate()}
            >
              {t("dental.sign", "Sign")}
            </button>
          </div>
        </fieldset>
      )}
      <ReasonDialog
        open={discarding}
        title={t("dental.discard", "Discard this draft")}
        label={t("dental.reason", "Reason")}
        confirmLabel={t("dental.discard_confirm", "Discard")}
        onClose={() => setDiscarding(false)}
        onConfirm={(why) => discard.mutate(why)}
        busy={discard.isPending}
        error={discard.error}
        danger
      />
      <Modal open={!!amending} title={t("dental.amend", "Amend")} onClose={() => setAmending(null)}>
        <div className="stack-sm">
          <textarea
            aria-label={t("dental.corrected_text", "Corrected text")}
            value={amendText}
            onChange={(e) => setAmendText(e.target.value)}
            rows={4}
          />
          <AmendReason
            busy={amend.isPending}
            error={amend.error}
            onCancel={() => setAmending(null)}
            onSave={(why) => amend.mutate(why)}
          />
        </div>
      </Modal>
    </div>
  );
}

export function AmendReason({
  busy,
  error,
  onCancel,
  onSave,
}: {
  busy: boolean;
  error: unknown;
  onCancel: () => void;
  onSave: (reason: string) => void;
}) {
  const { t } = useTranslation();
  const [why, setWhy] = useState("");
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        onSave(why);
      }}
    >
      <ErrorBanner error={error} />
      <Field label={t("dental.amend_reason", "Reason for the correction")} id="f-amend-reason">
        <input id="f-amend-reason" value={why} onChange={(e) => setWhy(e.target.value)} required />
      </Field>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onCancel}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={busy || !why.trim()}>
          {t("dental.save_amendment", "Save amendment")}
        </button>
      </div>
    </form>
  );
}
