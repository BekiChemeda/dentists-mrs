/**
 * Six-site periodontal chart (protocol pending dentist review). Blank stays blank: a site with no value is shown
 * empty, never as zero. Values are whole millimetres; the server refuses implausible values instead of changing them.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Printer } from "lucide-react";
import { api } from "../../api/client";
import { useGet } from "../../api/hooks";
import { Banner, ErrorBanner, Loading, Panel, Segmented, printElement, toast } from "../../ui";
import { formatDateTime } from "../../lib/format";
import { LOWER_PERMANENT, UPPER_PERMANENT, canHaveFurcation } from "../../lib/teeth";
import { ClinicHeader } from "../common";
import type { Finding, PerioExam, PerioSite, PerioTooth } from "./types";

const BUCCAL = ["MB", "B", "DB"];
const LINGUAL = ["ML", "L", "DL"];

type Draft = Record<number, PerioTooth>;

function emptyTooth(tooth: number): PerioTooth {
  return {
    tooth,
    missing: false,
    excluded: false,
    exclusion_reason: "",
    implant: false,
    mobility: null,
    furcation: null,
    notes: "",
    sites: {},
  };
}

function toInt(v: string): number | null {
  if (v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : NaN;
}

function SiteCells({
  tooth,
  sites,
  value,
  editable,
  onChange,
}: {
  tooth: PerioTooth;
  sites: string[];
  value: Record<string, PerioSite>;
  editable: boolean;
  onChange: (site: string, patch: Partial<PerioSite>) => void;
}) {
  const off = tooth.missing || tooth.excluded;
  return (
    <>
      {sites.map((site) => {
        const s = value[site];
        const label = `${tooth.tooth} ${site}`;
        if (!editable) {
          return (
            <td key={site} className={`perio-site${s?.bleeding ? " bop" : ""}`}>
              {off ? "" : s?.not_measured ? "NM" : s ? `${s.probing_depth_mm ?? ""}/${s.gingival_margin_mm ?? ""}` : ""}
              {s?.cal_mm != null && <div className="small subtle">CAL {s.cal_mm}</div>}
              {s?.bleeding && <span className="sr-only">bleeding</span>}
              {s?.bleeding && " •"}
            </td>
          );
        }
        return (
          <td key={site} className="perio-site">
            <input
              aria-label={`${label} probing depth (mm)`}
              className="perio-input"
              inputMode="numeric"
              disabled={off || s?.not_measured}
              value={s?.probing_depth_mm ?? ""}
              onChange={(e) => onChange(site, { probing_depth_mm: toInt(e.target.value) })}
            />
            <input
              aria-label={`${label} gingival margin (mm)`}
              className="perio-input"
              inputMode="numeric"
              disabled={off || s?.not_measured}
              value={s?.gingival_margin_mm ?? ""}
              onChange={(e) => onChange(site, { gingival_margin_mm: toInt(e.target.value) })}
            />
            <label className="perio-flag" title="Bleeding on probing">
              <input
                type="checkbox"
                disabled={off || s?.not_measured}
                checked={!!s?.bleeding}
                onChange={(e) => onChange(site, { bleeding: e.target.checked })}
              />
              B
            </label>
            <label className="perio-flag" title="Plaque">
              <input
                type="checkbox"
                disabled={off || s?.not_measured}
                checked={!!s?.plaque}
                onChange={(e) => onChange(site, { plaque: e.target.checked })}
              />
              P
            </label>
          </td>
        );
      })}
    </>
  );
}

/** Chart states that make a tooth absent from the mouth for periodontal charting. */
const ABSENT_CODES = ["missing", "extracted", "unerupted", "impacted"];

export function PerioChart({
  encounterId,
  patientId,
  editable,
}: {
  encounterId: string;
  patientId: string;
  editable: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const exam = useGet<PerioExam | null>(["dental", "perio", encounterId], `/dental/encounters/${encounterId}/perio/`);
  const [draft, setDraft] = useState<Draft>({});
  const [dirty, setDirty] = useState(false);
  const [arch, setArch] = useState<"upper" | "lower">("upper");
  // A new periodontal chart starts from the dental chart: teeth recorded as missing, extracted, unerupted or
  // impacted are pre-marked missing, and implants as implants. The examiner can change any of them before saving.
  const chart = useGet<{ findings: Finding[] }>(
    ["dental", "chart", patientId, ""],
    exam.data === null && editable ? `/dental/patients/${patientId}/chart/` : null,
  );
  const [prefilled, setPrefilled] = useState<number[]>([]);
  useEffect(() => {
    if (!exam.data || dirty) return;
    const d: Draft = {};
    for (const row of exam.data.teeth) d[row.tooth] = row;
    setDraft(d);
  }, [exam.data, dirty]);
  useEffect(() => {
    if (exam.data !== null || dirty || !chart.data) return;
    const d: Draft = {};
    for (const f of chart.data.findings) {
      const tooth = f.location.tooth;
      if (tooth == null || f.location.scope !== "tooth" || Math.floor(tooth / 10) > 4) continue;
      if (ABSENT_CODES.includes(f.finding_type.code)) d[tooth] = { ...emptyTooth(tooth), missing: true };
      else if (f.finding_type.code === "implant") d[tooth] = { ...(d[tooth] ?? emptyTooth(tooth)), implant: true };
    }
    setDraft(d);
    setPrefilled(Object.keys(d).map(Number));
  }, [exam.data, chart.data, dirty]);

  const save = useMutation({
    mutationFn: () => {
      const teeth = Object.values(draft).map((row) => ({
        ...row,
        sites: Object.fromEntries(
          Object.entries(row.sites).map(([k, s]) => [
            k,
            {
              probing_depth_mm: s.probing_depth_mm,
              gingival_margin_mm: s.gingival_margin_mm,
              bleeding: s.bleeding,
              plaque: s.plaque,
              suppuration: s.suppuration,
              not_measured: s.not_measured,
              not_measured_reason: s.not_measured_reason,
            },
          ]),
        ),
      }));
      return api.put<PerioExam>(`/dental/encounters/${encounterId}/perio/`, {
        version: exam.data?.version ?? 0,
        teeth,
      });
    },
    onSuccess: (data) => {
      qc.setQueryData(["dental", "perio", encounterId], data);
      setDirty(false);
      toast(t("dental.perio_saved", "Periodontal chart saved"));
    },
  });

  const update = (tooth: number, patch: Partial<PerioTooth>) => {
    setDirty(true);
    setDraft((d) => ({ ...d, [tooth]: { ...(d[tooth] ?? emptyTooth(tooth)), ...patch } }));
  };
  const updateSite = (tooth: number, site: string, patch: Partial<PerioSite>) => {
    setDirty(true);
    setDraft((d) => {
      const row = d[tooth] ?? emptyTooth(tooth);
      const cur: PerioSite = row.sites[site] ?? {
        probing_depth_mm: null,
        gingival_margin_mm: null,
        bleeding: null,
        plaque: null,
        suppuration: null,
        not_measured: false,
        not_measured_reason: "",
      };
      return { ...d, [tooth]: { ...row, sites: { ...row.sites, [site]: { ...cur, ...patch } } } };
    });
  };
  const teeth = arch === "upper" ? UPPER_PERMANENT : LOWER_PERMANENT;
  const s = exam.data?.summary;
  const printId = `perio-print-${encounterId}`;
  const hasBadNumber = useMemo(
    () =>
      Object.values(draft).some((row) =>
        Object.values(row.sites).some(
          (x) => Number.isNaN(x.probing_depth_mm as number) || Number.isNaN(x.gingival_margin_mm as number),
        ),
      ),
    [draft],
  );

  if (exam.isLoading) return <Loading />;
  return (
    <Panel
      title={t("dental.perio", "Periodontal chart")}
      actions={
        <>
          <Segmented
            label={t("dental.arch", "Arch")}
            value={arch}
            onChange={setArch}
            options={[
              { key: "upper", label: t("dental.upper", "Upper") },
              { key: "lower", label: t("dental.lower", "Lower") },
            ]}
          />
          <button className="btn btn-sm" onClick={() => printElement(printId, t("dental.perio", "Periodontal chart"))}>
            <Printer size={15} aria-hidden /> {t("common.print", "Print")}
          </button>
          {editable && (
            <button
              className="btn btn-sm btn-primary"
              disabled={!dirty || save.isPending || hasBadNumber}
              onClick={() => save.mutate()}
            >
              {t("common.save", "Save")}
            </button>
          )}
        </>
      }
    >
      <ErrorBanner error={exam.error || save.error} />
      <Banner tone="info">
        {t(
          "dental.perio_hint",
          "Enter two numbers per site in whole mm: pocket depth, then gum margin (positive = recession below the cemento-enamel junction). Tick B for bleeding and P for plaque. Leave a site blank if it was not measured.",
        )}
      </Banner>
      {exam.data === null && prefilled.length > 0 && (
        <Banner tone="info">
          {t(
            "dental.perio_prefilled",
            "From the dental chart, marked missing or implant: {{teeth}}. Check before saving.",
            {
              teeth: prefilled.sort((a, b) => a - b).join(", "),
            },
          )}
        </Banner>
      )}
      <div id={printId} className="stack-sm">
        <div className="print-only">
          <ClinicHeader title={t("dental.perio", "Periodontal chart")} />
          {exam.data && (
            <p>
              {formatDateTime(exam.data.created_at)} · {exam.data.examiner.full_name}
            </p>
          )}
        </div>
        <p className="small muted phone-only">
          {t(
            "dental.perio_scroll",
            "Swipe the chart sideways to see all teeth. A tablet or computer is easier for charting.",
          )}
        </p>
        <div className="table-wrap">
          <table className="data perio-table">
            <thead>
              <tr>
                <th>{t("dental.tooth", "Tooth")}</th>
                <th>{t("dental.missing", "Missing")}</th>
                <th>{t("dental.mobility", "Mobility")}</th>
                <th>{t("dental.furcation", "Furcation")}</th>
                {BUCCAL.map((x) => (
                  <th key={x}>{x}</th>
                ))}
                {LINGUAL.map((x) => (
                  <th key={x}>{x}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {teeth.map((n) => {
                const row = draft[n] ?? emptyTooth(n);
                return (
                  <tr key={n} className={row.missing ? "muted" : ""}>
                    <th scope="row">{n}</th>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${n} missing`}
                        disabled={!editable}
                        checked={row.missing}
                        onChange={(e) =>
                          update(n, { missing: e.target.checked, sites: e.target.checked ? {} : row.sites })
                        }
                      />
                    </td>
                    <td>
                      {editable ? (
                        <select
                          aria-label={`${n} mobility`}
                          value={row.mobility ?? ""}
                          disabled={row.missing}
                          onChange={(e) =>
                            update(n, { mobility: e.target.value === "" ? null : Number(e.target.value) })
                          }
                        >
                          <option value="">—</option>
                          {[0, 1, 2, 3].map((v) => (
                            <option key={v} value={v}>
                              {v}
                            </option>
                          ))}
                        </select>
                      ) : (
                        (row.mobility ?? "")
                      )}
                    </td>
                    <td>
                      {canHaveFurcation(n) ? (
                        editable ? (
                          <select
                            aria-label={`${n} furcation`}
                            value={row.furcation ?? ""}
                            disabled={row.missing}
                            onChange={(e) =>
                              update(n, { furcation: e.target.value === "" ? null : Number(e.target.value) })
                            }
                          >
                            <option value="">—</option>
                            {[0, 1, 2, 3].map((v) => (
                              <option key={v} value={v}>
                                {v}
                              </option>
                            ))}
                          </select>
                        ) : (
                          (row.furcation ?? "")
                        )
                      ) : (
                        <span className="subtle">n/a</span>
                      )}
                    </td>
                    <SiteCells
                      tooth={row}
                      sites={BUCCAL}
                      value={row.sites}
                      editable={editable}
                      onChange={(site, p) => updateSite(n, site, p)}
                    />
                    <SiteCells
                      tooth={row}
                      sites={LINGUAL}
                      value={row.sites}
                      editable={editable}
                      onChange={(site, p) => updateSite(n, site, p)}
                    />
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {s && (
          <div className="facts small">
            <span>
              {t("dental.bop", "Bleeding on probing")}:{" "}
              <strong>{s.bleeding.percent == null ? "—" : `${s.bleeding.percent}%`}</strong> ({s.bleeding.positive}/
              {s.bleeding.assessed} {t("dental.sites_assessed", "sites assessed")})
            </span>
            <span>
              {t("dental.plaque", "Plaque")}: <strong>{s.plaque.percent == null ? "—" : `${s.plaque.percent}%`}</strong>{" "}
              ({s.plaque.positive}/{s.plaque.assessed})
            </span>
            <span>
              {t("dental.pd4", "Sites ≥ 4 mm")}: <strong>{s.pd_4_or_more}</strong>
            </span>
            <span>
              {t("dental.pd6", "Sites ≥ 6 mm")}: <strong>{s.pd_6_or_more}</strong>
            </span>
            <span>
              {t("dental.sites_measured", "Sites with values")}: {s.sites_with_values} / {s.sites_possible}
            </span>
            <span className="subtle">{s.formula}</span>
          </div>
        )}
      </div>
    </Panel>
  );
}

export function PerioHistory({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const exams = useGet<PerioExam[]>(["dental", "perio-list", patientId], `/dental/patients/${patientId}/perio/`);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const cmp = useGet<{
    sites: {
      tooth: number;
      site: string;
      pd_before: number | null;
      pd_after: number | null;
      pd_change: number | null;
      cal_change: number | null;
    }[];
    missing_changed: number[];
  }>(["dental", "perio-compare", a, b], a && b && a !== b ? `/dental/perio/compare/?a=${a}&b=${b}` : null);
  if (exams.isLoading) return <Loading />;
  const list = exams.data ?? [];
  return (
    <Panel title={t("dental.perio_history", "Periodontal examinations")}>
      {list.length === 0 ? (
        <p className="muted">{t("dental.perio_none", "No periodontal charts recorded.")}</p>
      ) : (
        <div className="stack-sm">
          <table className="data">
            <thead>
              <tr>
                <th>{t("common.date", "Date")}</th>
                <th>{t("dental.examiner", "Examiner")}</th>
                <th className="num">{t("dental.bop", "Bleeding on probing")}</th>
                <th className="num">{t("dental.pd4", "Sites ≥ 4 mm")}</th>
                <th className="num">{t("dental.pd6", "Sites ≥ 6 mm")}</th>
              </tr>
            </thead>
            <tbody>
              {list.map((e) => (
                <tr key={e.id}>
                  <td>{formatDateTime(e.created_at)}</td>
                  <td>{e.examiner.full_name}</td>
                  <td className="num">{e.summary.bleeding.percent == null ? "—" : `${e.summary.bleeding.percent}%`}</td>
                  <td className="num">{e.summary.pd_4_or_more}</td>
                  <td className="num">{e.summary.pd_6_or_more}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.length > 1 && (
            <div className="row">
              <label>
                {t("dental.compare", "Compare")}{" "}
                <select value={a} onChange={(e) => setA(e.target.value)}>
                  <option value="">—</option>
                  {list.map((e) => (
                    <option key={e.id} value={e.id}>
                      {formatDateTime(e.created_at)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("dental.with", "with")}{" "}
                <select value={b} onChange={(e) => setB(e.target.value)}>
                  <option value="">—</option>
                  {list.map((e) => (
                    <option key={e.id} value={e.id}>
                      {formatDateTime(e.created_at)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
          {cmp.data && (
            <table className="data">
              <thead>
                <tr>
                  <th>{t("dental.site", "Site")}</th>
                  <th className="num">{t("dental.pd_before", "PD before")}</th>
                  <th className="num">{t("dental.pd_after", "PD after")}</th>
                  <th className="num">{t("dental.change", "Change")}</th>
                  <th className="num">{t("dental.cal_change", "CAL change")}</th>
                </tr>
              </thead>
              <tbody>
                {cmp.data.sites.map((r) => (
                  <tr key={`${r.tooth}-${r.site}`}>
                    <td>
                      {r.tooth} {r.site}
                    </td>
                    <td className="num">{r.pd_before ?? ""}</td>
                    <td className="num">{r.pd_after ?? ""}</td>
                    <td className="num">{r.pd_change ?? ""}</td>
                    <td className="num">{r.cal_change ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </Panel>
  );
}
