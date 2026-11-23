/**
 * Phones: the clinic's app licence, activating staff phones with a one-time QR code, and switching phones off.
 * The server enforces every rule (licence, phone limit, one-use codes, hardware keys); this page explains them.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { KeyRound, Smartphone, ShieldCheck, ShieldAlert } from "lucide-react";
import { api, queryString } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { Paginated, User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Empty, ErrorBanner, Field, Loading, Modal, PageHead, Panel, fieldErrors } from "../ui";

interface Person {
  id: string;
  username: string;
  full_name: string;
}

export interface LicenceStatus {
  installation_id: string;
  active_devices: number;
  valid: boolean;
  problem: string;
  installed_at?: string | null;
  licence_id?: string;
  clinic_name?: string;
  mobile_app?: boolean;
  max_devices?: number;
  expires_on?: string;
  days_left?: number;
}

export interface Device {
  id: string;
  label: string;
  model_name: string;
  os_version: string;
  key_storage: "strongbox" | "tee" | "software";
  boot_state: string;
  status: "active" | "revoked";
  activated_at: string;
  last_seen_at: string | null;
  for_user: Person | null;
  last_user: Person | null;
  revoked_at: string | null;
  revoked_by: Person | null;
  revoke_reason: string;
}

interface ActivationCode {
  code: string;
  expires_at: string;
  qr_svg: string;
  clinic_name: string;
  address: string;
}

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "—");

export function PhonesPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const licence = useGet<LicenceStatus>(["devices", "licence"], "/devices/licence/");
  const devices = useGet<Paginated<Device>>(["devices", "list"], can("devices.manage") ? "/devices/" : null);
  const [activating, setActivating] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [revoking, setRevoking] = useState<Device | null>(null);
  const l = licence.data;
  const full = !!l?.valid && (l.max_devices ?? 0) <= l.active_devices;

  return (
    <div className="stack">
      <PageHead
        title={t("nav.phones", "Phones")}
        sub={t(
          "phones.sub",
          "Staff can use the phone app only on phones activated here. Each phone is locked to this clinic by a key in its security chip.",
        )}
        actions={
          can("devices.manage") && (
            <button
              className="btn btn-primary"
              disabled={!l?.valid || full}
              title={full ? t("phones.full", "All phones allowed by the licence are in use.") : undefined}
              onClick={() => setActivating(true)}
            >
              <Smartphone size={18} aria-hidden /> {t("phones.activate", "Activate a phone")}
            </button>
          )
        }
      />
      <ErrorBanner error={licence.error} />

      <Panel
        title={t("phones.licence", "App licence")}
        actions={
          can("system.security.manage") && (
            <button className="btn btn-sm" onClick={() => setInstalling(true)}>
              <KeyRound size={16} aria-hidden /> {t("phones.install", "Install licence")}
            </button>
          )
        }
      >
        {licence.isLoading || !l ? (
          <Loading />
        ) : (
          <div className="stack-sm">
            <div className="row">
              {l.valid ? (
                <Badge tone="ok">
                  <ShieldCheck size={14} aria-hidden /> {t("phones.licence_ok", "Valid")}
                </Badge>
              ) : (
                <Badge tone="danger">
                  <ShieldAlert size={14} aria-hidden /> {t("phones.licence_bad", "App not available")}
                </Badge>
              )}
              {l.clinic_name && <strong>{l.clinic_name}</strong>}
            </div>
            {l.problem && <p className="small">{l.problem}</p>}
            <dl className="facts">
              {l.max_devices !== undefined && (
                <>
                  <dt>{t("phones.in_use", "Phones in use")}</dt>
                  <dd>
                    {l.active_devices} / {l.max_devices}
                  </dd>
                </>
              )}
              {l.expires_on && (
                <>
                  <dt>{t("phones.until", "Licence until")}</dt>
                  <dd>
                    {l.expires_on}
                    {l.valid && (l.days_left ?? 99) <= 30 && (
                      <>
                        {" "}
                        <Badge tone="wait">
                          {t("phones.days_left", "{{n}} days left: ask your supplier to renew", { n: l.days_left })}
                        </Badge>
                      </>
                    )}
                  </dd>
                </>
              )}
              <dt>{t("phones.installation", "Installation ID")}</dt>
              <dd className="mono small">{l.installation_id}</dd>
            </dl>
            {!l.licence_id && (
              <p className="small muted">
                {t(
                  "phones.no_licence",
                  "Send the installation ID to your supplier. They will send a licence file to install here.",
                )}
              </p>
            )}
          </div>
        )}
      </Panel>

      {can("devices.manage") && (
        <Panel title={t("phones.list", "Activated phones")} flush>
          <ErrorBanner error={devices.error} />
          {devices.isLoading ? (
            <Loading />
          ) : !devices.data?.results.length ? (
            <Empty icon={<Smartphone size={28} aria-hidden />}>{t("phones.none", "No phones activated yet.")}</Empty>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>{t("phones.phone", "Phone")}</th>
                    <th>{t("phones.for", "For")}</th>
                    <th>{t("phones.last_used", "Last used")}</th>
                    <th>{t("phones.security", "Key")}</th>
                    <th>{t("users.status")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {devices.data.results.map((d) => (
                    <tr key={d.id} className={d.status === "active" ? "" : "muted"}>
                      <td>
                        <strong>{d.label || d.model_name || t("phones.unnamed", "Phone")}</strong>
                        <div className="small subtle">
                          {[d.model_name, d.os_version && `Android ${d.os_version}`].filter(Boolean).join(" · ")}
                        </div>
                        <div className="small subtle">
                          {t("phones.activated_on", "Activated {{when}}", { when: when(d.activated_at) })}
                        </div>
                      </td>
                      <td className="small">{d.for_user?.full_name ?? t("phones.anyone", "Any staff member")}</td>
                      <td className="small">
                        {when(d.last_seen_at)}
                        {d.last_user && <div className="subtle">{d.last_user.full_name}</div>}
                      </td>
                      <td className="small">
                        {d.key_storage === "software" ? (
                          <Badge tone="wait">{t("phones.key_software", "Not proven (test server)")}</Badge>
                        ) : d.key_storage === "strongbox" ? (
                          t("phones.key_strongbox", "Security chip")
                        ) : (
                          t("phones.key_tee", "Secure area")
                        )}
                      </td>
                      <td>
                        {d.status === "active" ? (
                          <Badge tone="ok">{t("phones.active", "Active")}</Badge>
                        ) : (
                          <Badge>
                            {t("phones.revoked", "Switched off")}
                            {d.revoke_reason ? `: ${d.revoke_reason}` : ""}
                          </Badge>
                        )}
                      </td>
                      <td className="num">
                        {d.status === "active" && (
                          <button className="btn btn-sm btn-danger" onClick={() => setRevoking(d)}>
                            {t("phones.revoke", "Switch off")}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      )}

      <Modal open={activating} title={t("phones.activate", "Activate a phone")} onClose={() => setActivating(false)}>
        {activating && <ActivateForm onDone={() => setActivating(false)} />}
      </Modal>
      <Modal open={installing} wide title={t("phones.install", "Install licence")} onClose={() => setInstalling(false)}>
        {installing && <InstallForm onDone={() => setInstalling(false)} />}
      </Modal>
      <Modal
        open={revoking !== null}
        title={t("phones.revoke_title", "Switch off this phone?")}
        onClose={() => setRevoking(null)}
      >
        {revoking && <RevokeForm device={revoking} onDone={() => setRevoking(null)} />}
      </Modal>
    </div>
  );
}

function ActivateForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [label, setLabel] = useState("");
  const [forUser, setForUser] = useState("");
  const [result, setResult] = useState<ActivationCode | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const staff = useGet<Paginated<User>>(
    ["users", "active-all"],
    `/users/${queryString({ is_active: "true", page_size: 100 })}`,
  );
  const create = useAction(
    () => api.post<ActivationCode>("/devices/activation-codes/", { label, for_user: forUser || null }),
    [["devices"]],
    (r) => setResult(r),
    false,
  );
  useEffect(() => {
    if (!result) return;
    const tick = () =>
      setSecondsLeft(Math.max(0, Math.round((new Date(result.expires_at).getTime() - Date.now()) / 1000)));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [result]);

  if (result) {
    const expired = secondsLeft === 0;
    return (
      <div className="stack-sm">
        <div className="activation">
          <div
            className={`mfa-qr activation-qr${expired ? " expired" : ""}`}
            aria-label={t("phones.qr_label", "Activation QR code for the Clinic MRS app")}
            dangerouslySetInnerHTML={{ __html: result.qr_svg }}
          />
          <ol className="steps-list">
            <li>{t("phones.step1", "On the phone, open the Clinic MRS app.")}</li>
            <li>{t("phones.step2", "Tap Scan activation code and point the camera at this code.")}</li>
            <li>
              {t("phones.step3", "Cannot scan? Choose Enter the code, then type the address and the code:")}
              <div className="mono secret-key">{result.address}</div>{" "}
              <div className="mono secret-key">{result.code}</div>
            </li>
          </ol>
        </div>
        <p className={`small ${expired ? "text-danger" : "muted"}`} role="status">
          {expired
            ? t("phones.expired", "This code has expired. Close and create a new one.")
            : t("phones.expires_in", "Works once, for {{m}}:{{s}} more.", {
                m: Math.floor(secondsLeft / 60),
                s: String(secondsLeft % 60).padStart(2, "0"),
              })}
        </p>
        <div className="form-actions">
          <button className="btn" onClick={onDone}>
            {t("common.close", "Close")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate(undefined);
      }}
    >
      <ErrorBanner error={create.error} />
      <Field
        label={t("phones.label", "Name for the phone (optional)")}
        id="ph-l"
        hint={t("phones.label_hint", "For example: Ward 2 phone, or Dr Hana's phone.")}
      >
        <input id="ph-l" value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} />
      </Field>
      <Field
        label={t("phones.for_user", "Only for this staff member (optional)")}
        id="ph-u"
        error={fieldErrors(create.error, "for_user")}
        hint={t(
          "phones.for_user_hint",
          "Leave empty for a shared phone. Everyone still signs in with their own account.",
        )}
      >
        <select id="ph-u" value={forUser} onChange={(e) => setForUser(e.target.value)}>
          <option value="">{t("phones.anyone", "Any staff member")}</option>
          {staff.data?.results.map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name} ({u.username})
            </option>
          ))}
        </select>
      </Field>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onDone}>
          {t("common.cancel", "Cancel")}
        </button>
        <button className="btn btn-primary" disabled={create.isPending}>
          {t("phones.make_code", "Show activation code")}
        </button>
      </div>
    </form>
  );
}

function InstallForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const install = useAction(
    () => api.post<LicenceStatus>("/devices/licence/", { licence: text.trim() }),
    [["devices"]],
    () => onDone(),
    t("phones.installed", "Licence installed"),
  );
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        install.mutate(undefined);
      }}
    >
      <ErrorBanner error={install.error} />
      <Field
        label={t("phones.licence_text", "Licence from your supplier")}
        id="ph-lic"
        error={fieldErrors(install.error, "licence")}
        hint={t("phones.licence_hint", "Open the licence file and paste its whole content. It starts with MRSL1.")}
      >
        <textarea
          id="ph-lic"
          rows={5}
          className="mono"
          value={text}
          onChange={(e) => setText(e.target.value)}
          required
        />
      </Field>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onDone}>
          {t("common.cancel", "Cancel")}
        </button>
        <button className="btn btn-primary" disabled={install.isPending || !text.trim()}>
          {t("phones.install", "Install licence")}
        </button>
      </div>
    </form>
  );
}

function RevokeForm({ device, onDone }: { device: Device; onDone: () => void }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const revoke = useAction(
    () => api.post<Device>(`/devices/${device.id}/revoke/`, { reason }),
    [["devices"]],
    () => onDone(),
    t("phones.revoked_toast", "Phone switched off"),
  );
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        revoke.mutate(undefined);
      }}
    >
      <p>
        {t(
          "phones.revoke_text",
          "Anyone signed in on {{name}} is signed out now, and the phone cannot sign in again until it is activated with a new code.",
          { name: device.label || device.model_name || t("phones.unnamed", "Phone") },
        )}
      </p>
      <ErrorBanner error={revoke.error} />
      <Field label={t("phones.reason", "Reason")} id="ph-r" error={fieldErrors(revoke.error, "reason")}>
        <input
          id="ph-r"
          value={reason}
          maxLength={200}
          placeholder={t("phones.reason_hint", "Lost, replaced, staff member left…")}
          onChange={(e) => setReason(e.target.value)}
          required
        />
      </Field>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onDone}>
          {t("common.cancel", "Cancel")}
        </button>
        <button className="btn btn-danger-solid" disabled={revoke.isPending || !reason.trim()}>
          {t("phones.revoke", "Switch off")}
        </button>
      </div>
    </form>
  );
}
