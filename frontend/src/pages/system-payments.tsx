/** System > Payments by phone: Chapa and telebirr merchant settings. Keys are never shown again once saved. */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import { Badge, Banner, ErrorBanner, Field, Loading, Panel, fieldErrors, toast } from "../ui";

interface PaymentSettings {
  licensed: boolean;
  chapa_enabled: boolean;
  chapa_methods: string[];
  chapa_secret_key_set: boolean;
  chapa_webhook_secret_set: boolean;
  chapa_webhook_path: string;
  telebirr_enabled: boolean;
  telebirr_endpoint: string;
  telebirr_third_party_id: string;
  telebirr_identifier: string;
  telebirr_identifier_type: string;
  telebirr_short_code: string;
  telebirr_public_base_url: string;
  telebirr_password_set: boolean;
  telebirr_security_credential_set: boolean;
  telebirr_result_url: string;
}

const CHAPA_METHODS = [
  { key: "telebirr", label: "telebirr" },
  { key: "mpesa", label: "M-Pesa" },
  { key: "cbebirr", label: "CBE Birr" },
  { key: "ebirr", label: "E-birr" },
];

type Secrets = {
  chapa_secret_key: string;
  chapa_webhook_secret: string;
  telebirr_password: string;
  telebirr_security_credential: string;
};
const NO_SECRETS: Secrets = {
  chapa_secret_key: "",
  chapa_webhook_secret: "",
  telebirr_password: "",
  telebirr_security_credential: "",
};

export function PaymentsPanel() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useGet<PaymentSettings>(["settings", "payments"], "/settings/payments/");
  const [f, setF] = useState<PaymentSettings | null>(null);
  const [secrets, setSecrets] = useState<Secrets>(NO_SECRETS);
  const [testResult, setTestResult] = useState<string | null>(null);
  const form = f ?? q.data ?? null;

  const save = useAction(
    () => api.patch<PaymentSettings>("/settings/payments/", { ...form, ...secrets }),
    [["payments"]],
    (d) => {
      qc.setQueryData(["settings", "payments"], d);
      setF(null);
      setSecrets(NO_SECRETS);
    },
    t("payments.saved", "Payment settings saved"),
  );
  const test = useAction(
    (provider: string) => api.post<{ message: string }>("/settings/payments/test/", { provider }),
    [],
    (r) => {
      setTestResult(r.message);
      toast(r.message);
    },
    false,
  );

  if (q.isLoading || !form) return <Loading />;
  if (!form.licensed) {
    return (
      <Panel>
        <Banner tone="info">
          {t(
            "payments.not_licensed",
            "Payments by phone are not part of this clinic's licence. Cash and other payments are recorded as usual. Contact your supplier to add them.",
          )}
        </Banner>
      </Panel>
    );
  }
  const set = (patch: Partial<PaymentSettings>) => setF({ ...form, ...patch });
  const secret = (k: keyof Secrets, label: string, isSet: boolean) => (
    <Field
      label={label}
      id={`ps-${k}`}
      error={fieldErrors(save.error, k)}
      hint={isSet ? t("payments.secret_set", "Saved. Leave empty to keep it.") : undefined}
    >
      <input
        id={`ps-${k}`}
        type="password"
        autoComplete="off"
        value={secrets[k]}
        placeholder={isSet ? "••••••••" : ""}
        onChange={(e) => setSecrets({ ...secrets, [k]: e.target.value })}
      />
    </Field>
  );

  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined);
      }}
    >
      <ErrorBanner error={save.error} />
      <ErrorBanner error={test.error} />
      {testResult && <Banner tone="ok">{testResult}</Banner>}

      <Panel
        title="Chapa"
        actions={
          <label className="check">
            <input
              type="checkbox"
              checked={form.chapa_enabled}
              onChange={(e) => set({ chapa_enabled: e.target.checked })}
            />{" "}
            {form.chapa_enabled ? <Badge tone="ok">{t("payments.on", "On")}</Badge> : t("payments.off", "Off")}
          </label>
        }
      >
        <p className="small muted">
          {t(
            "payments.chapa_help",
            "The clinic's own verified Chapa account. Money goes to the clinic. Use the test key first, then the live key.",
          )}
        </p>
        <div className="form-grid">
          {secret("chapa_secret_key", t("payments.chapa_key", "Secret key"), form.chapa_secret_key_set)}
          {secret(
            "chapa_webhook_secret",
            t("payments.chapa_webhook", "Webhook secret hash (optional)"),
            form.chapa_webhook_secret_set,
          )}
        </div>
        <fieldset className="stack-sm">
          <legend className="small">{t("payments.methods", "Methods to offer")}</legend>
          {CHAPA_METHODS.map((m) => (
            <label key={m.key} className="check">
              <input
                type="checkbox"
                checked={form.chapa_methods.includes(m.key)}
                onChange={(e) =>
                  set({
                    chapa_methods: e.target.checked
                      ? [...form.chapa_methods, m.key]
                      : form.chapa_methods.filter((x) => x !== m.key),
                  })
                }
              />{" "}
              {m.label}
            </label>
          ))}
        </fieldset>
        <p className="small muted">
          {t(
            "payments.webhook_where",
            "Webhook address for the Chapa dashboard, if this server is reachable from the internet:",
          )}{" "}
          <span className="mono">https://&lt;public address&gt;{form.chapa_webhook_path}</span>
        </p>
        <div className="form-actions">
          <button
            type="button"
            className="btn"
            disabled={!form.chapa_secret_key_set || test.isPending}
            onClick={() => test.mutate("chapa")}
          >
            {t("payments.test", "Test connection")}
          </button>
        </div>
      </Panel>

      <Panel
        title={t("payments.telebirr", "telebirr (direct merchant)")}
        actions={
          <label className="check">
            <input
              type="checkbox"
              checked={form.telebirr_enabled}
              onChange={(e) => set({ telebirr_enabled: e.target.checked })}
            />{" "}
            {form.telebirr_enabled ? <Badge tone="ok">{t("payments.on", "On")}</Badge> : t("payments.off", "Off")}
          </label>
        }
      >
        <p className="small muted">
          {t(
            "payments.telebirr_help",
            "The clinic's telebirr merchant account from Ethio Telecom. telebirr sends results to this server's public address, so the server must be reachable from the internet.",
          )}
        </p>
        <div className="form-grid">
          <Field
            label={t("payments.endpoint", "Endpoint URL")}
            id="ps-te"
            error={fieldErrors(save.error, "telebirr_endpoint")}
          >
            <input
              id="ps-te"
              value={form.telebirr_endpoint}
              onChange={(e) => set({ telebirr_endpoint: e.target.value })}
            />
          </Field>
          <Field label={t("payments.third_party", "Third-party ID")} id="ps-tp">
            <input
              id="ps-tp"
              value={form.telebirr_third_party_id}
              onChange={(e) => set({ telebirr_third_party_id: e.target.value })}
            />
          </Field>
          {secret("telebirr_password", t("payments.tb_password", "Password"), form.telebirr_password_set)}
          <Field label={t("payments.identifier", "Initiator identifier")} id="ps-ti">
            <input
              id="ps-ti"
              value={form.telebirr_identifier}
              onChange={(e) => set({ telebirr_identifier: e.target.value })}
            />
          </Field>
          {secret(
            "telebirr_security_credential",
            t("payments.credential", "Security credential"),
            form.telebirr_security_credential_set,
          )}
          <Field label={t("payments.short_code", "Short code")} id="ps-sc">
            <input
              id="ps-sc"
              value={form.telebirr_short_code}
              onChange={(e) => set({ telebirr_short_code: e.target.value })}
            />
          </Field>
          <Field
            label={t("payments.public_address", "This server's public address")}
            id="ps-pa"
            hint="https://mrs.myclinic.et"
            error={fieldErrors(save.error, "telebirr_public_base_url")}
          >
            <input
              id="ps-pa"
              value={form.telebirr_public_base_url}
              onChange={(e) => set({ telebirr_public_base_url: e.target.value })}
            />
          </Field>
        </div>
        {form.telebirr_result_url && (
          <p className="small">
            {t("payments.result_url", "Result address (give it to Ethio Telecom if asked; keep it private):")}{" "}
            <span className="mono">{form.telebirr_result_url}</span>
          </p>
        )}
        <p className="small muted">
          {t(
            "payments.egress",
            "Also add the endpoint's host name to EGRESS_ALLOWED_HOSTS in the server's .env, then restart. See docs/operations/payments.md.",
          )}
        </p>
      </Panel>

      <div className="form-actions">
        <button className="btn btn-primary" disabled={save.isPending}>
          {t("common.save", "Save")}
        </button>
      </div>
    </form>
  );
}
