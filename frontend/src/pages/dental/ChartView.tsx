/** Chart with tooth panel, legend, "as of" examination and print. Editable only inside an open examination. */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Printer } from "lucide-react";
import { useGet } from "../../api/hooks";
import { useAuth } from "../../auth/AuthContext";
import { ErrorBanner, Field, Loading, Panel, printElement } from "../../ui";
import { formatDateTime } from "../../lib/format";
import type { Dentition } from "../../lib/teeth";
import { ClinicHeader } from "../common";
import { ChartLegend, DentitionSwitch, Odontogram, ToothPanel } from "./Odontogram";
import { useDentalCatalog } from "./common";
import type { DentalDiagnosis, EncounterBrief, Finding } from "./types";

interface ChartResponse {
  as_of: string;
  findings: Finding[];
  teeth_with_history: number[];
  has_primary: boolean;
}

export function ChartView({
  patientId,
  patientName,
  encounterId,
  editable,
  diagnoses = [],
  encounters = [],
  defaultDentition,
}: {
  patientId: string;
  patientName: string;
  /** The examination being recorded (editable) or viewed. */
  encounterId?: string;
  editable: boolean;
  diagnoses?: DentalDiagnosis[];
  /** Earlier examinations, offered for "chart as of". */
  encounters?: EncounterBrief[];
  defaultDentition?: Dentition;
}) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const catalog = useDentalCatalog();
  const [asOf, setAsOf] = useState<string>(editable ? "" : "");
  const query = asOf ? `?encounter=${asOf}` : "";
  const chart = useGet<ChartResponse>(
    ["dental", "chart", patientId, asOf],
    `/dental/patients/${patientId}/chart/${query}`,
  );
  const [tooth, setTooth] = useState<number | "mouth" | null>(null);
  const history = useGet<Finding[]>(
    ["dental", "chart-history", patientId, String(tooth)],
    typeof tooth === "number" ? `/dental/patients/${patientId}/chart/history/?tooth=${tooth}` : null,
  );
  const [dentition, setDentition] = useState<Dentition | null>(null);
  const shownDentition: Dentition = dentition ?? defaultDentition ?? (chart.data?.has_primary ? "mixed" : "permanent");
  const findings = chart.data?.findings ?? [];
  const current =
    tooth === "mouth"
      ? findings.filter((f) => f.location.tooth == null)
      : findings.filter((f) => f.location.tooth === tooth);
  const readOnly = !!asOf;
  const printId = `chart-print-${patientId}`;
  return (
    <Panel
      title={t("dental.chart", "Dental chart")}
      actions={
        <>
          <DentitionSwitch value={shownDentition} onChange={setDentition} />
          {encounters.length > 0 && (
            <select
              aria-label={t("dental.as_of", "Chart as of")}
              value={asOf}
              onChange={(e) => {
                setAsOf(e.target.value);
                setTooth(null);
              }}
            >
              <option value="">{t("dental.as_of_now", "Now")}</option>
              {encounters
                .filter((e) => e.status === "signed")
                .map((e) => (
                  <option key={e.id} value={e.id}>
                    {t("dental.as_of_exam", "As at examination of {{when}}", { when: formatDateTime(e.signed_at) })}
                  </option>
                ))}
            </select>
          )}
          <button className="btn btn-sm" onClick={() => printElement(printId, t("dental.chart", "Dental chart"))}>
            <Printer size={15} aria-hidden /> {t("common.print", "Print")}
          </button>
        </>
      }
    >
      <ErrorBanner error={chart.error} />
      {chart.isLoading || !catalog.data ? (
        <Loading />
      ) : (
        <div className="chart-layout">
          <div id={printId} className="doc-chart">
            <div className="print-only">
              <ClinicHeader title={t("dental.chart", "Dental chart")} />
              <p>
                <strong>{patientName}</strong> · {t("dental.as_at", "As at")} {formatDateTime(chart.data?.as_of)}
              </p>
            </div>
            {readOnly && (
              <p className="small muted">
                {t("dental.as_of_note", "Showing the chart as it was at that examination (read only).")}
              </p>
            )}
            <Odontogram
              findings={findings}
              dentition={shownDentition}
              selected={typeof tooth === "number" ? tooth : null}
              onSelect={setTooth}
            />
            <div className="row">
              <button
                type="button"
                className="btn btn-sm"
                aria-pressed={tooth === "mouth"}
                onClick={() => setTooth("mouth")}
              >
                {t("dental.mouth_regions", "Whole mouth and regions")} (
                {findings.filter((f) => f.location.tooth == null).length})
              </button>
            </div>
            <ChartLegend findings={findings} types={catalog.data.finding_types} />
            <ChartCompare patientId={patientId} encounters={encounters} />
          </div>
          <div className="side-sticky">
            {tooth === null ? (
              <p className="muted">
                {t("dental.pick_tooth", "Choose a tooth to see its findings and history")}
                {editable && !readOnly ? t("dental.pick_tooth_record", ", or to record a finding.") : "."}
              </p>
            ) : (
              <ToothPanel
                key={`${tooth}-${asOf}`}
                tooth={tooth}
                current={current}
                history={tooth === "mouth" ? current : (history.data ?? [])}
                types={catalog.data.finding_types}
                diagnoses={diagnoses}
                encounterId={encounterId}
                editable={editable && !readOnly && can("dental.chart.record")}
                canAmend={!readOnly && can("dental.amend")}
                invalidate={[
                  ["dental", "chart", patientId],
                  ["dental", "chart-history", patientId],
                  ["dental", "encounter"],
                ]}
              />
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}

/** What changed on the chart between two examinations: added, no longer present, unchanged. */
function ChartCompare({ patientId, encounters }: { patientId: string; encounters: EncounterBrief[] }) {
  const { t } = useTranslation();
  // Newest first; a draft examination counts as "now".
  const choices = [...encounters].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const [from, setFrom] = useState(choices[1]?.id ?? "");
  const [to, setTo] = useState(choices[0]?.id ?? "");
  const [open, setOpen] = useState(false);
  const diff = useGet<{ added: Finding[]; no_longer_present: Finding[]; unchanged: Finding[] }>(
    ["dental", "chart-compare", patientId, from, to],
    open && from && to && from !== to ? `/dental/patients/${patientId}/chart/compare/?from=${from}&to=${to}` : null,
  );
  if (choices.length < 2) return null;
  const label = (e: EncounterBrief) =>
    `${formatDateTime(e.signed_at ?? e.created_at)} · ${e.dentist.full_name}${
      e.status === "draft" ? ` (${t("dental.in_progress_exam", "this examination, not signed")})` : ""
    }`;
  const list = (rows: Finding[] | undefined) =>
    rows && rows.length ? (
      <ul className="plain-list">
        {rows.map((f) => (
          <li key={f.id}>
            <span className={`sym sym-${f.finding_type.kind}`}>{f.finding_type.symbol}</span> {f.finding_type.name}{" "}
            <span className="mono">{f.location.label}</span>
          </li>
        ))}
      </ul>
    ) : (
      <p className="small muted">{t("dental.no_findings_recorded", "No findings recorded.")}</p>
    );
  return (
    <details className="no-print" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>{t("dental.compare_charts", "Compare with an earlier examination")}</summary>
      <div className="stack-sm" style={{ marginTop: 10 }}>
        <div className="form-grid">
          <Field label={t("dental.compare_from", "Earlier")} id="cmp-from">
            <select id="cmp-from" value={from} onChange={(e) => setFrom(e.target.value)}>
              {choices.map((e) => (
                <option key={e.id} value={e.id}>
                  {label(e)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("dental.compare_to", "Later")} id="cmp-to">
            <select id="cmp-to" value={to} onChange={(e) => setTo(e.target.value)}>
              {choices.map((e) => (
                <option key={e.id} value={e.id}>
                  {label(e)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {from === to ? (
          <p className="small muted">{t("dental.compare_same", "Choose two different examinations.")}</p>
        ) : diff.isLoading ? (
          <Loading />
        ) : (
          <div className="form-grid">
            <div>
              <strong>{t("dental.added", "Added")}</strong>
              {list(diff.data?.added)}
            </div>
            <div>
              <strong>{t("dental.no_longer", "No longer present")}</strong>
              {list(diff.data?.no_longer_present)}
            </div>
          </div>
        )}
        <ErrorBanner error={diff.error} />
      </div>
    </details>
  );
}
