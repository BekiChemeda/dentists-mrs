/** Registration and edit form for a patient record, with the duplicate check. */
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ApiError, api } from "../api/client";
import type { Patient, PatientBrief } from "../api/types";
import { Banner, ErrorBanner, Field, fieldErrors } from "../ui";
import { EcDateInput, useClinic } from "./common";

type FormState = Record<string, string>;
const EMPTY: FormState = {
  first_name: "",
  middle_name: "",
  last_name: "",
  sex: "",
  birth_date: "",
  age_years: "",
  phone: "",
  alt_phone: "",
  region: "",
  city: "",
  subcity_woreda: "",
  kebele: "",
  house_number: "",
  national_id: "",
  blood_group: "",
  known_conditions: "",
  past_history: "",
  current_medications: "",
  contact_name: "",
  contact_relationship: "",
  contact_phone: "",
  allergy: "",
};

export function PatientForm({
  patient,
  onSaved,
  onReload,
}: {
  patient?: Patient;
  onSaved: (p: Patient) => void;
  onReload?: () => void;
}) {
  const clinic = useClinic();
  const { t } = useTranslation();
  const [f, setF] = useState<FormState>(() =>
    patient
      ? {
          ...EMPTY,
          ...(Object.fromEntries(Object.entries(patient).filter(([, v]) => typeof v === "string")) as FormState),
        }
      : EMPTY,
  );
  const [useAge, setUseAge] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [dupes, setDupes] = useState<(PatientBrief & { reason?: string })[] | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));

  const submit = async (confirm = false) => {
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = {};
    for (const k of [
      "first_name",
      "middle_name",
      "last_name",
      "sex",
      "phone",
      "alt_phone",
      "region",
      "city",
      "subcity_woreda",
      "kebele",
      "house_number",
      "national_id",
      "blood_group",
      "known_conditions",
      "past_history",
      "current_medications",
    ])
      body[k] = f[k];
    if (useAge && f.age_years) body.age_years = Number(f.age_years);
    else body.birth_date = f.birth_date || null;
    try {
      let saved: Patient;
      if (patient) {
        saved = await api.patch<Patient>(`/patients/${patient.id}/`, body, { ifMatch: patient.row_version });
      } else {
        if (f.contact_name && f.contact_phone) {
          body.emergency_contacts = [
            { name: f.contact_name, relationship: f.contact_relationship, phone: f.contact_phone },
          ];
        }
        if (f.allergy.trim()) {
          body.allergies = f.allergy
            .split(/[,;]/)
            .map((s) => s.trim())
            .filter(Boolean)
            .map((substance) => ({ substance }));
        }
        body.confirm_not_duplicate = confirm;
        saved = await api.post<Patient>("/patients/", body);
      }
      onSaved(saved);
    } catch (err) {
      if (err instanceof ApiError && err.code === "possible_duplicate") {
        setDupes((err.details.candidates as PatientBrief[] | undefined) ?? []);
      } else setError(err);
    } finally {
      setBusy(false);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submit(false);
  };

  if (dupes) {
    return (
      <div className="stack-sm">
        <Banner tone="warn">
          {t(
            "patients.possible_duplicate",
            "This patient may already be registered. Open the existing record if it is the same person.",
          )}
        </Banner>
        <div className="panel">
          {dupes.map((d) => (
            <div
              key={d.id}
              className="row-between"
              style={{ padding: "10px 16px", borderBottom: "1px solid var(--line-soft)" }}
            >
              <div>
                <strong>{d.full_name}</strong>
                <div className="small muted">
                  <span className="mono">{d.mrn}</span>, {d.sex}, born {d.birth_date}
                  {d.phone && `, ${d.phone}`}
                </div>
                {d.reason && (
                  <span className="badge badge-wait" style={{ marginTop: 4 }}>
                    {t(`patients.match.${d.reason}`, d.reason)}
                  </span>
                )}
              </div>
              <Link className="btn btn-sm" to={`/patients/${d.id}`}>
                {t("patients.open_existing", "Open this record")}
              </Link>
            </div>
          ))}
        </div>
        <div className="form-actions">
          <button className="btn" onClick={() => setDupes(null)}>
            {t("patients.back_to_form", "Back to the form")}
          </button>
          <button className="btn btn-primary" disabled={busy} onClick={() => void submit(true)}>
            {t("patients.register_anyway", "It is a different person: register")}
          </button>
        </div>
      </div>
    );
  }

  const fe = (k: string) => fieldErrors(error, k);
  const phoneBad = !!f.phone && /[^\d\s+()-]/.test(f.phone);
  return (
    <form onSubmit={onSubmit} noValidate className="stack">
      {!!error && Object.keys((error as ApiError).fields ?? {}).length === 0 && (
        <ErrorBanner error={error} onReload={onReload} />
      )}
      <fieldset className="fieldset">
        <legend>{t("patients.identity", "Identity")}</legend>
        <div className="form-grid-3">
          <Field label={t("patients.first_name", "Given name")} id="f-first_name" error={fe("first_name")}>
            <input id="f-first_name" value={f.first_name} onChange={set("first_name")} required autoFocus />
          </Field>
          <Field label={t("patients.middle_name", "Father's name")} id="f-middle_name" error={fe("middle_name")}>
            <input id="f-middle_name" value={f.middle_name} onChange={set("middle_name")} />
          </Field>
          <Field label={t("patients.last_name", "Grandfather's name")} id="f-last_name" error={fe("last_name")}>
            <input id="f-last_name" value={f.last_name} onChange={set("last_name")} />
          </Field>
          <Field label={t("patients.sex", "Sex")} id="f-sex" error={fe("sex")}>
            <select id="f-sex" value={f.sex} onChange={set("sex")} required>
              <option value="">{t("common.choose", "Choose…")}</option>
              <option value="female">{t("sex.female", "Female")}</option>
              <option value="male">{t("sex.male", "Male")}</option>
            </select>
          </Field>
          {useAge ? (
            <Field
              label={t("patients.age_years", "Age in years (estimated)")}
              id="f-age_years"
              error={fe("birth_date")}
            >
              <input id="f-age_years" type="number" min={0} max={130} value={f.age_years} onChange={set("age_years")} />
            </Field>
          ) : (
            <>
              <Field
                label={t("patients.birth_date", "Date of birth (Gregorian)")}
                id="f-birth_date"
                error={fe("birth_date")}
              >
                <input id="f-birth_date" type="date" value={f.birth_date} onChange={set("birth_date")} />
              </Field>
              {clinic?.show_ethiopian_calendar && (
                <Field label={t("patients.birth_date_ec", "or in the Ethiopian calendar")} id="f-ec-d">
                  <EcDateInput
                    idPrefix="f-ec"
                    value={f.birth_date}
                    onChange={(iso) => setF((s) => ({ ...s, birth_date: iso }))}
                  />
                </Field>
              )}
            </>
          )}
          <div className="field">
            <span className="label">&nbsp;</span>
            <label className="check">
              <input type="checkbox" checked={useAge} onChange={(e) => setUseAge(e.target.checked)} />
              {t("patients.dob_unknown", "Date of birth unknown: enter age")}
            </label>
          </div>
          <Field
            label={t("patients.phone", "Phone")}
            id="f-phone"
            error={
              fe("phone").length
                ? fe("phone")
                : phoneBad
                  ? [t("patients.phone_digits", "Use digits only, e.g. 0911 234 567 or +251 911 234 567.")]
                  : undefined
            }
            hint="09… or +251…"
          >
            <input id="f-phone" type="tel" inputMode="tel" value={f.phone} onChange={set("phone")} />
          </Field>
          <Field label={t("patients.alt_phone", "Second phone")} id="f-alt_phone" error={fe("alt_phone")}>
            <input id="f-alt_phone" type="tel" value={f.alt_phone} onChange={set("alt_phone")} />
          </Field>
          <Field
            label={t("patients.national_id", "National ID (optional)")}
            id="f-national_id"
            error={fe("national_id")}
          >
            <input id="f-national_id" value={f.national_id} onChange={set("national_id")} />
          </Field>
        </div>
      </fieldset>
      <fieldset className="fieldset">
        <legend>{t("patients.address", "Address")}</legend>
        <div className="form-grid-3">
          <Field label={t("patients.region", "Region")} id="f-region">
            <input id="f-region" value={f.region} onChange={set("region")} />
          </Field>
          <Field label={t("patients.city", "City / town")} id="f-city">
            <input id="f-city" value={f.city} onChange={set("city")} />
          </Field>
          <Field label={t("patients.subcity", "Sub-city / woreda")} id="f-subcity_woreda">
            <input id="f-subcity_woreda" value={f.subcity_woreda} onChange={set("subcity_woreda")} />
          </Field>
          <Field label={t("patients.kebele", "Kebele")} id="f-kebele">
            <input id="f-kebele" value={f.kebele} onChange={set("kebele")} />
          </Field>
          <Field label={t("patients.house", "House number")} id="f-house_number">
            <input id="f-house_number" value={f.house_number} onChange={set("house_number")} />
          </Field>
        </div>
      </fieldset>
      <fieldset className="fieldset">
        <legend>{t("patients.medical", "Medical background")}</legend>
        <div className="form-grid">
          <Field label={t("patients.blood_group", "Blood group, if known")} id="f-blood_group">
            <select id="f-blood_group" value={f.blood_group} onChange={set("blood_group")}>
              <option value="">{t("patients.unknown", "Unknown")}</option>
              {["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"].map((g) => (
                <option key={g}>{g}</option>
              ))}
            </select>
          </Field>
          {!patient && (
            <Field
              label={t("patients.allergies", "Known allergies")}
              id="f-allergy"
              hint={t("patients.allergy_hint", "Separate with commas. Leave empty if none known.")}
            >
              <input id="f-allergy" value={f.allergy} onChange={set("allergy")} />
            </Field>
          )}
          <Field
            label={t("patients.chronic_illness", "Chronic illness")}
            id="f-known_conditions"
            hint={t("patients.conditions_hint", "Long-term conditions, e.g. hypertension, diabetes, HIV on ART.")}
          >
            <textarea id="f-known_conditions" value={f.known_conditions} onChange={set("known_conditions")} rows={2} />
          </Field>
          <Field label={t("patients.past_history2", "Past medical & surgical history")} id="f-past_history">
            <textarea id="f-past_history" value={f.past_history} onChange={set("past_history")} rows={2} />
          </Field>
          <Field
            label={t("patients.current_medications", "Current medications")}
            id="f-current_medications"
            className="span-all"
            hint={t("patients.meds_hint", "Medicines the patient takes regularly, with dose if known.")}
          >
            <textarea
              id="f-current_medications"
              value={f.current_medications}
              onChange={set("current_medications")}
              rows={2}
            />
          </Field>
        </div>
      </fieldset>
      {!patient && (
        <fieldset className="fieldset">
          <legend>{t("patients.emergency_contact", "Emergency contact")}</legend>
          <div className="form-grid-3">
            <Field label={t("patients.contact_name", "Name")} id="f-contact_name">
              <input id="f-contact_name" value={f.contact_name} onChange={set("contact_name")} />
            </Field>
            <Field label={t("patients.relationship", "Relationship")} id="f-contact_relationship">
              <input
                id="f-contact_relationship"
                value={f.contact_relationship}
                onChange={set("contact_relationship")}
              />
            </Field>
            <Field label={t("patients.phone", "Phone")} id="f-contact_phone">
              <input id="f-contact_phone" type="tel" value={f.contact_phone} onChange={set("contact_phone")} />
            </Field>
          </div>
        </fieldset>
      )}
      <div className="form-actions">
        {(!f.first_name || !f.sex || phoneBad) && (
          <span className="small muted">
            {t("patients.still_needed", "Still needed: {{fields}}", {
              fields: [
                !f.first_name && t("patients.first_name", "First name"),
                !f.sex && t("patients.sex", "Sex"),
                phoneBad && t("patients.valid_phone", "a phone number with digits only"),
              ]
                .filter(Boolean)
                .join(", "),
            })}
          </span>
        )}
        <button className="btn btn-primary" type="submit" disabled={busy || !f.first_name || !f.sex || phoneBad}>
          {busy
            ? t("common.saving")
            : patient
              ? t("common.save_changes", "Save changes")
              : t("patients.register_btn", "Register patient")}
        </button>
      </div>
    </form>
  );
}
