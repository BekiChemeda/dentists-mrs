/**
 * Small, dependency-free charts drawn in SVG, so they work offline like the rest of the system.
 *
 * Rules (docs: dataviz method): one y-axis per chart; at most three series, coloured in a fixed order
 * (--series-1..3, validated for colour-blind separation in light and dark); 2px lines, >=8px markers with a
 * surface ring, columns <=24px with a 4px rounded end; hairline gridlines; a hover/focus tooltip on every
 * chart; a legend when there are two or more series; and the same numbers always available as a table.
 */
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

export interface Point {
  x: string;
  y: number | null;
}
export interface Series {
  key: string;
  label: string;
  points: Point[];
}

const SERIES_VARS = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

// --------------------------------------------------------------------------- helpers
function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setWidth(el.clientWidth);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/** Clean axis ticks (1, 2 or 5 times a power of ten) covering [min, max]. */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const start = Math.floor(min / step) * step;
  const out: number[] = [];
  for (let v = start; out.length < 50; v += step) {
    out.push(Number(v.toFixed(10)));
    if (v >= max - step * 1e-9) break; // the last tick is at or above the highest value
  }
  return out;
}

function compact(n: number): string {
  const a = Math.abs(n);
  if (a >= 1_000_000) return `${(n / 1_000_000).toFixed(a >= 10_000_000 ? 0 : 1)}M`;
  if (a >= 10_000) return `${Math.round(n / 1000)}K`;
  return n.toLocaleString("en-US", { maximumFractionDigits: 1 });
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "22 Nov" for dates; "22 Nov 10:40" for date-times. */
export function shortDate(iso: string, withTime = false): string {
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  const base = `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  return withTime
    ? `${base} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
    : base;
}

/** Indexes of x labels to draw: at least `gap` px apart, always the last one (dropping its neighbour). */
export function thinLabels(positions: number[], gap = 56): Set<number> {
  const keep: number[] = [];
  positions.forEach((x, i) => {
    if (!keep.length || x - positions[keep[keep.length - 1]] >= gap) keep.push(i);
  });
  const last = positions.length - 1;
  if (last >= 0 && keep[keep.length - 1] !== last) {
    while (keep.length && positions[last] - positions[keep[keep.length - 1]] < gap) keep.pop();
    keep.push(last);
  }
  return new Set(keep);
}

function Legend({ series }: { series: { label: string; color: string; kind: "line" | "rect" }[] }) {
  if (series.length < 2) return null;
  return (
    <ul className="chart-legend">
      {series.map((s) => (
        <li key={s.label}>
          <span className={`chart-key chart-key-${s.kind}`} style={{ background: s.color }} aria-hidden />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

/** Every chart's numbers as a table, one click away (and always for screen readers). */
export function ChartTable({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  const { t } = useTranslation();
  return (
    <details className="chart-table no-print">
      <summary>{t("charts.show_table", "Show as table")}</summary>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              {head.map((h, i) => (
                <th key={i} className={i ? "num" : ""}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, n) => (
              <tr key={n}>
                {r.map((c, i) => (
                  <td key={i} className={i ? "num" : ""}>
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function Tooltip({ x, y, width, children }: { x: number; y: number; width: number; children: ReactNode }) {
  const left = Math.min(Math.max(x + 12, 4), Math.max(width - 190, 4));
  return (
    <div className="chart-tip" role="status" style={{ left, top: Math.max(y - 8, 0) }}>
      {children}
    </div>
  );
}

// --------------------------------------------------------------------------- line chart
export function LineChart({
  series,
  height = 200,
  unit = "",
  band,
  format = compact,
  withTime = false,
  label,
}: {
  series: Series[];
  height?: number;
  /** Shown after values in the tooltip, e.g. "mmHg". */
  unit?: string;
  /** Optional normal/reference range drawn as a neutral wash. */
  band?: { low: number | null; high: number | null; label: string };
  format?: (n: number) => string;
  withTime?: boolean;
  /** Accessible description, e.g. "Blood pressure over the last 6 visits". */
  label: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const shown = series.slice(0, 3);
  const xs = useMemo(() => [...new Set(shown.flatMap((s) => s.points.map((p) => p.x)))].sort(), [shown]);
  const values = shown.flatMap((s) => s.points.map((p) => p.y)).filter((v): v is number => v !== null);
  if (band?.low != null) values.push(band.low);
  if (band?.high != null) values.push(band.high);
  const ticks = niceTicks(Math.min(...values), Math.max(...values));
  const yMin = ticks[0],
    yMax = ticks[ticks.length - 1];
  const pad = { l: 44, r: 16, t: 10, b: 26 };
  const w = Math.max(width, 240),
    h = height;
  const times = xs.map((x) => new Date(x.length === 10 ? `${x}T00:00:00` : x).getTime());
  const tMin = Math.min(...times),
    tMax = Math.max(...times);
  const px = (x: string) => {
    if (xs.length === 1 || tMax === tMin) return pad.l + (w - pad.l - pad.r) / 2;
    const t = new Date(x.length === 10 ? `${x}T00:00:00` : x).getTime();
    return pad.l + ((t - tMin) / (tMax - tMin)) * (w - pad.l - pad.r);
  };
  const py = (v: number) => pad.t + (1 - (v - yMin) / (yMax - yMin || 1)) * (h - pad.t - pad.b);
  const shownLabels = thinLabels(xs.map(px), 64);
  const onKey = (e: KeyboardEvent) => {
    if (!xs.length) return;
    if (e.key === "ArrowRight") {
      setHover((h0) => Math.min((h0 ?? -1) + 1, xs.length - 1));
      e.preventDefault();
    }
    if (e.key === "ArrowLeft") {
      setHover((h0) => Math.max((h0 ?? xs.length) - 1, 0));
      e.preventDefault();
    }
    if (e.key === "Escape") setHover(null);
  };
  const nearest = (clientX: number, rect: DOMRect) => {
    const x = clientX - rect.left;
    let best = 0;
    xs.forEach((v, i) => {
      if (Math.abs(px(v) - x) < Math.abs(px(xs[best]) - x)) best = i;
    });
    return best;
  };
  if (!values.length) return null;
  const hx = hover !== null ? xs[hover] : null;
  return (
    <div className="chart" ref={ref}>
      <Legend series={shown.map((s, i) => ({ label: s.label, color: SERIES_VARS[i], kind: "line" }))} />
      {width > 0 && (
        <svg
          width={w}
          height={h}
          role="img"
          aria-label={label}
          tabIndex={0}
          onKeyDown={onKey}
          onBlur={() => setHover(null)}
          onPointerMove={(e) => setHover(nearest(e.clientX, e.currentTarget.getBoundingClientRect()))}
          onPointerLeave={() => setHover(null)}
        >
          {band && (band.low != null || band.high != null) && (
            <rect
              className="chart-band"
              x={pad.l}
              width={w - pad.l - pad.r}
              y={py(band.high ?? yMax)}
              height={Math.max(py(band.low ?? yMin) - py(band.high ?? yMax), 0)}
            >
              <title>{band.label}</title>
            </rect>
          )}
          {ticks.map((tk) => (
            <g key={tk}>
              <line className="chart-grid" x1={pad.l} x2={w - pad.r} y1={py(tk)} y2={py(tk)} />
              <text className="chart-axis" x={pad.l - 8} y={py(tk)} dy="0.32em" textAnchor="end">
                {format(tk)}
              </text>
            </g>
          ))}
          {xs.map((x, i) =>
            shownLabels.has(i) ? (
              <text
                key={x}
                className="chart-axis"
                x={px(x)}
                y={h - 6}
                textAnchor={
                  i === 0 && xs.length > 1 ? "start" : i === xs.length - 1 && xs.length > 1 ? "end" : "middle"
                }
              >
                {shortDate(x)}
              </text>
            ) : null,
          )}
          {hx && <line className="chart-crosshair" x1={px(hx)} x2={px(hx)} y1={pad.t} y2={h - pad.b} />}
          {shown.map((s, i) => {
            const pts = s.points.filter((p) => p.y !== null).sort((a, b) => a.x.localeCompare(b.x));
            const d = pts
              .map((p, n) => `${n ? "L" : "M"}${px(p.x).toFixed(1)},${py(p.y as number).toFixed(1)}`)
              .join("");
            const last = pts[pts.length - 1];
            return (
              <g key={s.key} style={{ color: SERIES_VARS[i] }}>
                {pts.length > 1 && <path className="chart-line" d={d} />}
                {pts.map(
                  (p) =>
                    (pts.length <= 24 || p === last || p.x === hx) && (
                      <circle
                        key={p.x}
                        className="chart-dot"
                        cx={px(p.x)}
                        cy={py(p.y as number)}
                        r={p.x === hx ? 5 : 4}
                      />
                    ),
                )}
              </g>
            );
          })}
        </svg>
      )}
      {hx && (
        <Tooltip x={px(hx)} y={pad.t} width={w}>
          <div className="chart-tip-title">{shortDate(hx, withTime)}</div>
          {shown.map((s, i) => {
            const p = s.points.find((q) => q.x === hx);
            return p && p.y !== null ? (
              <div key={s.key} className="chart-tip-row">
                <span className="chart-key chart-key-line" style={{ background: SERIES_VARS[i] }} aria-hidden />
                <strong>
                  {format(p.y)}
                  {unit && ` ${unit}`}
                </strong>{" "}
                <span className="muted">{s.label}</span>
              </div>
            ) : null;
          })}
          {band && <div className="small muted">{band.label}</div>}
        </Tooltip>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- columns (counts per day)
export function ColumnChart({
  data,
  height = 180,
  label,
  valueLabel,
  format = compact,
}: {
  data: { x: string; y: number }[];
  height?: number;
  label: string;
  valueLabel: string;
  format?: (n: number) => string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const uid = useId();
  if (!data.length) return null;
  const ticks = niceTicks(0, Math.max(...data.map((d) => d.y), 1));
  const yMax = ticks[ticks.length - 1];
  const pad = { l: 40, r: 8, t: 10, b: 26 };
  const w = Math.max(width, 240),
    h = height;
  const slot = (w - pad.l - pad.r) / data.length;
  const bw = Math.min(24, Math.max(slot - 2, 2));
  const py = (v: number) => pad.t + (1 - v / (yMax || 1)) * (h - pad.t - pad.b);
  const shownLabels = thinLabels(
    data.map((_, i) => pad.l + i * slot + slot / 2),
    56,
  );
  const r = Math.min(4, bw / 2);
  const bar = (x: number, top: number, bottom: number) => {
    const hgt = bottom - top;
    if (hgt <= 0) return "";
    const rr = Math.min(r, hgt);
    return `M${x},${bottom}V${top + rr}Q${x},${top} ${x + rr},${top}H${x + bw - rr}Q${x + bw},${top} ${x + bw},${top + rr}V${bottom}Z`;
  };
  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={w} height={h} role="img" aria-label={label}>
          {ticks.map((tk) => (
            <g key={tk}>
              <line className="chart-grid" x1={pad.l} x2={w - pad.r} y1={py(tk)} y2={py(tk)} />
              <text className="chart-axis" x={pad.l - 8} y={py(tk)} dy="0.32em" textAnchor="end">
                {format(tk)}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const x = pad.l + i * slot + (slot - bw) / 2;
            return (
              <g key={d.x}>
                <path className={`chart-col${hover === i ? " is-hover" : ""}`} d={bar(x, py(d.y), py(0))} />
                <rect
                  className="chart-hit"
                  x={pad.l + i * slot}
                  y={pad.t}
                  width={slot}
                  height={h - pad.t - pad.b}
                  tabIndex={0}
                  aria-describedby={hover === i ? uid : undefined}
                  aria-label={`${shortDate(d.x)}: ${format(d.y)} ${valueLabel}`}
                  onPointerEnter={() => setHover(i)}
                  onPointerLeave={() => setHover(null)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                />
                {shownLabels.has(i) && (
                  <text className="chart-axis" x={x + bw / 2} y={h - 6} textAnchor="middle">
                    {shortDate(d.x)}
                  </text>
                )}
              </g>
            );
          })}
          <line className="chart-baseline" x1={pad.l} x2={w - pad.r} y1={py(0)} y2={py(0)} />
        </svg>
      )}
      {hover !== null && (
        <Tooltip x={pad.l + hover * slot + slot / 2} y={py(data[hover].y) - 30} width={w}>
          <span id={uid}>
            <strong>{format(data[hover].y)}</strong>{" "}
            <span className="muted">
              {valueLabel}, {shortDate(data[hover].x)}
            </span>
          </span>
        </Tooltip>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- horizontal bars (categories)
export function BarList({
  rows,
  label,
  valueLabel,
  format = compact,
  max = 12,
}: {
  rows: { label: string; value: number }[];
  label: string;
  valueLabel: string;
  format?: (n: number) => string;
  max?: number;
}) {
  const shown = rows.slice(0, max);
  const top = Math.max(...shown.map((r) => r.value), 1);
  return (
    <ul className="bar-list" role="list" aria-label={label}>
      {shown.map((r) => (
        <li key={r.label} tabIndex={0} title={`${r.label}: ${format(r.value)} ${valueLabel}`}>
          <span className="bar-list-label">{r.label}</span>
          <span className="bar-list-track">
            <span
              className="bar-list-bar"
              style={{ width: `calc((100% - 4.5rem) * ${r.value > 0 ? Math.max(r.value / top, 0.015) : 0})` }}
            />
            <span className="bar-list-value">{format(r.value)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
