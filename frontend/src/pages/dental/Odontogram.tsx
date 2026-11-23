/**
 * The dental chart. A drawing of dated findings, never the source of truth: the server keeps every finding with
 * who recorded it and when (ADR 0006). Symbols and text carry the meaning; colour is only a second cue, so the
 * chart stays readable in grayscale print and for colour-blind staff.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Badge, ConfirmDialog, ErrorBanner, Field, ReasonDialog, Segmented, toast } from "../../ui";
import { formatDateTime } from "../../lib/format";
import {
  REGION_NAMES,
  SURFACE_NAMES,
  allowedSurfaces,
  isUpper,
  mesialOnRight,
  orderSurfaces,
  rowsFor,
  type Dentition,
} from "../../lib/teeth";
import type { DentalDiagnosis, Finding, FindingType } from "./types";

const KIND_LABEL: Record<string, string> = {
  state: "Tooth state",
  condition: "Current condition",
  existing: "Existing treatment",
};

function findingsByTooth(findings: Finding[]): Map<number, Finding[]> {
  const map = new Map<number, Finding[]>();
  for (const f of findings) {
    if (f.location.tooth == null) continue;
    const list = map.get(f.location.tooth) ?? [];
    list.push(f);
    map.set(f.location.tooth, list);
  }
  return map;
}

/** Which surface of the five-part diagram sits where, for this tooth. */
function surfaceAt(tooth: number, position: "top" | "bottom" | "left" | "right" | "centre"): string {
  if (position === "centre") return allowedSurfaces(tooth).includes("O") ? "O" : "I";
  if (position === "top") return isUpper(tooth) ? "B" : "L";
  if (position === "bottom") return isUpper(tooth) ? "L" : "B";
  const mesialRight = mesialOnRight(tooth);
  if (position === "right") return mesialRight ? "M" : "D";
  return mesialRight ? "D" : "M";
}

const POLYGONS: Record<"top" | "bottom" | "left" | "right" | "centre", string> = {
  top: "0,0 30,0 21,9 9,9",
  bottom: "9,21 21,21 30,30 0,30",
  left: "0,0 9,9 9,21 0,30",
  right: "30,0 30,30 21,21 21,9",
  centre: "9,9 21,9 21,21 9,21",
};

function ToothDiagram({ tooth, findings }: { tooth: number; findings: Finding[] }) {
  const onSurface = (letter: string) => findings.filter((f) => f.location.surfaces.includes(letter));
  const whole = findings.filter((f) => f.location.scope === "tooth");
  const missing = whole.some((f) => ["missing", "extracted"].includes(f.finding_type.code));
  return (
    <svg viewBox="-1 -1 32 32" width="32" height="32" aria-hidden className="tooth-svg">
      <defs>
        <pattern id={`hatch-${tooth}`} width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="4" stroke="currentColor" strokeWidth="2" />
        </pattern>
      </defs>
      {(Object.keys(POLYGONS) as (keyof typeof POLYGONS)[]).map((pos) => {
        const letter = surfaceAt(tooth, pos);
        const hits = onSurface(letter);
        const condition = hits.find((f) => f.finding_type.kind === "condition");
        const existing = hits.find((f) => f.finding_type.kind !== "condition");
        const shown = condition ?? existing;
        return (
          <polygon
            key={pos}
            points={POLYGONS[pos]}
            className={`tooth-surface${shown ? (condition ? " has-condition" : " has-existing") : ""}`}
            style={shown ? { color: shown.finding_type.color || undefined } : undefined}
            fill={shown ? (condition ? "currentColor" : `url(#hatch-${tooth})`) : undefined}
          />
        );
      })}
      {missing && <path d="M2 2 L28 28 M28 2 L2 28" className="tooth-missing" />}
    </svg>
  );
}

export function Odontogram({
  findings,
  dentition,
  selected,
  onSelect,
}: {
  findings: Finding[];
  dentition: Dentition;
  selected: number | null;
  onSelect: (tooth: number) => void;
}) {
  const { t } = useTranslation();
  const byTooth = useMemo(() => findingsByTooth(findings), [findings]);
  const rows = rowsFor(dentition);
  return (
    <div className="odontogram" role="group" aria-label={t("dental.chart", "Dental chart")}>
      <div className="odontogram-sides small subtle" aria-hidden>
        <span>{t("dental.patient_right", "Patient's right")}</span>
        <span>{t("dental.patient_left", "Patient's left")}</span>
      </div>
      {rows.map((row, i) => (
        <div key={i} className={`odontogram-row${i === rows.length / 2 - 1 ? " arch-gap" : ""}`}>
          {row.map((tooth) => {
            const list = byTooth.get(tooth) ?? [];
            const label = list.length
              ? `${t("dental.tooth", "Tooth")} ${tooth}: ${list
                  .map((f) => `${f.finding_type.name}${f.location.surfaces ? ` ${f.location.surfaces}` : ""}`)
                  .join("; ")}`
              : `${t("dental.tooth", "Tooth")} ${tooth}: ${t("dental.no_findings", "no findings")}`;
            return (
              <button
                key={tooth}
                type="button"
                className={`tooth${selected === tooth ? " selected" : ""}${list.length ? " has-findings" : ""}`}
                aria-pressed={selected === tooth}
                aria-label={label}
                title={label}
                onClick={() => onSelect(tooth)}
              >
                <span className="tooth-num">{tooth}</span>
                <ToothDiagram tooth={tooth} findings={list} />
                <span className="tooth-symbols">
                  {list.map((f) => (
                    <span key={f.id} className={`sym sym-${f.finding_type.kind}`}>
                      {f.finding_type.symbol}
                    </span>
                  ))}
                </span>
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

/** Explains every symbol in use, by kind. Printed with the chart. */
export function ChartLegend({ findings, types }: { findings: Finding[]; types: FindingType[] }) {
  const { t } = useTranslation();
  const used = new Set(findings.map((f) => f.finding_type.code));
  const shown = types.filter((ft) => used.has(ft.code));
  return (
    <div className="chart-legend-dental small">
      <strong>{t("dental.legend", "Legend")}</strong>
      <ul>
        <li>
          <span className="legend-swatch solid" /> {t("dental.legend_condition", "Filled surface: current condition")}
        </li>
        <li>
          <span className="legend-swatch hatch" /> {t("dental.legend_existing", "Hatched surface: existing treatment")}
        </li>
        <li>✕ {t("dental.legend_missing", "Cross: tooth missing or extracted")}</li>
        {shown.map((ft) => (
          <li key={ft.code}>
            <span className={`sym sym-${ft.kind}`}>{ft.symbol}</span> {ft.name}{" "}
            <span className="subtle">({KIND_LABEL[ft.kind]})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DentitionSwitch({ value, onChange }: { value: Dentition; onChange: (d: Dentition) => void }) {
  const { t } = useTranslation();
  return (
    <Segmented
      label={t("dental.dentition", "Dentition")}
      value={value}
      onChange={onChange}
      options={[
        { key: "permanent", label: t("dental.permanent", "Permanent") },
        { key: "primary", label: t("dental.primary", "Primary") },
        { key: "mixed", label: t("dental.mixed", "Mixed") },
      ]}
    />
  );
}

function FindingLine({ f }: { f: Finding }) {
  const { t } = useTranslation();
  const struck = !!f.voided_at || !!f.resolved_at;
  return (
    <div className={`finding-line${struck ? " struck" : ""}`}>
      <span className={`sym sym-${f.finding_type.kind}`}>{f.finding_type.symbol}</span>{" "}
      <strong>{f.finding_type.name}</strong> <span className="mono">{f.location.label}</span>
      {f.is_existing_work && <Badge tone="info">{t("dental.existing", "existing")}</Badge>}
      {f.note && <span> — {f.note}</span>}
      {f.diagnosis && (
        <span className="small subtle">
          {" "}
          ({f.diagnosis.code} {f.diagnosis.term})
        </span>
      )}
      <div className="small subtle">
        {t("dental.recorded_by", "Recorded by {{who}}, {{when}}", {
          who: f.recorded_by.full_name,
          when: formatDateTime(f.recorded_at),
        })}
        {f.resolved_at &&
          ` · ${t("dental.resolved", "No longer present")}: ${f.resolution_note} (${f.resolved_by?.full_name}, ${formatDateTime(f.resolved_at)})`}
        {f.voided_at &&
          ` · ${t("dental.voided", "Entered in error")}: ${f.void_reason} (${f.voided_by?.full_name}, ${formatDateTime(f.voided_at)})`}
      </div>
    </div>
  );
}

/**
 * The selected tooth (or the whole mouth): current findings, history, and — in an open examination — the form to
 * record a finding. `encounterId` set and `editable` true = the chart is being recorded in that examination.
 */
export function ToothPanel({
  tooth,
  current,
  history,
  types,
  diagnoses,
  encounterId,
  editable,
  canAmend,
  invalidate,
}: {
  tooth: number | "mouth";
  current: Finding[];
  history: Finding[];
  types: FindingType[];
  diagnoses: DentalDiagnosis[];
  encounterId?: string;
  editable: boolean;
  canAmend: boolean;
  invalidate: string[][];
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const isMouth = tooth === "mouth";
  const [scope, setScope] = useState<"tooth" | "surfaces" | "region" | "mouth">(isMouth ? "mouth" : "tooth");
  const [surfaces, setSurfaces] = useState<string[]>([]);
  const [region, setRegion] = useState("q1");
  const [typeId, setTypeId] = useState("");
  const [note, setNote] = useState("");
  const [diagnosisId, setDiagnosisId] = useState("");
  const [resolving, setResolving] = useState<Finding | null>(null);
  const [voiding, setVoiding] = useState<Finding | null>(null);
  const [removing, setRemoving] = useState<Finding | null>(null);

  const refresh = () => invalidate.forEach((k) => void qc.invalidateQueries({ queryKey: k }));
  const allowedTypes = types.filter((ft) => {
    if (scope === "region" || scope === "mouth") return ft.applies_to === "area";
    if (scope === "surfaces") return ft.applies_to === "surface" || ft.applies_to === "either";
    return ft.applies_to === "tooth" || ft.applies_to === "either";
  });
  const add = useMutation({
    mutationFn: () =>
      api.post(`/dental/encounters/${encounterId}/findings/`, {
        finding_type_id: typeId,
        scope,
        tooth: isMouth ? null : tooth,
        surfaces: scope === "surfaces" ? orderSurfaces(surfaces.join("")) : "",
        region: scope === "region" ? region : "",
        note,
        diagnosis_id: diagnosisId || null,
      }),
    onSuccess: () => {
      setNote("");
      setSurfaces([]);
      refresh();
      toast(t("dental.finding_saved", "Finding recorded"));
    },
  });
  const remove = useMutation({
    mutationFn: (f: Finding) => api.delete(`/dental/findings/${f.id}/`),
    onSuccess: () => {
      setRemoving(null);
      refresh();
    },
  });
  const resolve = useMutation({
    mutationFn: (v: { f: Finding; note: string }) =>
      api.post(`/dental/findings/${v.f.id}/resolve/`, { encounter_id: encounterId, note: v.note }),
    onSuccess: () => {
      setResolving(null);
      refresh();
    },
  });
  const voidIt = useMutation({
    mutationFn: (v: { f: Finding; reason: string }) =>
      api.post(`/dental/findings/${v.f.id}/void/`, { reason: v.reason }),
    onSuccess: () => {
      setVoiding(null);
      refresh();
    },
  });

  const past = history.filter((f) => !current.some((c) => c.id === f.id));
  return (
    <div className="stack-sm tooth-panel">
      <h3>
        {isMouth ? t("dental.mouth_regions", "Whole mouth and regions") : `${t("dental.tooth", "Tooth")} ${tooth}`}
      </h3>
      {current.length === 0 ? (
        <p className="muted small">{t("dental.no_current", "No current findings.")}</p>
      ) : (
        current.map((f) => (
          <div key={f.id} className="row-between">
            <FindingLine f={f} />
            <div className="row">
              {editable && f.encounter === encounterId && (
                <button className="btn btn-sm btn-ghost" onClick={() => setRemoving(f)}>
                  {t("common.remove", "Remove")}
                </button>
              )}
              {editable && f.encounter !== encounterId && (
                <button className="btn btn-sm" onClick={() => setResolving(f)}>
                  {t("dental.resolve", "No longer present…")}
                </button>
              )}
              {canAmend && f.encounter_signed_at && (
                <button className="btn btn-sm btn-ghost" onClick={() => setVoiding(f)}>
                  {t("dental.void", "Entered in error…")}
                </button>
              )}
            </div>
          </div>
        ))
      )}
      {editable && (
        <form
          className="stack-sm fieldset"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <ErrorBanner error={add.error} />
          <Segmented
            label={t("dental.where", "Where")}
            value={scope}
            onChange={(s) => {
              setScope(s);
              setTypeId("");
            }}
            options={
              isMouth
                ? [
                    { key: "mouth", label: t("dental.scope_mouth", "Whole mouth") },
                    { key: "region", label: t("dental.scope_region", "Region") },
                  ]
                : [
                    { key: "tooth", label: t("dental.scope_tooth", "Whole tooth") },
                    { key: "surfaces", label: t("dental.scope_surfaces", "Surfaces") },
                  ]
            }
          />
          {scope === "surfaces" && typeof tooth === "number" && (
            <div className="row" role="group" aria-label={t("dental.surfaces", "Surfaces")}>
              {allowedSurfaces(tooth).map((s) => (
                <button
                  key={s}
                  type="button"
                  className="btn btn-sm surface-toggle"
                  aria-pressed={surfaces.includes(s)}
                  title={SURFACE_NAMES[s]}
                  onClick={() => setSurfaces((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]))}
                >
                  {s} <span className="sr-only">{SURFACE_NAMES[s]}</span>
                </button>
              ))}
            </div>
          )}
          {scope === "region" && (
            <Field label={t("dental.region", "Region")} id="f-region">
              <select id="f-region" value={region} onChange={(e) => setRegion(e.target.value)}>
                {Object.entries(REGION_NAMES).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label={t("dental.finding", "Finding")} id="f-finding_type_id" error={add.error}>
            <select id="f-finding_type_id" value={typeId} onChange={(e) => setTypeId(e.target.value)} required>
              <option value="">—</option>
              {(["condition", "existing", "state"] as const).map((kind) => (
                <optgroup key={kind} label={KIND_LABEL[kind]}>
                  {allowedTypes
                    .filter((ft) => ft.kind === kind)
                    .map((ft) => (
                      <option key={ft.id} value={ft.id}>
                        {ft.symbol} — {ft.name}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </Field>
          {diagnoses.length > 0 && (
            <Field label={t("dental.link_diagnosis", "Diagnosis (optional)")} id="f-diagnosis_id">
              <select id="f-diagnosis_id" value={diagnosisId} onChange={(e) => setDiagnosisId(e.target.value)}>
                <option value="">—</option>
                {diagnoses.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.code} {d.term_text} ({d.location.label})
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label={t("dental.note", "Note (optional)")} id="f-note">
            <input id="f-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={255} />
          </Field>
          <div className="form-actions">
            <button
              className="btn btn-primary"
              disabled={add.isPending || !typeId || (scope === "surfaces" && surfaces.length === 0)}
            >
              {t("dental.record_finding", "Record finding")}
            </button>
          </div>
        </form>
      )}
      {past.length > 0 && (
        <details>
          <summary>{t("dental.history", "History ({{n}})", { n: past.length })}</summary>
          {past.map((f) => (
            <FindingLine key={f.id} f={f} />
          ))}
        </details>
      )}
      <ReasonDialog
        open={!!resolving}
        title={t("dental.resolve_title", "No longer present")}
        label={t("dental.resolve_label", "Why it no longer applies (e.g. restored, extracted)")}
        confirmLabel={t("common.save", "Save")}
        onClose={() => setResolving(null)}
        onConfirm={(reason) => resolving && resolve.mutate({ f: resolving, note: reason })}
        busy={resolve.isPending}
        error={resolve.error}
      />
      <ReasonDialog
        open={!!voiding}
        title={t("dental.void_title", "Mark as entered in error")}
        label={t("dental.void_label", "Reason")}
        confirmLabel={t("dental.void_confirm", "Mark as entered in error")}
        onClose={() => setVoiding(null)}
        onConfirm={(reason) => voiding && voidIt.mutate({ f: voiding, reason })}
        busy={voidIt.isPending}
        error={voidIt.error}
        danger
      />
      <ConfirmDialog
        open={!!removing}
        title={t("dental.remove_finding", "Remove this finding?")}
        body={t(
          "dental.remove_finding_body",
          "Use this only to correct a mistake made in this examination. The removal is saved in the record history with your name.",
        )}
        confirmLabel={t("common.remove", "Remove")}
        onClose={() => setRemoving(null)}
        onConfirm={() => removing && remove.mutate(removing)}
        danger
      />
    </div>
  );
}
