/** System > Off-site backup. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { CloudUpload, KeyRound } from "lucide-react";
import { api } from "../api/client";
import { useGet } from "../api/hooks";
import type { OffsiteRun, OffsiteStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime } from "../lib/format";
import { Badge, Banner, Empty, ErrorBanner, Field, Loading, Panel, toast } from "../ui";
import { bytes } from "./system";

const EVERY = (h: number) => (h === 1 ? "Every hour" : h === 24 ? "Once a day" : `Every ${h} hours`);

export function OffsitePanel() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useGet<OffsiteStatus & { interval_choices: number[]; runs: OffsiteRun[] }>(
    ["system", "offsite"],
    "/system/offsite/",
    { refetchInterval: 60_000 },
  );
  const save = useMutation({
    mutationFn: (body: { enabled?: boolean; interval_hours?: number }) =>
      api.patch<typeof q.data>("/system/offsite/", body),
    onSuccess: (data) => {
      qc.setQueryData(["system", "offsite"], data);
      void qc.invalidateQueries({ queryKey: ["system", "health"] });
      toast(t("system.offsite_saved", "Off-site backup settings saved"));
    },
  });
  if (!q.data) return q.error ? <ErrorBanner error={q.error} /> : <Loading />;
  const o = q.data;
  const editable = can("backups.manage");
  const neverRan = !o.last_attempt_at;
  return (
    <div className="stack">
      <ErrorBanner error={save.error} />
      <Panel
        title={
          <div className="row" style={{ gap: 10 }}>
            <CloudUpload size={18} aria-hidden />
            <h2>{t("system.offsite", "Off-site copy")}</h2>
            {!o.enabled ? (
              <Badge>{t("common.off", "Off")}</Badge>
            ) : o.overdue ? (
              <Badge tone="danger">{t("system.offsite_overdue", "Overdue")}</Badge>
            ) : (
              <Badge tone="ok">{t("common.on", "On")}</Badge>
            )}
          </div>
        }
      >
        <p className="small muted">
          {t(
            "system.offsite_help",
            "Sends an encrypted copy of the database to storage outside the clinic. The copy is locked with the owner's secret phrase on this server before it leaves; the storage company cannot read it.",
          )}
        </p>
        <div className="offsite-controls">
          <label className="switch">
            <input
              type="checkbox"
              role="switch"
              checked={o.enabled}
              disabled={!editable || save.isPending}
              onChange={(e) => save.mutate({ enabled: e.target.checked })}
            />
            <span>
              {o.enabled
                ? t("system.offsite_is_on", "Off-site backup is on")
                : t("system.offsite_is_off", "Off-site backup is off")}
            </span>
          </label>
          <Field label={t("system.offsite_every", "How often")} id="of-int">
            <select
              id="of-int"
              value={o.interval_hours}
              disabled={!editable || save.isPending}
              onChange={(e) => save.mutate({ interval_hours: Number(e.target.value) })}
            >
              {o.interval_choices.map((h) => (
                <option key={h} value={h}>
                  {t(`system.every_${h}`, EVERY(h))}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {o.enabled && neverRan && (
          <Banner tone="warn">
            {t(
              "system.offsite_waiting",
              "Switched on, but the server has not tried an upload yet. If this stays for more than 15 minutes, the server setup (secret phrase and storage address) has not been done; see docs/operations/offsite-backup.md.",
            )}
          </Banner>
        )}
        {o.enabled && o.last_status === "failure" && (
          <Banner tone={o.overdue ? "error" : "warn"}>
            {t("system.offsite_failed", "Last attempt failed: {{msg}}", { msg: o.last_message || "unknown reason" })}
          </Banner>
        )}
        <dl className="facts" style={{ marginTop: 12 }}>
          <dt>{t("system.offsite_last_ok", "Last copy sent")}</dt>
          <dd>{formatDateTime(o.last_success_at, t("common.never"))}</dd>
          <dt>{t("system.offsite_next", "Next copy due")}</dt>
          <dd>{o.enabled ? formatDateTime(o.next_due_at) : "—"}</dd>
          <dt>{t("system.offsite_where", "Stored at")}</dt>
          <dd className="mono small">{o.target || "—"}</dd>
        </dl>
        {!o.enabled && o.last_success_at && (
          <p className="small muted" style={{ marginTop: 8 }}>
            {t(
              "system.offsite_off_note",
              "Switching off stops new uploads. Copies already sent stay at the storage and can still be recovered with the secret phrase.",
            )}
          </p>
        )}
      </Panel>
      <Panel
        title={
          <div className="row" style={{ gap: 10 }}>
            <KeyRound size={18} aria-hidden />
            <h2>{t("system.offsite_recover", "Getting the data back")}</h2>
          </div>
        }
      >
        <ol className="steps-list">
          <li>{t("system.offsite_r1", "Install the system on any computer (a new server if this one is lost).")}</li>
          <li>{t("system.offsite_r2", "Put the storage address in its settings file.")}</li>
          <li>
            {t(
              "system.offsite_r3",
              "Run: deploy/scripts/offsite-backup.sh restore latest --import, and type the secret phrase when asked.",
            )}
          </li>
        </ol>
        <Banner tone="warn">
          {t(
            "system.offsite_phrase_warning",
            "Without the secret phrase the copies cannot be opened by anyone, including your IT provider. Keep it written down in a sealed envelope away from the clinic.",
          )}
        </Banner>
      </Panel>
      <Panel title={t("system.offsite_history", "Recent uploads")} flush>
        {!o.runs.length ? (
          <Empty>{t("system.offsite_none", "No uploads yet.")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("audit.when")}</th>
                  <th>{t("audit.outcome")}</th>
                  <th className="num">{t("system.offsite_new_data", "New data sent")}</th>
                  <th>{t("system.offsite_copy", "Copy")}</th>
                  <th>{t("system.offsite_note", "Note")}</th>
                </tr>
              </thead>
              <tbody>
                {o.runs.map((r) => (
                  <tr key={r.id}>
                    <td className="nowrap">{formatDateTime(r.finished_at)}</td>
                    <td>
                      {r.status === "success" ? (
                        <Badge tone="ok">{t("system.offsite_sent", "Sent")}</Badge>
                      ) : (
                        <Badge tone="danger">{t("system.offsite_fail", "Failed")}</Badge>
                      )}
                    </td>
                    <td className="num">{r.bytes_added === null ? "—" : bytes(r.bytes_added)}</td>
                    <td className="mono small">{r.snapshot_id ? r.snapshot_id.slice(0, 8) : "—"}</td>
                    <td className="small">{r.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
