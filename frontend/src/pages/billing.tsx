import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Banknote, FilePlus2, Printer, RotateCcw, Trash2 } from "lucide-react";
import { api, queryString } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { Approval, Invoice, Paginated, Payment, PatientBrief, ServicePrice, Visit } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { PAYMENT_METHODS, StateBadge, useStateLabel } from "../labels";
import { formatDateTime, formatDay } from "../lib/format";
import {
  Segmented,
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
  Tabs,
  money,
  printElement,
} from "../ui";
import { ClinicHeader, Ec, PatientLine, PatientPicker, todayIso, useClinic } from "./common";
import { PayByPhone, usePayOptions } from "./pay-by-phone";

type Tab = "open" | "all" | "payments";

export function BillingPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [tab, setTab] = useState<Tab>("open");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const status = tab === "open" ? "draft,issued,partial" : "";
  const invoices = useGet<Paginated<Invoice>>(
    ["invoices", tab, q, page],
    tab !== "payments" ? `/billing/invoices/${queryString({ status, q, page })}` : null,
  );
  const payments = useGet<Paginated<Payment>>(
    ["payments", "today"],
    tab === "payments" ? `/billing/payments/?date=${todayIso()}&page_size=100` : null,
  );
  const summary = useGet<DailySummary>(
    ["billing", "summary"],
    can("billing.payment", "reports.financial") ? "/billing/daily-summary/" : null,
    { refetchInterval: 60_000 },
  );
  const navigate = useNavigate();

  return (
    <div className="stack">
      <PageHead
        title={t("nav.billing")}
        sub={t("billing.sub", "Invoices, payments and receipts, in Ethiopian birr.")}
        actions={
          can("billing.invoice") && (
            <button className="btn btn-primary" onClick={() => setCreating(true)}>
              <FilePlus2 size={18} aria-hidden /> {t("billing.new", "New invoice")}
            </button>
          )
        }
      />
      {summary.data && <SummaryFigures s={summary.data} />}
      <Tabs
        value={tab}
        onChange={(k) => {
          setTab(k);
          setPage(1);
        }}
        tabs={[
          { key: "open", label: t("billing.open", "Open invoices") },
          { key: "all", label: t("billing.all", "All invoices") },
          { key: "payments", label: t("billing.payments_today", "Payments today") },
        ]}
      />
      {tab !== "payments" && (
        <>
          <div className="filters">
            <div className="field">
              <label htmlFor="bq">{t("billing.find", "Invoice number, MRN or name")}</label>
              <input
                id="bq"
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setPage(1);
                }}
              />
            </div>
          </div>
          <Panel flush>
            {invoices.isLoading ? (
              <Loading />
            ) : !invoices.data?.results.length ? (
              <Empty>{t("billing.none", "No invoices.")}</Empty>
            ) : (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>{t("billing.invoice", "Invoice")}</th>
                      <th>{t("patients.patient", "Patient")}</th>
                      <th>{t("common.date", "Date")}</th>
                      <th className="num">{t("billing.total", "Total")}</th>
                      <th className="num">{t("billing.paid", "Paid")}</th>
                      <th className="num">{t("billing.balance", "Balance")}</th>
                      <th>{t("common.status", "Status")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {invoices.data.results.map((i) => (
                      <tr key={i.id} className="clickable" onClick={() => navigate(`/billing/invoices/${i.id}`)}>
                        <td>
                          <Link to={`/billing/invoices/${i.id}`} className="mono" onClick={(e) => e.stopPropagation()}>
                            {i.number}
                          </Link>
                        </td>
                        <td>
                          {i.patient.full_name}
                          <div className="small subtle mono">{i.patient.mrn}</div>
                        </td>
                        <td className="nowrap">{formatDateTime(i.issued_at ?? i.created_at)}</td>
                        <td className="num">{money(i.total)}</td>
                        <td className="num">{money(i.amount_paid)}</td>
                        <td className="num">
                          <strong>{money(i.balance)}</strong>
                        </td>
                        <td>
                          <StateBadge set="invoice" value={i.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {invoices.data && <Pager page={page} count={invoices.data.count} pageSize={25} onPage={setPage} />}
          </Panel>
        </>
      )}
      {tab === "payments" && (
        <Panel flush>
          {!payments.data ? (
            <Loading />
          ) : !payments.data.results.length ? (
            <Empty>{t("billing.no_payments", "No payments today.")}</Empty>
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th>{t("billing.receipt", "Receipt")}</th>
                  <th>{t("common.time", "Time")}</th>
                  <th>{t("patients.patient", "Patient")}</th>
                  <th>{t("billing.method", "Method")}</th>
                  <th className="num">{t("billing.amount", "Amount")}</th>
                  <th>{t("billing.cashier", "Cashier")}</th>
                </tr>
              </thead>
              <tbody>
                {payments.data.results.map((p) => (
                  <tr key={p.id}>
                    <td className="mono">
                      <Link to={`/billing/invoices/${p.invoice}`}>{p.receipt_number}</Link>
                    </td>
                    <td>{formatDateTime(p.received_at)}</td>
                    <td>{p.patient_name}</td>
                    <td>
                      {PAYMENT_METHODS.find((m) => m.key === p.method)?.label}
                      {p.reference && <div className="small subtle">{p.reference}</div>}
                    </td>
                    <td className="num">{money(p.amount)}</td>
                    <td>{p.received_by.full_name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      )}
      <Modal open={creating} title={t("billing.new", "New invoice")} onClose={() => setCreating(false)}>
        <NewInvoiceForm onDone={(inv) => navigate(`/billing/invoices/${inv.id}`)} />
      </Modal>
    </div>
  );
}

export interface DailySummary {
  date: string;
  collected_total: string;
  payment_count: number;
  by_method: Record<string, string>;
  by_cashier: { cashier: string; total: string; count: number }[];
  invoiced_total: string;
  discounts_total: string;
  outstanding_total: string;
  outstanding_count: number;
}

export function SummaryFigures({ s }: { s: DailySummary }) {
  const { t } = useTranslation();
  return (
    <div className="figures">
      <div className="figure">
        <b>{money(s.collected_total)}</b>
        <span>{t("billing.collected_today", "Collected today, ETB ({{n}} receipts)", { n: s.payment_count })}</span>
      </div>
      {Object.entries(s.by_method).map(([m, v]) => (
        <div key={m} className="figure">
          <b>{money(v)}</b>
          <span>{PAYMENT_METHODS.find((x) => x.key === m)?.label ?? m}</span>
        </div>
      ))}
      <div className="figure attention">
        <b>{money(s.outstanding_total)}</b>
        <span>{t("billing.outstanding", "Outstanding, {{n}} invoices", { n: s.outstanding_count })}</span>
      </div>
    </div>
  );
}

function NewInvoiceForm({ onDone }: { onDone: (inv: Invoice) => void }) {
  const { t } = useTranslation();
  const stateLabel = useStateLabel();
  const [patient, setPatient] = useState<PatientBrief | null>(null);
  const [visit, setVisit] = useState("");
  const [visitTouched, setVisitTouched] = useState(false);
  const visits = useGet<Paginated<Visit>>(
    ["visits", "patient", patient?.id],
    patient ? `/visits/?patient=${patient.id}&page_size=10` : null,
  );
  // Most invoices are for today's visit: choose it unless the cashier picks something else.
  useEffect(() => {
    if (visitTouched || visit) return;
    const today = visits.data?.results.find((v) => v.visit_date === todayIso() && v.status !== "cancelled");
    if (today) setVisit(today.id);
  }, [visits.data, visitTouched, visit]);
  const create = useAction(
    () => api.post<Invoice>("/billing/invoices/", { patient_id: patient?.id, visit_id: visit || null }),
    [["invoices"]],
    onDone,
  );
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate(undefined);
      }}
    >
      <ErrorBanner error={create.error} />
      <div className="field">
        <span className="label">{t("patients.patient", "Patient")}</span>
        <PatientPicker
          value={patient}
          onChange={(p) => {
            setPatient(p);
            setVisit("");
            setVisitTouched(false);
          }}
          autoFocus
        />
      </div>
      {patient && (
        <Field
          label={t("billing.visit", "Visit")}
          id="ni-v"
          hint={t(
            "billing.visit_hint",
            "Linking a visit adds its consultation, laboratory and dispensed medicines automatically.",
          )}
        >
          <select
            id="ni-v"
            value={visit}
            onChange={(e) => {
              setVisit(e.target.value);
              setVisitTouched(true);
            }}
          >
            <option value="">
              {t("billing.no_visit", "No visit (counter sale, or orthodontic instalments only)")}
            </option>
            {visits.data?.results.map((v) => (
              <option key={v.id} value={v.id}>
                {formatDay(v.visit_date)}, {t("billing.ticket", "ticket")} {v.queue_number},{" "}
                {stateLabel("visit", v.status)}
              </option>
            ))}
          </select>
        </Field>
      )}
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!patient || create.isPending}>
          {t("billing.create", "Create invoice")}
        </button>
      </div>
    </form>
  );
}

export function InvoicePage() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const { can, user, moduleOn } = useAuth();
  const inv = useGet<Invoice>(["invoice", id], `/billing/invoices/${id}/`);
  // Approvals for this invoice (discount, void) and for its payments (refunds).
  const objectIds = [id, ...(inv.data?.payments ?? []).map((p) => p.id)].join(",");
  const approvals = useGet<Paginated<Approval>>(
    ["approvals", objectIds],
    inv.data ? `/approvals/?object_id=${objectIds}` : null,
  );
  const services = useGet<ServicePrice[]>(["services", "active"], "/billing/services/?active=true");
  const [paying, setPaying] = useState(false);
  const [discountOpen, setDiscountOpen] = useState(false);
  const [voidOpen, setVoidOpen] = useState(false);
  const [receipt, setReceipt] = useState<Payment | null>(null);
  const [refundFor, setRefundFor] = useState<Payment | null>(null);
  const [payOut, setPayOut] = useState<Approval | null>(null);
  const [serviceId, setServiceId] = useState("");
  const [svcQty, setSvcQty] = useState("1");
  const keys = [["invoice", id], ["invoices"], ["approvals"], ["billing"]];
  const act = useAction(
    (v: { action: string; body?: object }) => api.post<Invoice>(`/billing/invoices/${id}/${v.action}/`, v.body ?? {}),
    keys,
    () => {
      setDiscountOpen(false);
      setVoidOpen(false);
    },
  );
  const removeLine = useAction((lineId: string) => api.post(`/billing/lines/${lineId}/remove/`), keys);

  if (!inv.data) return inv.error ? <ErrorBanner error={inv.error} /> : <Loading />;
  const i = inv.data;
  const draft = i.status === "draft";
  const open = ["draft", "issued", "partial"].includes(i.status);
  const myApproved =
    approvals.data?.results.filter(
      (a) => a.status === "approved" && a.requested_by.id === user?.id && a.kind !== "refund",
    ) ?? [];
  const refundsToPay = approvals.data?.results.filter((a) => a.status === "approved" && a.kind === "refund") ?? [];
  const pending = approvals.data?.results.filter((a) => a.status === "pending") ?? [];

  return (
    <div className="stack">
      <PageHead
        title={`${t("billing.invoice", "Invoice")} ${i.number}`}
        sub={
          <>
            {t("billing.created", "Created {{when}}", { when: formatDateTime(i.created_at) })}
            {i.visit_date ? `, ${t("billing.for_visit", "visit of {{d}}", { d: formatDay(i.visit_date) })}` : ""}
          </>
        }
        actions={<StateBadge set="invoice" value={i.status} />}
      />
      <ErrorBanner error={act.error ?? removeLine.error} />
      {pending.map((a) => (
        <Banner key={a.id} tone="warn">
          {a.kind_label}: {t("billing.waiting_approval", "waiting for approval")} ({a.summary})
        </Banner>
      ))}
      {myApproved.map((a) => (
        <Banner key={a.id} tone="ok">
          <div className="row-between">
            <span>
              {a.kind_label} {t("billing.approved_by", "approved by {{who}}", { who: a.decided_by?.full_name })}.
            </span>
            <button
              className="btn btn-sm btn-primary"
              disabled={act.isPending}
              onClick={() =>
                act.mutate({ action: a.kind === "discount" ? "apply-discount" : "void", body: { approval_id: a.id } })
              }
            >
              {a.kind === "discount"
                ? t("billing.apply_discount", "Apply discount")
                : t("billing.void_now", "Void invoice")}
            </button>
          </div>
        </Banner>
      ))}
      {can("billing.payment") &&
        refundsToPay.map((a) => (
          <Banner key={a.id} tone="ok">
            <div className="row-between">
              <span>
                {a.summary}: {t("billing.approved_by", "approved by {{who}}", { who: a.decided_by?.full_name })}.
              </span>
              <button className="btn btn-sm btn-primary" onClick={() => setPayOut(a)}>
                {t("billing.pay_refund", "Pay out refund")}
              </button>
            </div>
          </Banner>
        ))}
      {i.status === "void" && (
        <Banner tone="error">
          {t("billing.voided", "This invoice is void.")} {i.void_reason}
        </Banner>
      )}

      <div className="split">
        <Panel
          flush
          title={<PatientLine patient={i.patient} link />}
          actions={
            draft &&
            can("billing.invoice") &&
            (i.visit || moduleOn("orthodontics")) && (
              <button className="btn btn-sm" onClick={() => act.mutate({ action: "pull-charges" })}>
                {i.visit
                  ? t("billing.pull", "Add visit charges")
                  : t("billing.pull_instalments", "Add orthodontic instalments due")}
              </button>
            )
          }
        >
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("billing.item", "Item")}</th>
                  <th className="num">{t("rx.quantity", "Qty")}</th>
                  <th className="num">{t("billing.unit_price", "Unit price")}</th>
                  <th className="num">{t("billing.amount", "Amount")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(i.lines ?? []).length === 0 && (
                  <tr>
                    <td colSpan={5} className="subtle">
                      {t("billing.no_lines", "No charges yet.")}
                    </td>
                  </tr>
                )}
                {(i.lines ?? []).map((l) => (
                  <tr key={l.id} className={l.is_void ? "muted" : ""}>
                    <td>
                      {l.description}
                      <div className="small subtle">
                        {l.kind}
                        {Number(l.tax_rate) > 0 && `, ${t("billing.tax", "Tax")} ${Number(l.tax_rate)}%`}
                      </div>
                    </td>
                    <td className="num">{Number(l.quantity)}</td>
                    <td className="num">{money(l.unit_price)}</td>
                    <td className="num">{money(l.line_total)}</td>
                    <td className="num">
                      {draft && can("billing.invoice") && (
                        <button
                          className="btn btn-sm btn-ghost btn-icon"
                          aria-label={t("common.remove", "Remove")}
                          onClick={() => removeLine.mutate(l.id)}
                        >
                          <Trash2 size={15} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={3}>{t("billing.subtotal", "Subtotal")}</td>
                  <td className="num">{money(i.subtotal)}</td>
                  <td />
                </tr>
                {Number(i.discount_amount) > 0 && (
                  <tr>
                    <td colSpan={3}>{t("billing.discount", "Discount")}</td>
                    <td className="num">−{money(i.discount_amount)}</td>
                    <td />
                  </tr>
                )}
                {Number(i.tax_amount) > 0 && (
                  <tr>
                    <td colSpan={3}>{t("billing.tax", "Tax")}</td>
                    <td className="num">{money(i.tax_amount)}</td>
                    <td />
                  </tr>
                )}
                <tr>
                  <td colSpan={3}>{t("billing.total", "Total")} ETB</td>
                  <td className="num" style={{ fontSize: "1.2rem" }}>
                    {money(i.total)}
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
          {draft && can("billing.invoice") && (
            <form
              className="row"
              style={{ padding: 16, borderTop: "1px solid var(--line-soft)" }}
              onSubmit={(e) => {
                e.preventDefault();
                act.mutate({ action: "lines", body: { service_id: serviceId, quantity: svcQty } });
                setServiceId("");
                setSvcQty("1");
              }}
            >
              <select
                className="grow"
                value={serviceId}
                onChange={(e) => setServiceId(e.target.value)}
                aria-label={t("billing.service", "Service")}
              >
                <option value="">{t("billing.add_service", "Add a service…")}</option>
                {services.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}, {money(s.price)} ETB
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={1}
                value={svcQty}
                onChange={(e) => setSvcQty(e.target.value)}
                style={{ width: 80 }}
                aria-label={t("rx.quantity", "Quantity")}
              />
              <button className="btn" disabled={!serviceId}>
                {t("common.add", "Add")}
              </button>
            </form>
          )}
        </Panel>

        <div className="stack">
          <Panel title={t("billing.payment", "Payment")}>
            <div className="figures" style={{ gap: 24 }}>
              <div className="figure">
                <b>{money(i.amount_paid)}</b>
                <span>{t("billing.paid", "Paid")}</span>
              </div>
              <div className={`figure${Number(i.balance) > 0 ? " attention" : ""}`}>
                <b>{money(i.balance)}</b>
                <span>{t("billing.balance", "Balance")} ETB</span>
              </div>
            </div>
            <div className="stack-sm" style={{ marginTop: 16 }}>
              {draft && can("billing.invoice") && (
                <button
                  className="btn btn-primary"
                  style={{ width: "100%" }}
                  disabled={!Number(i.subtotal) || act.isPending}
                  onClick={() => act.mutate({ action: "issue" })}
                >
                  {t("billing.issue", "Issue invoice")}
                </button>
              )}
              {(i.status === "issued" || i.status === "partial") && can("billing.payment") && (
                <button className="btn btn-primary" style={{ width: "100%" }} onClick={() => setPaying(true)}>
                  <Banknote size={18} aria-hidden /> {t("billing.take_payment", "Take payment")}
                </button>
              )}
              {open && can("billing.invoice", "billing.payment") && !pending.length && (
                <div className="row">
                  <button className="btn btn-sm" onClick={() => setDiscountOpen(true)}>
                    {t("billing.request_discount", "Request discount")}
                  </button>
                  {Number(i.amount_paid) === 0 && (
                    <button className="btn btn-sm btn-danger" onClick={() => setVoidOpen(true)}>
                      {t("billing.request_void", "Request void")}
                    </button>
                  )}
                </div>
              )}
            </div>
          </Panel>
          {(i.payments ?? []).length > 0 && (
            <Panel title={t("billing.receipts", "Receipts")} flush>
              <table className="data">
                <tbody>
                  {i.payments!.map((p) => (
                    <tr key={p.id}>
                      <td className="mono">
                        {p.receipt_number}
                        <div className="small subtle">{formatDateTime(p.received_at)}</div>
                      </td>
                      <td>
                        {PAYMENT_METHODS.find((m) => m.key === p.method)?.label}
                        {Number(p.refunded) > 0 && (
                          <div className="small subtle">
                            {t("billing.refunded_n", "Refunded {{a}}", { a: money(p.refunded) })}
                          </div>
                        )}
                      </td>
                      <td className="num">{money(p.amount)}</td>
                      <td className="num">
                        <div className="row" style={{ gap: 4, justifyContent: "flex-end", flexWrap: "nowrap" }}>
                          {can("billing.payment") &&
                            i.status !== "void" &&
                            Number(p.refundable) > 0 &&
                            !approvals.data?.results.some(
                              (a) => a.object_id === p.id && ["pending", "approved"].includes(a.status),
                            ) && (
                              <button
                                className="btn btn-sm btn-ghost btn-icon"
                                aria-label={t("billing.request_refund", "Request refund")}
                                title={t("billing.request_refund", "Request refund")}
                                onClick={() => setRefundFor(p)}
                              >
                                <RotateCcw size={16} />
                              </button>
                            )}
                          <button
                            className="btn btn-sm btn-ghost btn-icon"
                            aria-label={t("billing.print", "Print receipt")}
                            onClick={() => setReceipt(p)}
                          >
                            <Printer size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}
          {(i.refunds ?? []).length > 0 && (
            <Panel title={t("billing.refunds", "Refunds")} flush>
              <table className="data">
                <tbody>
                  {i.refunds!.map((r) => (
                    <tr key={r.id}>
                      <td className="mono">
                        {r.number}
                        <div className="small subtle">
                          {formatDateTime(r.refunded_at)}, {t("billing.against", "against")} {r.receipt_number}
                        </div>
                      </td>
                      <td>
                        {r.reason}
                        <div className="small subtle">
                          {t("billing.approved_by2", "Approved by {{a}}, paid by {{p}}", {
                            a: r.approved_by,
                            p: r.refunded_by,
                          })}
                        </div>
                      </td>
                      <td className="num">−{money(r.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}
        </div>
      </div>

      <Modal open={paying} title={t("billing.take_payment", "Take payment")} onClose={() => setPaying(false)}>
        {pending.some((a) => a.kind === "discount") && (
          <Banner tone="warn">
            {t(
              "billing.discount_pending_pay",
              "A discount on this invoice is still waiting for approval, so the balance below does not include it. Ask the manager to approve it first, or take only part of the payment.",
            )}
          </Banner>
        )}
        <PaymentForm
          invoice={i}
          onDone={(p) => {
            setPaying(false);
            setReceipt(p);
          }}
        />
      </Modal>
      <Modal
        open={discountOpen}
        title={t("billing.request_discount", "Request discount")}
        onClose={() => setDiscountOpen(false)}
      >
        <DiscountForm
          invoice={i}
          busy={act.isPending}
          error={act.error}
          onSubmit={(amount, reason) => act.mutate({ action: "request-discount", body: { amount, reason } })}
        />
      </Modal>
      <ReasonDialog
        open={voidOpen}
        title={t("billing.request_void", "Request void")}
        label={t("billing.void_reason", "Why must this invoice be voided?")}
        confirmLabel={t("billing.send_request", "Send for approval")}
        danger
        busy={act.isPending}
        error={act.error}
        onClose={() => setVoidOpen(false)}
        onConfirm={(reason) => act.mutate({ action: "request-void", body: { reason } })}
      />
      <Modal
        open={refundFor !== null}
        title={t("billing.request_refund", "Request refund")}
        onClose={() => setRefundFor(null)}
      >
        {refundFor && (
          <RefundRequestForm
            payment={refundFor}
            onDone={() => {
              setRefundFor(null);
              void approvals.refetch();
            }}
          />
        )}
      </Modal>
      <Modal open={payOut !== null} title={t("billing.pay_refund", "Pay out refund")} onClose={() => setPayOut(null)}>
        {payOut && (
          <RefundPayOutForm
            approval={payOut}
            invoiceId={i.id}
            onDone={() => {
              setPayOut(null);
              void approvals.refetch();
            }}
          />
        )}
      </Modal>
      <Modal open={receipt !== null} title={t("billing.receipt", "Receipt")} onClose={() => setReceipt(null)}>
        {receipt && <Receipt invoice={i} payment={receipt} />}
      </Modal>
    </div>
  );
}

function PaymentForm({ invoice, onDone }: { invoice: Invoice; onDone: (p: Payment) => void }) {
  const { t } = useTranslation();
  const options = usePayOptions();
  const [mode, setMode] = useState<"record" | "phone">("record");
  const phoneOptions = options.data?.options ?? [];
  const body =
    mode === "phone" && phoneOptions.length ? (
      <PayByPhone
        invoice={invoice}
        options={phoneOptions}
        onPaid={async (receipt) => {
          const fresh = await api.get<Invoice>(`/billing/invoices/${invoice.id}/`);
          const p = fresh.payments?.find((x) => x.receipt_number === receipt);
          if (p) onDone(p);
        }}
      />
    ) : (
      <RecordPaymentForm invoice={invoice} onDone={onDone} />
    );
  if (!phoneOptions.length) return body;
  return (
    <div className="stack-sm">
      <Segmented
        label={t("pay.how_paid", "How is the patient paying?")}
        value={mode}
        onChange={setMode}
        options={[
          { key: "record", label: t("pay.mode_record", "Cash or other") },
          { key: "phone", label: t("pay.mode_phone", "Pay by phone") },
        ]}
      />
      {body}
    </div>
  );
}

function RecordPaymentForm({ invoice, onDone }: { invoice: Invoice; onDone: (p: Payment) => void }) {
  const { t } = useTranslation();
  const [amount, setAmount] = useState(String(Number(invoice.balance)));
  const [method, setMethod] = useState("cash");
  const [reference, setReference] = useState("");
  const [tendered, setTendered] = useState("");
  const pay = useAction(
    () => api.post<Invoice>(`/billing/invoices/${invoice.id}/payments/`, { amount, method, reference }),
    [["invoice", invoice.id], ["invoices"], ["billing"], ["payments"]],
    (res) => res.new_payment && onDone(res.new_payment),
  );
  const change = Number(tendered) - Number(amount);
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        pay.mutate(undefined);
      }}
    >
      <ErrorBanner error={pay.error} />
      <div className="form-grid">
        <Field
          label={t("billing.amount", "Amount ETB")}
          id="p-a"
          hint={t("billing.balance_is", "Balance {{b}}", { b: money(invoice.balance) })}
        >
          <input
            id="p-a"
            type="number"
            min={0.01}
            step="0.01"
            max={Number(invoice.balance)}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            autoFocus
          />
        </Field>
        <Field label={t("billing.method", "Method")} id="p-m">
          <select id="p-m" value={method} onChange={(e) => setMethod(e.target.value)}>
            {PAYMENT_METHODS.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        {method === "cash" ? (
          <Field
            label={t("billing.tendered", "Cash received (optional)")}
            id="p-t"
            hint={change > 0 ? t("billing.change", "Change to give: {{c}}", { c: money(change) }) : undefined}
          >
            <input
              id="p-t"
              type="number"
              min={0}
              step="0.01"
              value={tendered}
              onChange={(e) => setTendered(e.target.value)}
            />
          </Field>
        ) : (
          <Field label={t("billing.reference", "Transaction reference")} id="p-r">
            <input id="p-r" value={reference} onChange={(e) => setReference(e.target.value)} />
          </Field>
        )}
      </div>
      <div className="form-actions">
        <button
          className="btn btn-primary"
          disabled={!(Number(amount) > 0) || (method !== "cash" && !reference.trim()) || pay.isPending}
        >
          {t("billing.record_payment", "Record payment")}
        </button>
      </div>
    </form>
  );
}

function DiscountForm({
  invoice,
  onSubmit,
  busy,
  error,
}: {
  invoice: Invoice;
  onSubmit: (amount: string, reason: string) => void;
  busy: boolean;
  error: unknown;
}) {
  const { t } = useTranslation();
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(amount, reason);
      }}
    >
      <Banner tone="info">
        {t("billing.discount_note", "A clinic administrator must approve the discount before it is applied.")}
      </Banner>
      <ErrorBanner error={error} />
      <Field
        label={t("billing.discount_amount", "Discount amount ETB")}
        id="dc-a"
        hint={t("billing.max_subtotal", "Up to {{s}}", { s: money(invoice.subtotal) })}
      >
        <input
          id="dc-a"
          type="number"
          min={0.01}
          step="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </Field>
      <Field label={t("common.reason", "Reason")} id="dc-r">
        <input id="dc-r" value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!(Number(amount) > 0) || !reason.trim() || busy}>
          {t("billing.send_request", "Send for approval")}
        </button>
      </div>
    </form>
  );
}

function RefundRequestForm({ payment, onDone }: { payment: Payment; onDone: () => void }) {
  const { t } = useTranslation();
  const [amount, setAmount] = useState(String(Number(payment.refundable ?? payment.amount)));
  const [reason, setReason] = useState("");
  const send = useAction(
    () => api.post(`/billing/payments/${payment.id}/request-refund/`, { amount, reason }),
    [["approvals"]],
    onDone,
    t("billing.refund_requested", "Refund sent for approval"),
  );
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        send.mutate(undefined);
      }}
    >
      <Banner tone="info">
        {t(
          "billing.refund_note",
          "A second person with approval rights must approve the refund. You then pay it out and it is recorded against receipt {{r}}.",
          { r: payment.receipt_number },
        )}
      </Banner>
      <ErrorBanner error={send.error} />
      <Field
        label={t("billing.refund_amount", "Refund amount ETB")}
        id="rf-a"
        hint={t("billing.max_refund", "Up to {{s}}", { s: money(payment.refundable ?? payment.amount) })}
      >
        <input
          id="rf-a"
          type="number"
          min={0.01}
          step="0.01"
          max={Number(payment.refundable ?? payment.amount)}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </Field>
      <Field label={t("common.reason", "Reason")} id="rf-r">
        <input
          id="rf-r"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={t("billing.refund_ph", "e.g. test not done, patient left")}
        />
      </Field>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!(Number(amount) > 0) || !reason.trim() || send.isPending}>
          {t("billing.send_request", "Send for approval")}
        </button>
      </div>
    </form>
  );
}

function RefundPayOutForm({
  approval,
  invoiceId,
  onDone,
}: {
  approval: Approval;
  invoiceId: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [method, setMethod] = useState("cash");
  const [reference, setReference] = useState("");
  const pay = useAction(
    () => api.post(`/billing/payments/${approval.object_id}/refund/`, { approval_id: approval.id, method, reference }),
    [["invoice", invoiceId], ["invoices"], ["billing"], ["payments"], ["approvals"]],
    onDone,
    t("billing.refunded_toast", "Refund paid and recorded"),
  );
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        pay.mutate(undefined);
      }}
    >
      <p>
        <strong>{money(approval.amount ?? "0")} ETB</strong> · {approval.reason}
      </p>
      <ErrorBanner error={pay.error} />
      <div className="form-grid">
        <Field label={t("billing.method", "Method")} id="ro-m">
          <select id="ro-m" value={method} onChange={(e) => setMethod(e.target.value)}>
            {PAYMENT_METHODS.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        {method !== "cash" && (
          <Field label={t("billing.reference", "Transaction reference")} id="ro-r">
            <input id="ro-r" value={reference} onChange={(e) => setReference(e.target.value)} />
          </Field>
        )}
      </div>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={(method !== "cash" && !reference.trim()) || pay.isPending}>
          {t("billing.pay_refund", "Pay out refund")}
        </button>
      </div>
    </form>
  );
}

function Receipt({ invoice, payment }: { invoice: Invoice; payment: Payment }) {
  const { t } = useTranslation();
  const clinic = useClinic();
  return (
    <div className="stack-sm">
      <div className="receipt" id="receipt">
        <ClinicHeader title={t("billing.receipt", "Receipt")} number={payment.receipt_number} />
        {clinic?.tin && <p className="small muted">TIN {clinic.tin}</p>}
        <p className="small muted">
          {formatDateTime(payment.received_at)}
          <Ec value={payment.received_at} />
        </p>
        <p style={{ marginTop: 12 }}>
          <strong>{invoice.patient.full_name}</strong> <span className="mono small">{invoice.patient.mrn}</span>
        </p>
        <p className="small">
          {t("billing.invoice", "Invoice")} {invoice.number}
        </p>
        <table>
          <tbody>
            {(invoice.lines ?? [])
              .filter((l) => !l.is_void)
              .map((l) => (
                <tr key={l.id}>
                  <td>
                    {l.description} × {Number(l.quantity)}
                  </td>
                  <td className="num">{money(l.line_total)}</td>
                </tr>
              ))}
            {Number(invoice.discount_amount) > 0 && (
              <tr>
                <td>{t("billing.discount", "Discount")}</td>
                <td className="num">−{money(invoice.discount_amount)}</td>
              </tr>
            )}
            {Number(invoice.tax_amount) > 0 && (
              <tr>
                <td>{t("billing.tax", "Tax")}</td>
                <td className="num">{money(invoice.tax_amount)}</td>
              </tr>
            )}
            <tr>
              <th>{t("billing.total", "Total")} ETB</th>
              <th className="num">{money(invoice.total)}</th>
            </tr>
            <tr>
              <td>
                {t("billing.this_payment", "This payment")} (
                {PAYMENT_METHODS.find((m) => m.key === payment.method)?.label}
                {payment.reference ? `, ${payment.reference}` : ""})
              </td>
              <td className="num">{money(payment.amount)}</td>
            </tr>
            <tr>
              <td>{t("billing.balance", "Balance")}</td>
              <td className="num">{money(invoice.balance)}</td>
            </tr>
          </tbody>
        </table>
        <p className="small muted">
          {t("billing.received_by", "Received by {{who}}", { who: payment.received_by.full_name })}
        </p>
      </div>
      <div className="form-actions no-print">
        <button className="btn btn-primary" onClick={() => printElement("receipt", t("billing.receipt", "Receipt"))}>
          <Printer size={16} aria-hidden /> {t("billing.print", "Print receipt")}
        </button>
      </div>
    </div>
  );
}
