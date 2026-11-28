import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { queryString } from "../api/client";
import { useGet } from "../api/hooks";
import type {
  Appointment,
  Approval,
  AuditEvent,
  LabOrder,
  Paginated,
  PatientBrief,
  Prescription,
  Visit,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { StateBadge } from "../labels";
import { formatDateTime, formatDay, formatLongDate, isoDateDaysAgo } from "../lib/format";
import { dashboardFor } from "../navigation";
import { Empty, Loading, PageHead, Panel } from "../ui";
import { SummaryFigures, type DailySummary } from "./billing";
import { Ec, sexAge, timeOf, todayIso, waitLabel } from "./common";
import { StockAlerts } from "./inventory";
import { SystemHealthBlock, StorageTrendBlock } from "./system";
import { AnnouncementsBlock } from "./announcements";
import { BarList, ChartTable, ColumnChart, shortDate } from "../charts";
import type { ReportResult } from "../api/types";
import { SetupChecklistBlock } from "./setup";

export function DashboardPage() {
  const { user, can } = useAuth();
  const { t } = useTranslation();
  if (!user) return null;
  const kind = dashboardFor(user.roles.map((r) => r.code));

  const blocks: { key: string; show: boolean; node: ReactNode }[] = [
    { key: "announcements", show: true, node: <AnnouncementsBlock /> },
    { key: "setup", show: can("settings.manage") && kind === "clinic_admin", node: <SetupChecklistBlock /> },
    { key: "health", show: can("system.health.view"), node: <SystemHealthBlock /> },
    { key: "storage", show: can("system.health.view") && kind === "system_admin", node: <StorageTrendBlock /> },
    {
      key: "trends",
      show: can("reports.operational") && (kind === "clinic_admin" || kind === "clinic_director"),
      node: <ClinicTrendsBlock />,
    },
    { key: "critical", show: can("clinical.write"), node: <CriticalBlock /> },
    { key: "labcases", show: can("dental.labcase.work"), node: <LabCasesBlock /> },
    {
      key: "queue",
      show: can("queue.manage", "triage.record", "clinical.write", "dental.write"),
      node: <QueueBlock />,
    },
    { key: "unsigned", show: can("dental.write"), node: <UnsignedExamsBlock /> },
    { key: "appointments", show: can("appointments.view") && kind !== "doctor", node: <AppointmentsBlock /> },
    { key: "lab", show: can("lab.result.enter"), node: <LabBlock /> },
    { key: "pharmacy", show: can("pharmacy.dispense"), node: <PharmacyBlock /> },
    {
      key: "approvals",
      show: can("pharmacy.dispense.override", "billing.discount.approve", "billing.void.approve"),
      node: <ApprovalsBlock />,
    },
    { key: "billing", show: can("billing.payment", "reports.financial"), node: <BillingBlock /> },
    { key: "staff", show: can("staff.manage") && !can("users.manage"), node: <StaffBlock /> },
    { key: "stock", show: can("inventory.manage") || kind === "pharmacist", node: <StockAlerts compact /> },
    { key: "accounts", show: can("users.view") && kind === "system_admin", node: <AccountsBlock /> },
    { key: "security", show: can("audit.view") && kind === "system_admin", node: <SecurityBlock /> },
  ];

  return (
    <div className="stack">
      <PageHead
        title={t(`dashboard.titles.${kind}`)}
        sub={
          <>
            {`${t("dashboard.welcome", { name: user.first_name })}. ${t("dashboard.today", { date: formatLongDate(new Date()) })}`}
            <Ec value={new Date()} />
          </>
        }
      />
      {blocks
        .filter((b) => b.show)
        .map((b) => (
          <div key={b.key}>{b.node}</div>
        ))}
      {!blocks.some((b) => b.show && b.key !== "announcements") && <Empty>{t("dashboard.focus.general")}</Empty>}
    </div>
  );
}

function CriticalBlock() {
  const { t } = useTranslation();
  const q = useGet<
    {
      id: string;
      test: string;
      result: string;
      unit: string;
      flag: string;
      verified_at: string;
      patient: PatientBrief;
      ordered_by: string;
      reported_to: string;
    }[]
  >(["lab", "critical", "mine"], "/lab/critical/?mine=1", { refetchInterval: 30_000 });
  if (!q.data?.length) return null;
  return (
    <Panel
      title={
        <h2 className="flag-H">
          {t("dash.critical", "Critical results to acknowledge ({{n}})", { n: q.data.length })}
        </h2>
      }
      flush
    >
      <table className="data">
        <tbody>
          {q.data.map((c) => (
            <tr key={c.id}>
              <td>
                <Link to={`/patients/${c.patient.id}?tab=labs`}>
                  <strong>{c.patient.full_name}</strong>
                </Link>
                <div className="small muted">{sexAge(c.patient, t)}</div>
              </td>
              <td>
                {c.test}:{" "}
                <span className={`flag-${c.flag}`}>
                  {c.result} {c.unit}
                </span>
              </td>
              <td className="small muted">{formatDateTime(c.verified_at)}</td>
              <td className="num">
                <Link className="btn btn-sm btn-danger-solid" to={`/patients/${c.patient.id}?tab=labs`}>
                  {t("dash.review", "Review")}
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function QueueBlock() {
  const { t } = useTranslation();
  const { user, can, moduleOn } = useAuth();
  const doctorOnly = can("clinical.write", "dental.write") && !can("queue.manage");
  const doctorHome = can("clinical.write") ? "/consultations" : "/dental/encounters";
  const q = useGet<Visit[]>(
    ["visits", "dash", doctorOnly],
    `/visits/${doctorOnly && user ? `?doctor=${user.id}` : ""}`,
    { refetchInterval: 30_000 },
  );
  const v = q.data ?? [];
  // Until the first answer arrives, show a dash rather than a misleading 0.
  const count = (s: string): number | string => (q.data ? v.filter((x) => x.status === s).length : "–");
  const waiting = v.filter((x) => x.status === "waiting_doctor" || x.status === "waiting_triage");
  const longest = Math.max(0, ...waiting.map((x) => x.waiting_minutes ?? 0));
  return (
    <Panel
      title={doctorOnly ? t("dash.my_queue", "Your patients today") : t("dash.clinic_today", "The clinic today")}
      actions={
        <Link className="btn btn-sm" to={doctorOnly ? doctorHome : "/queue"}>
          {t("dash.open_queue", "Open waiting list")}
        </Link>
      }
    >
      <div className="figures">
        {moduleOn("triage") && (
          <div className={`figure${Number(count("waiting_triage")) > 0 ? " attention" : ""}`}>
            <b>{count("waiting_triage")}</b>
            <span>{t("queue.lane_triage", "Waiting for triage")}</span>
          </div>
        )}
        <div className={`figure${Number(count("waiting_doctor")) > 0 ? " attention" : ""}`}>
          <b>{count("waiting_doctor")}</b>
          <span>{t("queue.lane_doctor", "Waiting for doctors")}</span>
        </div>
        <div className="figure">
          <b>{count("in_consultation")}</b>
          <span>{t("queue.lane_consult", "Being managed")}</span>
        </div>
        <div className="figure">
          <b>{count("after_consult")}</b>
          <span>{t("dash.after_consult", "After consultation")}</span>
        </div>
        <div className="figure">
          <b>{count("completed")}</b>
          <span>{t("dash.seen", "Completed visits")}</span>
        </div>
        <div className={`figure${longest >= 60 ? " danger" : ""}`}>
          <b>{q.data ? waitLabel(longest) || "0 min" : "–"}</b>
          <span>{t("dash.longest_wait", "Longest wait")}</span>
        </div>
      </div>
      {waiting.length > 0 && (
        <table className="data" style={{ marginTop: 12 }}>
          <tbody>
            {waiting.slice(0, 6).map((x) => (
              <tr key={x.id}>
                <td style={{ width: 60 }}>
                  <strong className="token" style={{ fontSize: "1.6rem", border: 0 }}>
                    {x.queue_number}
                  </strong>
                </td>
                <td>
                  <Link to={`/patients/${x.patient.id}`}>
                    <strong>{x.patient.full_name}</strong>
                  </Link>
                  <div className="small muted">{sexAge(x.patient, t)}</div>
                </td>
                <td>
                  <StateBadge set="visit" value={x.status} />{" "}
                  {x.priority !== "routine" && <StateBadge set="priority" value={x.priority} />}
                </td>
                <td className="num">{waitLabel(x.waiting_minutes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function UnsignedExamsBlock() {
  const { t } = useTranslation();
  const q = useGet<Paginated<{ id: string; created_at: string; patient: PatientBrief; chief_complaint: string }>>(
    ["dental", "encounters", "draft", 1],
    `/dental/encounters/${queryString({ mine: "true", status: "draft", page: 1 })}`,
  );
  const rows = q.data?.results ?? [];
  if (!rows.length) return null;
  return (
    <Panel
      title={t("dash.unsigned_exams", "Your unsigned examinations ({{n}})", { n: q.data?.count ?? rows.length })}
      actions={
        <Link className="btn btn-sm" to="/dental/encounters">
          {t("dash.see_all", "See all")}
        </Link>
      }
      flush
    >
      <table className="data">
        <tbody>
          {rows.slice(0, 5).map((e) => (
            <tr key={e.id}>
              <td className="nowrap muted">{formatDateTime(e.created_at)}</td>
              <td>
                <strong>{e.patient.full_name}</strong> <span className="mono small subtle">{e.patient.mrn}</span>
              </td>
              <td className="muted">{e.chief_complaint || "—"}</td>
              <td className="num">
                <Link className="btn btn-sm btn-primary" to={`/dental/encounters/${e.id}`}>
                  {t("dental.continue_note", "Continue writing")}
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function LabCasesBlock() {
  const { t } = useTranslation();
  const q = useGet<
    Paginated<{ id: string; number: string; patient: PatientBrief; case_type_label: string; due_date: string | null }>
  >(["dental", "lab-cases", "dash"], "/dental/lab-cases/", { refetchInterval: 60_000 });
  const rows = q.data?.results ?? [];
  const today = todayIso();
  return (
    <Panel
      title={t("dash.lab_cases", "Laboratory work in progress")}
      actions={
        <Link className="btn btn-sm" to="/dental/lab-cases">
          {t("dash.open_lab", "Open laboratory")}
        </Link>
      }
      flush
    >
      {q.isLoading ? (
        <Loading />
      ) : !rows.length ? (
        <Empty>{t("dash.no_lab_cases", "No open laboratory cases.")}</Empty>
      ) : (
        <table className="data">
          <tbody>
            {rows.slice(0, 8).map((c) => (
              <tr key={c.id}>
                <td className="mono small">{c.number}</td>
                <td>{c.patient.full_name}</td>
                <td className="muted">{c.case_type_label}</td>
                <td className={`num nowrap${c.due_date && c.due_date < today ? " text-danger" : ""}`}>
                  {c.due_date ? t("dash.due", "Due {{d}}", { d: formatDay(c.due_date) }) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function AppointmentsBlock() {
  const { t } = useTranslation();
  const q = useGet<Paginated<Appointment>>(
    ["appointments", "dash"],
    `/appointments/${queryString({ date: todayIso(), status: "scheduled", page_size: 8 })}`,
  );
  return (
    <Panel
      title={t("dash.appointments", "Still expected today")}
      actions={
        <Link className="btn btn-sm" to="/appointments">
          {t("dash.all_appointments", "All appointments")}
        </Link>
      }
      flush
    >
      {!q.data?.results.length ? (
        <Empty>{t("dash.no_appointments", "No more scheduled appointments today.")}</Empty>
      ) : (
        <table className="data">
          <tbody>
            {q.data.results.map((a) => (
              <tr key={a.id}>
                <td className="nowrap">
                  <strong>{timeOf(a.scheduled_at)}</strong>
                </td>
                <td>{a.patient.full_name}</td>
                <td className="muted">Dr. {a.doctor.full_name}</td>
                <td className="muted">{a.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function LabBlock() {
  const { t } = useTranslation();
  const q = useGet<Paginated<LabOrder>>(["lab", "dash"], "/lab/orders/?status=ordered,in_progress&page_size=100", {
    refetchInterval: 30_000,
  });
  const items = q.data?.results.flatMap((o) => o.items) ?? [];
  const urgent = q.data?.results.filter((o) => o.priority === "urgent").length ?? 0;
  return (
    <Panel
      title={t("dash.lab", "Laboratory work")}
      actions={
        <Link className="btn btn-sm" to="/laboratory">
          {t("dash.open_worklist", "Open worklist")}
        </Link>
      }
    >
      <div className="figures">
        <div className="figure attention">
          <b>{items.filter((i) => i.status === "ordered").length}</b>
          <span>{t("dash.to_collect", "Specimens to collect")}</span>
        </div>
        <div className="figure">
          <b>{items.filter((i) => i.status === "collected").length}</b>
          <span>{t("dash.to_result", "Results to enter")}</span>
        </div>
        <div className="figure attention">
          <b>{items.filter((i) => i.status === "resulted").length}</b>
          <span>{t("dash.to_verify", "Results to verify")}</span>
        </div>
        <div className={`figure${urgent ? " danger" : ""}`}>
          <b>{urgent}</b>
          <span>{t("dash.urgent_orders", "Urgent orders")}</span>
        </div>
      </div>
    </Panel>
  );
}

function PharmacyBlock() {
  const { t } = useTranslation();
  const q = useGet<Paginated<Prescription>>(
    ["prescriptions", "pending"],
    "/prescriptions/?status=active,partial&page_size=50",
    { refetchInterval: 30_000 },
  );
  return (
    <Panel
      title={t("dash.pharmacy", "Prescriptions waiting")}
      actions={
        <Link className="btn btn-sm" to="/pharmacy">
          {t("dash.open_pharmacy", "Open pharmacy")}
        </Link>
      }
      flush
    >
      {!q.data?.results.length ? (
        <Empty>{t("pharmacy.none", "No prescriptions waiting.")}</Empty>
      ) : (
        <table className="data">
          <tbody>
            {q.data.results.slice(0, 8).map((rx) => (
              <tr key={rx.id}>
                <td>
                  <strong>{rx.patient.full_name}</strong>
                </td>
                <td className="muted">{rx.items.map((i) => i.drug_name).join(", ")}</td>
                <td className="num">
                  <StateBadge set="rx" value={rx.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function BillingBlock() {
  const { t } = useTranslation();
  const q = useGet<DailySummary>(["billing", "summary"], "/billing/daily-summary/", { refetchInterval: 60_000 });
  return (
    <Panel
      title={t("dash.money", "Money today")}
      actions={
        <Link className="btn btn-sm" to="/billing">
          {t("dash.open_billing", "Open billing")}
        </Link>
      }
    >
      {q.data && <SummaryFigures s={q.data} />}
      {q.data && q.data.by_cashier.length > 0 && (
        <table className="data" style={{ marginTop: 12 }}>
          <thead>
            <tr>
              <th>{t("billing.cashier", "Cashier")}</th>
              <th className="num">{t("billing.receipts", "Receipts")}</th>
              <th className="num">ETB</th>
            </tr>
          </thead>
          <tbody>
            {q.data.by_cashier.map((c) => (
              <tr key={c.cashier}>
                <td>{c.cashier}</td>
                <td className="num">{c.count}</td>
                <td className="num">{Number(c.total).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function useUserCount(key: string, params: Record<string, string>) {
  return useGet<Paginated<unknown>>(["count", key], `/users/${queryString({ ...params, page_size: 1 })}`).data?.count;
}

function ApprovalsBlock() {
  const { t } = useTranslation();
  const q = useGet<Paginated<Approval>>(["approvals", "dash"], "/approvals/?status=pending&page_size=20", {
    refetchInterval: 60_000,
  });
  const mine = q.data?.results.filter((a) => a.can_decide) ?? [];
  return (
    <Panel
      title={t("dash.approvals", "Waiting for your approval ({{n}})", { n: mine.length })}
      actions={
        <Link className="btn btn-sm" to="/approvals">
          {t("dash.open_approvals", "Open approvals")}
        </Link>
      }
      flush
    >
      {!mine.length ? (
        <Empty>{t("approvals.none", "Nothing waiting.")}</Empty>
      ) : (
        <table className="data">
          <tbody>
            {mine.slice(0, 6).map((a) => (
              <tr key={a.id}>
                <td>
                  <strong>{a.kind_label}</strong>
                  <div className="small muted">{a.summary}</div>
                </td>
                <td className="muted">{a.requested_by.full_name}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function AccountsBlock() {
  const { t } = useTranslation();
  const active = useUserCount("active", { is_active: "true" });
  const locked = useUserCount("locked", { locked: "true" });
  const pending = useUserCount("pending", { pending_password: "true" });
  return (
    <Panel
      title={t("nav.users")}
      actions={
        <Link className="btn btn-sm" to="/admin/users">
          {t("dash.manage_accounts", "Manage accounts")}
        </Link>
      }
    >
      <div className="figures">
        <div className="figure">
          <b>{active ?? "…"}</b>
          <span>{t("dashboard.stats.active_users")}</span>
        </div>
        <div className={`figure${locked ? " danger" : ""}`}>
          <b>{locked ?? "…"}</b>
          <span>{t("dashboard.stats.locked_users")}</span>
        </div>
        <div className="figure">
          <b>{pending ?? "…"}</b>
          <span>{t("dashboard.stats.pending_password")}</span>
        </div>
      </div>
    </Panel>
  );
}

function StaffBlock() {
  const { t } = useTranslation();
  const active = useUserCount("active", { is_active: "true" });
  const locked = useUserCount("locked", { locked: "true" });
  const depts = useGet<{ id: string; name: string; staff_count?: number; is_active: boolean }[]>(
    ["departments", "all"],
    "/departments/",
  );
  return (
    <Panel
      title={t("dash.staff", "Staff")}
      actions={
        <>
          <Link className="btn btn-sm" to="/admin/departments">
            {t("nav.departments", "Departments")}
          </Link>
          <Link className="btn btn-sm" to="/admin/users">
            {t("dash.manage_staff", "Manage staff")}
          </Link>
        </>
      }
    >
      <div className="figures">
        <div className="figure">
          <b>{active ?? "…"}</b>
          <span>{t("dashboard.stats.active_users")}</span>
        </div>
        <div className={`figure${locked ? " danger" : ""}`}>
          <b>{locked ?? "…"}</b>
          <span>{t("dashboard.stats.locked_users")}</span>
        </div>
        {depts.data
          ?.filter((d) => d.is_active && d.staff_count)
          .slice(0, 4)
          .map((d) => (
            <div key={d.id} className="figure">
              <b>{d.staff_count}</b>
              <span>{d.name}</span>
            </div>
          ))}
      </div>
    </Panel>
  );
}

function SecurityBlock() {
  const { t } = useTranslation();
  const q = useGet<Paginated<AuditEvent>>(
    ["audit", "dash"],
    `/audit-events/${queryString({ action: "auth.", date_from: isoDateDaysAgo(1), page_size: 8 })}`,
  );
  return (
    <Panel
      title={t("dashboard.recent_security")}
      actions={
        <Link className="btn btn-sm" to="/admin/audit">
          {t("dashboard.view_audit")}
        </Link>
      }
      flush
    >
      {!q.data?.results.length ? (
        <Empty>{t("audit.empty")}</Empty>
      ) : (
        <table className="data">
          <tbody>
            {q.data.results.map((e) => (
              <tr key={e.id}>
                <td className="nowrap">{formatDateTime(e.occurred_at)}</td>
                <td>{e.actor_username || String(e.details.username_entered ?? "")}</td>
                <td className="mono small">{e.action}</td>
                <td>
                  {e.outcome === "success" ? (
                    <span className="badge badge-ok">{t("audit.outcome_success")}</span>
                  ) : (
                    <span className="badge badge-danger">{t(`audit.outcome_${e.outcome}`)}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

/** Visits per day for the last 30 days, and the median wait to see a doctor per department. */
function ClinicTrendsBlock() {
  const { t } = useTranslation();
  const from = isoDateDaysAgo(29);
  const visits = useGet<ReportResult>(
    ["report", "visits", "dash", from],
    `/reports/visits/${queryString({ date_from: from })}`,
  );
  const depts = useGet<ReportResult>(
    ["report", "department_activity", "dash", from],
    `/reports/department_activity/${queryString({ date_from: from })}`,
  );
  // Every day of the period, including days without visits (zero), so gaps are visible.
  const byDay = new Map((visits.data?.rows ?? []).map((r) => [String(r.date), Number(r.total ?? 0)]));
  const days = Array.from({ length: 30 }, (_, i) => isoDateDaysAgo(29 - i)).map((d) => ({
    x: d,
    y: byDay.get(d) ?? 0,
  }));
  const total = days.reduce((s, d) => s + d.y, 0);
  const waits = (depts.data?.rows ?? [])
    .filter((r) => r.median_wait !== null && r.median_wait !== undefined)
    .map((r) => ({ label: String(r.department), value: Number(r.median_wait) }))
    .sort((a, b) => b.value - a.value);
  return (
    <Panel
      title={t("dash.trends", "The last 30 days")}
      actions={
        <Link className="btn btn-sm" to="/reports">
          {t("dash.all_reports", "All reports")}
        </Link>
      }
    >
      <div className="chart-grid-2">
        <div className="chart-card">
          <h3>
            {t("dash.visits_per_day", "Visits per day")}{" "}
            <span className="muted small">({t("dash.total_n", "{{n}} in total", { n: total })})</span>
          </h3>
          {visits.data && (
            <ColumnChart
              data={days}
              valueLabel={t("dash.visits", "visits")}
              label={t("dash.visits_aria", "Visits per day for the last 30 days, {{n}} in total", { n: total })}
            />
          )}
          <ChartTable
            head={[t("common.date", "Date"), t("dash.visits_col", "Visits")]}
            rows={days.map((d) => [shortDate(d.x), d.y])}
          />
        </div>
        <div className="chart-card">
          <h3>
            {t("dash.median_wait", "Median wait to see a doctor")}{" "}
            <span className="muted small">({t("dash.minutes", "minutes")})</span>
          </h3>
          {depts.data &&
            (waits.length ? (
              <BarList
                rows={waits}
                valueLabel={t("dash.minutes", "minutes")}
                label={t("dash.median_wait", "Median wait to see a doctor")}
                format={(n) => `${n} min`}
              />
            ) : (
              <p className="subtle small">{t("dash.no_waits", "No consultations in this period yet.")}</p>
            ))}
          {waits.length > 0 && (
            <ChartTable
              head={[t("reports.department", "Department"), t("dash.minutes_col", "Minutes")]}
              rows={waits.map((w) => [w.label, w.value])}
            />
          )}
        </div>
      </div>
    </Panel>
  );
}
