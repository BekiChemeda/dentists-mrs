import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Wrench } from "lucide-react";
import { api, queryString } from "../api/client";
import { useGet } from "../api/hooks";
import type { ErrorEvent, Paginated, SecuritySettings, SystemHealth } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime } from "../lib/format";
import { ModulesPanel } from "./modules";
import {
  Badge,
  Banner,
  Empty,
  ErrorBanner,
  Field,
  Loading,
  PageHead,
  Pager,
  Panel,
  Tabs,
  fieldErrors,
  toast,
} from "../ui";
import { ChartTable, LineChart, shortDate } from "../charts";
import { EmailPanel } from "./system-email";
import { OffsitePanel } from "./system-offsite";
import { PaymentsPanel } from "./system-payments";
// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------
export function bytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d} d ${h} h`;
  if (h) return `${h} h ${m} min`;
  return `${m} min`;
}

function Meter({ label, percent, detail }: { label: string; percent: number | null | undefined; detail: string }) {
  const p = percent ?? 0;
  const tone = p >= 90 ? "danger" : p >= 75 ? "wait" : "ok";
  return (
    <div className="meter">
      <div className="meter-head">
        <span>{label}</span>
        <strong>{percent === null || percent === undefined ? "—" : `${p}%`}</strong>
      </div>
      <div
        className={`meter-bar meter-${tone}`}
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={p}
        aria-label={label}
      >
        <span style={{ width: `${Math.min(100, p)}%` }} />
      </div>
      <div className="small muted">{detail}</div>
    </div>
  );
}

const STATUS_TONE = { ok: "ok", warning: "wait", error: "danger" } as const;

// ---------------------------------------------------------------------------
// System page
// ---------------------------------------------------------------------------
type SystemTab = "health" | "modules" | "offsite" | "email" | "payments" | "security" | "errors";

export function SystemPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as SystemTab) || "health";
  const setTab = (k: SystemTab) => setParams({ tab: k });
  return (
    <div className="stack">
      <PageHead
        title={t("system.title", "System")}
        sub={t(
          "system.sub",
          "Server health, security rules and maintenance. Patient records, money and clinic settings are not managed here.",
        )}
      />
      <Tabs<SystemTab>
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "health", label: t("system.tab_health", "Health") },
          { key: "modules", label: t("system.tab_modules", "Modules") },
          { key: "offsite", label: t("system.tab_offsite", "Off-site backup") },
          { key: "email", label: t("system.tab_email", "Email") },
          ...(can("payments.gateway.manage")
            ? [{ key: "payments" as SystemTab, label: t("system.tab_payments", "Payments by phone") }]
            : []),
          { key: "security", label: t("system.tab_security", "Security and maintenance") },
          { key: "errors", label: t("system.tab_errors", "Error log") },
        ]}
      />
      {tab === "health" &&
        (can("system.health.view") ? (
          <>
            <HealthPanel />
            <StorageTrendBlock />
          </>
        ) : (
          <Empty>{t("system.no_health", "You cannot view server health.")}</Empty>
        ))}
      {tab === "modules" && <ModulesPanel editable={can("system.security.manage")} />}
      {tab === "offsite" && <OffsitePanel />}
      {tab === "email" && <EmailPanel />}
      {tab === "payments" && can("payments.gateway.manage") && <PaymentsPanel />}
      {tab === "security" && <SecurityPanel />}
      {tab === "errors" && <ErrorLog />}
    </div>
  );
}

function HealthPanel() {
  const { t } = useTranslation();
  const q = useGet<SystemHealth>(["system", "health"], "/system/health/", { refetchInterval: 30_000 });
  if (!q.data) return q.error ? <ErrorBanner error={q.error} /> : <Loading />;
  const h = q.data;
  const b = h.backup;
  return (
    <div className="stack">
      <Panel
        title={
          <div className="row" style={{ gap: 10 }}>
            <h2>{t("system.overall", "Overall")}</h2>
            <Badge tone={STATUS_TONE[h.status]}>
              {t(
                `system.status_${h.status}`,
                h.status === "ok" ? "Healthy" : h.status === "warning" ? "Needs attention" : "Not working",
              )}
            </Badge>
          </div>
        }
        actions={
          <span className="small muted">
            {t("system.checked", "Checked {{when}}", { when: formatDateTime(h.checked_at) })}
          </span>
        }
      >
        {h.warnings.length ? (
          <ul className="warning-list">
            {h.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">
            {t("system.all_good", "Database, storage, memory and backups are all within limits.")}
          </p>
        )}
      </Panel>
      <div className="cols-2">
        <Panel title={t("system.server", "Server")}>
          <div className="stack-sm">
            <Meter
              label={t("system.disk", "Disk")}
              percent={h.disk?.percent_used}
              detail={
                h.disk
                  ? t("system.disk_detail", "{{free}} free of {{total}}", {
                      free: bytes(h.disk.free),
                      total: bytes(h.disk.total),
                    })
                  : "—"
              }
            />
            <Meter
              label={t("system.memory", "Memory")}
              percent={h.memory?.percent_used}
              detail={
                h.memory
                  ? t("system.mem_detail", "{{free}} available of {{total}}", {
                      free: bytes(h.memory.available),
                      total: bytes(h.memory.total),
                    })
                  : "—"
              }
            />
            <Meter
              label={t("system.cpu", "Processor load (5 min)")}
              percent={h.load && h.load.cpus ? Math.round((h.load["5m"] / h.load.cpus) * 100) : null}
              detail={
                h.load
                  ? t("system.load_detail", "{{l1}} / {{l5}} / {{l15}} on {{cpus}} cores", {
                      l1: h.load["1m"],
                      l5: h.load["5m"],
                      l15: h.load["15m"],
                      cpus: h.load.cpus ?? "?",
                    })
                  : "—"
              }
            />
          </div>
          <dl className="facts" style={{ marginTop: 14 }}>
            <dt>{t("system.host_uptime", "Server running for")}</dt>
            <dd>{duration(h.host_uptime_seconds)}</dd>
            <dt>{t("system.app_uptime", "Application running for")}</dt>
            <dd>{duration(h.app_uptime_seconds)}</dd>
            <dt>{t("system.software", "Software")}</dt>
            <dd className="mono small">
              {h.version ? `MRS ${h.version} · ` : ""}Django {h.django} · Python {h.python}
            </dd>
            <dt>HTTPS</dt>
            <dd>
              {h.https ? (
                <Badge tone="ok">{t("common.on", "On")}</Badge>
              ) : (
                <Badge tone="danger">{t("common.off", "Off")}</Badge>
              )}
            </dd>
            {h.debug && (
              <>
                <dt>{t("system.debug", "Debug mode")}</dt>
                <dd>
                  <Badge tone="danger">{t("system.debug_on", "On: not for real patients")}</Badge>
                </dd>
              </>
            )}
          </dl>
        </Panel>
        <Panel title={t("system.database", "Database")}>
          <dl className="facts">
            <dt>{t("system.db_status", "Status")}</dt>
            <dd>
              <Badge tone={h.database.status === "ok" ? "ok" : "danger"}>
                {h.database.status === "ok"
                  ? t("system.responding", "Responding")
                  : t("system.not_responding", "Not responding")}
              </Badge>
            </dd>
            <dt>{t("system.latency", "Response time")}</dt>
            <dd>{h.database.latency_ms ?? "—"} ms</dd>
            <dt>{t("system.db_size", "Size")}</dt>
            <dd>{bytes(h.database.size_bytes)}</dd>
            <dt>{t("system.migrations", "Pending updates")}</dt>
            <dd>
              {h.database.pending_migrations.length ? (
                <span className="flag-H">{h.database.pending_migrations.join(", ")}</span>
              ) : (
                t("system.none", "None")
              )}
            </dd>
          </dl>
        </Panel>
        <Panel title={t("system.backups", "Backups")}>
          {!b.configured ? (
            <Banner tone="warn">
              {t("system.backup_unset", "BACKUP_DIR is not set on the server, so backups cannot be checked here.")}
            </Banner>
          ) : !b.found ? (
            <Banner tone="error">
              {t("system.backup_none", "No backup file found in {{dir}}.", { dir: b.directory })}
            </Banner>
          ) : (
            <dl className="facts">
              <dt>{t("system.backup_last", "Newest backup")}</dt>
              <dd>
                {formatDateTime(b.taken_at ?? null)}{" "}
                {b.stale ? (
                  <Badge tone="danger">{t("system.backup_old", "Over a day old")}</Badge>
                ) : (
                  <Badge tone="ok">{t("system.backup_fresh", "Recent")}</Badge>
                )}
              </dd>
              <dt>{t("system.backup_file", "File")}</dt>
              <dd className="mono small">
                {b.file} ({bytes(b.size_bytes)})
              </dd>
              <dt>{t("system.backup_count", "Backups kept")}</dt>
              <dd>{b.count}</dd>
              <dt>{t("system.backup_space", "Free space for backups")}</dt>
              <dd>{h.backup_disk ? bytes(h.backup_disk.free) : "—"}</dd>
            </dl>
          )}
          <dl className="facts" style={{ marginTop: 10 }}>
            <dt>{t("system.offsite", "Off-site copy")}</dt>
            <dd>
              {!h.offsite.enabled ? (
                <Badge>{t("common.off", "Off")}</Badge>
              ) : h.offsite.overdue ? (
                <Badge tone="danger">{t("system.offsite_overdue", "Overdue")}</Badge>
              ) : (
                <Badge tone="ok">{t("system.offsite_ok", "Up to date")}</Badge>
              )}{" "}
              {h.offsite.last_success_at && (
                <span className="small muted">
                  {t("system.offsite_last", "last sent {{when}}", { when: formatDateTime(h.offsite.last_success_at) })}
                </span>
              )}
            </dd>
          </dl>
          <p className="small muted" style={{ marginTop: 10 }}>
            {t(
              "system.restore_note",
              "Restoring a backup is done on the server by a technician (docs/operations/restore.md). It is not possible from this screen, on purpose.",
            )}
          </p>
        </Panel>
        <Panel title={t("system.access", "Sign-ins and errors")}>
          <div className="figures">
            <div className="figure">
              <b>{h.sessions_active}</b>
              <span>{t("system.sessions", "Signed in now")}</span>
            </div>
            <div className={`figure${h.failed_logins_24h >= 10 ? " attention" : ""}`}>
              <b>{h.failed_logins_24h}</b>
              <span>{t("system.failed_logins", "Failed sign-ins (24 h)")}</span>
            </div>
            <div className={`figure${h.locked_accounts ? " danger" : ""}`}>
              <b>{h.locked_accounts}</b>
              <span>{t("system.locked", "Locked accounts")}</span>
            </div>
            <div className={`figure${h.errors_24h ? " danger" : ""}`}>
              <b>{h.errors_24h}</b>
              <span>{t("system.errors_24h", "Server errors (24 h)")}</span>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function SecurityPanel() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useGet<SecuritySettings>(["system", "security"], "/system/security/");
  const [f, setF] = useState<Partial<SecuritySettings> | null>(null);
  const save = useMutation({
    mutationFn: (body: Partial<SecuritySettings>) =>
      api.patch<SecuritySettings>("/system/security/", body, { ifMatch: q.data?.row_version }),
    onSuccess: (data) => {
      qc.setQueryData(["system", "security"], data);
      void qc.invalidateQueries({ queryKey: ["system"] });
      setF(null);
      toast(t("system.saved", "Security settings saved"));
    },
  });
  if (!q.data) return q.error ? <ErrorBanner error={q.error} /> : <Loading />;
  const v = { ...q.data, ...f };
  const editable = can("system.security.manage");
  const num = (k: "password_min_length" | "login_max_failures" | "login_lockout_minutes" | "session_idle_minutes") => ({
    value: v[k],
    min: k === "password_min_length" ? q.data.floor.password_min_length : q.data.limits[k][0],
    max:
      k === "session_idle_minutes"
        ? Math.min(q.data.limits[k][1], q.data.session_absolute_hours * 60)
        : q.data.limits[k][1],
    disabled: !editable,
    type: "number",
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: Number(e.target.value) }),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (f) save.mutate(f);
  };
  return (
    <form className="stack" onSubmit={submit}>
      <ErrorBanner error={save.error} onReload={() => setF(null)} />
      <Panel
        title={
          <div className="row" style={{ gap: 10 }}>
            <Wrench size={18} aria-hidden />
            <h2>{t("system.maintenance", "Maintenance mode")}</h2>
            {v.maintenance_mode && <Badge tone="danger">{t("common.on", "On")}</Badge>}
          </div>
        }
      >
        <p className="small muted">
          {t(
            "system.maintenance_help",
            "While it is on, only system administrators can use the system. Everyone else sees your message, including on the sign-in page. Use it for upgrades and restores.",
          )}
        </p>
        <label className="check" style={{ margin: "10px 0" }}>
          <input
            type="checkbox"
            checked={v.maintenance_mode}
            disabled={!editable}
            onChange={(e) => setF({ ...f, maintenance_mode: e.target.checked })}
          />{" "}
          {t("system.maintenance_on", "Put the system in maintenance mode")}
        </label>
        <Field
          label={t("system.maintenance_message", "Message for staff")}
          id="ss-msg"
          error={fieldErrors(save.error, "maintenance_message")}
        >
          <input
            id="ss-msg"
            value={v.maintenance_message}
            disabled={!editable}
            maxLength={255}
            placeholder={t("system.maintenance_ph", "e.g. System upgrade until 14:00. Use paper forms meanwhile.")}
            onChange={(e) => setF({ ...f, maintenance_message: e.target.value })}
          />
        </Field>
      </Panel>
      <Panel title={t("system.security", "Sign-in and password rules")}>
        <div className="form-grid">
          <Field
            label={t("system.pw_len", "Minimum password length")}
            id="ss-pw"
            error={fieldErrors(save.error, "password_min_length")}
            hint={t("system.pw_len_hint", "The server requires at least {{n}}. Applies to new passwords.", {
              n: q.data.floor.password_min_length,
            })}
          >
            <input id="ss-pw" {...num("password_min_length")} />
          </Field>
          <Field
            label={t("system.max_fail", "Failed attempts before lock")}
            id="ss-mf"
            error={fieldErrors(save.error, "login_max_failures")}
          >
            <input id="ss-mf" {...num("login_max_failures")} />
          </Field>
          <Field
            label={t("system.lock_min", "Lock lasts (minutes)")}
            id="ss-lm"
            error={fieldErrors(save.error, "login_lockout_minutes")}
          >
            <input id="ss-lm" {...num("login_lockout_minutes")} />
          </Field>
          <Field
            label={t("system.idle", "Sign out after inactivity (minutes)")}
            id="ss-idle"
            error={fieldErrors(save.error, "session_idle_minutes")}
            hint={t("system.idle_hint", "Sessions also end after {{h}} hours, however active.", {
              h: q.data.session_absolute_hours,
            })}
          >
            <input id="ss-idle" {...num("session_idle_minutes")} />
          </Field>
          <Field
            label={t("system.dormant", "Switch off accounts unused for (days)")}
            id="ss-dorm"
            error={fieldErrors(save.error, "dormant_account_days")}
            hint={t(
              "system.dormant_hint",
              "Catches staff who left without anyone telling you. 0 = never. Administrators are told who was switched off.",
            )}
          >
            <input
              id="ss-dorm"
              type="number"
              min={0}
              max={730}
              value={v.dormant_account_days}
              disabled={!editable}
              onChange={(e) => setF({ ...f, dormant_account_days: Number(e.target.value) })}
            />
          </Field>
        </div>
        <Field
          label={t("system.mfa_policy", "Two-step sign-in required for")}
          id="ss-mfa"
          className="narrow-field"
          hint={t(
            "system.mfa_policy_hint",
            "People covered must set it up at their next sign-in before they can do anything else. Others can still turn it on for themselves.",
          )}
        >
          <select
            id="ss-mfa"
            value={v.mfa_required_for}
            disabled={!editable}
            onChange={(e) => setF({ ...f, mfa_required_for: e.target.value as SecuritySettings["mfa_required_for"] })}
          >
            <option value="admins">{t("system.mfa_admins", "Administrators and the clinic director")}</option>
            <option value="all">{t("system.mfa_all", "Everyone")}</option>
            <option value="off">{t("system.mfa_off", "Nobody (optional)")}</option>
          </select>
        </Field>
      </Panel>
      {editable && (
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
      )}
    </form>
  );
}

function ErrorLog() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const [rid, setRid] = useState("");
  const [applied, setApplied] = useState("");
  const q = useGet<Paginated<ErrorEvent>>(
    ["system", "errors", applied, page],
    `/system/errors/${queryString({ request_id: applied, page })}`,
  );
  return (
    <div className="stack">
      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setApplied(rid.trim());
        }}
      >
        <Field label={t("system.request_id", "Request ID (from the error message a user reported)")} id="er-rid">
          <input id="er-rid" className="mono" value={rid} onChange={(e) => setRid(e.target.value)} />
        </Field>
        <button className="btn" type="submit">
          {t("common.search")}
        </button>
      </form>
      <ErrorBanner error={q.error} />
      <Panel flush>
        {q.isLoading ? (
          <Loading />
        ) : !q.data?.results.length ? (
          <Empty>{t("system.no_errors", "No server errors recorded.")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("audit.when")}</th>
                  <th>{t("system.request", "Request")}</th>
                  <th>{t("system.error", "Error")}</th>
                  <th>{t("system.request_id_short", "Request ID")}</th>
                </tr>
              </thead>
              <tbody>
                {q.data.results.map((e) => (
                  <tr key={e.id}>
                    <td className="nowrap">{formatDateTime(e.occurred_at)}</td>
                    <td className="mono small">
                      {e.method} {e.path}
                    </td>
                    <td>
                      <span className="mono small">{e.exception_type}</span>
                      {e.message && <div className="small muted">{e.message}</div>}
                    </td>
                    <td className="mono small">{e.request_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {q.data && <Pager page={page} count={q.data.count} pageSize={25} onPage={setPage} />}
      </Panel>
      <p className="small muted">
        {t(
          "system.errors_note",
          "Only the error type and first line are kept, never form contents. Full details are in the server logs under the same request ID.",
        )}
      </p>
    </div>
  );
}

interface HealthSampleRow {
  day: string;
  disk_percent_used: string | null;
  disk_free_bytes: number | null;
  database_bytes: number | null;
  newest_backup_bytes: number | null;
}

const mb = (b: number | null) => (b === null ? null : Math.round((b / 1_048_576) * 10) / 10);

/** Disk use and storage sizes over the last 90 days: one reading a day. */
export function StorageTrendBlock() {
  const { t } = useTranslation();
  const q = useGet<HealthSampleRow[]>(["system", "health", "history"], "/system/health/history/?days=90");
  const rows = q.data ?? [];
  if (q.isLoading) return null;
  return (
    <Panel title={t("system.storage_trend", "Storage over the last 90 days")}>
      {rows.length < 2 ? (
        <p className="subtle small">
          {t("system.trend_soon", "The charts fill in from one reading a day; check back tomorrow.")}
        </p>
      ) : (
        <div className="chart-grid-2">
          <div className="chart-card">
            <h3>
              {t("system.disk_used", "Server disk used")} <span className="muted small">(%)</span>
            </h3>
            <LineChart
              series={[
                {
                  key: "disk",
                  label: t("system.disk_used", "Server disk used"),
                  points: rows.map((r) => ({
                    x: r.day,
                    y: r.disk_percent_used === null ? null : Number(r.disk_percent_used),
                  })),
                },
              ]}
              unit="%"
              band={{ low: 90, high: 100, label: t("system.disk_alert_band", "Shaded: over 90% raises an alert") }}
              label={t("system.disk_aria", "Server disk used, percent, by day")}
            />
            <p className="chart-caption">{t("system.disk_alert_band", "Shaded: over 90% raises an alert")}</p>
          </div>
          <div className="chart-card">
            <h3>
              {t("system.sizes", "Database and newest backup")} <span className="muted small">(MB)</span>
            </h3>
            <LineChart
              unit="MB"
              label={t("system.sizes_aria", "Database size and newest backup size in megabytes, by day")}
              series={[
                {
                  key: "db",
                  label: t("system.database_size", "Database"),
                  points: rows.map((r) => ({ x: r.day, y: mb(r.database_bytes) })),
                },
                {
                  key: "bk",
                  label: t("system.backup_size", "Newest backup"),
                  points: rows.map((r) => ({ x: r.day, y: mb(r.newest_backup_bytes) })),
                },
              ]}
            />
          </div>
        </div>
      )}
      {rows.length > 0 && (
        <ChartTable
          head={[
            t("common.date", "Date"),
            t("system.disk_used_pct", "Disk used %"),
            t("system.database_mb", "Database MB"),
            t("system.backup_mb", "Newest backup MB"),
          ]}
          rows={[...rows]
            .reverse()
            .map((r) => [
              shortDate(r.day),
              r.disk_percent_used ?? "—",
              mb(r.database_bytes) ?? "—",
              mb(r.newest_backup_bytes) ?? "—",
            ])}
        />
      )}
    </Panel>
  );
}

/** Compact health card for the system administrator's dashboard. */
export function SystemHealthBlock() {
  const { t } = useTranslation();
  const q = useGet<SystemHealth>(["system", "health"], "/system/health/", { refetchInterval: 60_000 });
  const h = q.data;
  return (
    <Panel
      title={
        <div className="row" style={{ gap: 10 }}>
          <h2>{t("system.health", "System health")}</h2>
          {h && (
            <Badge tone={STATUS_TONE[h.status]}>
              {h.status === "ok"
                ? t("system.status_ok", "Healthy")
                : h.status === "warning"
                  ? t("system.status_warning", "Needs attention")
                  : t("system.status_error", "Not working")}
            </Badge>
          )}
        </div>
      }
      actions={
        <Link className="btn btn-sm" to="/admin/system">
          {t("system.open", "Open system page")}
        </Link>
      }
    >
      {!h ? (
        q.error ? (
          <ErrorBanner error={q.error} />
        ) : (
          <Loading />
        )
      ) : (
        <div className="stack-sm">
          <div className="figures">
            <div className={`figure${(h.disk?.percent_used ?? 0) >= 90 ? " danger" : ""}`}>
              <b>{h.disk?.percent_used ?? "—"}%</b>
              <span>{t("system.disk_used", "Disk used")}</span>
            </div>
            <div className={`figure${(h.memory?.percent_used ?? 0) >= 90 ? " danger" : ""}`}>
              <b>{h.memory?.percent_used ?? "—"}%</b>
              <span>{t("system.memory_used", "Memory used")}</span>
            </div>
            <div className={`figure${h.backup.stale || !h.backup.found ? " danger" : ""}`}>
              <b>{h.backup.found ? `${h.backup.age_hours} h` : "—"}</b>
              <span>{t("system.backup_age", "Since last backup")}</span>
            </div>
            <div className={`figure${h.errors_24h ? " danger" : ""}`}>
              <b>{h.errors_24h}</b>
              <span>{t("system.errors_24h", "Server errors (24 h)")}</span>
            </div>
            <div className="figure">
              <b>{duration(h.host_uptime_seconds)}</b>
              <span>{t("system.uptime", "Uptime")}</span>
            </div>
          </div>
          {h.warnings.length > 0 && (
            <ul className="warning-list">
              {h.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Panel>
  );
}

/** Shown across the app while maintenance mode is on (system administrators keep working). */
export function MaintenanceStrip() {
  const { t } = useTranslation();
  const q = useGet<{ maintenance_mode: boolean; maintenance_message: string }>(
    ["system", "status"],
    "/system/status/",
    { refetchInterval: 60_000 },
  );
  if (!q.data?.maintenance_mode) return null;
  return (
    <div className="maintenance-strip" role="status">
      <Wrench size={16} aria-hidden />
      <strong>{t("system.maintenance_active", "Maintenance mode is on.")}</strong> {q.data.maintenance_message}
    </div>
  );
}
