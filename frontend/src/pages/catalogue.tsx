import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import { api } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { LabRange, LabTest, ServicePrice } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import {
  Badge,
  Banner,
  Empty,
  ErrorBanner,
  Field,
  Loading,
  Modal,
  PageHead,
  Panel,
  Tabs,
  fieldErrors,
  money,
  qty,
} from "../ui";

export function CataloguePage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const tabs = [
    ...(can("settings.manage", "billing.view")
      ? [{ key: "services" as const, label: t("catalogue.services", "Service prices") }]
      : []),
    ...(can("lab.catalog.manage") ? [{ key: "lab" as const, label: t("catalogue.lab", "Laboratory tests") }] : []),
  ];
  const [tab, setTab] = useState<"services" | "lab">(tabs[0]?.key ?? "services");
  return (
    <div className="stack">
      <PageHead
        title={t("nav.catalogue")}
        sub={t(
          "catalogue.sub",
          "Prices apply to new charges only; issued invoices keep the price they were billed at. Medicines are managed under Inventory.",
        )}
      />
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "services" && <Services />}
      {tab === "lab" && <LabTests />}
    </div>
  );
}

function Services() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const q = useGet<ServicePrice[]>(["services", "all"], "/billing/services/");
  const [editing, setEditing] = useState<ServicePrice | "new" | null>(null);
  return (
    <Panel
      flush
      actions={
        can("settings.manage") && (
          <button className="btn btn-sm" onClick={() => setEditing("new")}>
            <Plus size={15} aria-hidden /> {t("catalogue.add_service", "Add service")}
          </button>
        )
      }
      title={t("catalogue.services", "Service prices")}
    >
      {!q.data ? (
        <Loading />
      ) : !q.data.length ? (
        <Empty>{t("catalogue.no_services", "No services. Run the starter catalogue or add them here.")}</Empty>
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>{t("inventory.code", "Code")}</th>
              <th>{t("inventory.name", "Name")}</th>
              <th>{t("inventory.category", "Category")}</th>
              <th className="num">{t("inventory.price", "Price ETB")}</th>
              <th className="num">{t("billing.tax", "Tax")} %</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {q.data.map((s) => (
              <tr key={s.id} className={s.is_active ? "" : "muted"}>
                <td className="mono">{s.code}</td>
                <td>
                  {s.name}
                  {s.code === "CONSULT" && (
                    <div className="small subtle">
                      {t("catalogue.consult_note", "Added automatically to visits with a consultation")}
                    </div>
                  )}
                </td>
                <td>{s.category}</td>
                <td className="num">{money(s.price)}</td>
                <td className="num">{Number(s.tax_rate) || "—"}</td>
                <td className="num">
                  {can("settings.manage") && (
                    <button className="btn btn-sm" onClick={() => setEditing(s)}>
                      {t("common.edit", "Edit")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Modal
        open={editing !== null}
        title={
          editing === "new" ? t("catalogue.add_service", "Add service") : t("catalogue.edit_service", "Edit service")
        }
        onClose={() => setEditing(null)}
      >
        {editing && <ServiceForm service={editing === "new" ? undefined : editing} onDone={() => setEditing(null)} />}
      </Modal>
    </Panel>
  );
}

function ServiceForm({ service, onDone }: { service?: ServicePrice; onDone: () => void }) {
  const { t } = useTranslation();
  const [f, setF] = useState(
    service ?? { code: "", name: "", category: "procedure", price: "", tax_rate: "0", is_active: true },
  );
  const save = useAction(
    () =>
      service
        ? api.patch(`/billing/services/${service.id}/`, f, { ifMatch: service.row_version })
        : api.post("/billing/services/", f),
    [["services"]],
    onDone,
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
        <Field label={t("inventory.code", "Code")} id="sv-c" error={fieldErrors(save.error, "code")}>
          <input
            id="sv-c"
            value={f.code}
            disabled={!!service}
            onChange={(e) => setF({ ...f, code: e.target.value.toUpperCase() })}
          />
        </Field>
        <Field label={t("inventory.category", "Category")} id="sv-k">
          <select
            id="sv-k"
            value={f.category}
            onChange={(e) => setF({ ...f, category: e.target.value as ServicePrice["category"] })}
          >
            <option value="consultation">Consultation</option>
            <option value="procedure">Procedure</option>
            <option value="other">Other</option>
          </select>
        </Field>
        <Field label={t("inventory.name", "Name")} id="sv-n">
          <input id="sv-n" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label={t("inventory.price", "Price ETB")} id="sv-p" error={fieldErrors(save.error, "price")}>
          <input
            id="sv-p"
            type="number"
            min={0}
            step="0.01"
            value={f.price}
            onChange={(e) => setF({ ...f, price: e.target.value })}
          />
        </Field>
        <Field
          label={t("billing.tax_rate", "Tax rate %")}
          id="sv-t"
          error={fieldErrors(save.error, "tax_rate")}
          hint={t("billing.tax_hint", "0 unless the clinic's tax adviser confirms this service is taxable.")}
        >
          <input
            id="sv-t"
            type="number"
            min={0}
            max={100}
            step="0.01"
            value={f.tax_rate}
            onChange={(e) => setF({ ...f, tax_rate: e.target.value })}
          />
        </Field>
      </div>
      <label className="check">
        <input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />{" "}
        {t("common.active")}
      </label>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!f.code || !f.name || f.price === "" || save.isPending}>
          {t("common.save", "Save")}
        </button>
      </div>
    </form>
  );
}

function LabTests() {
  const { t } = useTranslation();
  const q = useGet<LabTest[]>(["lab-tests", "all"], "/lab/tests/");
  const [editing, setEditing] = useState<LabTest | "new" | null>(null);
  return (
    <Panel
      flush
      title={t("catalogue.lab", "Laboratory tests")}
      actions={
        <button className="btn btn-sm" onClick={() => setEditing("new")}>
          <Plus size={15} aria-hidden /> {t("catalogue.add_test", "Add test")}
        </button>
      }
    >
      {!q.data ? (
        <Loading />
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>{t("inventory.code", "Code")}</th>
              <th>{t("lab.test", "Test")}</th>
              <th>{t("lab.result_type", "Result")}</th>
              <th>{t("lab.reference", "Reference")}</th>
              <th className="num">{t("inventory.price", "Price ETB")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {q.data.map((lt) => (
              <tr key={lt.id} className={lt.is_active ? "" : "muted"}>
                <td className="mono">{lt.code}</td>
                <td>
                  <strong>{lt.name}</strong>
                  <div className="small subtle">
                    {lt.category}, {lt.specimen_type}
                  </div>
                </td>
                <td>
                  {lt.result_type}
                  {lt.choices && <div className="small subtle">{lt.choices}</div>}
                  {(lt.critical_low || lt.critical_high || lt.critical_choices) && (
                    <div className="small flag-H">{t("lab.has_critical", "Critical limits set")}</div>
                  )}
                  {lt.ranges.length > 0 && (
                    <div className="small subtle">
                      {t("lab.n_ranges", "{{n}} age/sex ranges", { n: lt.ranges.length })}
                    </div>
                  )}
                </td>
                <td className="small">
                  {lt.ref_low !== null || lt.ref_high !== null
                    ? `${lt.ref_low !== null ? qty(lt.ref_low) : ""}–${lt.ref_high !== null ? qty(lt.ref_high) : ""} ${lt.unit}`
                    : lt.ref_text || lt.normal_choice || "—"}
                </td>
                <td className="num">{money(lt.price)}</td>
                <td className="num">
                  {!lt.is_active && <Badge>{t("common.inactive")}</Badge>}{" "}
                  <button className="btn btn-sm" onClick={() => setEditing(lt)}>
                    {t("common.edit", "Edit")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Modal
        wide
        open={editing !== null}
        title={editing === "new" ? t("catalogue.add_test", "Add test") : t("catalogue.edit_test", "Edit test")}
        onClose={() => setEditing(null)}
      >
        {editing && <LabTestForm test={editing === "new" ? undefined : editing} onDone={() => setEditing(null)} />}
      </Modal>
    </Panel>
  );
}

function LabTestForm({ test, onDone }: { test?: LabTest; onDone: () => void }) {
  const { t } = useTranslation();
  const [f, setF] = useState<Record<string, string | boolean | null>>(
    test
      ? ({ ...test, ranges: null, answers: null } as unknown as Record<string, string | boolean | null>)
      : {
          code: "",
          name: "",
          category: "",
          specimen_type: "",
          result_type: "numeric",
          unit: "",
          ref_low: "",
          ref_high: "",
          ref_text: "",
          choices: "",
          normal_choice: "",
          critical_low: "",
          critical_high: "",
          critical_choices: "",
          price: "0",
          is_active: true,
        },
  );
  const [ranges, setRanges] = useState<LabRange[]>(test?.ranges ?? []);
  const nullable = (v: unknown) => (v === "" || v === undefined ? null : v);
  const body = () => {
    const { ranges: _r, answers: _a, ...rest } = f as Record<string, unknown>;
    void _r;
    void _a;
    return {
      ...rest,
      ref_low: nullable(f.ref_low),
      ref_high: nullable(f.ref_high),
      critical_low: nullable(f.critical_low),
      critical_high: nullable(f.critical_high),
    };
  };
  const save = useAction(
    async () => {
      const saved = test
        ? await api.patch<LabTest>(`/lab/tests/${test.id}/`, body(), { ifMatch: test.row_version })
        : await api.post<LabTest>("/lab/tests/", body());
      if (f.result_type === "numeric") {
        await api.put(
          `/lab/tests/${saved.id}/ranges/`,
          ranges.map((r) => ({
            ...r,
            ref_low: nullable(r.ref_low),
            ref_high: nullable(r.ref_high),
            critical_low: nullable(r.critical_low),
            critical_high: nullable(r.critical_high),
            age_max_days: nullable(r.age_max_days),
          })),
          { ifMatch: saved.row_version },
        );
      }
      return saved;
    },
    [["lab-tests"]],
    onDone,
    t("catalogue.test_saved", "Test saved"),
  );
  const input = (k: string, label: string, type = "text", hint?: string) => (
    <Field label={label} id={`lt-${k}`} error={fieldErrors(save.error, k)} hint={hint}>
      <input
        id={`lt-${k}`}
        type={type}
        step="any"
        value={String(f[k] ?? "")}
        disabled={k === "code" && !!test}
        onChange={(e) => setF({ ...f, [k]: e.target.value })}
      />
    </Field>
  );
  const setRange = (i: number, k: keyof LabRange, v: string) =>
    setRanges(ranges.map((r, n) => (n === i ? { ...r, [k]: k === "age_min_days" ? Number(v) || 0 : v } : r)));
  const listed = f.result_type === "choice" || f.result_type === "qualitative";
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined);
      }}
    >
      {test && (
        <Banner tone="info">
          {t(
            "catalogue.ref_note",
            "Changed reference ranges apply to new requests; results already ordered keep their original range.",
          )}
        </Banner>
      )}
      <ErrorBanner error={save.error} onReload={onDone} />
      <div className="form-grid">
        {input("code", t("inventory.code", "Code"))}
        {input("name", t("inventory.name", "Name"))}
        {input(
          "category",
          t("lab.department", "Department"),
          "text",
          t("lab.dept_hint", "e.g. Haematology, Chemistry, Parasitology, Serology"),
        )}
        {input("specimen_type", t("lab.specimen", "Specimen"))}
        <Field label={t("lab.result_type", "Result type")} id="lt-rt">
          <select
            id="lt-rt"
            value={String(f.result_type)}
            onChange={(e) => setF({ ...f, result_type: e.target.value })}
          >
            <option value="numeric">{t("lab.rt.numeric", "Number")}</option>
            <option value="qualitative">{t("lab.rt.qualitative", "Positive / negative")}</option>
            <option value="choice">{t("lab.rt.choice", "One of a list (categorical)")}</option>
            <option value="text">{t("lab.rt.text", "Free text")}</option>
          </select>
        </Field>
        {input("price", t("inventory.price", "Price ETB"), "number")}
        {f.result_type === "numeric" && (
          <>
            {input("unit", t("lab.unit", "Unit"))}
            {input("ref_low", t("lab.ref_low", "Normal from"), "number")}
            {input("ref_high", t("lab.ref_high", "Normal to"), "number")}
            {input("critical_low", t("lab.critical_low", "Critical at or below"), "number")}
            {input("critical_high", t("lab.critical_high", "Critical at or above"), "number")}
          </>
        )}
        {listed && (
          <>
            {input(
              "choices",
              t("lab.choices", "Options, comma-separated"),
              "text",
              f.result_type === "qualitative"
                ? t("lab.qual_hint", "Leave empty for Negative, Positive, Indeterminate")
                : undefined,
            )}
            {input(
              "normal_choice",
              t("lab.normal_choice", "Normal option"),
              "text",
              f.result_type === "qualitative" ? t("lab.qual_normal", "Empty means Negative") : undefined,
            )}
            {input("critical_choices", t("lab.critical_choices", "Critical options, comma-separated"))}
          </>
        )}
        {input("ref_text", t("lab.ref_text", "Reference note"))}
      </div>
      {f.result_type === "numeric" && (
        <fieldset className="fieldset">
          <legend>{t("lab.ranges", "Ranges by age and sex")}</legend>
          <p className="small muted">
            {t(
              "lab.ranges_hint",
              "The most specific matching row is used; otherwise the default range above. Ages in days (365 = 1 year). Empty 'to' means no upper age.",
            )}
          </p>
          {ranges.length > 0 && (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>{t("lab.sex", "Sex")}</th>
                    <th>{t("lab.age_from", "Age from (days)")}</th>
                    <th>{t("lab.age_to", "to (days)")}</th>
                    <th>{t("lab.ref_low", "Normal from")}</th>
                    <th>{t("lab.ref_high", "to")}</th>
                    <th>{t("lab.critical_low_s", "Critical ≤")}</th>
                    <th>{t("lab.critical_high_s", "Critical ≥")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {ranges.map((r, i) => (
                    <tr key={i}>
                      <td>
                        <select aria-label="Sex" value={r.sex} onChange={(e) => setRange(i, "sex", e.target.value)}>
                          <option value="">{t("lab.any", "Any")}</option>
                          <option value="female">F</option>
                          <option value="male">M</option>
                        </select>
                      </td>
                      {(
                        [
                          "age_min_days",
                          "age_max_days",
                          "ref_low",
                          "ref_high",
                          "critical_low",
                          "critical_high",
                        ] as const
                      ).map((k) => (
                        <td key={k}>
                          <input
                            aria-label={k}
                            type="number"
                            step="any"
                            style={{ width: 90 }}
                            value={r[k] ?? ""}
                            onChange={(e) => setRange(i, k, e.target.value)}
                          />
                        </td>
                      ))}
                      <td>
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={() => setRanges(ranges.filter((_, n) => n !== i))}
                        >
                          {t("common.remove", "Remove")}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <button
            type="button"
            className="btn btn-sm"
            style={{ marginTop: 8 }}
            onClick={() =>
              setRanges([
                ...ranges,
                {
                  sex: "",
                  age_min_days: 0,
                  age_max_days: null,
                  ref_low: "",
                  ref_high: "",
                  ref_text: "",
                  critical_low: "",
                  critical_high: "",
                },
              ])
            }
          >
            {t("lab.add_range", "Add range")}
          </button>
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
