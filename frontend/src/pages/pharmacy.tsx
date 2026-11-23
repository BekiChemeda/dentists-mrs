import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Pill } from "lucide-react";
import { ApiError, api, queryString } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { Approval, Dispensation, Paginated, Prescription, RxItem, StockItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { StateBadge } from "../labels";
import { formatDateTime } from "../lib/format";
import { Badge, Banner, Empty, ErrorBanner, Field, Loading, Modal, PageHead, Panel, Segmented, qty } from "../ui";
import { sexAge, todayIso } from "./common";
import { StockAlerts } from "./inventory";

export function PharmacyPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [view, setView] = useState<"pending" | "today" | "register">("pending");
  const pending = useGet<Paginated<Prescription>>(
    ["prescriptions", "pending"],
    "/prescriptions/?status=active,partial&page_size=50",
    { refetchInterval: 20_000 },
  );
  const today = useGet<Paginated<Dispensation>>(
    ["dispensations", "today"],
    view === "today" ? `/pharmacy/dispensations/?date=${todayIso()}&page_size=100` : null,
  );
  const [dispensing, setDispensing] = useState<{ rx: Prescription; line: RxItem } | null>(null);

  return (
    <div className="stack">
      <PageHead
        title={t("nav.pharmacy")}
        sub={t("pharmacy.sub", "Dispense against prescriptions. Stock is taken from the batch that expires first.")}
        actions={
          <Segmented
            label="View"
            value={view}
            onChange={setView}
            options={[
              { key: "pending", label: t("pharmacy.to_dispense", "To dispense") },
              { key: "today", label: t("pharmacy.today", "Dispensed today") },
              ...(can("pharmacy.dispense", "inventory.manage")
                ? [{ key: "register" as const, label: t("pharmacy.register", "Controlled register") }]
                : []),
            ]}
          />
        }
      />
      {view === "register" && <ControlledRegister />}
      {view === "pending" && (
        <div className="split">
          <div className="stack">
            {pending.isLoading ? (
              <Loading />
            ) : !pending.data?.results.length ? (
              <Empty icon={<Pill size={28} />}>{t("pharmacy.none", "No prescriptions waiting.")}</Empty>
            ) : (
              pending.data.results.map((rx) => (
                <Panel
                  key={rx.id}
                  flush
                  title={
                    <div>
                      <div className="row">
                        <Link to={`/patients/${rx.patient.id}`}>
                          <h2>{rx.patient.full_name}</h2>
                        </Link>
                        <StateBadge set="rx" value={rx.status} />
                      </div>
                      <div className="small muted">
                        {sexAge(rx.patient, t)}, <span className="mono">{rx.patient.mrn}</span>, Dr.{" "}
                        {rx.prescriber.full_name}, {formatDateTime(rx.created_at)}
                      </div>
                    </div>
                  }
                >
                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th>{t("rx.medicine", "Medicine")}</th>
                          <th>{t("rx.directions", "Directions")}</th>
                          <th className="num">{t("rx.prescribed", "Prescribed")}</th>
                          <th className="num">{t("rx.remaining", "Remaining")}</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {rx.items.map((line) => (
                          <tr key={line.id} className={Number(line.remaining) === 0 ? "muted" : ""}>
                            <td>
                              <strong>{line.drug_name}</strong>
                              {rx.controlled_class && (
                                <>
                                  {" "}
                                  <Badge tone="danger">{rx.controlled_class}</Badge>
                                </>
                              )}
                              {!line.item && (
                                <div className="small subtle">
                                  {t("pharmacy.not_catalogued", "Written as free text")}
                                </div>
                              )}
                              {line.allergy_override_reason && (
                                <div className="small flag-H">{t("pharmacy.allergy_flag", "Allergy override")}</div>
                              )}
                            </td>
                            <td>
                              {line.dose}, {line.route}, {line.frequency}
                              {line.duration_days ? `, ${line.duration_days} days` : ""}
                              {line.instructions && <div className="small muted">{line.instructions}</div>}
                            </td>
                            <td className="num">{qty(line.quantity)}</td>
                            <td className="num">
                              <strong>{qty(line.remaining)}</strong>
                            </td>
                            <td className="num">
                              {Number(line.remaining) > 0 && (
                                <button className="btn btn-sm btn-primary" onClick={() => setDispensing({ rx, line })}>
                                  {t("pharmacy.dispense", "Dispense")}
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              ))
            )}
          </div>
          <StockAlerts compact />
        </div>
      )}
      {view === "today" && (
        <Panel flush>
          {today.isLoading ? (
            <Loading />
          ) : !today.data?.results.length ? (
            <Empty>{t("pharmacy.none_today", "Nothing dispensed today yet.")}</Empty>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>{t("common.time", "Time")}</th>
                    <th>{t("patients.patient", "Patient")}</th>
                    <th>{t("rx.medicine", "Medicine")}</th>
                    <th className="num">{t("rx.quantity", "Quantity")}</th>
                    <th>{t("common.by", "By")}</th>
                  </tr>
                </thead>
                <tbody>
                  {today.data.results.map((d) => (
                    <tr key={d.id}>
                      <td>{formatDateTime(d.dispensed_at)}</td>
                      <td>{d.patient.full_name}</td>
                      <td>
                        {d.item_name}
                        {d.override_approval && (
                          <div className="small" style={{ color: "var(--amber-ink)" }}>
                            {t("pharmacy.override_used", "Dispensed under approved override")}
                          </div>
                        )}
                      </td>
                      <td className="num">
                        {qty(d.quantity)} {d.unit}
                      </td>
                      <td>{d.dispensed_by.full_name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      )}
      <Modal
        open={dispensing !== null}
        title={t("pharmacy.dispense_title", "Dispense {{name}}", { name: dispensing?.line.drug_name ?? "" })}
        onClose={() => setDispensing(null)}
      >
        {dispensing && <DispenseForm rx={dispensing.rx} line={dispensing.line} onDone={() => setDispensing(null)} />}
      </Modal>
    </div>
  );
}

function DispenseForm({ rx, line, onDone }: { rx: Prescription; line: RxItem; onDone: () => void }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [itemId, setItemId] = useState(line.item ?? "");
  const [search, setSearch] = useState(line.item ? "" : line.drug_name.split(" ")[0]);
  const [quantity, setQuantity] = useState(String(Number(line.remaining)));
  const [overrideReason, setOverrideReason] = useState("");
  const [batchId, setBatchId] = useState("");
  const [batchReason, setBatchReason] = useState("");
  const [formChecked, setFormChecked] = useState(false);
  const [counselled, setCounselled] = useState(false);
  const item = useGet<StockItem>(["item", itemId], itemId ? `/inventory/items/${itemId}/` : null);
  const options = useGet<Paginated<StockItem>>(
    ["items", "medicine", search],
    !line.item
      ? `/inventory/items/${queryString({ category: "medicine", active: "true", q: search, page_size: 8 })}`
      : null,
  );
  const approvals = useGet<Paginated<Approval>>(["approvals", line.id], `/approvals/?object_id=${line.id}`);
  const usable = approvals.data?.results.find((a) => a.status === "approved" && a.requested_by.id === user?.id);
  const pendingReq = approvals.data?.results.find((a) => a.status === "pending");

  const dispense = useAction(
    (approvalId: string | null) =>
      api.post(`/prescription-items/${line.id}/dispense/`, {
        quantity,
        item_id: line.item ? null : itemId,
        override_approval_id: approvalId,
        batch_id: batchId || null,
        batch_reason: batchReason,
        special_form_checked: formChecked,
        counselling_given: counselled,
      }),
    [["prescriptions"], ["items"], ["dispensations"], ["approvals"]],
    onDone,
    t("pharmacy.dispensed_toast", "Dispensed"),
  );
  const requestOverride = useAction(
    () => api.post(`/prescription-items/${line.id}/override-request/`, { quantity, reason: overrideReason }),
    [["approvals"]],
  );
  const insufficient = dispense.error instanceof ApiError && dispense.error.code === "insufficient_stock";
  const batches = (item.data?.batches ?? []).filter(
    (b) => (!b.expiry_date || b.expiry_date >= todayIso()) && Number(b.on_hand) > 0,
  );
  const controlled = !!rx.controlled_class || !!item.data?.controlled_class;
  const notFirst = batchId && batches[0] && batches[0].id !== batchId;

  return (
    <div className="stack-sm">
      <p>
        <strong>{rx.patient.full_name}</strong> <span className="muted">{sexAge(rx.patient, t)}</span>
      </p>
      <p>
        {line.strength && (
          <strong>
            {line.strength} {line.dosage_form}:{" "}
          </strong>
        )}
        {line.dose}, {line.route}, {line.frequency}
        {line.duration_days ? `, ${line.duration_days} days` : ""}
      </p>
      {line.instructions && (
        <p className="small">
          {t("rx.instructions", "Instructions")}: {line.instructions}
        </p>
      )}
      {line.warnings && (
        <Banner tone="warn">
          {t("pharmacy.warnings", "Counsel the patient")}: {line.warnings}
        </Banner>
      )}
      {line.allergy_override_reason && (
        <Banner tone="error">
          {t("pharmacy.allergy_override", "Prescribed despite a recorded allergy. Doctor's reason")}:{" "}
          {line.allergy_override_reason}
        </Banner>
      )}
      {controlled && (
        <Banner tone="info">
          {t(
            "pharmacy.controlled_info",
            "Controlled medicine. Check the original special prescription (serial {{serial}}, stamped, written within 15 days, patient 18 or over). Dispense the full quantity once.",
            { serial: rx.special_form_serial || "?" },
          )}
        </Banner>
      )}
      {!line.item && (
        <Field label={t("pharmacy.match", "Catalogue medicine to give")} id="d-item">
          <div className="stack-sm">
            <input id="d-item" value={search} onChange={(e) => setSearch(e.target.value)} />
            <div className="row" style={{ gap: 6 }}>
              {options.data?.results.map((m) => (
                <button
                  type="button"
                  key={m.id}
                  className={`btn btn-sm${itemId === m.id ? " btn-primary" : ""}`}
                  onClick={() => setItemId(m.id)}
                >
                  {m.name} {m.strength}
                </button>
              ))}
            </div>
          </div>
        </Field>
      )}
      {item.data && (
        <div className="panel" style={{ padding: "10px 14px" }}>
          <div className="row-between">
            <strong>
              {item.data.name} {item.data.strength}
            </strong>
            <span>
              {t("pharmacy.usable", "Usable stock")}:{" "}
              <strong>
                {qty(item.data.usable)} {item.data.unit}
              </strong>
            </span>
          </div>
        </div>
      )}
      {batches.length > 0 && (
        <Field
          label={t("pharmacy.batch", "Batch")}
          id="d-b"
          hint={t(
            "pharmacy.batch_hint",
            "Expired batches are never offered. The earliest-expiring batch is used unless you choose another.",
          )}
        >
          <select id="d-b" value={batchId} onChange={(e) => setBatchId(e.target.value)}>
            <option value="">{t("pharmacy.batch_auto", "Earliest expiry first (automatic)")}</option>
            {batches.map((b) => (
              <option key={b.id} value={b.id}>
                {b.batch_number}: {qty(b.on_hand)} {item.data?.unit}, exp. {b.expiry_date ?? "none"}
              </option>
            ))}
          </select>
        </Field>
      )}
      {notFirst && (
        <Field
          label={t("pharmacy.batch_reason", "Reason for not using the earliest-expiring batch")}
          id="d-br"
          error={dispense.error}
        >
          <input id="d-br" value={batchReason} onChange={(e) => setBatchReason(e.target.value)} />
        </Field>
      )}
      <Field
        label={t("rx.quantity", "Quantity")}
        id="d-q"
        hint={t("pharmacy.max", "Up to {{n}} remain on this prescription line", { n: qty(line.remaining) })}
      >
        <input
          id="d-q"
          type="number"
          min={0}
          step="any"
          max={Number(line.remaining)}
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
        />
      </Field>
      {controlled && (
        <div className="stack-sm">
          <label className="check">
            <input type="checkbox" checked={formChecked} onChange={(e) => setFormChecked(e.target.checked)} />
            <span>
              {t(
                "pharmacy.form_checked",
                "I checked the original special prescription form: serial number, facility stamp, prescriber's signature and registration number",
              )}
            </span>
          </label>
          <label className="check">
            <input type="checkbox" checked={counselled} onChange={(e) => setCounselled(e.target.checked)} />
            <span>{t("pharmacy.counselled", "The patient was counselled on dose, duration and risks")}</span>
          </label>
        </div>
      )}
      {!insufficient && <ErrorBanner error={dispense.error} />}
      {usable && (
        <Banner tone="ok">
          {t("pharmacy.override_ready", "Override approved by {{who}}. You can dispense beyond recorded stock once.", {
            who: usable.decided_by?.full_name,
          })}
        </Banner>
      )}
      {pendingReq && (
        <Banner tone="warn">
          {t("pharmacy.override_pending", "Override requested. Waiting for a clinic administrator to approve.")}
        </Banner>
      )}
      {insufficient && !usable && !pendingReq && (
        <div className="stack-sm">
          <Banner tone="warn">
            {dispense.error?.message}{" "}
            {t(
              "pharmacy.override_explain",
              "If the medicine is physically available (e.g. a delivery not yet entered), request an override. A second person must approve it.",
            )}
          </Banner>
          <ErrorBanner error={requestOverride.error} />
          <Field label={t("pharmacy.override_reason", "Reason for the override")} id="d-or">
            <input id="d-or" value={overrideReason} onChange={(e) => setOverrideReason(e.target.value)} />
          </Field>
          <button
            className="btn"
            disabled={!overrideReason.trim() || requestOverride.isPending}
            onClick={() => requestOverride.mutate(undefined)}
          >
            {t("pharmacy.request_override", "Request override approval")}
          </button>
        </div>
      )}
      <div className="form-actions">
        <button
          className="btn btn-primary"
          disabled={
            !itemId ||
            !(Number(quantity) > 0) ||
            dispense.isPending ||
            (controlled && (!formChecked || !counselled)) ||
            (!!notFirst && !batchReason.trim())
          }
          onClick={() => dispense.mutate(usable?.id ?? null)}
        >
          {usable ? t("pharmacy.dispense_override", "Dispense with override") : t("pharmacy.dispense", "Dispense")}
        </button>
      </div>
    </div>
  );
}

interface RegisterRow {
  date: string;
  kind: string;
  batch: string;
  expiry: string;
  received: string;
  issued: string;
  balance: string;
  by: string;
  reference: string;
  patient: string;
  mrn: string;
  prescriber: string;
  prescriber_reg: string;
  form_serial: string;
}

/** Register of a controlled medicine, generated from the stock ledger (EFDA Directive 1121/2025, Art. 29). */
function ControlledRegister() {
  const { t } = useTranslation();
  const [item, setItem] = useState("");
  const list = useGet<{ items: { id: string; name: string; class: string }[] }>(
    ["register", "items"],
    "/pharmacy/controlled-register/",
  );
  const reg = useGet<{ item: { name: string; class: string; unit: string }; rows: RegisterRow[]; balance: string }>(
    ["register", item],
    item ? `/pharmacy/controlled-register/?item=${item}` : null,
  );
  return (
    <div className="stack">
      <div className="filters">
        <div className="field">
          <label htmlFor="cr-i">{t("pharmacy.controlled_item", "Controlled medicine")}</label>
          <select id="cr-i" value={item} onChange={(e) => setItem(e.target.value)}>
            <option value="">{t("common.choose", "Choose…")}</option>
            {list.data?.items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name} ({i.class})
              </option>
            ))}
          </select>
        </div>
        {item && (
          <a className="btn" href={`/api/v1/pharmacy/controlled-register/?item=${item}&export=csv`}>
            {t("reports.csv", "Download CSV")}
          </a>
        )}
      </div>
      {!list.data?.items.length && (
        <Empty>
          {t("pharmacy.no_controlled", "No medicine in the catalogue is marked as narcotic or psychotropic.")}
        </Empty>
      )}
      {reg.data && (
        <Panel
          flush
          title={
            <h2>
              {reg.data.item.name}:{" "}
              {t("pharmacy.balance", "balance {{b}} {{u}}", { b: qty(reg.data.balance), u: reg.data.item.unit })}
            </h2>
          }
        >
          {reg.data.rows.length === 0 ? (
            <Empty>{t("pharmacy.no_movements", "No movements yet.")}</Empty>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>{t("common.date", "Date")}</th>
                    <th>{t("pharmacy.movement", "Movement")}</th>
                    <th>{t("pharmacy.batch", "Batch")}</th>
                    <th className="num">{t("pharmacy.in", "In")}</th>
                    <th className="num">{t("pharmacy.out", "Out")}</th>
                    <th className="num">{t("pharmacy.balance_col", "Balance")}</th>
                    <th>{t("patients.patient", "Patient")}</th>
                    <th>{t("pharmacy.prescriber", "Prescriber")}</th>
                    <th>{t("pharmacy.form", "Form no.")}</th>
                    <th>{t("pharmacy.reference", "Reference")}</th>
                  </tr>
                </thead>
                <tbody>
                  {reg.data.rows.map((r, i) => (
                    <tr key={i}>
                      <td className="nowrap small">{formatDateTime(r.date)}</td>
                      <td>{r.kind}</td>
                      <td className="mono small">{r.batch}</td>
                      <td className="num">{r.received && qty(r.received)}</td>
                      <td className="num">{r.issued && qty(r.issued)}</td>
                      <td className="num">
                        <strong>{qty(r.balance)}</strong>
                      </td>
                      <td>
                        {r.patient}
                        {r.mrn && <div className="small subtle mono">{r.mrn}</div>}
                      </td>
                      <td>
                        {r.prescriber}
                        {r.prescriber_reg && <div className="small subtle">{r.prescriber_reg}</div>}
                      </td>
                      <td className="mono small">{r.form_serial}</td>
                      <td className="small">
                        {r.reference}
                        <div className="subtle">{r.by}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}
