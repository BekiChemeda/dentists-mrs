/** Vital signs and triage form. */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { Paginated, Patient, Visit, Vitals, VitalsReading } from "../api/types";
import { GENERAL_APPEARANCE, useTriageDestinations, useTriageLabel } from "../labels";
import { Banner, ErrorBanner, Field, fieldErrors } from "../ui";
import { sexAge, timeOf } from "./common";

const VITAL_INPUTS: { key: string; label: string; unit: string; step?: string; min: number; max: number }[] = [
  { key: "systolic", label: "Systolic BP", unit: "mmHg", min: 40, max: 300 },
  { key: "diastolic", label: "Diastolic BP", unit: "mmHg", min: 20, max: 200 },
  { key: "temperature_c", label: "Temperature", unit: "°C", step: "0.1", min: 25, max: 45 },
  { key: "heart_rate", label: "Heart rate", unit: "bpm", min: 20, max: 300 },
  { key: "respiratory_rate", label: "Respiratory rate", unit: "/min", min: 2, max: 120 },
  { key: "spo2", label: "Oxygen saturation", unit: "%", min: 30, max: 100 },
  { key: "weight_kg", label: "Weight", unit: "kg", step: "0.1", min: 0.3, max: 400 },
  { key: "height_cm", label: "Height", unit: "cm", step: "0.1", min: 20, max: 250 },
  { key: "pain_score", label: "Pain score", unit: "0–10", min: 0, max: 10 },
];

const CONSCIOUSNESS = [
  { key: "alert", label: "Alert" },
  { key: "confusion", label: "New confusion" },
  { key: "voice", label: "Responds to voice" },
  { key: "pain", label: "Responds to pain" },
  { key: "unresponsive", label: "Unresponsive" },
];

function measurementBody(v: Record<string, string>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const f of VITAL_INPUTS) if (v[f.key]) body[f.key] = f.step ? v[f.key] : Number(v[f.key]);
  if (v.consciousness) body.consciousness = v.consciousness;
  if (v.on_oxygen) body.on_oxygen = v.on_oxygen === "yes";
  return body;
}

/** Shows how the entered values read against the reference for the patient's age, while typing. */
function useVitalsPreview(visitId: string, v: Record<string, string>) {
  const [reading, setReading] = useState<VitalsReading | null>(null);
  const key = JSON.stringify(measurementBody(v));
  useEffect(() => {
    if (key === "{}") {
      setReading(null);
      return;
    }
    const id = setTimeout(() => {
      api
        .post<VitalsReading>(`/visits/${visitId}/vitals/preview/`, JSON.parse(key))
        .then(setReading)
        .catch(() => setReading(null));
    }, 350);
    return () => clearTimeout(id);
  }, [key, visitId]);
  return reading;
}

export function VitalsForm({ visit, onDone }: { visit: Visit; onDone: (v: Vitals) => void }) {
  const { t } = useTranslation();
  const triageLabel = useTriageLabel();
  const destinations = useTriageDestinations();
  const patient = useGet<Patient>(["patient", visit.patient.id], `/patients/${visit.patient.id}/`);
  const previous = useGet<Paginated<Vitals>>(["vitals", "visit", visit.id], `/visits/${visit.id}/vitals/`);
  const [v, setV] = useState<Record<string, string>>({});
  const [allergiesOk, setAllergiesOk] = useState(false);
  const [medsTouched, setMedsTouched] = useState(false);
  const [priority, setPriority] = useState(visit.priority);
  const reading = useVitalsPreview(visit.id, v);
  const meds = medsTouched
    ? (v.current_medications ?? "")
    : (v.current_medications ?? patient.data?.current_medications ?? "");
  const save = useAction(
    () =>
      api.post<Vitals>(`/visits/${visit.id}/vitals/`, {
        ...measurementBody(v),
        priority,
        notes: v.notes ?? "",
        chief_complaint: v.chief_complaint ?? "",
        complaint_duration: v.complaint_duration ?? "",
        general_appearance: v.general_appearance ?? "",
        triage_to: v.triage_to ?? "",
        symptoms: v.symptoms ?? "",
        current_medications: meds,
        allergies_confirmed: allergiesOk || null,
      }),
    [["visits"], ["vitals"]],
    onDone,
    t("triage.saved_toast", "Triage saved; patient sent to {{to}}", { to: triageLabel(v.triage_to ?? "") }),
  );
  const w = Number(v.weight_kg),
    h = Number(v.height_cm) / 100;
  const bmi = w && h ? (w / (h * h)).toFixed(1) : null;
  const set = (k: string) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  const allergies = patient.data?.allergies?.filter((a) => a.is_active) ?? [];
  const last = previous.data?.results[0];
  const suggestEmergency = reading?.worst === "critical" && priority !== "emergency";

  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined);
      }}
    >
      <p>
        <strong>{visit.patient.full_name}</strong> <span className="muted">{sexAge(visit.patient, t)}</span>
      </p>
      {save.error && Object.keys((save.error as { fields?: object }).fields ?? {}).length === 0 && (
        <ErrorBanner error={save.error} />
      )}
      {last && (
        <p className="small muted">
          {t("triage.previous", "Previous measurement today at {{time}}: kept in the chart; this adds a new one.", {
            time: timeOf(last.recorded_at),
          })}
        </p>
      )}

      <fieldset className="fieldset">
        <legend>{t("triage.assessment", "Assessment")}</legend>
        <div className="form-grid">
          <div className="complaint-row">
            <Field label={t("triage.complaint", "Main complaint")} id="v-cc">
              <input id="v-cc" value={v.chief_complaint ?? ""} onChange={set("chief_complaint")} autoFocus />
            </Field>
            <Field
              label={t("triage.duration", "Duration")}
              id="v-dur"
              error={fieldErrors(save.error, "complaint_duration")}
            >
              <input
                id="v-dur"
                value={v.complaint_duration ?? ""}
                onChange={set("complaint_duration")}
                maxLength={60}
                placeholder={t("consult.duration_ph", "e.g. 3 days")}
              />
            </Field>
          </div>
          <Field label={t("triage.symptoms", "Relevant symptoms")} id="v-sym">
            <input id="v-sym" value={v.symptoms ?? ""} onChange={set("symptoms")} />
          </Field>
          <Field
            label={t("triage.meds", "Current medications")}
            id="v-meds"
            hint={
              patient.data?.current_medications
                ? t("triage.meds_hint", "From the patient record; correct if changed.")
                : undefined
            }
          >
            <input
              id="v-meds"
              value={meds}
              onChange={(e) => {
                setMedsTouched(true);
                setV({ ...v, current_medications: e.target.value });
              }}
            />
          </Field>
          <Field label={t("triage.general_appearance", "General appearance")} id="v-ga">
            <select id="v-ga" value={v.general_appearance ?? ""} onChange={set("general_appearance")}>
              <option value="">{t("common.not_recorded", "Not recorded")}</option>
              {GENERAL_APPEARANCE.map((g) => (
                <option key={g.key} value={g.key}>
                  {t(`ga.${g.key}`, g.label)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <label className="check" style={{ marginTop: 8 }}>
          <input type="checkbox" checked={allergiesOk} onChange={(e) => setAllergiesOk(e.target.checked)} />
          <span>
            {allergies.length
              ? t("triage.allergy_confirm", "Allergies checked with the patient: {{list}}", {
                  list: allergies.map((a) => a.substance).join(", "),
                })
              : t("triage.allergy_none", "Asked about allergies: none known")}
          </span>
        </label>
      </fieldset>

      <fieldset className="fieldset">
        <legend>{t("triage.measurements", "Measurements")}</legend>
        <div className="form-grid-3">
          {VITAL_INPUTS.map((f) => {
            const flag = reading?.flags[f.key];
            return (
              <Field
                key={f.key}
                label={`${t(`vitals.${f.key}`, f.label)} (${f.unit})`}
                id={`v-${f.key}`}
                error={fieldErrors(save.error, f.key)}
                className={flag ? `vital-${flag.level}` : undefined}
                hint={flag?.text}
              >
                <input
                  id={`v-${f.key}`}
                  type="number"
                  inputMode="decimal"
                  step={f.step ?? "1"}
                  min={f.min}
                  max={f.max}
                  value={v[f.key] ?? ""}
                  onChange={set(f.key)}
                  aria-describedby={flag ? `v-${f.key}-flag` : undefined}
                />
              </Field>
            );
          })}
          <Field
            label={t("vitals.consciousness", "Level of consciousness")}
            id="v-con"
            className={reading?.flags.consciousness ? "vital-critical" : undefined}
          >
            <select id="v-con" value={v.consciousness ?? ""} onChange={set("consciousness")}>
              <option value="">{t("common.not_recorded", "Not recorded")}</option>
              {CONSCIOUSNESS.map((c) => (
                <option key={c.key} value={c.key}>
                  {t(`vitals.acvpu.${c.key}`, c.label)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("vitals.on_oxygen", "Receiving oxygen")} id="v-o2">
            <select id="v-o2" value={v.on_oxygen ?? ""} onChange={set("on_oxygen")}>
              <option value="">{t("common.not_recorded", "Not recorded")}</option>
              <option value="no">{t("vitals.room_air", "No, room air")}</option>
              <option value="yes">{t("common.yes", "Yes")}</option>
            </select>
          </Field>
        </div>
        {(bmi || reading) && (
          <div className="row small" style={{ marginTop: 10, gap: 12 }}>
            {bmi && <span className="badge badge-muted">BMI {bmi}</span>}
            {reading?.news2 && (
              <span
                className={`badge ${reading.news2.risk === "high" ? "badge-danger" : reading.news2.total > 0 ? "badge-wait" : "badge-ok"}`}
              >
                NEWS2 {reading.news2.total}
                {reading.news2.complete
                  ? `, ${t(`triage.risk.${reading.news2.risk}`, `${reading.news2.risk} risk`)}`
                  : ` (${t("triage.incomplete", "incomplete")})`}
              </span>
            )}
            {reading && (
              <span className="subtle">
                {t("triage.reference", "Reference")}: {reading.reference}
              </span>
            )}
          </div>
        )}
      </fieldset>

      {suggestEmergency && (
        <Banner tone="error">
          {t(
            "triage.suggest_emergency",
            "Critical readings. Consider setting the priority to emergency; the doctor is alerted when you save.",
          )}
        </Banner>
      )}
      <div className="form-grid">
        <Field label={t("queue.priority", "Priority")} id="v-pri">
          <select id="v-pri" value={priority} onChange={(e) => setPriority(e.target.value as Visit["priority"])}>
            <option value="routine">{t("state.priority.routine", "Routine")}</option>
            <option value="urgent">{t("state.priority.urgent", "Urgent")}</option>
            <option value="emergency">{t("state.priority.emergency", "Emergency")}</option>
          </select>
        </Field>
        <Field label={t("vitals.notes", "Triage notes")} id="v-notes">
          <input id="v-notes" value={v.notes ?? ""} onChange={set("notes")} maxLength={255} />
        </Field>
        <Field label={t("triage.triage_to", "Triage to")} id="v-to" error={fieldErrors(save.error, "triage_to")}>
          <select id="v-to" value={v.triage_to ?? ""} onChange={set("triage_to")} required>
            <option value="">{t("triage.choose_to", "Choose where the patient goes")}</option>
            {destinations.map((d) => (
              <option key={d.code} value={d.code}>
                {d.name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={save.isPending || !v.triage_to}>
          {t("triage.save", "Save and send")}
        </button>
      </div>
    </form>
  );
}
