/** Trends in the patient record: vital signs and repeated numeric laboratory results over time. */
import { useTranslation } from "react-i18next";
import type { LabOrder, Vitals } from "../api/types";
import { ChartTable, LineChart, shortDate, type Series } from "../charts";
import { formatDateTime } from "../lib/format";
import { Panel } from "../ui";

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/** Small multiples, one per measure, each with its own axis. Shown once a measure has two readings. */
export function VitalsTrends({ vitals }: { vitals: Vitals[] }) {
  const { t } = useTranslation();
  const rows = [...vitals].sort((a, b) => a.recorded_at.localeCompare(b.recorded_at));
  const pts = (key: keyof Vitals) =>
    rows.map((v) => ({ x: v.recorded_at, y: num(v[key]) })).filter((p) => p.y !== null);
  const panels: { title: string; unit: string; series: Series[] }[] = [
    {
      title: t("trends.bp", "Blood pressure"),
      unit: "mmHg",
      series: [
        { key: "sys", label: t("trends.systolic", "Systolic"), points: pts("systolic") },
        { key: "dia", label: t("trends.diastolic", "Diastolic"), points: pts("diastolic") },
      ],
    },
    {
      title: t("trends.temp", "Temperature"),
      unit: "°C",
      series: [{ key: "t", label: t("trends.temp", "Temperature"), points: pts("temperature_c") }],
    },
    {
      title: t("trends.hr", "Heart rate"),
      unit: "bpm",
      series: [{ key: "hr", label: t("trends.hr", "Heart rate"), points: pts("heart_rate") }],
    },
    {
      title: t("trends.spo2", "Oxygen saturation"),
      unit: "%",
      series: [{ key: "o2", label: "SpO₂", points: pts("spo2") }],
    },
    {
      title: t("trends.weight", "Weight"),
      unit: "kg",
      series: [{ key: "w", label: t("trends.weight", "Weight"), points: pts("weight_kg") }],
    },
  ].filter((p) => p.series.some((s) => s.points.length >= 2));
  if (!panels.length) return null;
  return (
    <Panel title={t("trends.vitals_title", "Trends")}>
      <p className="chart-caption">
        {t(
          "trends.vitals_caption",
          "Each reading from triage, oldest on the left. Hover or use the arrow keys for values; the table below lists every reading.",
        )}
      </p>
      <div className="chart-grid-2">
        {panels.map((p) => (
          <div className="chart-card" key={p.title}>
            <h3>
              {p.title} <span className="muted small">({p.unit})</span>
            </h3>
            <LineChart
              series={p.series}
              unit={p.unit}
              withTime
              height={170}
              label={t("trends.aria", "{{what}} over {{n}} readings", { what: p.title, n: p.series[0].points.length })}
            />
          </div>
        ))}
      </div>
    </Panel>
  );
}

/** One line per numeric test done at least twice, with the reference range of the latest result. */
export function LabTrends({ orders }: { orders: LabOrder[] }) {
  const { t } = useTranslation();
  const byTest = new Map<
    string,
    {
      name: string;
      unit: string;
      points: { x: string; y: number }[];
      ref: { low: number | null; high: number | null; text: string };
    }
  >();
  const items = orders
    .flatMap((o) => o.items.map((i) => ({ o, i })))
    .filter(({ i }) => i.status === "verified" && num(i.result_numeric) !== null)
    .sort((a, b) => (a.i.verified_at ?? a.o.created_at).localeCompare(b.i.verified_at ?? b.o.created_at));
  for (const { o, i } of items) {
    const g = byTest.get(i.test.code) ?? {
      name: i.test.name,
      unit: i.unit,
      points: [],
      ref: { low: null, high: null, text: "" },
    };
    g.points.push({ x: i.verified_at ?? o.created_at, y: num(i.result_numeric) as number });
    const lo = num(i.ref_low),
      hi = num(i.ref_high);
    g.ref = { low: lo, high: hi, text: lo !== null || hi !== null ? `${lo ?? ""}–${hi ?? ""} ${i.unit}` : "" };
    byTest.set(i.test.code, g);
  }
  const tests = [...byTest.values()].filter((g) => g.points.length >= 2);
  if (!tests.length) return null;
  return (
    <Panel title={t("trends.lab_title", "Results over time")}>
      <p className="chart-caption">
        {t(
          "trends.lab_caption",
          "Verified numeric results of tests done more than once. The shaded band is the reference range of the latest result.",
        )}
      </p>
      <div className="chart-grid-2">
        {tests.map((g) => (
          <div className="chart-card" key={g.name}>
            <h3>
              {g.name} {g.unit && <span className="muted small">({g.unit})</span>}
            </h3>
            <LineChart
              series={[{ key: g.name, label: g.name, points: g.points }]}
              unit={g.unit}
              withTime
              height={170}
              band={
                g.ref.low !== null || g.ref.high !== null
                  ? { low: g.ref.low, high: g.ref.high, label: `${t("lab.reference", "Reference")} ${g.ref.text}` }
                  : undefined
              }
              label={t("trends.aria", "{{what}} over {{n}} readings", { what: g.name, n: g.points.length })}
            />
            <ChartTable
              head={[t("common.date", "Date"), g.unit || t("lab.result", "Result")]}
              rows={g.points.map((p) => [`${shortDate(p.x)} (${formatDateTime(p.x)})`, p.y])}
            />
          </div>
        ))}
      </div>
    </Panel>
  );
}
