/** System > Email: sending settings, provider help and the outbox. */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Mail, Send } from "lucide-react";
import { api, queryString } from "../api/client";
import { useGet } from "../api/hooks";
import type { EmailSettingsData, OutboundEmailRow, Paginated } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime } from "../lib/format";
import { Badge, Banner, Empty, ErrorBanner, Field, Loading, Pager, Panel, fieldErrors, toast } from "../ui";

type EmailForm = Pick<
  EmailSettingsData,
  "provider" | "host" | "port" | "security" | "username" | "from_email" | "from_name" | "reply_to" | "site_url"
> & { password: string };

const PROVIDERS: { key: EmailSettingsData["provider"]; title: string; text: string }[] = [
  {
    key: "cpanel",
    title: "Clinic email (cPanel)",
    text: "An address on the clinic's own website, e.g. mrs@myclinic.et, from its web host.",
  },
  { key: "brevo", title: "Brevo", text: "A sending service. Free for up to 300 emails a day." },
  { key: "custom", title: "Other email server", text: "Any server that accepts SMTP with a username and password." },
];

export function EmailPanel() {
  const { t } = useTranslation();
  const { can, user } = useAuth();
  const qc = useQueryClient();
  const q = useGet<EmailSettingsData>(["system", "email"], "/system/email/");
  const [f, setF] = useState<EmailForm | null>(null);
  const [testTo, setTestTo] = useState(user?.email ?? "");
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const editable = can("system.security.manage");
  const form: EmailForm | null =
    f ??
    (q.data
      ? {
          provider: q.data.provider,
          host: q.data.host,
          port: q.data.port,
          security: q.data.security,
          username: q.data.username,
          from_email: q.data.from_email,
          from_name: q.data.from_name,
          reply_to: q.data.reply_to,
          site_url: q.data.site_url,
          password: "",
        }
      : null);
  const save = useMutation({
    mutationFn: (body: Partial<EmailForm> & { enabled?: boolean }) =>
      api.patch<EmailSettingsData>("/system/email/", body, { ifMatch: q.data?.row_version }),
    onSuccess: (d) => {
      qc.setQueryData(["system", "email"], d);
      setF(null);
      toast(t("email.saved", "Email settings saved"));
    },
  });
  const test = useMutation({
    mutationFn: () =>
      api.post<{ ok: boolean; message: string }>("/system/email/test/", {
        ...(f ?? {}),
        password: f?.password || undefined,
        to: testTo,
      }),
    onSuccess: (r) => {
      setTestResult(r);
      void qc.invalidateQueries({ queryKey: ["system", "email"] });
    },
  });
  if (!q.data || !form) return q.error ? <ErrorBanner error={q.error} /> : <Loading />;
  const d = q.data;
  const set = (patch: Partial<EmailForm>) => {
    setF({ ...form, ...patch });
    setTestResult(null);
  };
  const pick = (provider: EmailForm["provider"]) => {
    const p = d.presets[provider];
    const domain = form.from_email.split("@")[1];
    set({
      provider,
      port: p.port,
      security: p.security,
      host: provider === "brevo" ? p.host : provider === "cpanel" ? (domain ? `mail.${domain}` : form.host) : form.host,
    });
  };
  const val = (k: keyof EmailForm) => ({
    value: String(form[k] ?? ""),
    disabled: !editable,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      set({ [k]: k === "port" ? Number(e.target.value) : e.target.value } as Partial<EmailForm>),
  });
  const err = (k: string) => fieldErrors(save.error, k);
  return (
    <div className="stack">
      <ErrorBanner error={save.error} onReload={() => setF(null)} />
      <Panel
        title={
          <div className="row" style={{ gap: 10 }}>
            <Mail size={18} aria-hidden />
            <h2>{t("email.title", "Email")}</h2>
            {d.enabled ? <Badge tone="ok">{t("common.on", "On")}</Badge> : <Badge>{t("common.off", "Off")}</Badge>}
          </div>
        }
      >
        <p className="small muted">
          {t(
            "email.help",
            "Sends alerts to staff by email: system problems, security notices about their own account, and (if they choose) notifications. Emails never contain patient names or results, only a link to sign in.",
          )}
        </p>
        <div className="offsite-controls">
          <label className="switch">
            <input
              type="checkbox"
              role="switch"
              checked={d.enabled}
              disabled={!editable || save.isPending || (!d.configured && !d.enabled)}
              onChange={(e) => save.mutate({ enabled: e.target.checked })}
            />
            <span>{d.enabled ? t("email.is_on", "Email is on") : t("email.is_off", "Email is off")}</span>
          </label>
          {!d.configured && (
            <span className="small muted">
              {t("email.fill_first", "Fill in the settings below and send a test first.")}
            </span>
          )}
        </div>
        {d.outbox.queued > 0 && (
          <Banner tone={d.enabled ? "warn" : "info"}>
            {t("email.queued", "{{n}} email(s) waiting to be sent.", { n: d.outbox.queued })}
            {d.outbox.oldest_queued_at &&
              ` ${t("email.oldest", "Oldest from {{when}}.", { when: formatDateTime(d.outbox.oldest_queued_at) })}`}
          </Banner>
        )}
      </Panel>

      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          if (f) save.mutate({ ...f, password: f.password || undefined });
        }}
      >
        <Panel title={t("email.provider", "1. How the clinic sends email")}>
          <div
            className="choice-cards"
            role="radiogroup"
            aria-label={t("email.provider", "How the clinic sends email")}
          >
            {PROVIDERS.map((p) => (
              <label key={p.key} className={`choice-card${form.provider === p.key ? " is-selected" : ""}`}>
                <input
                  type="radio"
                  name="provider"
                  checked={form.provider === p.key}
                  disabled={!editable}
                  onChange={() => pick(p.key)}
                />
                <strong>{t(`email.p_${p.key}`, p.title)}</strong>
                <span className="small muted">{t(`email.p_${p.key}_text`, p.text)}</span>
              </label>
            ))}
          </div>
          <EmailProviderHelp provider={form.provider} />
        </Panel>

        <Panel title={t("email.account", "2. Account details")}>
          <div className="form-grid">
            <Field
              label={t("email.from_email", "Send from (email address)")}
              id="em-from"
              error={err("from_email")}
              hint={
                form.provider === "brevo"
                  ? t("email.from_brevo", "Must be a sender or domain verified in Brevo.")
                  : t("email.from_cpanel", "Usually the same address as the username.")
              }
            >
              <input
                id="em-from"
                type="email"
                {...val("from_email")}
                placeholder="mrs@myclinic.et"
                onBlur={() => {
                  if (form.provider === "cpanel" && !form.host && form.from_email.includes("@"))
                    set({ host: `mail.${form.from_email.split("@")[1]}`, username: form.username || form.from_email });
                }}
              />
            </Field>
            <Field label={t("email.from_name", "Sender name")} id="em-name">
              <input id="em-name" {...val("from_name")} placeholder="Example Clinic" />
            </Field>
            <Field
              label={form.provider === "brevo" ? t("email.user_brevo", "SMTP login") : t("email.user", "Username")}
              id="em-user"
              error={err("username")}
              hint={
                form.provider === "brevo"
                  ? t("email.user_brevo_hint", "From Brevo › SMTP & API › SMTP, e.g. 9a1b2c001@smtp-brevo.com")
                  : t("email.user_hint", "The full email address")
              }
            >
              <input id="em-user" autoComplete="off" {...val("username")} />
            </Field>
            <Field
              label={form.provider === "brevo" ? t("email.pass_brevo", "SMTP key") : t("email.pass", "Password")}
              id="em-pass"
              error={err("password")}
              hint={
                d.password_set
                  ? t("email.pass_set", "Saved (hidden). Leave empty to keep it.")
                  : t("email.pass_none", "Stored encrypted; never shown again.")
              }
            >
              <input
                id="em-pass"
                type="password"
                autoComplete="new-password"
                value={form.password}
                disabled={!editable}
                onChange={(e) => set({ password: e.target.value })}
                placeholder={d.password_set ? "••••••••" : ""}
              />
            </Field>
          </div>
        </Panel>

        <Panel title={t("email.server", "3. Server")}>
          <div className="form-grid">
            <Field
              label={t("email.host", "Server name")}
              id="em-host"
              error={err("host")}
              hint={
                form.provider === "cpanel"
                  ? t(
                      "email.host_cpanel",
                      "Shown in cPanel › Email Accounts › Connect Devices (Outgoing server), often mail.yourdomain",
                    )
                  : undefined
              }
            >
              <input
                id="em-host"
                {...val("host")}
                placeholder={form.provider === "brevo" ? "smtp-relay.brevo.com" : "mail.myclinic.et"}
              />
            </Field>
            <Field label={t("email.security", "Security")} id="em-sec">
              <select
                id="em-sec"
                {...val("security")}
                onChange={(e) =>
                  set({ security: e.target.value as EmailForm["security"], port: e.target.value === "ssl" ? 465 : 587 })
                }
              >
                <option value="ssl">{t("email.ssl", "SSL/TLS (port 465)")}</option>
                <option value="starttls">{t("email.starttls", "STARTTLS (port 587)")}</option>
              </select>
            </Field>
            <Field label={t("email.port", "Port")} id="em-port" error={err("port")}>
              <input id="em-port" type="number" min={1} max={65535} {...val("port")} />
            </Field>
            <Field
              label={t("email.site_url", "Address of this system (for links)")}
              id="em-site"
              error={err("site_url")}
              hint={t("email.site_hint", "What staff type to open Clinic MRS, e.g. https://mrs.myclinic.local")}
            >
              <input id="em-site" type="url" {...val("site_url")} />
            </Field>
            <Field label={t("email.reply_to", "Replies go to (optional)")} id="em-reply" error={err("reply_to")}>
              <input id="em-reply" type="email" {...val("reply_to")} />
            </Field>
          </div>
        </Panel>

        <Panel title={t("email.test", "4. Send a test")}>
          <div className="row" style={{ gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
            <Field label={t("email.test_to", "Send a test to")} id="em-to">
              <input id="em-to" type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} />
            </Field>
            <button
              type="button"
              className="btn"
              disabled={!editable || !testTo || test.isPending}
              onClick={() => test.mutate()}
            >
              <Send size={16} aria-hidden />{" "}
              {test.isPending ? t("email.sending", "Sending…") : t("email.send_test", "Send test email")}
            </button>
          </div>
          <ErrorBanner error={test.error} />
          {testResult && <Banner tone={testResult.ok ? "ok" : "error"}>{testResult.message}</Banner>}
          {!testResult && d.last_test_at && (
            <p className="small muted" style={{ marginTop: 8 }}>
              {d.last_test_ok
                ? t("email.last_ok", "Last test succeeded {{when}}.", { when: formatDateTime(d.last_test_at) })
                : t("email.last_bad", "Last test failed {{when}}.", { when: formatDateTime(d.last_test_at) })}
            </p>
          )}
          <p className="small muted" style={{ marginTop: 8 }}>
            {t("email.test_note", "The test uses what is in the form, even before you save.")}
          </p>
        </Panel>

        {editable && (
          <div className="form-actions">
            {f && (
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setF(null);
                  setTestResult(null);
                }}
              >
                {t("common.cancel", "Cancel")}
              </button>
            )}
            <button className="btn btn-primary" disabled={!f || save.isPending}>
              {t("common.save", "Save")}
            </button>
          </div>
        )}
      </form>
      <OutboxPanel />
    </div>
  );
}

function EmailProviderHelp({ provider }: { provider: EmailSettingsData["provider"] }) {
  const { t } = useTranslation();
  if (provider === "brevo")
    return (
      <ol className="steps-list small" style={{ marginTop: 14 }}>
        <li>{t("email.b1", "Create a free account at brevo.com.")}</li>
        <li>
          {t(
            "email.b2",
            "Senders, Domains & Dedicated IPs: add and verify the clinic's address or domain (Brevo shows the DNS records to add).",
          )}
        </li>
        <li>{t("email.b3", "SMTP & API › SMTP: copy the SMTP login and create an SMTP key. Paste them below.")}</li>
      </ol>
    );
  if (provider === "cpanel")
    return (
      <ol className="steps-list small" style={{ marginTop: 14 }}>
        <li>
          {t("email.c1", "In cPanel › Email Accounts, create an address for the system, e.g. mrs@yourclinic.et.")}
        </li>
        <li>{t("email.c2", "Click Connect Devices next to it: it shows the outgoing server name and port.")}</li>
        <li>{t("email.c3", "Use the full address as the username and that account's password below.")}</li>
      </ol>
    );
  return (
    <p className="small muted" style={{ marginTop: 14 }}>
      {t(
        "email.custom_help",
        "Ask your email provider for the SMTP server name, port, security type, username and password.",
      )}
    </p>
  );
}

function OutboxPanel() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const q = useGet<Paginated<OutboundEmailRow>>(
    ["system", "outbox", status, page],
    `/system/email/outbox/${queryString({ status, page })}`,
    { refetchInterval: 30_000 },
  );
  const retry = useMutation({
    mutationFn: (id: number) => api.post(`/system/email/outbox/${id}/retry/`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["system", "outbox"] }),
  });
  const tone = { sent: "ok", queued: "wait", failed: "danger" } as const;
  return (
    <Panel
      flush
      title={t("email.outbox", "Sent and waiting")}
      actions={
        <select
          aria-label={t("email.filter", "Show")}
          value={status}
          onChange={(e) => {
            setPage(1);
            setStatus(e.target.value);
          }}
        >
          <option value="">{t("common.all")}</option>
          <option value="queued">{t("email.st_queued", "Waiting")}</option>
          <option value="sent">{t("email.st_sent", "Sent")}</option>
          <option value="failed">{t("email.st_failed", "Failed")}</option>
        </select>
      }
    >
      {!q.data?.results.length ? (
        <Empty>{t("email.none", "No emails yet.")}</Empty>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>{t("audit.when")}</th>
                <th>{t("email.to", "To")}</th>
                <th>{t("email.subject", "Subject")}</th>
                <th>{t("users.status")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {q.data.results.map((e) => (
                <tr key={e.id}>
                  <td className="nowrap">{formatDateTime(e.created_at)}</td>
                  <td className="small">{e.to_email}</td>
                  <td className="small">
                    {e.subject}
                    {e.last_error && <div className="small muted">{e.last_error}</div>}
                  </td>
                  <td>
                    <Badge tone={tone[e.status]}>{t(`email.st_${e.status}`, e.status)}</Badge>
                    {e.attempts > 1 && <span className="small muted"> ×{e.attempts}</span>}
                  </td>
                  <td className="num">
                    {e.status === "failed" && can("system.security.manage") && (
                      <button className="btn btn-sm" onClick={() => retry.mutate(e.id)}>
                        {t("email.retry", "Try again")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {q.data && <Pager page={page} count={q.data.count} pageSize={25} onPage={setPage} />}
    </Panel>
  );
}
