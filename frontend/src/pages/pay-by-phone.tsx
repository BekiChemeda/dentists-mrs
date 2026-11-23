/**
 * Pay by phone: send a payment prompt (Chapa or telebirr) to the patient's phone and follow it until the
 * provider confirms. The server records the payment only on the provider's confirmation.
 */
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { CheckCircle2, Smartphone, XCircle } from "lucide-react";
import { api, queryString } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { Invoice, Paginated } from "../api/types";
import { ErrorBanner, Field, Segmented, fieldErrors, money } from "../ui";

export interface PayOption {
  provider: "chapa" | "telebirr";
  method: string;
  label: string;
}

export interface OnlinePayment {
  id: string;
  invoice: string;
  invoice_number: string;
  provider: string;
  method: string;
  method_label: string;
  phone: string;
  amount: string;
  reference: string;
  status: "pending" | "succeeded" | "failed" | "expired" | "cancelled" | "unapplied";
  status_label: string;
  message: string;
  receipt_number: string | null;
  created_at: string;
}

export function usePayOptions() {
  return useGet<{ options: PayOption[]; licensed: boolean }>(["payments", "options"], "/payments/options/", {
    staleTime: 60_000,
  });
}

export function PayByPhone({
  invoice,
  options,
  onPaid,
}: {
  invoice: Invoice;
  options: PayOption[];
  onPaid: (receiptNumber: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [choice, setChoice] = useState(`${options[0].provider}:${options[0].method}`);
  const [phone, setPhone] = useState(invoice.patient.phone ?? "");
  const [amount, setAmount] = useState(String(Number(invoice.balance)));
  const [current, setCurrent] = useState<OnlinePayment | null>(null);

  // A request already waiting (the modal was closed, or someone else sent it): follow that one.
  const waiting = useGet<Paginated<OnlinePayment>>(
    ["payments", "online", invoice.id, "pending"],
    `/payments/online/${queryString({ invoice: invoice.id, status: "pending" })}`,
  );
  useEffect(() => {
    if (!current && waiting.data?.results.length) setCurrent(waiting.data.results[0]);
  }, [waiting.data, current]);

  const [provider, method] = choice.split(":");
  const send = useAction(
    () => api.post<OnlinePayment>(`/billing/invoices/${invoice.id}/pay-by-phone/`, { provider, method, phone, amount }),
    [["payments", "online"]],
    (r) => setCurrent(r),
    false,
  );
  const stop = useAction(
    () => api.post<OnlinePayment>(`/payments/online/${current!.id}/cancel/`),
    [["payments", "online"]],
    (r) => setCurrent(r),
    false,
  );

  // Follow the request every 3 seconds while it waits.
  useEffect(() => {
    if (!current || current.status !== "pending") return;
    const id = window.setInterval(async () => {
      try {
        const r = await api.get<OnlinePayment>(`/payments/online/${current.id}/`);
        setCurrent(r);
      } catch {
        // A dropped connection: try again on the next tick.
      }
    }, 3000);
    return () => window.clearInterval(id);
  }, [current]);

  useEffect(() => {
    if (current?.status === "succeeded" && current.receipt_number) {
      void qc.invalidateQueries({ queryKey: ["invoice", invoice.id] });
      void qc.invalidateQueries({ queryKey: ["invoices"] });
      void qc.invalidateQueries({ queryKey: ["billing"] });
      void qc.invalidateQueries({ queryKey: ["payments"] });
    }
  }, [current?.status, current?.receipt_number, invoice.id, qc]);

  if (current) {
    const s = current.status;
    return (
      <div className="stack-sm" role="status" aria-live="polite">
        <div className={`phone-pay phone-pay-${s}`}>
          {s === "pending" ? (
            <span className="spinner" aria-hidden />
          ) : s === "succeeded" ? (
            <CheckCircle2 size={32} aria-hidden />
          ) : (
            <XCircle size={32} aria-hidden />
          )}
          <div>
            <strong>
              {s === "pending"
                ? t("pay.waiting", "Waiting for the patient to enter their PIN")
                : s === "succeeded"
                  ? t("pay.paid", "Paid")
                  : current.status_label}
            </strong>
            <div className="small">
              {current.method_label} · {current.phone} · {money(current.amount)} ETB
            </div>
            {current.message && s !== "pending" && <div className="small">{current.message}</div>}
            {s === "pending" && (
              <div className="small muted">
                {t("pay.waiting_hint", "The patient's phone shows a prompt. This screen updates by itself.")}
              </div>
            )}
          </div>
        </div>
        <ErrorBanner error={stop.error} />
        <div className="form-actions">
          {s === "pending" && (
            <button
              type="button"
              className="btn btn-danger"
              disabled={stop.isPending}
              onClick={() => stop.mutate(undefined)}
            >
              {t("pay.stop", "Stop waiting")}
            </button>
          )}
          {s === "succeeded" && current.receipt_number && (
            <button type="button" className="btn btn-primary" onClick={() => onPaid(current.receipt_number!)}>
              {t("pay.receipt", "Show receipt {{r}}", { r: current.receipt_number })}
            </button>
          )}
          {s !== "pending" && s !== "succeeded" && (
            <button type="button" className="btn" onClick={() => setCurrent(null)}>
              {t("pay.again", "Send again")}
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        send.mutate(undefined);
      }}
    >
      <ErrorBanner error={send.error} />
      <Segmented
        label={t("pay.method", "Pay with")}
        value={choice}
        onChange={setChoice}
        options={options.map((o) => ({
          key: `${o.provider}:${o.method}`,
          label: o.provider === "chapa" && o.method === "telebirr" ? `${o.label} (Chapa)` : o.label,
        }))}
      />
      <div className="form-grid">
        <Field
          label={t("pay.phone", "Patient's phone number")}
          id="pp-phone"
          error={fieldErrors(send.error, "phone")}
          hint={method === "mpesa" ? t("pay.mpesa_hint", "Safaricom number, starts with 07") : undefined}
        >
          <input
            id="pp-phone"
            inputMode="tel"
            autoComplete="off"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            required
          />
        </Field>
        <Field
          label={t("billing.amount", "Amount ETB")}
          id="pp-amount"
          error={fieldErrors(send.error, "amount")}
          hint={t("billing.balance_is", "Balance {{b}}", { b: money(invoice.balance) })}
        >
          <input
            id="pp-amount"
            type="number"
            min={0.01}
            step="0.01"
            max={Number(invoice.balance)}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </Field>
      </div>
      <p className="small muted">
        <Smartphone size={14} aria-hidden />{" "}
        {t(
          "pay.how",
          "The patient gets a prompt on this phone and enters only their PIN. Nothing is recorded until the payment is confirmed.",
        )}
      </p>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={send.isPending || !phone.trim() || !(Number(amount) > 0)}>
          {t("pay.send", "Send payment request")}
        </button>
      </div>
    </form>
  );
}
