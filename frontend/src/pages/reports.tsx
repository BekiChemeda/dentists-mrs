import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, Printer } from "lucide-react";
import { queryString } from "../api/client";
import { useGet } from "../api/hooks";
import type { ReportInfo, ReportResult } from "../api/types";
import { formatDateTime } from "../lib/format";
import { Empty, ErrorBanner, Field, Loading, PageHead, Panel, money, qty } from "../ui";
import { todayIso } from "./common";
import { useTriageDestinations } from "../labels";
import { BarList, ColumnChart } from "../charts";

/** Which reports get a chart above the table, and what it shows. Financial reports have none. */
const REPORT_CHARTS: Record<string, { kind: "time"; value: string } | { kind: "bars"; label: string; value: string }> =
  {
    registrations: { kind: "time", value: "total" },
    visits: { kind: "time", value: "total" },
    department_activity: { kind: "bars", label: "department", value: "visits" },
    consultations: { kind: "bars", label: "doctor", value: "consultations" },
    appointments: { kind: "bars", label: "status", value: "total" },
    lab_requests: { kind: "bars", label: "test", value: "requested" },
    lab_results: { kind: "bars", label: "test", value: "results" },
    dispensing: { kind: "bars", label: "medicine", value: "times" },
    diagnoses: { kind: "bars", label: "diagnosis", value: "cases" },
    opd_morbidity: { kind: "bars", label: "diagnosis", value: "total" },
  };

function ReportChart({ report }: { report: ReportResult }) {
  const spec = REPORT_CHARTS[report.key];
  if (!spec || report.rows.length < 2) return null;
  const col = report.columns.find((c) => c.key === spec.value);
  if (!col) return null;
  if (spec.kind === "time") {
    // Every day in the range, zero where nothing happened, so quiet days show as gaps rather than vanishing.
    const byDay = new Map(report.rows.map((r) => [String(r.date), Number(r[spec.value] ?? 0)]));
    const days: { x: string; y: number }[] = [];
    for (
      let d = new Date(`${report.date_from}T00:00:00`);
      d <= new Date(`${report.date_to}T00:00:00`) && days.length < 370;
      d.setDate(d.getDate() + 1)
    ) {
      const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      days.push({ x: iso, y: byDay.get(iso) ?? 0 });
    }
    return (
      <div className="report-chart">
        <ColumnChart data={days} valueLabel={col.label.toLowerCase()} label={`${report.title}: ${col.label} per day`} />
      </div>
    );
  }
  const rows = report.rows
    .map((r) => ({ label: String(r[spec.label] ?? "—"), value: Number(r[spec.value] ?? 0) }))
    .sort((a, b) => b.value - a.value);
  return (
    <div className="report-chart">
      <p className="chart-caption">
        {col.label}
        {rows.length > 12 ? ` (top 12 of ${rows.length}; all rows in the table)` : ""}
      </p>
      <BarList rows={rows} valueLabel={col.label.toLowerCase()} label={`${report.title}: ${col.label}`} />
    </div>
  );
}

function firstOfMonth(): string {
  return `${todayIso().slice(0, 8)}01`;
}

export function ReportsPage() {
  const { t } = useTranslation();
  const catalog = useGet<ReportInfo[]>(["reports"], "/reports/");
  const [key, setKey] = useState("");
  const [from, setFrom] = useState(firstOfMonth());
  const [to, setTo] = useState(todayIso());
  const [dept, setDept] = useState("");
  const departments = useTriageDestinations();
  const active = key || catalog.data?.[0]?.key || "";
  const info = catalog.data?.find((r) => r.key === active);
  const deptParam = info?.by_department ? dept : "";
  const params = { date_from: from, date_to: to, department: deptParam || undefined };
  const report = useGet<ReportResult>(
    ["report", active, from, to, deptParam],
    active ? `/reports/${active}/${queryString(params)}` : null,
  );

  const format = (kind: string, value: unknown) => {
    if (value === null || value === undefined || value === "") return "—";
    if (kind === "money") return money(value as string);
    if (kind === "number") return qty(value as string);
    return String(value);
  };
  const totals = (col: { key: string; kind: string }) =>
    (col.kind === "money" || col.kind === "number") && !/median|longest/.test(col.key)
      ? (report.data?.rows ?? []).reduce((s, r) => s + Number(r[col.key] ?? 0), 0)
      : null;
  const summable =
    report.data && report.data.rows.length > 1 && !["pharmacy_stock", "outstanding"].includes(report.data.key)
      ? report.data.columns
      : null;

  return (
    <div className="stack">
      <PageHead
        title={t("nav.reports")}
        sub={t("reports.sub", "Choose a report and a date range. Exports are recorded in the audit log.")}
      />
      {catalog.data?.length === 0 && <Empty>{t("reports.none", "Your role has no reports.")}</Empty>}
      <div className="filters no-print">
        <div className="field" style={{ minWidth: 260 }}>
          <label htmlFor="rk">{t("reports.report", "Report")}</label>
          <select id="rk" value={active} onChange={(e) => setKey(e.target.value)}>
            {catalog.data?.map((r) => (
              <option key={r.key} value={r.key}>
                {r.title}
              </option>
            ))}
          </select>
        </div>
        {info?.uses_dates !== false && (
          <>
            <Field label={t("reports.from", "From")} id="rf">
              <input id="rf" type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
            </Field>
            <Field label={t("reports.to", "To")} id="rt">
              <input id="rt" type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
            </Field>
          </>
        )}
        {info?.by_department && (
          <Field label={t("reports.department", "Department")} id="rd">
            <select id="rd" value={dept} onChange={(e) => setDept(e.target.value)}>
              <option value="">{t("reports.all_departments", "All departments")}</option>
              {departments.map((d) => (
                <option key={d.code} value={d.code}>
                  {d.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <div className="row">
          {report.data?.can_export && (
            <a className="btn" href={`/api/v1/reports/${active}/${queryString({ ...params, export: "csv" })}`}>
              <Download size={16} aria-hidden /> CSV
            </a>
          )}
          <button className="btn" onClick={() => window.print()}>
            <Printer size={16} aria-hidden /> {t("reports.print", "Print or save as PDF")}
          </button>
        </div>
      </div>
      <ErrorBanner error={report.error} />
      {report.isLoading && <Loading />}
      {report.data && (
        <Panel
          flush
          title={
            <div>
              <h2>{report.data.title}</h2>
              <p className="small muted">
                {report.data.description}{" "}
                {report.data.uses_dates
                  ? t("reports.range", "{{from}} to {{to}}.", { from: report.data.date_from, to: report.data.date_to })
                  : t("reports.as_of", "As of now.")}
                {report.data.department_name
                  ? ` ${t("reports.for_department", "Department: {{name}}.", { name: report.data.department_name })}`
                  : ""}{" "}
                {t("reports.generated", "Generated {{when}}.", { when: formatDateTime(report.data.generated_at) })}
              </p>
            </div>
          }
        >
          {report.data.rows.length === 0 ? (
            <Empty>{t("reports.no_rows", "No data for this period.")}</Empty>
          ) : (
            <>
              <ReportChart report={report.data} />
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      {report.data.columns.map((c) => (
                        <th key={c.key} className={c.kind === "money" || c.kind === "number" ? "num" : ""}>
                          {c.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {report.data.rows.map((r, n) => (
                      <tr key={n}>
                        {report.data!.columns.map((c) => (
                          <td key={c.key} className={c.kind === "money" || c.kind === "number" ? "num" : ""}>
                            {format(c.kind, r[c.key])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                  {summable && (
                    <tfoot>
                      <tr>
                        {summable.map((c, n) => {
                          const total = totals(c);
                          return (
                            <td key={c.key} className={total !== null ? "num" : ""}>
                              {n === 0 ? t("reports.total", "Total") : total !== null ? format(c.kind, total) : ""}
                            </td>
                          );
                        })}
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            </>
          )}
        </Panel>
      )}
    </div>
  );
}
