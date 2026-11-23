import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api, queryString } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import type { ClinicSettings, LabItem, Paginated, Patient, PatientBrief, PersonBrief } from "../api/types";
import { EC_MONTHS, ecMonthLength, formatEc, fromEthiopian, toEthiopian } from "../lib/ethiopian";

/** Search-as-you-type patient selector used by every "choose a patient" flow. */
export function PatientPicker({
  value,
  onChange,
  autoFocus,
}: {
  value: PatientBrief | null;
  onChange: (p: PatientBrief | null) => void;
  autoFocus?: boolean;
}) {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const id = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(id);
  }, [q]);
  const results = useGet<Paginated<Patient>>(
    ["patients", "picker", debounced],
    debounced.length >= 2 ? `/patients/${queryString({ q: debounced, page_size: 6 })}` : null,
  );

  if (value) {
    return (
      <div className="row-between panel" style={{ padding: "10px 14px" }}>
        <PatientLine patient={value} />
        <button type="button" className="btn btn-sm" onClick={() => onChange(null)}>
          {t("common.change", "Change")}
        </button>
      </div>
    );
  }
  return (
    <div className="stack-sm">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        autoFocus={autoFocus}
        placeholder={t("app.search_patients")}
        aria-label={t("app.search_patients")}
        style={{ width: "100%" }}
      />
      {debounced.length >= 2 && (
        <div className="panel">
          {results.isLoading && <div className="loading">{t("common.loading")}</div>}
          {results.data?.results.length === 0 && (
            <div className="loading">
              {t("patients.no_match_register", "No match.")}{" "}
              <Link to="/patients?register=1">{t("patients.register", "Register a new patient")}</Link>
            </div>
          )}
          {results.data?.results.map((p) => (
            <button key={p.id} type="button" className="search-item" onClick={() => onChange(p)}>
              <strong>{p.full_name}</strong>
              <span className="mono subtle">{p.mrn}</span>
              <span className="subtle">
                {sexAge(p, t)}
                {p.phone && `, ${p.phone}`}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function sexAge(p: { sex: string; age: number }, t: (k: string, d: string) => string): string {
  return `${p.sex === "female" ? t("sex.female", "Female") : t("sex.male", "Male")}, ${p.age} ${t("common.years", "years")}`;
}

export function PatientLine({ patient, link }: { patient: PatientBrief; link?: boolean }) {
  const { t } = useTranslation();
  return (
    <div>
      {link ? (
        <Link to={`/patients/${patient.id}`}>
          <strong>{patient.full_name}</strong>
        </Link>
      ) : (
        <strong>{patient.full_name}</strong>
      )}
      <div className="small muted">
        <span className="mono">{patient.mrn}</span>, {sexAge(patient, t)}
      </div>
    </div>
  );
}

export function useDoctors() {
  return useGet<PersonBrief[]>(["doctors"], "/doctors/");
}

export function DoctorSelect({
  value,
  onChange,
  id,
  allowNone,
  noneLabel,
}: {
  value: string;
  onChange: (id: string) => void;
  id: string;
  allowNone?: boolean;
  noneLabel?: string;
}) {
  const doctors = useDoctors();
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      {allowNone && <option value="">{noneLabel ?? "Any doctor"}</option>}
      {!allowNone && !value && <option value="">Choose…</option>}
      {doctors.data?.map((d) => (
        <option key={d.id} value={d.id}>
          Dr. {d.full_name}
        </option>
      ))}
    </select>
  );
}

export function todayIso(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Addis_Ababa" }).format(new Date());
}

export function timeOf(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Africa/Addis_Ababa",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function waitLabel(minutes: number | null): string {
  if (minutes === null) return "";
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

export function useClinic() {
  return useGet<ClinicSettings>(["settings", "clinic"], "/settings/clinic/").data;
}

/** Address of the clinic logo, with its version so browsers fetch a new one after a change. */
export function logoSrc(clinic: ClinicSettings | undefined): string | null {
  return clinic?.has_logo && clinic.logo_version ? `/api/v1/branding/logo/?v=${clinic.logo_version}` : null;
}

/** The Ethiopian calendar date beside a Gregorian one, when the clinic has it switched on. */
export function Ec({ value, paren = true }: { value: string | Date | null | undefined; paren?: boolean }) {
  const clinic = useClinic();
  if (!value || !clinic?.show_ethiopian_calendar) return null;
  const text = formatEc(value);
  return <span className="ec-date">{paren ? ` (${text})` : text}</span>;
}

/** "(Hidar 1 to Hidar 3, 2019 EC)" for a period, when the clinic shows the Ethiopian calendar. */
export function EcRange({ from, to }: { from: string; to: string }) {
  const clinic = useClinic();
  if (!clinic?.show_ethiopian_calendar) return null;
  return <span className="ec-date">{` (${formatEc(from).replace(/ EC$/, "")} to ${formatEc(to)})`}</span>;
}

/** Day, month and year in the Ethiopian calendar; reports the Gregorian ISO date, or "" while incomplete. */
export function EcDateInput({
  value,
  onChange,
  idPrefix,
}: {
  value: string;
  onChange: (iso: string) => void;
  idPrefix: string;
}) {
  const { t } = useTranslation();
  const fromValue = () => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return { day: "", month: "", year: "" };
    const [y, m, d] = value.split("-").map(Number);
    const ec = toEthiopian(y, m, d);
    return { day: String(ec.day), month: String(ec.month), year: String(ec.year) };
  };
  const [ec, setEc] = useState(fromValue);
  useEffect(() => {
    const current = fromEthiopian(Number(ec.year), Number(ec.month), Number(ec.day));
    if (value && value !== current) setEc(fromValue());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  const update = (k: "day" | "month" | "year", v: string) => {
    const next = { ...ec, [k]: v };
    setEc(next);
    const iso = fromEthiopian(Number(next.year), Number(next.month), Number(next.day));
    onChange(iso ?? "");
  };
  const max = ec.year && ec.month ? ecMonthLength(Number(ec.year), Number(ec.month)) : 30;
  return (
    <div className="ec-input">
      <input
        id={`${idPrefix}-d`}
        type="number"
        min={1}
        max={max}
        placeholder={t("ec.day", "Day")}
        value={ec.day}
        onChange={(e) => update("day", e.target.value)}
        aria-label={t("ec.day", "Day")}
      />
      <select
        id={`${idPrefix}-m`}
        value={ec.month}
        onChange={(e) => update("month", e.target.value)}
        aria-label={t("ec.month", "Month")}
      >
        <option value="">{t("ec.month", "Month")}</option>
        {EC_MONTHS.map((m, i) => (
          <option key={m} value={i + 1}>
            {m}
          </option>
        ))}
      </select>
      <input
        id={`${idPrefix}-y`}
        type="number"
        min={1880}
        max={2100}
        placeholder={t("ec.year", "Year")}
        value={ec.year}
        onChange={(e) => update("year", e.target.value)}
        aria-label={t("ec.year", "Year")}
      />
    </div>
  );
}

/** The clinic's own short footer for a kind of document (opening hours, "bring this paper back"...). */
export function DocFooter({
  kind,
}: {
  kind:
    | "note_prescription"
    | "note_referral"
    | "note_certificate"
    | "note_lab_report"
    | "note_consultation"
    | "note_patient_card";
}) {
  const text = useClinic()?.[kind];
  return text ? <p className="doc-foot small">{text}</p> : null;
}

/** Letterhead for printed documents: facility name, address, phone, licence. */
export function ClinicHeader({ title, number }: { title: string; number?: string }) {
  const clinic = useClinic();
  return (
    <header className="doc-head">
      <div className="doc-head-id">
        {logoSrc(clinic) && <img className="doc-logo" src={logoSrc(clinic) ?? ""} alt="" />}
        <div>
          <strong className="doc-facility">{clinic?.facility_name ?? ""}</strong>
          <div className="small muted">{[clinic?.address, clinic?.phone].filter(Boolean).join(", ")}</div>
          {clinic?.license_number && <div className="small muted">Licence {clinic.license_number}</div>}
        </div>
      </div>
      <div style={{ textAlign: "right" }}>
        <strong>{title}</strong>
        {number && <div className="mono small">{number}</div>}
      </div>
    </header>
  );
}

/** Critical result: who was told, and whether a clinician has acknowledged it (with the button to do so). */
export function CriticalNote({ item }: { item: LabItem }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const ack = useAction(
    () => api.post(`/lab/items/${item.id}/acknowledge/`),
    [["lab"]],
    undefined,
    t("lab.ack_toast", "Critical result acknowledged"),
  );
  if (!item.is_critical) return null;
  return (
    <div className="critical-box">
      <strong>{t("lab.critical", "Critical result")}</strong>
      {item.critical_reported_to && (
        <span>. {t("lab.reported_to", "Reported to {{who}}", { who: item.critical_reported_to })}</span>
      )}
      {item.critical_acknowledged_at ? (
        <div className="small">
          {t("lab.acked_by", "Acknowledged by {{who}}", { who: item.critical_acknowledged_by?.full_name ?? "" })}
        </div>
      ) : can("clinical.write") ? (
        <div style={{ marginTop: 6 }}>
          <button
            type="button"
            className="btn btn-sm btn-danger-solid"
            disabled={ack.isPending}
            onClick={() => ack.mutate(undefined)}
          >
            {t("lab.acknowledge", "Acknowledge: I have seen this result")}
          </button>
        </div>
      ) : (
        <div className="small">{t("lab.not_acked", "Not yet acknowledged by a clinician.")}</div>
      )}
    </div>
  );
}
