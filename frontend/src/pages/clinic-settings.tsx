/** Clinic settings: facility details, waiting list, document notes, logo, opening hours, modules (read-only). */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useGet } from "../api/hooks";
import type { ClinicSettings } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ConfirmDialog, ErrorBanner, Field, Loading, PageHead, Panel, fieldErrors, toast } from "../ui";
import { ModulesPanel } from "./modules";
import { OpeningHoursPanel } from "./setup";

const FACILITY_LEVELS = [
  { key: "medium_clinic", label: "Medium clinic" },
  { key: "specialty_clinic", label: "Specialty clinic" },
  { key: "specialty_center", label: "Specialty center" },
  { key: "hospital", label: "Hospital" },
  { key: "other", label: "Other" },
];
const LAB_BILLING_POINTS = [
  { key: "ordered", label: "When the test is requested" },
  { key: "collected", label: "When the specimen is collected" },
  { key: "verified", label: "When the result is verified" },
];

/** Facility details printed on receipts, referrals and certificates, and the billing policy. */
export function ClinicSettingsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useGet<ClinicSettings>(["settings", "clinic"], "/settings/clinic/");
  const [f, setF] = useState<ClinicSettings | null>(null);
  const save = useMutation({
    mutationFn: (body: ClinicSettings) =>
      api.patch<ClinicSettings>("/settings/clinic/", body, { ifMatch: q.data?.row_version }),
    onSuccess: (data) => {
      qc.setQueryData(["settings", "clinic"], data);
      setF(null);
      toast(t("clinic.saved", "Clinic settings saved"));
    },
  });
  if (!q.data) return q.error ? <ErrorBanner error={q.error} /> : <Loading />;
  const v = f ?? q.data;
  const set = <K extends keyof ClinicSettings>(k: K, value: ClinicSettings[K]) => setF({ ...v, [k]: value });
  return (
    <div className="stack">
      <PageHead
        title={t("nav.clinic", "Clinic settings")}
        sub={t(
          "clinic.sub",
          "Printed on receipts, referral letters and certificates. Every change is written to the audit log.",
        )}
      />
      {can("branding.manage") && <LogoPanel clinic={q.data} />}
      {!can("settings.manage") ? (
        <Panel title={t("clinic.facility", "Facility")}>
          <p className="muted">{t("clinic.readonly", "The clinic administrator keeps these details up to date.")}</p>
          <dl className="facts">
            <dt>{t("clinic.name", "Facility name")}</dt>
            <dd>{v.facility_name}</dd>
            <dt>{t("clinic.address", "Address")}</dt>
            <dd>{v.address || "—"}</dd>
            <dt>{t("clinic.phone", "Phone")}</dt>
            <dd>{v.phone || "—"}</dd>
          </dl>
        </Panel>
      ) : (
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(v);
          }}
        >
          <ErrorBanner error={save.error} onReload={() => setF(null)} />
          <Panel title={t("clinic.facility", "Facility")}>
            <div className="form-grid">
              <Field
                label={t("clinic.name", "Facility name")}
                id="cs-n"
                error={fieldErrors(save.error, "facility_name")}
              >
                <input
                  id="cs-n"
                  value={v.facility_name}
                  onChange={(e) => set("facility_name", e.target.value)}
                  required
                />
              </Field>
              <Field
                label={t("clinic.level", "Facility level")}
                id="cs-l"
                hint={t(
                  "clinic.level_hint",
                  "Decides which controlled medicines may be prescribed (EFDA Directive 1121/2025).",
                )}
              >
                <select id="cs-l" value={v.facility_level} onChange={(e) => set("facility_level", e.target.value)}>
                  {FACILITY_LEVELS.map((l) => (
                    <option key={l.key} value={l.key}>
                      {l.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t("clinic.licence", "Licence number")} id="cs-lic">
                <input id="cs-lic" value={v.license_number} onChange={(e) => set("license_number", e.target.value)} />
              </Field>
              <Field label="TIN" id="cs-tin" error={fieldErrors(save.error, "tin")}>
                <input id="cs-tin" value={v.tin} inputMode="numeric" onChange={(e) => set("tin", e.target.value)} />
              </Field>
              <Field label={t("clinic.address", "Address")} id="cs-a">
                <input id="cs-a" value={v.address} onChange={(e) => set("address", e.target.value)} />
              </Field>
              <Field label={t("clinic.phone", "Phone")} id="cs-p">
                <input id="cs-p" value={v.phone} onChange={(e) => set("phone", e.target.value)} />
              </Field>
            </div>
          </Panel>
          <Panel title={t("clinic.policy", "Billing and display")}>
            <div className="form-grid">
              <Field
                label={t("clinic.lab_billing", "Charge laboratory tests")}
                id="cs-lb"
                hint={t(
                  "clinic.lab_billing_hint",
                  "Tests not yet at this point are left off the invoice, so patients are not charged for tests never done.",
                )}
              >
                <select
                  id="cs-lb"
                  value={v.lab_billing_point}
                  onChange={(e) => set("lab_billing_point", e.target.value as ClinicSettings["lab_billing_point"])}
                >
                  {LAB_BILLING_POINTS.map((l) => (
                    <option key={l.key} value={l.key}>
                      {l.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <label className="check" style={{ marginTop: 12 }}>
              <input
                type="checkbox"
                checked={v.show_ethiopian_calendar}
                onChange={(e) => set("show_ethiopian_calendar", e.target.checked)}
              />{" "}
              {t("clinic.show_ec", "Show Ethiopian calendar dates beside Gregorian dates")}
            </label>
          </Panel>
          <Panel title={t("clinic.waiting_list", "Waiting list")}>
            <div className="form-grid">
              <Field
                label={t("clinic.wait_alert", "Highlight patients waiting longer than (minutes)")}
                id="cs-wait"
                error={fieldErrors(save.error, "wait_alert_minutes")}
              >
                <input
                  id="cs-wait"
                  type="number"
                  min={10}
                  max={480}
                  value={v.wait_alert_minutes ?? 60}
                  onChange={(e) => set("wait_alert_minutes", Number(e.target.value))}
                />
              </Field>
              <Field
                label={t("clinic.auto_close", "Close finished visits automatically")}
                id="cs-auto"
                error={fieldErrors(save.error, "auto_complete_minutes")}
                hint={t(
                  "clinic.auto_close_hint",
                  "A visit closes by itself this long after the doctor signs, but only when nothing is left: tests verified, medicines dispensed, bill paid. Visits with anything open still wait for staff.",
                )}
              >
                <select
                  id="cs-auto"
                  value={String(v.auto_complete_minutes ?? 0)}
                  onChange={(e) => set("auto_complete_minutes", Number(e.target.value))}
                >
                  {[
                    ...AUTO_CLOSE,
                    ...(AUTO_CLOSE.some((o) => o.minutes === (v.auto_complete_minutes ?? 0))
                      ? []
                      : [
                          {
                            minutes: v.auto_complete_minutes ?? 0,
                            label: `${v.auto_complete_minutes} minutes after signing`,
                          },
                        ]),
                  ].map((o) => (
                    <option key={o.minutes} value={o.minutes}>
                      {t(`clinic.auto_close_${o.minutes}`, o.label)}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <label className="check" style={{ marginTop: 12 }}>
              <input
                type="checkbox"
                checked={v.allow_skip_triage ?? true}
                onChange={(e) => set("allow_skip_triage", e.target.checked)}
              />{" "}
              {t("clinic.allow_skip", "Reception may send a patient straight to the doctor without triage")}
            </label>
          </Panel>
          <Panel title={t("clinic.doc_notes", "Document notes")}>
            <p className="small muted">
              {t(
                "clinic.doc_notes_hint",
                'A short line printed at the bottom of each kind of document, for example opening hours or "Bring this paper on your next visit". Up to 300 characters.',
              )}
            </p>
            <div className="form-grid">
              {DOC_NOTES.map((n) => (
                <Field
                  key={n.key}
                  label={t(`clinic.${n.key}`, n.label)}
                  id={`cs-${n.key}`}
                  error={fieldErrors(save.error, n.key)}
                >
                  <textarea
                    id={`cs-${n.key}`}
                    rows={2}
                    maxLength={300}
                    value={v[n.key] ?? ""}
                    onChange={(e) => set(n.key, e.target.value)}
                  />
                </Field>
              ))}
            </div>
          </Panel>
          <div className="form-actions">
            {f && (
              <button type="button" className="btn" onClick={() => setF(null)}>
                {t("common.cancel", "Cancel")}
              </button>
            )}
            <button className="btn btn-primary" disabled={!f || save.isPending}>
              {t("common.save", "Save")}
            </button>
          </div>
        </form>
      )}
      {can("settings.manage") && <OpeningHoursPanel clinic={q.data} />}
      {can("settings.manage") && <ModulesPanel editable={false} />}
    </div>
  );
}

const AUTO_CLOSE = [
  { minutes: 0, label: "Off: staff close each visit" },
  { minutes: 15, label: "15 minutes after signing" },
  { minutes: 30, label: "30 minutes after signing" },
  { minutes: 60, label: "1 hour after signing" },
  { minutes: 120, label: "2 hours after signing" },
];

const DOC_NOTES: {
  key:
    | "note_prescription"
    | "note_referral"
    | "note_certificate"
    | "note_lab_report"
    | "note_consultation"
    | "note_patient_card";
  label: string;
}[] = [
  { key: "note_prescription", label: "Prescription" },
  { key: "note_referral", label: "Referral letter" },
  { key: "note_certificate", label: "Medical certificate" },
  { key: "note_lab_report", label: "Laboratory report" },
  { key: "note_consultation", label: "Consultation summary" },
  { key: "note_patient_card", label: "Patient card" },
];

/** Clinic logo: shown in the menu, on the sign-in page and on every printed document. */
function LogoPanel({ clinic }: { clinic: ClinicSettings }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [confirmRemove, setConfirmRemove] = useState(false);
  const done = (msg: string) => {
    void qc.invalidateQueries({ queryKey: ["settings", "clinic"] });
    toast(msg);
  };
  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("logo", file);
      return api.upload("/settings/clinic/logo/", form);
    },
    onSuccess: () => done(t("clinic.logo_saved", "Logo updated")),
  });
  const remove = useMutation({
    mutationFn: () => api.delete("/settings/clinic/logo/"),
    onSuccess: () => {
      setConfirmRemove(false);
      done(t("clinic.logo_removed", "Logo removed"));
    },
  });
  const src = clinic.has_logo && clinic.logo_version ? `/api/v1/branding/logo/?v=${clinic.logo_version}` : null;
  return (
    <Panel title={t("clinic.logo", "Clinic logo")}>
      <div className="logo-setting">
        <div className="logo-preview" aria-label={t("clinic.logo_preview", "Current logo")}>
          {src ? (
            <img src={src} alt={t("clinic.logo_alt", "Clinic logo")} />
          ) : (
            <span className="muted small">{t("clinic.no_logo", "No logo yet")}</span>
          )}
        </div>
        <div className="stack-sm">
          <p className="small muted">
            {t(
              "clinic.logo_hint",
              "PNG or JPEG, up to 2 MB, at least 32 pixels on each side. A square or wide logo on a plain background prints best. It is resized to 512 pixels and cleaned before it is stored.",
            )}
          </p>
          <ErrorBanner error={upload.error ?? remove.error} />
          <div className="row">
            <label className="btn btn-sm">
              {upload.isPending
                ? t("common.saving", "Saving…")
                : src
                  ? t("clinic.logo_replace", "Replace logo")
                  : t("clinic.logo_upload", "Upload logo")}
              <input
                type="file"
                accept="image/png,image/jpeg"
                hidden
                disabled={upload.isPending}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) upload.mutate(file);
                }}
              />
            </label>
            {src && (
              <button type="button" className="btn btn-sm" onClick={() => setConfirmRemove(true)}>
                {t("clinic.logo_remove", "Remove logo")}
              </button>
            )}
          </div>
        </div>
      </div>
      <ConfirmDialog
        open={confirmRemove}
        title={t("clinic.logo_remove_title", "Remove the clinic logo?")}
        body={t("clinic.logo_remove_body", "Screens and printed documents will show the clinic name only.")}
        confirmLabel={t("clinic.logo_remove", "Remove logo")}
        danger
        onClose={() => setConfirmRemove(false)}
        onConfirm={() => remove.mutate()}
      />
    </Panel>
  );
}
