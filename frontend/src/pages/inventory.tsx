import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PackagePlus, Plus } from "lucide-react";
import { api, queryString } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { Batch, Movement, Paginated, Purchase, StockItem, Supplier } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime } from "../lib/format";
import {
  Badge,
  Empty,
  ErrorBanner,
  Field,
  Loading,
  Modal,
  PageHead,
  Pager,
  Panel,
  Tabs,
  fieldErrors,
  money,
  qty,
} from "../ui";
import { todayIso } from "./common";

type Tab = "stock" | "alerts" | "purchases" | "movements" | "suppliers";

export function InventoryPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [tab, setTab] = useState<Tab>("stock");
  const [receiving, setReceiving] = useState(false);
  const [newItem, setNewItem] = useState(false);
  return (
    <div className="stack">
      <PageHead
        title={t("nav.inventory")}
        sub={t("inventory.sub", "Stock on hand is calculated from every receipt, dispensing and adjustment.")}
        actions={
          <>
            {can("inventory.manage", "medicines.manage") && (
              <button className="btn" onClick={() => setNewItem(true)}>
                <Plus size={16} aria-hidden /> {t("inventory.new_item", "New item")}
              </button>
            )}
            {can("inventory.manage") && (
              <button className="btn btn-primary" onClick={() => setReceiving(true)}>
                <PackagePlus size={18} aria-hidden /> {t("inventory.receive", "Receive stock")}
              </button>
            )}
          </>
        }
      />
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "stock", label: t("inventory.stock", "Stock") },
          { key: "alerts", label: t("inventory.alerts", "Alerts") },
          { key: "purchases", label: t("inventory.purchases", "Purchases") },
          { key: "movements", label: t("inventory.movements", "Movements") },
          { key: "suppliers", label: t("inventory.suppliers", "Suppliers") },
        ]}
      />
      {tab === "stock" && <StockList />}
      {tab === "alerts" && <StockAlerts />}
      {tab === "purchases" && <Purchases />}
      {tab === "movements" && <Movements />}
      {tab === "suppliers" && <Suppliers />}
      <Modal open={receiving} wide title={t("inventory.receive", "Receive stock")} onClose={() => setReceiving(false)}>
        <ReceiveForm onDone={() => setReceiving(false)} />
      </Modal>
      <Modal open={newItem} title={t("inventory.new_item", "New item")} onClose={() => setNewItem(false)}>
        <ItemForm onDone={() => setNewItem(false)} />
      </Modal>
    </div>
  );
}

const CATEGORIES = [
  ["medicine", "Medicine"],
  ["supply", "Medical supply"],
  ["consumable", "Consumable"],
  ["reagent", "Laboratory reagent"],
  ["restorative", "Restorative material"],
  ["anaesthetic", "Anaesthetic supply"],
  ["endodontic", "Endodontic material"],
  ["impression", "Impression material"],
  ["prosthetic", "Prosthetic material"],
  ["sterilisation", "Sterilisation supply"],
  ["infection_control", "Infection-control supply"],
  ["instrument", "Instrument or reusable equipment (never consumed)"],
];

function StockList() {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  const list = useGet<Paginated<StockItem>>(
    ["items", "stock", q, category, page],
    `/inventory/items/${queryString({ q, category, page, page_size: 30 })}`,
  );
  return (
    <>
      <div className="filters">
        <div className="field">
          <label htmlFor="iq">{t("common.search")}</label>
          <input
            id="iq"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="ic">{t("inventory.category", "Category")}</label>
          <select
            id="ic"
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
              setPage(1);
            }}
          >
            <option value="">{t("common.all")}</option>
            {CATEGORIES.map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
        </div>
      </div>
      <Panel flush>
        {list.isLoading ? (
          <Loading />
        ) : !list.data?.results.length ? (
          <Empty>{t("inventory.no_items", "No items. Add items to the catalogue first.")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("inventory.item", "Item")}</th>
                  <th>{t("inventory.code", "Code")}</th>
                  <th className="num">{t("inventory.usable", "Usable stock")}</th>
                  <th className="num">{t("inventory.reorder", "Reorder at")}</th>
                  <th className="num">{t("inventory.price", "Price ETB")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.data.results.map((i) => (
                  <tr key={i.id} className={`clickable${i.is_active ? "" : " muted"}`} onClick={() => setOpen(i.id)}>
                    <td>
                      <strong>
                        {i.name} {i.strength}
                      </strong>
                      <div className="small subtle">
                        {[i.generic_name !== i.name && i.generic_name, i.dosage_form].filter(Boolean).join(", ")}
                      </div>
                    </td>
                    <td className="mono">{i.code}</td>
                    <td className="num">
                      <strong>{qty(i.usable)}</strong> {i.unit}
                    </td>
                    <td className="num">{qty(i.reorder_level)}</td>
                    <td className="num">{money(i.selling_price)}</td>
                    <td>
                      {i.is_low && <Badge tone="wait">{t("inventory.low", "Low")}</Badge>}
                      {!i.is_active && <Badge>{t("common.inactive")}</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {list.data && <Pager page={page} count={list.data.count} pageSize={30} onPage={setPage} />}
      </Panel>
      <Modal open={open !== null} wide title={t("inventory.item_detail", "Stock item")} onClose={() => setOpen(null)}>
        {open && <ItemDetail id={open} />}
      </Modal>
    </>
  );
}

function ItemDetail({ id }: { id: string }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const item = useGet<StockItem>(["item", id], `/inventory/items/${id}/`);
  const [adjusting, setAdjusting] = useState<Batch | null>(null);
  const [editing, setEditing] = useState(false);
  if (!item.data) return <Loading />;
  const i = item.data;
  if (editing)
    return (
      <ItemForm
        item={i}
        onDone={() => {
          setEditing(false);
          void item.refetch();
        }}
      />
    );
  return (
    <div className="stack">
      <div className="row-between">
        <div>
          <h2>
            {i.name} {i.strength}
          </h2>
          <p className="muted">
            {i.code}, {i.dosage_form}, {t("inventory.unit", "unit")}: {i.unit}
          </p>
        </div>
        {can("inventory.manage", "medicines.manage") && (
          <button className="btn" onClick={() => setEditing(true)}>
            {t("common.edit", "Edit")}
          </button>
        )}
      </div>
      <div className="figures">
        <div className="figure">
          <b>{qty(i.usable)}</b>
          <span>{t("inventory.usable", "Usable stock")}</span>
        </div>
        <div className="figure">
          <b>{qty(i.on_hand)}</b>
          <span>{t("inventory.on_hand", "On hand incl. expired")}</span>
        </div>
        <div className="figure">
          <b>{money(i.selling_price)}</b>
          <span>{t("inventory.price", "Price ETB")}</span>
        </div>
      </div>
      <table className="data">
        <thead>
          <tr>
            <th>{t("inventory.batch", "Batch")}</th>
            <th>{t("inventory.expiry", "Expiry")}</th>
            <th className="num">{t("inventory.on_hand_short", "On hand")}</th>
            <th className="num">{t("inventory.cost", "Unit cost")}</th>
            <th>{t("inventory.supplier", "Supplier")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {(i.batches ?? []).map((b) => (
            <tr key={b.id} className={b.expiry_date && b.expiry_date < todayIso() ? "muted" : ""}>
              <td className="mono">{b.batch_number}</td>
              <td>
                {b.expiry_date ?? "—"}
                {b.expiry_date && b.expiry_date < todayIso() && (
                  <Badge tone="danger">{t("inventory.expired", "Expired")}</Badge>
                )}
              </td>
              <td className="num">{qty(b.on_hand)}</td>
              <td className="num">{money(b.unit_cost)}</td>
              <td>{b.supplier_name || "—"}</td>
              <td className="num">
                {can("inventory.adjust") && (
                  <button className="btn btn-sm" onClick={() => setAdjusting(b)}>
                    {t("inventory.adjust", "Adjust")}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {adjusting && (
        <AdjustForm
          batch={adjusting}
          unit={i.unit}
          onDone={() => {
            setAdjusting(null);
            void item.refetch();
          }}
          onCancel={() => setAdjusting(null)}
        />
      )}
    </div>
  );
}

function AdjustForm({
  batch,
  unit,
  onDone,
  onCancel,
}: {
  batch: Batch;
  unit: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [kind, setKind] = useState("adjustment");
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("");
  const save = useAction(
    () =>
      api.post("/inventory/movements/", {
        batch_id: batch.id,
        kind,
        quantity: kind === "expired" ? `-${Math.abs(Number(quantity))}` : quantity,
        reason,
      }),
    [["items"], ["movements"]],
    onDone,
  );
  return (
    <form
      className="panel"
      style={{ padding: 16 }}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined);
      }}
    >
      <h3>{t("inventory.adjust_batch", "Adjust batch {{b}}", { b: batch.batch_number })}</h3>
      <ErrorBanner error={save.error} />
      <div className="form-grid-3" style={{ marginTop: 12 }}>
        <Field label={t("inventory.type", "Type")} id="aj-k">
          <select id="aj-k" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="adjustment">{t("inventory.count_correction", "Count correction (+/−)")}</option>
            <option value="expired">{t("inventory.write_off", "Expired or damaged write-off")}</option>
          </select>
        </Field>
        <Field
          label={`${t("rx.quantity", "Quantity")} (${unit})`}
          id="aj-q"
          hint={kind === "adjustment" ? t("inventory.signed", "Negative to reduce, positive to add") : undefined}
        >
          <input id="aj-q" type="number" step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </Field>
        <Field label={t("common.reason", "Reason")} id="aj-r">
          <input id="aj-r" value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </div>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onCancel}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={!Number(quantity) || !reason.trim() || save.isPending}>
          {t("inventory.record_adjustment", "Record adjustment")}
        </button>
      </div>
    </form>
  );
}

export function ItemForm({ item, onDone }: { item?: StockItem; onDone: () => void }) {
  const { t } = useTranslation();
  const [f, setF] = useState<Record<string, string | boolean>>(
    item
      ? ({ ...item } as unknown as Record<string, string | boolean>)
      : {
          code: "",
          name: "",
          generic_name: "",
          brand_name: "",
          category: "medicine",
          dosage_form: "",
          strength: "",
          unit: "tablet",
          route: "",
          therapeutic_category: "",
          controlled_class: "",
          allergy_groups: "",
          warnings: "",
          default_supplier: "",
          reorder_level: "0",
          selling_price: "0",
          is_active: true,
          pack_unit: "",
          units_per_pack: "",
        },
  );
  const suppliers = useGet<{ id: string; name: string; is_active: boolean }[]>(["suppliers"], "/inventory/suppliers/");
  const body = () => {
    const { batches: _b, on_hand: _o, usable: _u, is_low: _l, ...rest } = f as Record<string, unknown>;
    void _b;
    void _o;
    void _u;
    void _l;
    return { ...rest, default_supplier: f.default_supplier || null, units_per_pack: f.units_per_pack || null };
  };
  const save = useAction(
    () =>
      item
        ? api.patch(`/inventory/items/${item.id}/`, body(), { ifMatch: item.row_version })
        : api.post("/inventory/items/", body()),
    [["items"], ["item"]],
    onDone,
    t("inventory.saved_toast", "Item saved"),
  );
  const input = (k: string, label: string, type = "text") => (
    <Field label={label} id={`it-${k}`} error={fieldErrors(save.error, k)}>
      <input
        id={`it-${k}`}
        type={type}
        step="any"
        value={String(f[k] ?? "")}
        disabled={k === "code" && !!item}
        onChange={(e) => setF({ ...f, [k]: e.target.value })}
      />
    </Field>
  );
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined);
      }}
    >
      <ErrorBanner error={save.error} onReload={onDone} />
      <div className="form-grid">
        {input("code", t("inventory.code", "Code"))}
        <Field label={t("inventory.category", "Category")} id="it-cat">
          <select id="it-cat" value={String(f.category)} onChange={(e) => setF({ ...f, category: e.target.value })}>
            {CATEGORIES.map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        {input("name", t("inventory.name", "Name"))}
        {input("generic_name", t("inventory.generic", "Generic name"))}
        {input("brand_name", t("inventory.brand", "Brand name"))}
        {input("dosage_form", t("inventory.form", "Dosage form"))}
        {input("strength", t("inventory.strength", "Strength"))}
        {input("unit", t("inventory.unit_label", "Counting unit (tablet, ml, vial…)"))}
        {input("reorder_level", t("inventory.reorder", "Reorder level"), "number")}
        {input("selling_price", t("inventory.price", "Selling price ETB per unit"), "number")}
        {input("pack_unit", t("inventory.pack_unit", "Pack (box, syringe…), optional"))}
        {input("units_per_pack", t("inventory.units_per_pack", "Units in one pack"), "number")}
        <Field label={t("inventory.supplier_default", "Usual supplier")} id="it-sup">
          <select
            id="it-sup"
            value={String(f.default_supplier ?? "")}
            onChange={(e) => setF({ ...f, default_supplier: e.target.value })}
          >
            <option value="">{t("common.none", "None")}</option>
            {(Array.isArray(suppliers.data)
              ? suppliers.data
              : ((suppliers.data as unknown as { results?: { id: string; name: string }[] })?.results ?? [])
            ).map((sp) => (
              <option key={sp.id} value={sp.id}>
                {sp.name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {f.category === "medicine" && (
        <fieldset className="fieldset">
          <legend>{t("inventory.medicine_info", "Medicine information")}</legend>
          <div className="form-grid">
            {input("route", t("inventory.route", "Usual route (oral, IV, IM…)"))}
            {input("therapeutic_category", t("inventory.therapeutic", "Medicine category (e.g. antibiotic)"))}
            <Field
              label={t("inventory.controlled", "Controlled classification")}
              id="it-ctl"
              hint={t(
                "inventory.controlled_hint",
                "Narcotic and psychotropic medicines follow EFDA Directive 1121/2025: special prescription and register.",
              )}
            >
              <select
                id="it-ctl"
                value={String(f.controlled_class ?? "")}
                onChange={(e) => setF({ ...f, controlled_class: e.target.value })}
              >
                <option value="">{t("inventory.not_controlled", "Not controlled")}</option>
                <option value="psychotropic">{t("inventory.psychotropic", "Psychotropic")}</option>
                <option value="narcotic">{t("inventory.narcotic", "Narcotic")}</option>
              </select>
            </Field>
            {input(
              "allergy_groups",
              t("inventory.allergy_groups", "Allergy groups, comma-separated (e.g. Penicillin, Beta-lactam)"),
            )}
            <div className="span-all">
              {input("warnings", t("inventory.warnings", "Warnings printed for the patient (e.g. Avoid alcohol)"))}
            </div>
          </div>
        </fieldset>
      )}
      <label className="check">
        <input type="checkbox" checked={!!f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />{" "}
        {t("common.active")}
      </label>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!f.code || !f.name || save.isPending}>
          {t("common.save", "Save")}
        </button>
      </div>
    </form>
  );
}

export function StockAlerts({ compact }: { compact?: boolean }) {
  const { t } = useTranslation();
  const q = useGet<{ low_stock: StockItem[]; expiring: Batch[]; expiry_window_days: number }>(
    ["items", "alerts"],
    "/inventory/alerts/?days=90",
  );
  if (!q.data) return <Loading />;
  const low = q.data.low_stock,
    exp = q.data.expiring;
  return (
    <div className="stack">
      <Panel title={t("inventory.low_stock", "Low stock ({{n}})", { n: low.length })} flush>
        {low.length === 0 ? (
          <Empty>{t("inventory.no_low", "Nothing below its reorder level.")}</Empty>
        ) : (
          <table className="data">
            <tbody>
              {low.slice(0, compact ? 8 : undefined).map((i) => (
                <tr key={i.id}>
                  <td>
                    <strong>
                      {i.name} {i.strength}
                    </strong>
                  </td>
                  <td className="num">
                    {qty(i.usable)} / {qty(i.reorder_level)} {i.unit}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
      <Panel
        title={t("inventory.expiring", "Expiring within {{d}} days ({{n}})", {
          d: q.data.expiry_window_days,
          n: exp.length,
        })}
        flush
      >
        {exp.length === 0 ? (
          <Empty>{t("inventory.no_expiring", "No batches close to expiry.")}</Empty>
        ) : (
          <table className="data">
            <tbody>
              {exp.slice(0, compact ? 8 : undefined).map((b) => (
                <tr key={b.id}>
                  <td>
                    <strong>{b.item_name}</strong>
                    <div className="small subtle mono">{b.batch_number}</div>
                  </td>
                  <td className="num">
                    <span style={{ color: b.expiry_date && b.expiry_date < todayIso() ? "var(--danger)" : undefined }}>
                      {b.expiry_date}
                    </span>
                    <div className="small">
                      {qty(b.on_hand)} {b.unit}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}

function Purchases() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const q = useGet<Paginated<Purchase>>(["purchases", page], `/inventory/purchases/?page=${page}`);
  return (
    <Panel flush>
      {!q.data ? (
        <Loading />
      ) : !q.data.results.length ? (
        <Empty>{t("inventory.no_purchases", "No stock received yet.")}</Empty>
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>{t("common.date", "Date")}</th>
              <th>{t("inventory.supplier", "Supplier")}</th>
              <th>{t("inventory.supplier_invoice", "Supplier invoice")}</th>
              <th className="num">{t("inventory.lines", "Lines")}</th>
              <th className="num">{t("inventory.cost_total", "Cost ETB")}</th>
              <th>{t("inventory.received_by", "Received by")}</th>
            </tr>
          </thead>
          <tbody>
            {q.data.results.map((p) => (
              <tr key={p.id}>
                <td>{p.purchase_date}</td>
                <td>{p.supplier.name}</td>
                <td>{p.supplier_invoice_no || "—"}</td>
                <td className="num">{p.line_count}</td>
                <td className="num">{money(p.total_cost)}</td>
                <td>{p.received_by.full_name}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {q.data && <Pager page={page} count={q.data.count} pageSize={25} onPage={setPage} />}
    </Panel>
  );
}

function Movements() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const [kind, setKind] = useState("");
  const q = useGet<Paginated<Movement>>(
    ["movements", page, kind],
    `/inventory/movements/${queryString({ page, kind })}`,
  );
  return (
    <>
      <div className="filters">
        <div className="field">
          <label htmlFor="mk">{t("inventory.type", "Type")}</label>
          <select
            id="mk"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setPage(1);
            }}
          >
            <option value="">{t("common.all")}</option>
            <option value="receipt">Receipts</option>
            <option value="dispense">Dispensed</option>
            <option value="adjustment">Adjustments</option>
            <option value="expired">Write-offs</option>
          </select>
        </div>
      </div>
      <Panel flush>
        {!q.data ? (
          <Loading />
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>{t("common.when", "When")}</th>
                <th>{t("inventory.item", "Item")}</th>
                <th>{t("inventory.batch", "Batch")}</th>
                <th>{t("inventory.type", "Type")}</th>
                <th className="num">{t("rx.quantity", "Quantity")}</th>
                <th>{t("common.by", "By")}</th>
              </tr>
            </thead>
            <tbody>
              {q.data.results.map((m) => (
                <tr key={m.id}>
                  <td className="nowrap">{formatDateTime(m.created_at)}</td>
                  <td>
                    {m.item_name}
                    {m.reason && <div className="small muted">{m.reason}</div>}
                  </td>
                  <td className="mono">{m.batch_number}</td>
                  <td>
                    {m.kind}
                    {m.is_override && <Badge tone="wait">override</Badge>}
                  </td>
                  <td className="num" style={{ color: Number(m.quantity) < 0 ? "var(--danger)" : "var(--ok)" }}>
                    {Number(m.quantity) > 0 ? "+" : ""}
                    {qty(m.quantity)}
                  </td>
                  <td>{m.created_by.full_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {q.data && <Pager page={page} count={q.data.count} pageSize={25} onPage={setPage} />}
      </Panel>
    </>
  );
}

function Suppliers() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const q = useGet<Supplier[]>(["suppliers"], "/inventory/suppliers/");
  const [f, setF] = useState({ name: "", contact_person: "", phone: "", tin: "" });
  const add = useAction(
    () => api.post("/inventory/suppliers/", f),
    [["suppliers"]],
    () => setF({ name: "", contact_person: "", phone: "", tin: "" }),
  );
  return (
    <div className="split">
      <Panel flush>
        {!q.data?.length ? (
          <Empty>{t("inventory.no_suppliers", "No suppliers yet.")}</Empty>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>{t("inventory.supplier", "Supplier")}</th>
                <th>{t("inventory.contact", "Contact")}</th>
                <th>{t("patients.phone", "Phone")}</th>
                <th>TIN</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((s) => (
                <tr key={s.id}>
                  <td>
                    <strong>{s.name}</strong>
                  </td>
                  <td>{s.contact_person || "—"}</td>
                  <td>{s.phone || "—"}</td>
                  <td>{s.tin || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
      {can("inventory.manage") && (
        <Panel title={t("inventory.add_supplier", "Add supplier")}>
          <form
            className="stack-sm"
            onSubmit={(e) => {
              e.preventDefault();
              add.mutate(undefined);
            }}
          >
            <ErrorBanner error={add.error} />
            <Field label={t("inventory.name", "Name")} id="s-n">
              <input id="s-n" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            </Field>
            <Field label={t("inventory.contact", "Contact person")} id="s-c">
              <input
                id="s-c"
                value={f.contact_person}
                onChange={(e) => setF({ ...f, contact_person: e.target.value })}
              />
            </Field>
            <Field label={t("patients.phone", "Phone")} id="s-p">
              <input id="s-p" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
            </Field>
            <Field label="TIN" id="s-t">
              <input id="s-t" value={f.tin} onChange={(e) => setF({ ...f, tin: e.target.value })} />
            </Field>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={!f.name || add.isPending}>
                {t("inventory.add_supplier", "Add supplier")}
              </button>
            </div>
          </form>
        </Panel>
      )}
    </div>
  );
}

interface Line {
  item: StockItem | null;
  batch_number: string;
  expiry_date: string;
  quantity: string;
  unit_cost: string;
}

function ReceiveForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const suppliers = useGet<Supplier[]>(["suppliers"], "/inventory/suppliers/");
  const [supplier, setSupplier] = useState("");
  const [date, setDate] = useState(todayIso());
  const [invoiceNo, setInvoiceNo] = useState("");
  const [lines, setLines] = useState<Line[]>([
    { item: null, batch_number: "", expiry_date: "", quantity: "", unit_cost: "" },
  ]);
  const [search, setSearch] = useState("");
  const [target, setTarget] = useState(0);
  const items = useGet<Paginated<StockItem>>(
    ["items", "receive", search],
    search ? `/inventory/items/${queryString({ q: search, active: "true", page_size: 8 })}` : null,
  );
  const save = useAction(
    () =>
      api.post("/inventory/purchases/", {
        supplier_id: supplier,
        purchase_date: date,
        supplier_invoice_no: invoiceNo,
        lines: lines
          .filter((l) => l.item)
          .map((l) => ({
            item_id: l.item!.id,
            batch_number: l.batch_number,
            expiry_date: l.expiry_date || null,
            quantity: l.quantity,
            unit_cost: l.unit_cost || "0",
          })),
      }),
    [["items"], ["purchases"], ["movements"]],
    onDone,
  );
  const set = (i: number, p: Partial<Line>) => setLines(lines.map((l, n) => (n === i ? { ...l, ...p } : l)));
  const total = lines.reduce((s, l) => s + Number(l.quantity || 0) * Number(l.unit_cost || 0), 0);
  const valid =
    supplier && lines.some((l) => l.item) && lines.every((l) => !l.item || (l.batch_number && Number(l.quantity) > 0));

  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined);
      }}
    >
      <ErrorBanner error={save.error} />
      <div className="form-grid-3">
        <Field label={t("inventory.supplier", "Supplier")} id="rc-s">
          <select id="rc-s" value={supplier} onChange={(e) => setSupplier(e.target.value)}>
            <option value="">{t("common.choose", "Choose…")}</option>
            {suppliers.data
              ?.filter((s) => s.is_active)
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
          </select>
        </Field>
        <Field label={t("common.date", "Date received")} id="rc-d">
          <input id="rc-d" type="date" max={todayIso()} value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label={t("inventory.supplier_invoice", "Supplier invoice no.")} id="rc-i">
          <input id="rc-i" value={invoiceNo} onChange={(e) => setInvoiceNo(e.target.value)} />
        </Field>
      </div>
      <table className="data">
        <thead>
          <tr>
            <th style={{ width: "34%" }}>{t("inventory.item", "Item")}</th>
            <th>{t("inventory.batch", "Batch no.")}</th>
            <th>{t("inventory.expiry", "Expiry")}</th>
            <th>{t("rx.quantity", "Quantity")}</th>
            <th>{t("inventory.cost", "Unit cost")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i}>
              <td>
                {l.item ? (
                  <button type="button" className="link-btn" onClick={() => set(i, { item: null })}>
                    {l.item.name} {l.item.strength} ({l.item.unit})
                  </button>
                ) : (
                  <div className="stack-sm">
                    <input
                      value={target === i ? search : ""}
                      onFocus={() => setTarget(i)}
                      onChange={(e) => {
                        setTarget(i);
                        setSearch(e.target.value);
                      }}
                      placeholder={t("inventory.find_item", "Find item")}
                      aria-label={t("inventory.find_item", "Find item")}
                      style={{ width: "100%" }}
                    />
                    {target === i && search && (
                      <div className="row" style={{ gap: 4 }}>
                        {items.data?.results.map((it) => (
                          <button
                            key={it.id}
                            type="button"
                            className="btn btn-sm"
                            onClick={() => {
                              set(i, { item: it, unit_cost: "" });
                              setSearch("");
                            }}
                          >
                            {it.name} {it.strength}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </td>
              <td>
                <input
                  aria-label="Batch"
                  value={l.batch_number}
                  onChange={(e) => set(i, { batch_number: e.target.value })}
                  style={{ width: "100%" }}
                />
              </td>
              <td>
                <input
                  aria-label="Expiry"
                  type="date"
                  min={todayIso()}
                  value={l.expiry_date}
                  onChange={(e) => set(i, { expiry_date: e.target.value })}
                />
              </td>
              <td>
                <input
                  aria-label="Quantity"
                  type="number"
                  min={0}
                  step="any"
                  value={l.quantity}
                  onChange={(e) => set(i, { quantity: e.target.value })}
                  style={{ width: 100 }}
                />
              </td>
              <td>
                <input
                  aria-label="Unit cost"
                  type="number"
                  min={0}
                  step="0.01"
                  value={l.unit_cost}
                  onChange={(e) => set(i, { unit_cost: e.target.value })}
                  style={{ width: 100 }}
                />
              </td>
              <td>
                {lines.length > 1 && (
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    onClick={() => setLines(lines.filter((_, n) => n !== i))}
                  >
                    {t("common.remove", "Remove")}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={4}>{t("inventory.total_cost", "Total cost")}</td>
            <td className="num">{money(total)}</td>
            <td />
          </tr>
        </tfoot>
      </table>
      <div className="row-between">
        <button
          type="button"
          className="btn"
          onClick={() =>
            setLines([...lines, { item: null, batch_number: "", expiry_date: "", quantity: "", unit_cost: "" }])
          }
        >
          <Plus size={15} aria-hidden /> {t("inventory.add_line", "Add line")}
        </button>
        <button className="btn btn-primary" disabled={!valid || save.isPending}>
          {t("inventory.save_receipt", "Record receipt")}
        </button>
      </div>
    </form>
  );
}
