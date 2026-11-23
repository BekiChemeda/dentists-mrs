import { Cross } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ApiError, api } from "../api/client";
import { useGet } from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { formatLongDate } from "../lib/format";
import { Banner, ErrorBanner, Field, fieldErrors } from "../ui";

export function LoginPage() {
  const { user, login, loginWithCode } = useAuth();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = mfaToken ? await loginWithCode(mfaToken, code) : await login(username, password);
      if ("mfa_required" in result) {
        setMfaToken(result.mfa_token);
        setPassword("");
        return;
      }
      const from = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(result.must_change_password ? "/account/password" : from, { replace: true });
    } catch (err) {
      setError(err);
      setPassword("");
      setCode("");
      // An expired or refused second step starts again from the password.
      if (mfaToken && err instanceof ApiError && err.status === 400 && /expired/i.test(err.message)) setMfaToken(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <section className="auth-side" aria-hidden>
        <div className="big">{t("app.name")}</div>
        <div>
          <p className="big" style={{ fontSize: "2.2rem" }}>
            {formatLongDate(new Date())}
          </p>
          <p>
            {t(
              "auth.side_note",
              "Patient records stay on this clinic's own server. Sign in with your personal account; never share it.",
            )}
          </p>
        </div>
      </section>
      <section className="auth-form">
        <form onSubmit={onSubmit} noValidate className="stack-sm">
          <AuthBrand />
          <h1>{t("auth.sign_in")}</h1>
          <MaintenanceNotice />
          <ErrorBanner error={error} />
          {mfaToken ? (
            <>
              <p className="muted">
                {t(
                  "auth.mfa_prompt",
                  "Open your authenticator app and enter the 6-digit code for Clinic MRS. Lost your phone? Enter one of your recovery codes instead.",
                )}
              </p>
              <Field label={t("auth.mfa_code", "Code")} id="mfa-code">
                <input
                  id="mfa-code"
                  className="mono code-input"
                  inputMode="text"
                  autoComplete="one-time-code"
                  autoCapitalize="none"
                  spellCheck={false}
                  maxLength={11}
                  value={code}
                  onChange={(e) => setCode(e.target.value.trim())}
                  required
                  autoFocus
                />
              </Field>
              <button
                className="btn btn-primary"
                style={{ width: "100%" }}
                type="submit"
                disabled={busy || code.length < 6}
              >
                {busy ? t("auth.signing_in") : t("auth.verify", "Verify and sign in")}
              </button>
              <button
                type="button"
                className="link-btn small"
                onClick={() => {
                  setMfaToken(null);
                  setCode("");
                  setError(null);
                }}
              >
                {t("auth.start_again", "Use a different account")}
              </button>
            </>
          ) : (
            <>
              <Field label={t("auth.username")} id="username">
                <input
                  id="username"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  autoFocus
                />
              </Field>
              <Field label={t("auth.password")} id="password">
                <input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </Field>
              <button
                className="btn btn-primary"
                style={{ width: "100%" }}
                type="submit"
                disabled={busy || !username || !password}
              >
                {busy ? t("auth.signing_in") : t("auth.sign_in")}
              </button>
              <p className="small muted">{t("auth.forgot")}</p>
            </>
          )}
        </form>
      </section>
    </div>
  );
}

export function ChangePasswordPage() {
  const { user, refresh, logout } = useAuth();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const mismatch = confirm.length > 0 && next !== confirm;
  const forced = user?.must_change_password;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (mismatch) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/password/change/", { current_password: current, new_password: next });
      await refresh();
      setDone(true);
      setCurrent("");
      setNext("");
      setConfirm("");
      if (forced) navigate("/", { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const form = (
    <form className="panel" style={{ maxWidth: 460, padding: 28 }} onSubmit={onSubmit} noValidate>
      <div className="stack-sm">
        <h1>{t("auth.change_password")}</h1>
        {forced && <Banner tone="warn">{t("auth.must_change")}</Banner>}
        {done && <Banner tone="ok">{t("auth.password_changed")}</Banner>}
        {!!error &&
          fieldErrors(error, "current_password").length === 0 &&
          fieldErrors(error, "new_password").length === 0 && <ErrorBanner error={error} />}
        <Field label={t("auth.current_password")} id="current" error={fieldErrors(error, "current_password")}>
          <input
            id="current"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
        </Field>
        <Field
          label={t("auth.new_password")}
          id="new"
          error={fieldErrors(error, "new_password")}
          hint={t("auth.password_rules")}
        >
          <input
            id="new"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            required
          />
        </Field>
        <Field label={t("auth.confirm_password")} id="confirm" error={mismatch ? [t("auth.passwords_differ")] : []}>
          <input
            id="confirm"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
        </Field>
        <div className="form-actions">
          {forced && (
            <button type="button" className="btn" onClick={() => void logout()}>
              {t("auth.sign_out")}
            </button>
          )}
          <button className="btn btn-primary" type="submit" disabled={busy || !current || !next || mismatch}>
            {busy ? t("common.saving") : t("auth.save_password", "Save new password")}
          </button>
        </div>
      </div>
    </form>
  );
  return forced ? <div className="auth-single">{form}</div> : form;
}

function MaintenanceNotice() {
  const { t } = useTranslation();
  const q = useGet<{ maintenance_mode: boolean; maintenance_message: string }>(["system", "status"], "/system/status/");
  if (!q.data?.maintenance_mode) return null;
  return (
    <Banner tone="warn">
      <strong>{t("system.maintenance_active", "Maintenance mode is on.")}</strong>{" "}
      {q.data.maintenance_message ||
        t("system.maintenance_default", "Only system administrators can use the system until it ends.")}
    </Banner>
  );
}

/** Sign-in page mark: the clinic logo when one is set (public address), otherwise the product mark. */
function AuthBrand() {
  const [logo, setLogo] = useState<"loading" | "shown" | "none">("loading");
  return (
    <div className="brand auth-brand">
      {logo !== "none" && (
        <img
          className="auth-logo"
          src="/api/v1/branding/logo/"
          alt=""
          hidden={logo !== "shown"}
          onLoad={() => setLogo("shown")}
          onError={() => setLogo("none")}
        />
      )}
      {logo !== "shown" && (
        <>
          <span className="brand-mark" aria-hidden>
            <Cross size={17} strokeWidth={3} />
          </span>
          <span>
            clinic<span className="brand-muted">mrs</span>
          </span>
        </>
      )}
    </div>
  );
}
