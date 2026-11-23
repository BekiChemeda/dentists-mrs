/** The signed-in user's two-step sign-in: set up, recovery codes, turn off. */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Copy, Printer, ShieldCheck, Smartphone } from "lucide-react";
import { api } from "../api/client";
import { useGet } from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime } from "../lib/format";
import { Badge, Banner, ErrorBanner, Field, Loading, PageHead, Panel, fieldErrors, toast } from "../ui";

interface MfaStatus {
  enabled: boolean;
  enabled_at: string | null;
  required: boolean;
  recovery_codes_left: number;
}
interface Setup {
  secret: string;
  uri: string;
  qr_svg: string;
}

export function AccountSecurityPage() {
  const { t } = useTranslation();
  const { user, refresh, logout } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const status = useGet<MfaStatus>(["auth", "mfa"], "/auth/mfa/");
  const [setup, setSetup] = useState<Setup | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [mode, setMode] = useState<"none" | "regenerate" | "disable">("none");
  const [password, setPassword] = useState("");
  const forced = !!user?.mfa_setup_required;

  const done = () => {
    void qc.invalidateQueries({ queryKey: ["auth", "mfa"] });
    setCode("");
    setPassword("");
    setMode("none");
  };
  const start = useMutation({
    mutationFn: () => api.post<Setup>("/auth/mfa/setup/"),
    onSuccess: (s) => {
      setSetup(s);
      setCode("");
    },
  });
  const confirm = useMutation({
    mutationFn: () => api.post<{ recovery_codes: string[] }>("/auth/mfa/confirm/", { code }),
    onSuccess: (r) => {
      setCodes(r.recovery_codes);
      setSetup(null);
      done();
      toast(t("mfa.on_toast", "Two-step sign-in is on"));
    },
  });
  const regenerate = useMutation({
    mutationFn: () => api.post<{ recovery_codes: string[] }>("/auth/mfa/recovery-codes/", { code }),
    onSuccess: (r) => {
      setCodes(r.recovery_codes);
      done();
    },
  });
  const disable = useMutation({
    mutationFn: () => api.post("/auth/mfa/disable/", { password, code }),
    onSuccess: () => {
      done();
      toast(t("mfa.off_toast", "Two-step sign-in is off"));
    },
  });

  if (!status.data) return status.error ? <ErrorBanner error={status.error} /> : <Loading />;
  const s = status.data;

  const finish = async () => {
    setCodes(null);
    await refresh();
    if (forced) navigate("/", { replace: true });
  };

  return (
    <div className={forced ? "forced-page stack" : "stack"}>
      <PageHead
        title={forced ? t("mfa.title", "Two-step sign-in") : t("mfa.page_title", "Security and alerts")}
        sub={t(
          "mfa.sub",
          "After your password, the system asks for a 6-digit code from an app on your phone. A stolen password alone is then not enough to get in.",
        )}
      />
      {forced && !codes && (
        <Banner tone="warn">
          {t(
            "mfa.forced",
            "Your role has access to sensitive settings, so two-step sign-in is required. Set it up now to continue.",
          )}
        </Banner>
      )}

      {codes ? (
        <Panel
          title={
            <div className="row" style={{ gap: 10 }}>
              <ShieldCheck size={18} aria-hidden />
              <h2>{t("mfa.codes_title", "Your recovery codes")}</h2>
            </div>
          }
        >
          <p>
            {t(
              "mfa.codes_help",
              "If you lose your phone, each of these codes lets you sign in once. They are shown only now. Print them or write them down and keep them somewhere safe, away from your phone.",
            )}
          </p>
          <ol className="recovery-codes mono">
            {codes.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ol>
          <div className="row" style={{ gap: 8 }}>
            <button
              type="button"
              className="btn"
              onClick={() => {
                void navigator.clipboard?.writeText(codes.join("\n"));
                toast(t("mfa.copied", "Copied"));
              }}
            >
              <Copy size={16} aria-hidden /> {t("mfa.copy", "Copy")}
            </button>
            <button type="button" className="btn" onClick={() => window.print()}>
              <Printer size={16} aria-hidden /> {t("mfa.print", "Print")}
            </button>
            <button type="button" className="btn btn-primary" onClick={() => void finish()}>
              {t("mfa.saved_codes", "I have saved them")}
            </button>
          </div>
        </Panel>
      ) : !s.enabled ? (
        <Panel
          title={
            <div className="row" style={{ gap: 10 }}>
              <Smartphone size={18} aria-hidden />
              <h2>{t("mfa.set_up", "Set up")}</h2>
              <Badge>{t("common.off", "Off")}</Badge>
            </div>
          }
        >
          {!setup ? (
            <div className="stack-sm">
              <p>
                {t(
                  "mfa.need_app",
                  "You need an authenticator app on your phone, for example Google Authenticator, Microsoft Authenticator or Aegis. They are free and work without internet.",
                )}
              </p>
              <ErrorBanner error={start.error} />
              <div>
                <button className="btn btn-primary" onClick={() => start.mutate()} disabled={start.isPending}>
                  {t("mfa.begin", "Begin set-up")}
                </button>
              </div>
            </div>
          ) : (
            <form
              className="mfa-setup"
              onSubmit={(e) => {
                e.preventDefault();
                confirm.mutate();
              }}
            >
              <div
                className="mfa-qr"
                aria-label={t("mfa.qr_label", "QR code for your authenticator app")}
                dangerouslySetInnerHTML={{ __html: setup.qr_svg }}
              />
              <div className="stack-sm">
                <ol className="steps-list">
                  <li>{t("mfa.step1", "In the app, choose to add an account and scan this code.")}</li>
                  <li>
                    {t("mfa.step2", "Cannot scan? Choose to enter a key and type:")}{" "}
                    <span className="mono secret-key">{setup.secret.match(/.{1,4}/g)?.join(" ")}</span>
                  </li>
                  <li>{t("mfa.step3", "Type the 6-digit code the app now shows.")}</li>
                </ol>
                <ErrorBanner error={confirm.error} />
                <Field label={t("auth.mfa_code", "Code")} id="mfa-new" error={fieldErrors(confirm.error, "code")}>
                  <input
                    id="mfa-new"
                    className="mono code-input"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                    autoFocus
                  />
                </Field>
                <div className="row" style={{ gap: 8 }}>
                  <button className="btn btn-primary" disabled={code.length !== 6 || confirm.isPending}>
                    {t("mfa.turn_on", "Turn on")}
                  </button>
                  <button type="button" className="btn" onClick={() => setSetup(null)}>
                    {t("common.cancel", "Cancel")}
                  </button>
                </div>
              </div>
            </form>
          )}
        </Panel>
      ) : (
        <Panel
          title={
            <div className="row" style={{ gap: 10 }}>
              <ShieldCheck size={18} aria-hidden />
              <h2>{t("mfa.status", "Status")}</h2>
              <Badge tone="ok">{t("common.on", "On")}</Badge>
            </div>
          }
        >
          <dl className="facts">
            <dt>{t("mfa.since", "Turned on")}</dt>
            <dd>{formatDateTime(s.enabled_at)}</dd>
            <dt>{t("mfa.codes_left", "Recovery codes left")}</dt>
            <dd>
              {s.recovery_codes_left <= 3 ? (
                <Badge tone="danger">{s.recovery_codes_left}</Badge>
              ) : (
                s.recovery_codes_left
              )}
            </dd>
            <dt>{t("mfa.required", "Required for your role")}</dt>
            <dd>{s.required ? t("common.yes", "Yes") : t("common.no", "No")}</dd>
          </dl>
          {mode === "none" ? (
            <div className="row" style={{ gap: 8, marginTop: 14 }}>
              <button className="btn" onClick={() => setMode("regenerate")}>
                {t("mfa.new_codes", "New recovery codes")}
              </button>
              {!s.required && (
                <button className="btn btn-danger" onClick={() => setMode("disable")}>
                  {t("mfa.turn_off", "Turn off")}
                </button>
              )}
            </div>
          ) : (
            <form
              className="stack-sm"
              style={{ marginTop: 14, maxWidth: 420 }}
              onSubmit={(e) => {
                e.preventDefault();
                if (mode === "regenerate") regenerate.mutate();
                else disable.mutate();
              }}
            >
              <p className="small muted">
                {mode === "regenerate"
                  ? t("mfa.regen_help", "Your old recovery codes stop working. Confirm with a code from your app.")
                  : t("mfa.off_help", "Confirm with your password and a code from your app.")}
              </p>
              <ErrorBanner error={regenerate.error ?? disable.error} />
              {mode === "disable" && (
                <Field label={t("auth.password")} id="mfa-pw" error={fieldErrors(disable.error, "password")}>
                  <input
                    id="mfa-pw"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </Field>
              )}
              <Field label={t("auth.mfa_code", "Code")} id="mfa-c">
                <input
                  id="mfa-c"
                  className="mono code-input"
                  autoComplete="one-time-code"
                  value={code}
                  onChange={(e) => setCode(e.target.value.trim())}
                  maxLength={11}
                />
              </Field>
              <div className="row" style={{ gap: 8 }}>
                <button
                  className={`btn ${mode === "disable" ? "btn-danger" : "btn-primary"}`}
                  disabled={code.length < 6}
                >
                  {t("common.confirm", "Confirm")}
                </button>
                <button type="button" className="btn" onClick={() => setMode("none")}>
                  {t("common.cancel", "Cancel")}
                </button>
              </div>
            </form>
          )}
        </Panel>
      )}
      {!forced && <EmailAlertsPanel />}
      {forced && !codes && (
        <button type="button" className="link-btn small" onClick={() => void logout()}>
          {t("auth.sign_out", "Sign out")}
        </button>
      )}
    </div>
  );
}

function EmailAlertsPanel() {
  const { t } = useTranslation();
  const { user, refresh } = useAuth();
  const save = useMutation({
    mutationFn: (email_alerts: string) => api.patch("/auth/me/email-alerts/", { email_alerts }),
    onSuccess: () => {
      void refresh();
      toast(t("common.saved_toast", "Changes saved"));
    },
  });
  if (!user) return null;
  const options = [
    {
      key: "important",
      label: t("alerts.important", "Important only"),
      text: t("alerts.important_text", "Emergencies, critical results, approvals, system problems"),
    },
    {
      key: "all",
      label: t("alerts.all", "Everything"),
      text: t("alerts.all_text", "Every notification you get in the system"),
    },
    {
      key: "off",
      label: t("alerts.off", "None"),
      text: t("alerts.off_text", "Only security notices about your own account"),
    },
  ];
  return (
    <Panel title={t("alerts.title", "Email alerts")}>
      <p className="small muted">
        {user.email
          ? t(
              "alerts.to",
              "Sent to {{email}} when the clinic has email set up. Emails never contain patient details.",
              { email: user.email },
            )
          : t("alerts.no_email", "No email address on your account. Ask an administrator to add one.")}
      </p>
      <ErrorBanner error={save.error} />
      <div
        className="choice-cards"
        role="radiogroup"
        aria-label={t("alerts.title", "Email alerts")}
        style={{ marginTop: 10 }}
      >
        {options.map((o) => (
          <label key={o.key} className={`choice-card${user.email_alerts === o.key ? " is-selected" : ""}`}>
            <input
              type="radio"
              name="email-alerts"
              checked={user.email_alerts === o.key}
              disabled={save.isPending}
              onChange={() => save.mutate(o.key)}
            />
            <strong>{o.label}</strong>
            <span className="small muted">{o.text}</span>
          </label>
        ))}
      </div>
    </Panel>
  );
}
