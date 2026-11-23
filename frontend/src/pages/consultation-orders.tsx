/** What the doctor orders and records in a consultation: diagnoses, laboratory requests, prescriptions, amendments. */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";
import { ApiError, api, queryString } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import {
  type Encounter,
  type Icd,
  type LabOrder,
  type LabTest,
  type NoteField,
  type Paginated,
  type StockItem,
} from "../api/types";
import { FLAG_LABEL, FREQUENCIES, StateBadge } from "../labels";
import { Badge, Banner, ErrorBanner, Field, Loading, Panel } from "../ui";
import { CriticalNote } from "./common";

export function DiagnosesPanel({
  encounter: e,
  editable,
  onChange,
}: {
  encounter: Encounter;
  editable: boolean;
  onChange: () => void;
}) {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("primary");
  const [certainty, setCertainty] = useState("confirmed");
  const codes = useGet<Icd[]>(["icd", q], editable ? `/icd-codes/${queryString({ q })}` : null);
  const add = useAction(
    (code: string) => api.post(`/encounters/${e.id}/diagnoses/`, { icd_code: code, kind, certainty }),
    [],
    () => {
      setQ("");
      onChange();
    },
  );
  const remove = useAction((dxId: string) => api.post(`/diagnoses/${dxId}/remove/`), [], onChange);

  return (
    <Panel title={t("consult.physician_dx", "5. Physician diagnosis")}>
      {e.diagnoses.length === 0 && (
        <p className="subtle">{t("consult.no_dx2", "No diagnosis yet. Required before prescribing and signing.")}</p>
      )}
      {e.diagnoses.length > 0 && (
        <table className="data">
          <tbody>
            {e.diagnoses.map((d) => (
              <tr key={d.id}>
                <td>
                  <strong>{d.icd ? `Code ${d.icd.code} ` : ""}</strong>
                  {d.description}
                </td>
                <td>
                  <Badge tone={d.kind === "primary" ? "info" : "muted"}>{d.kind}</Badge>{" "}
                  {d.certainty === "provisional" && <Badge tone="wait">provisional</Badge>}
                </td>
                <td className="num">
                  {editable && (
                    <button
                      className="btn btn-sm btn-ghost btn-icon"
                      aria-label={t("common.remove", "Remove")}
                      onClick={() => remove.mutate(d.id)}
                    >
                      <Trash2 size={15} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editable && (
        <div className="stack-sm" style={{ marginTop: 16 }}>
          <ErrorBanner error={add.error} />
          <div className="row">
            <select value={kind} onChange={(ev) => setKind(ev.target.value)} aria-label="Type">
              <option value="primary">Primary</option>
              <option value="secondary">Secondary</option>
            </select>
            <select value={certainty} onChange={(ev) => setCertainty(ev.target.value)} aria-label="Certainty">
              <option value="confirmed">Confirmed</option>
              <option value="provisional">Provisional</option>
            </select>
            <input
              className="grow"
              value={q}
              onChange={(ev) => setQ(ev.target.value)}
              placeholder={t("consult.search_icd", "Search ICD-10 by code or name")}
              aria-label={t("consult.search_icd", "Search ICD-10")}
            />
          </div>
          <div className="row" style={{ gap: 6 }}>
            {codes.data?.slice(0, 12).map((c) => (
              <button
                key={c.code}
                type="button"
                className="btn btn-sm btn-wrap"
                disabled={add.isPending}
                onClick={() => add.mutate(c.code)}
              >
                <span className="mono">{c.code}</span> {c.title}
              </button>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}

export function LabPanel({ orders, loading }: { orders: LabOrder[]; loading: boolean }) {
  const { t } = useTranslation();
  const items = orders.flatMap((o) => o.items.map((i) => ({ o, i })));
  return (
    <Panel title={t("consult.investigations2", "Investigations sent")}>
      {loading ? (
        <Loading />
      ) : items.length === 0 ? (
        <p className="subtle">{t("consult.no_labs", "No tests requested.")}</p>
      ) : (
        <table className="data">
          <tbody>
            {items.map(({ o, i }) => (
              <tr key={i.id}>
                <td>
                  <strong>{i.test.name}</strong>
                  <div className="small subtle mono">{o.accession_number}</div>
                </td>
                <td>
                  {i.display_result ? (
                    <span className={`flag-${i.flag}`}>
                      {i.display_result} {i.unit} {i.flag && i.flag !== "N" ? `(${FLAG_LABEL[i.flag]})` : ""}
                    </span>
                  ) : (
                    "—"
                  )}
                  <CriticalNote item={i} />
                </td>
                <td className="num">
                  <StateBadge set="labItem" value={i.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

export function AmendForm({
  encounter,
  field,
  onDone,
}: {
  encounter: Encounter;
  field: NoteField;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const current =
    [...encounter.amendments].reverse().find((a) => a.field_name === field)?.amended_text ?? encounter[field];
  const [text, setText] = useState(current);
  const [reason, setReason] = useState("");
  const save = useAction(
    () => api.post(`/encounters/${encounter.id}/amendments/`, { field_name: field, text, reason }),
    [],
    onDone,
  );
  return (
    <form
      className="stack-sm"
      onSubmit={(ev) => {
        ev.preventDefault();
        save.mutate(undefined);
      }}
    >
      <Banner tone="info">
        {t(
          "consult.amend_note",
          "The signed text is kept unchanged. Your correction, name, time and reason are recorded alongside it.",
        )}
      </Banner>
      <ErrorBanner error={save.error} />
      <Field label={t("consult.corrected_text", "Corrected text")} id="am-text">
        <textarea id="am-text" rows={5} value={text} onChange={(ev) => setText(ev.target.value)} />
      </Field>
      <Field label={t("consult.reason", "Reason for the amendment")} id="am-reason">
        <input id="am-reason" value={reason} onChange={(ev) => setReason(ev.target.value)} />
      </Field>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!reason.trim() || !text.trim() || save.isPending}>
          {t("consult.save_amendment", "Save amendment")}
        </button>
      </div>
    </form>
  );
}

interface RxLine {
  item: StockItem | null;
  drug_name: string;
  dose: string;
  route: string;
  frequency: string;
  duration_days: string;
  quantity: string;
  instructions: string;
  allergy_override_reason: string;
}
const BLANK_LINE: RxLine = {
  item: null,
  drug_name: "",
  dose: "",
  route: "oral",
  frequency: "",
  duration_days: "",
  quantity: "",
  instructions: "",
  allergy_override_reason: "",
};

export function PrescriptionForm({ encounterId, onDone }: { encounterId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const [lines, setLines] = useState<RxLine[]>([{ ...BLANK_LINE }]);
  const [search, setSearch] = useState("");
  const [target, setTarget] = useState(0);
  const meds = useGet<Paginated<StockItem>>(
    ["items", "medicine", search],
    `/inventory/items/${queryString({ category: "medicine", active: "true", q: search, page_size: 8 })}`,
  );
  const [serial, setSerial] = useState("");
  const [weight, setWeight] = useState("");
  const save = useAction(
    () =>
      api.post(`/encounters/${encounterId}/prescriptions/`, {
        items: lines
          .filter((l) => l.item || l.drug_name)
          .map((l) => ({
            item_id: l.item?.id ?? null,
            drug_name: l.item ? "" : l.drug_name,
            dose: l.dose,
            route: l.route,
            frequency: l.frequency,
            duration_days: l.duration_days ? Number(l.duration_days) : null,
            quantity: l.quantity,
            instructions: l.instructions,
            allergy_override_reason: l.allergy_override_reason,
          })),
        special_form_serial: serial,
        patient_weight_kg: weight || null,
      }),
    [["prescriptions"], ["encounter"]],
    onDone,
    t("rx.saved_toast", "Prescription saved"),
  );
  const update = (i: number, patch: Partial<RxLine>) =>
    setLines(lines.map((l, n) => (n === i ? { ...l, ...patch } : l)));
  const conflicts =
    save.error instanceof ApiError && save.error.code === "allergy_warning"
      ? (save.error.details.conflicts as Record<string, string[]>)
      : {};
  const controlled = lines.find((l) => l.item?.controlled_class)?.item ?? null;

  return (
    <form
      className="stack"
      onSubmit={(ev) => {
        ev.preventDefault();
        save.mutate(undefined);
      }}
    >
      {Object.keys(conflicts).length > 0 ? (
        <Banner tone="error">{save.error instanceof Error ? save.error.message : ""}</Banner>
      ) : (
        <ErrorBanner error={save.error} />
      )}
      {controlled && (
        <fieldset className="fieldset">
          <legend>{t("rx.controlled", "Controlled medicine: {{cls}}", { cls: controlled.controlled_class })}</legend>
          <p className="small muted">
            {t(
              "rx.controlled_rules",
              "EFDA Directive 1121/2025: write it on the official special prescription form (the paper form remains the legal document), one controlled medicine per prescription, diagnosis recorded, no more than three months' supply, patients 18 and over only.",
            )}
          </p>
          <div className="form-grid">
            <Field
              label={t("rx.form_serial", "Special prescription form serial number")}
              id="rx-serial"
              error={save.error}
            >
              <input id="rx-serial" value={serial} onChange={(ev) => setSerial(ev.target.value)} />
            </Field>
            <Field
              label={t("rx.weight", "Patient weight (kg)")}
              id="rx-weight"
              hint={t("rx.weight_hint", "Leave empty to use today's triage weight.")}
              error={save.error}
            >
              <input
                id="rx-weight"
                type="number"
                step="0.1"
                min={0.3}
                value={weight}
                onChange={(ev) => setWeight(ev.target.value)}
              />
            </Field>
          </div>
        </fieldset>
      )}
      {lines.map((l, i) => (
        <fieldset key={i} className="fieldset">
          <legend>{t("rx.line", "Medicine {{n}}", { n: i + 1 })}</legend>
          {l.item ? (
            <div className="row-between">
              <div>
                <strong>
                  {l.item.name} {l.item.strength}
                </strong>{" "}
                <span className="muted">
                  {l.item.dosage_form}
                  {l.item.route && `, ${l.item.route}`}
                </span>
                {l.item.controlled_class && <Badge tone="danger">{l.item.controlled_class}</Badge>}
                {l.item.warnings && (
                  <div className="small" style={{ color: "var(--amber-ink)" }}>
                    {l.item.warnings}
                  </div>
                )}
                <div className="small subtle">
                  {t("rx.in_stock", "In stock")}: {Number(l.item.usable ?? 0)} {l.item.unit}
                </div>
              </div>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => update(i, { item: null, allergy_override_reason: "" })}
              >
                {t("common.change", "Change")}
              </button>
            </div>
          ) : (
            <div className="stack-sm">
              <input
                value={target === i ? search : ""}
                onFocus={() => setTarget(i)}
                onChange={(ev) => {
                  setTarget(i);
                  setSearch(ev.target.value);
                }}
                placeholder={t("rx.search", "Search the medicine catalogue")}
                aria-label={t("rx.search", "Search medicine")}
                style={{ width: "100%" }}
              />
              {target === i && search && (
                <div className="row" style={{ gap: 6 }}>
                  {meds.data?.results.map((m) => (
                    <button
                      type="button"
                      key={m.id}
                      className="btn btn-sm btn-wrap"
                      onClick={() => {
                        update(i, { item: m, route: m.route || l.route });
                        setSearch("");
                      }}
                    >
                      {m.name} {m.strength}
                      {m.is_low && <Badge tone="wait">{t("rx.low", "low stock")}</Badge>}
                    </button>
                  ))}
                </div>
              )}
              <input
                value={l.drug_name}
                onChange={(ev) => update(i, { drug_name: ev.target.value })}
                placeholder={t("rx.free_text", "Or write a medicine not in the catalogue")}
                aria-label={t("rx.free_text", "Medicine name")}
                style={{ width: "100%" }}
              />
            </div>
          )}
          <div className="form-grid-4" style={{ marginTop: 12 }}>
            <Field label={t("rx.dose", "Dose")} id={`rx-dose-${i}`}>
              <input
                id={`rx-dose-${i}`}
                value={l.dose}
                onChange={(ev) => update(i, { dose: ev.target.value })}
                placeholder="500 mg"
              />
            </Field>
            <Field label={t("rx.frequency", "Frequency")} id={`rx-freq-${i}`}>
              <select
                id={`rx-freq-${i}`}
                value={l.frequency}
                onChange={(ev) => update(i, { frequency: ev.target.value })}
              >
                <option value="">{t("rx.choose", "Choose")}</option>
                {FREQUENCIES.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("rx.days", "Days")} id={`rx-days-${i}`}>
              <input
                id={`rx-days-${i}`}
                type="number"
                min={1}
                value={l.duration_days}
                onChange={(ev) => update(i, { duration_days: ev.target.value })}
              />
            </Field>
            <Field label={t("rx.quantity", "Quantity to dispense")} id={`rx-qty-${i}`}>
              <input
                id={`rx-qty-${i}`}
                type="number"
                min={0}
                step="any"
                value={l.quantity}
                onChange={(ev) => update(i, { quantity: ev.target.value })}
              />
            </Field>
            <Field label={t("rx.route", "Route")} id={`rx-route-${i}`}>
              <select id={`rx-route-${i}`} value={l.route} onChange={(ev) => update(i, { route: ev.target.value })}>
                {["oral", "IV", "IM", "SC", "topical", "inhaled", "rectal", "eye", "ear"].map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </Field>
            <Field label={t("rx.instructions_opt", "Instructions (optional)")} id={`rx-ins-${i}`} className="span-all">
              <input
                id={`rx-ins-${i}`}
                value={l.instructions}
                onChange={(ev) => update(i, { instructions: ev.target.value })}
                placeholder={t("rx.instructions_ph", "e.g. after meals")}
              />
            </Field>
          </div>
          {conflicts[String(i)] && (
            <div className="critical-box" style={{ marginTop: 10 }}>
              <strong>
                {t("rx.allergy_match", "Matches a recorded allergy")}: {conflicts[String(i)].join(", ")}
              </strong>
              <Field
                label={t("rx.allergy_reason", "Reason to prescribe anyway (or change the medicine)")}
                id={`rx-alg-${i}`}
              >
                <input
                  id={`rx-alg-${i}`}
                  value={l.allergy_override_reason}
                  onChange={(ev) => update(i, { allergy_override_reason: ev.target.value })}
                />
              </Field>
            </div>
          )}
          {lines.length > 1 && (
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={() => setLines(lines.filter((_, n) => n !== i))}
            >
              {t("common.remove", "Remove")}
            </button>
          )}
        </fieldset>
      ))}
      <div className="row-between">
        <button type="button" className="btn" onClick={() => setLines([...lines, { ...BLANK_LINE }])}>
          <Plus size={15} aria-hidden /> {t("rx.add_line", "Add another medicine")}
        </button>
        <button
          className="btn btn-primary"
          disabled={
            save.isPending ||
            !lines.every((l) => (l.item || l.drug_name) && l.dose && l.frequency && Number(l.quantity) > 0)
          }
        >
          {t("rx.save", "Save prescription")}
        </button>
      </div>
    </form>
  );
}

/** Active laboratory tests grouped by department, as checkboxes. */
export function LabTestChecklist({ selected, onToggle }: { selected: Set<string>; onToggle: (id: string) => void }) {
  const tests = useGet<LabTest[]>(["lab-tests", "active"], "/lab/tests/?active=true");
  const groups = useMemo(() => {
    const m = new Map<string, LabTest[]>();
    for (const test of tests.data ?? [])
      m.set(test.category || "Other", [...(m.get(test.category || "Other") ?? []), test]);
    return [...m.entries()];
  }, [tests.data]);
  if (tests.isLoading) return <Loading />;
  return (
    <div className="cols-2">
      {groups.map(([cat, list]) => (
        <fieldset key={cat} className="fieldset">
          <legend>{cat}</legend>
          {list.map((test) => (
            <label key={test.id} className="check">
              <input type="checkbox" checked={selected.has(test.id)} onChange={() => onToggle(test.id)} />
              {test.name}
            </label>
          ))}
        </fieldset>
      ))}
    </div>
  );
}

export function LabOrderForm({ encounterId, onDone }: { encounterId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [priority, setPriority] = useState("routine");
  const [notes, setNotes] = useState("");
  const save = useAction(
    () =>
      api.post(`/encounters/${encounterId}/lab-orders/`, { test_ids: [...selected], priority, clinical_notes: notes }),
    [["lab"]],
    () => {
      setSelected(new Set());
      setNotes("");
      onDone();
    },
    t("lab.sent_toast", "Investigations sent to the laboratory"),
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
      onSubmit={(ev) => {
        ev.preventDefault();
        save.mutate(undefined);
      }}
    >
      <ErrorBanner error={save.error} />
      <LabTestChecklist selected={selected} onToggle={toggle} />
      <div className="form-grid">
        <Field label={t("queue.priority", "Priority")} id="lo-p">
          <select id="lo-p" value={priority} onChange={(ev) => setPriority(ev.target.value)}>
            <option value="routine">Routine</option>
            <option value="urgent">Urgent</option>
          </select>
        </Field>
        <Field label={t("lab.clinical_notes", "Clinical notes for the lab")} id="lo-n">
          <input id="lo-n" value={notes} onChange={(ev) => setNotes(ev.target.value)} />
        </Field>
      </div>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!selected.size || save.isPending}>
          {t("lab.request_n", "Request {{n}} test(s)", { n: selected.size })}
        </button>
      </div>
    </form>
  );
}
