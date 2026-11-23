import { useTranslation } from "react-i18next";
import { Printer } from "lucide-react";
import type { Encounter, LabOrder, Patient } from "../api/types";
import { formatDateTime } from "../lib/format";
import { printElement } from "../ui";
import { ClinicHeader, DocFooter, Ec, logoSrc, sexAge, useClinic } from "./common";

/**
 * Patient card: what the patient keeps and brings to every visit, so reception finds the record at once.
 * Wallet size when printed (85 x 54 mm); several fit on one A4 sheet if needed.
 */
export function PatientCard({ patient: p }: { patient: Patient }) {
  const { t } = useTranslation();
  const clinic = useClinic();
  return (
    <div className="stack-sm">
      <div id="patient-card-doc">
        <article className="patient-card">
          <header className="patient-card-head">
            {logoSrc(clinic) && <img src={logoSrc(clinic) ?? ""} alt="" className="patient-card-logo" />}
            <div>
              <strong>{clinic?.facility_name ?? ""}</strong>
              {clinic?.phone && <div className="small">{clinic.phone}</div>}
            </div>
          </header>
          <img className="patient-card-qr" src={`/api/v1/patients/${p.id}/card-qr/`} alt={`QR code, MRN ${p.mrn}`} />
          <div className="patient-card-mrn">
            <span className="small">MRN</span> <b className="mono">{p.mrn}</b>
          </div>
          <div className="patient-card-name">{p.full_name}</div>
          <div className="small">
            {sexAge(p, t)}, {t("patients.born", "Born")} {p.birth_date}
          </div>
          {p.blood_group && (
            <div className="small">
              {t("patients.blood", "Blood")} {p.blood_group}
            </div>
          )}
          <DocFooter kind="note_patient_card" />
        </article>
      </div>
      <p className="small muted">
        {t("card.help", "Prints at bank-card size. The card shows no diagnoses or other clinical details.")}
      </p>
      <div className="form-actions">
        <button className="btn btn-primary" onClick={() => printElement("patient-card-doc", `MRN ${p.mrn}`)}>
          <Printer size={16} aria-hidden /> {t("common.print", "Print")}
        </button>
      </div>
    </div>
  );
}

/**
 * Consultation summary for the patient to take home or to another health worker: what was found, the
 * diagnosis, the treatment and the plan. Only from a signed note, and only verified laboratory results.
 */
export function ConsultationSummary({ encounter: e, labs }: { encounter: Encounter; labs: LabOrder[] }) {
  const { t } = useTranslation();
  const results = labs.flatMap((o) => o.items).filter((i) => i.status === "verified");
  const doctor = e.doctor_details;
  const section = (title: string, text: string | undefined | null) =>
    text?.trim() ? (
      <>
        <h3>{title}</h3>
        <p className="prewrap">{text}</p>
      </>
    ) : null;
  return (
    <div className="stack-sm">
      <article className="doc" id="consultation-summary-doc">
        <ClinicHeader title={t("summary.title", "Consultation summary")} />
        <dl className="facts">
          <dt>{t("common.date", "Date")}</dt>
          <dd>
            {formatDateTime(e.signed_at ?? e.created_at)}
            <Ec value={e.signed_at ?? e.created_at} />
          </dd>
          <dt>{t("patients.patient", "Patient")}</dt>
          <dd>
            {e.patient.full_name}, {sexAge(e.patient, t)}, MRN <span className="mono">{e.patient.mrn}</span>
          </dd>
          {e.allergy_notes && (
            <>
              <dt>{t("patients.allergies", "Allergies")}</dt>
              <dd>{e.allergy_notes}</dd>
            </>
          )}
        </dl>
        {section(
          t("summary.complaint", "Reason for the visit"),
          [e.chief_complaint, e.complaint_duration].filter(Boolean).join(", "),
        )}
        {section(t("summary.findings", "Examination"), e.physical_examination)}
        {e.diagnoses.length > 0 && (
          <>
            <h3>{t("summary.diagnosis", "Diagnosis")}</h3>
            <ul>
              {e.diagnoses.map((d) => (
                <li key={d.id}>
                  {d.icd ? `${d.icd.title} (${d.icd.code})` : d.description}
                  {d.certainty === "provisional" && (
                    <span className="small"> — {t("summary.provisional", "provisional")}</span>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
        {results.length > 0 && (
          <>
            <h3>{t("summary.lab", "Laboratory results")}</h3>
            <table className="data">
              <tbody>
                {results.map((i) => (
                  <tr key={i.id}>
                    <td>{i.test.name}</td>
                    <td>
                      <strong>{i.display_result}</strong> {i.unit}
                    </td>
                    <td className="small">
                      {i.ref_text || (i.ref_low && i.ref_high ? `${Number(i.ref_low)}–${Number(i.ref_high)}` : "")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        {e.prescriptions.filter((rx) => rx.status !== "cancelled").length > 0 && (
          <>
            <h3>{t("summary.medicines", "Medicines")}</h3>
            <ul>
              {e.prescriptions
                .filter((rx) => rx.status !== "cancelled")
                .flatMap((rx) => rx.items)
                .map((i) => (
                  <li key={i.id}>
                    <strong>{i.drug_name}</strong>: {i.dose}, {i.route}, {i.frequency}
                    {i.duration_days ? `, ${i.duration_days} ${t("rx.days", "days")}` : ""}
                    {i.instructions && <span className="small"> ({i.instructions})</span>}
                  </li>
                ))}
            </ul>
          </>
        )}
        {section(t("summary.plan", "Plan"), e.plan)}
        {section(t("summary.advice", "Advice"), e.non_drug_treatment)}
        {(e.follow_up_instructions?.trim() || e.follow_up_date) && (
          <>
            <h3>{t("summary.follow_up", "Follow-up")}</h3>
            <p className="prewrap">
              {[
                e.follow_up_date && t("summary.come_back", "Come back on {{date}}.", { date: e.follow_up_date }),
                e.follow_up_instructions,
              ]
                .filter(Boolean)
                .join(" ")}
            </p>
          </>
        )}
        <div className="doc-sign">
          <div>
            {doctor?.full_name ?? e.doctor.full_name}
            {doctor?.job_title && `, ${doctor.job_title}`}
          </div>
          {doctor?.registration_number && (
            <div className="small">
              {t("consult.reg_no", "Registration no.")} {doctor.registration_number}
            </div>
          )}
          <div className="doc-sign-line">{t("consult.signature_stamp", "Signature and stamp")}</div>
        </div>
        <DocFooter kind="note_consultation" />
      </article>
      <div className="form-actions">
        <button
          className="btn btn-primary"
          onClick={() => printElement("consultation-summary-doc", t("summary.title", "Consultation summary"))}
        >
          <Printer size={16} aria-hidden /> {t("common.print", "Print")}
        </button>
      </div>
    </div>
  );
}
