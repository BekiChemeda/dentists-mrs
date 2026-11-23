# Gap analysis: Clinic MRS against the completion brief

Date: 21 November 2026. Baseline: commit `fa58f21`, 80 backend tests passing.

This traces what the code actually does, not what the screens suggest. Each item names the
file that shows it. "Done" means implemented on the server, enforced, and reachable from the UI.

## How a visit actually flows today

1. `patients/services.register_patient` creates the patient. Duplicate check: same phone, or
   trigram name similarity ≥ 0.55 with birth year ±1.
2. Walk-in: `scheduling/services.register_walk_in` creates a `Visit` (status `waiting_triage`).
   Appointment: `book_appointment` then `check_in` (appointment → `arrived`, creates the visit).
3. `clinical/services.record_vitals` saves one `VitalSigns` row and moves the visit to
   `waiting_doctor`.
4. `start_encounter` moves the visit to `in_consultation` and creates a draft `Encounter`.
5. Diagnoses, lab orders and prescriptions are created against the draft encounter.
6. **`sign_encounter` signs the note and immediately sets the visit to `completed`.**
7. Lab, pharmacy and billing then work against a visit that is already "completed".
8. `billing/services.add_pending_charges` bills the consultation, **every non-cancelled lab test
   (even ones never collected)** and every dispensation.

## 1. Fully implemented

- Patient registration with MRN (`{facility}-{year}-{000001}`, unique), estimated age, phone
  normalisation, allergies, emergency contacts, trigram search.
- Appointment booking with doctor slot-clash check and one active appointment per patient per day.
- Walk-ins, daily queue numbers, one open visit per patient per day (database constraint).
- Vital signs with physiological limits as database constraints; BMI calculated.
- Consultation note with optimistic locking, sign-and-lock, amendments that keep the original.
- ICD-10 diagnoses (primary/secondary, confirmed/provisional), free-text diagnoses.
- Lab orders with accession numbers, specimen collection, numeric/text/choice results,
  automatic H/L/A flags, verification, correction with history, cancellation with reason.
- Dispensing with FEFO batch allocation, expired stock excluded, never above prescribed
  quantity, approved override for stock shortfall.
- Invoices with draft/issued/partial/paid/void, discounts and voids by a second person,
  unique invoice and receipt numbers, transaction references for non-cash payments,
  money as Decimal with database consistency constraints.
- RBAC on every endpoint, append-only audit log, session timeouts, lockout, backups.

## 2. Partially implemented

| Area | What exists | What is missing | Where |
| --- | --- | --- | --- |
| Demographic history | Changes go to the audit log as a diff | No readable history in the chart | `patients/services.update_patient` |
| Emergency contacts | Saved | Replaced by delete-and-recreate (history only in audit) | `set_emergency_contacts` |
| Duplicate detection | Phone or similar name + birth year | National ID not checked; no sex check; alt phone not matched against new phone's alt | `find_possible_duplicates` |
| Appointments | Book, check in, cancel, no-show | No confirmed status, reschedule, notes, service, arrival notifications | `scheduling` |
| Queue | Add, remove, priority, send to doctor | Reassign doctor (API only, no UI), call next, skip with reason, return to queue | `queue.tsx`, `update_queue_entry` |
| Triage | Vital signs + notes | Chief complaint, symptoms, allergy confirmation, current medications, observations; age-specific interpretation; abnormal flags on the server | `record_vitals` |
| Consultation | One text box per history section | Complaint duration, surgical history, general appearance, differential diagnoses, non-drug treatment, referral, follow-up booking; doctor's context panel lacks previous diagnoses and results | `Encounter` |
| Lab catalogue | Category, specimen, unit, one range | Age/sex-specific ranges, critical limits, qualitative type | `LabTest` |
| Lab notifications | "Results ready" and abnormal | No critical-result path or acknowledgement | `verify_result` |
| Prescriptions | Dose, route, frequency, days, quantity | Strength and form are not stored on the line; no allergy warning; no controlled-medicine rules | `PrescriptionItem` |
| Dispensing | FEFO automatic | Pharmacist cannot choose a batch; no "not collected" outcome | `pharmacy/services.dispense` |
| Billing | Invoice from visit charges | No billing policy (labs billed even if never done), no refunds, no tax handling | `add_pending_charges` |
| Patient chart | Overview, visits, vitals, consultations, labs, medicines, billing | Diagnoses list, referrals, follow-ups, documents, payments, visit timeline | `patients.tsx` |
| Notifications | Lab results, approvals | New appointment, arrival, prescriptions waiting, low stock, expiry, follow-up reminders | `notifications` |
| Duplicate merge | Permission `patients.merge` | No merge function | `accounts/catalog.py` |
| Translation | All strings through `t()` | No Amharic or Afaan Oromo files, no language switch | `i18n` |

## 3. Missing

- Visit completion as its own step with outcomes (completed, referred, left before
  completion) and a list of what is still outstanding.
- Visit timeline.
- Referrals and referral letters; medical certificates (sick leave).
- Follow-up appointment booked from the consultation.
- Critical lab results, repeat tests, age/sex reference ranges.
- Controlled-medicine workflow and register (EFDA Directive 1121/2025).
- Refunds.
- Ethiopian calendar display.
- Prescriber title and professional registration number on staff accounts (needed on
  controlled-medicine prescriptions and referral letters).
- Clinic settings (facility name, level, address, TIN, billing policy).
- Lab results report.
- End-to-end browser tests of whole visits.

## 4. Incorrect workflow transitions

1. **Signing the note completes the visit** (`clinical/services.sign_encounter`,
   `complete_visit=True`). Lab, pharmacy and billing then happen on a "completed" visit; the
   queue and dashboards drop the patient while tests are still running.
2. A doctor cannot record a second consultation (for example reviewing results) on the same
   visit, because the visit is closed at the first signature.
3. Appointment goes straight from `scheduled` to `arrived`; there is no `confirmed` step, and it
   is set to `completed` by the same premature visit completion.
4. `start_encounter` accepts a visit still waiting for triage and silently skips triage. This is
   sometimes clinically right (emergencies) but should be explicit and recorded.

## 5. Missing or incorrect fields

- Patient: no current medications field (brief asks for it); "relevant medical history" is
  one text field covering both conditions and history.
- Visit: no completion outcome, completion note, completed-by, skip reason, called time.
- Vital signs: no chief complaint, symptoms, allergy confirmation, current medications.
- Encounter: no complaint duration, surgical history, general appearance, differential, non-drug
  treatment.
- Prescription line: no strength, dosage form or warnings snapshot.
- Lab test: no critical low/high, no age/sex ranges, no department beyond free-text category.
- Medicine: no route, therapeutic category, controlled class, default supplier.
- Staff: no professional title or registration number.

## 6. Incorrect validation rules

- Vital-sign limits are hard database limits only; nothing on the server classifies values as
  abnormal or critical, and nothing considers age (a respiratory rate of 45 is normal for a
  newborn and alarming for an adult).
- Lab flags ignore age and sex, and have no critical level.
- Lab charges are pulled for tests that were ordered but never collected.

## 7. Missing database relationships

- Referral, follow-up appointment and certificate have no tables.
- No link from a follow-up appointment to the encounter that requested it.
- No repeat-test link between lab items.
- Controlled-medicine prescriptions have nowhere to record the paper special-prescription
  serial number.

## 8. Broken module integrations

- Visit completion (see 4.1) breaks queue, dashboards and "today" reports for lab/pharmacy.
- Billing pulls lab tests regardless of status.
- Dispensing does not warn when the medicine matches a recorded allergy.

## 9. UI inconsistencies

- Queue: no reassign, call next, skip, return.
- Appointments: no reschedule or confirm.
- Doctor context: previous diagnoses and results are on other tabs, not beside the note.
- Decorative sidebar card adds nothing for staff (brief: avoid decoration).

## 10. Bugs and security problems

- Emergency contacts are deleted and recreated on every edit; history survives only in the
  audit log. Acceptable for demographics but inconsistent with "never delete history".
- Backups are not encrypted (documented in `docs/security-review.md`).
- No other security defects found in the visit path; all endpoints checked carry
  `required_permissions`.

## Ethiopian requirements checked so far

| Instrument | What it means for this system | Source |
| --- | --- | --- |
| Narcotic and Psychotropic Medicine Control Directive No. 1121/2025 (EFDA) | Special prescription form with serial number; one controlled medicine per prescription; prescriber and dispenser full name, title, registration number; patient age, sex, weight, address, diagnosis; dispense only within 15 days, never to under-18s, never twice; register kept at least 5 years; medium clinics may handle psychotropics only. The electronic format is mentioned but not specified, so the paper form remains the legal document. | [EFDA PDF](https://www.efda.gov.et/wp-content/uploads/2025/12/Narcotic-and-Psychotropic-Medicine-Control-Directive-1121-የናርኮቲክ-እና-የሳይኮትሮፒክ-መድኃኒት-ቁጥጥር-መመሪያ-ቁጥር-1121-2018.pdf) |
| Personal Data Protection Proclamation No. 1321/2024 | Health data is sensitive personal data (Art. 2(5)); in force 24 July 2024. Consent, data-subject rights and local storage obligations need legal review before go-live. | [DLA Piper summary](https://www.dlapiperdataprotection.com/?c=ET&t=law) |
| Health Service Administration and Regulation Proclamation No. 1362/2024 | Parent law for MoH directives (e.g. referral directives). Medical-record content rules not yet located. | [MoH directive citing it](https://www.moh.gov.et/sites/default/files/2026-03/1124_2026_Health_Profession_Licensing_Exam_Implementation_Directive1.pdf) |

| National disease classification (ESV-ICD-11) | The Ministry of Health launched the Ethiopian Simplified Version of ICD-11 on 18 March 2022 for HMIS morbidity reporting, replacing the earlier ICD-10-mapped list. This system codes diagnoses in ICD-10, so its OPD morbidity report is a clinic report, not the official HMIS return. A mapping to ESV-ICD-11 needs the official code list. | [JSI / Ethiopia Data Use Partnership](https://www.jsi.com/?p=19652) |
| VAT Proclamation No. 1341/2024 | Standard rate 15%. Secondary sources (EY, tax guides) list medical services and prescription drugs as exempt; the primary text has not been read here. Tax rates on services and medicines therefore default to 0 and are set per item by the clinic on its tax adviser's advice. | [EY tax alert](https://globaltaxnews.ey.com/news/2024-1317-ethiopia-issues-directive-to-review-list-of-goods-exempt-from-vat) |

Not yet verified: the official HMIS OPD age groups and disease list (ESV-ICD-11), whether private
clinics must report through DHIS2, receipt rules (fiscal device or sales register), and the
medical-record retention period. These stay flagged until a primary source is read.

## Status after the completion work (November 2026)

Everything in sections 2 to 10 above is now built and tested, except where noted.

| Area | Done |
| --- | --- |
| Visit lifecycle | Signing no longer closes the visit; completion with outcome and outstanding check; reopen with reason; timeline |
| Registration | Five-digit MRN for new patients; Ethiopian-calendar birth date entry; readable change history; duplicate merge (patients.merge) with audit, the retired record points to the kept one |
| Waiting list | Tabs per stage with one row per patient; call next, skip, return, reassign; laboratory-only visits |
| Triage | Complaint and duration, general appearance, Triage to (Adult EOPD, Pediatric EOPD, OPD 1, OPD 2, Labour ward), age-specific interpretation |
| Doctor | Evaluation note with system findings (HEENT, LGS, RESP, CVS, ABD, GUS, CNS); ICD-10 coded diagnosis required before prescribing and signing; investigations and prescription on their own pages, before or after signing while the visit is open; referral, certificate, follow-up booking |
| Laboratory | Age/sex ranges, critical results with acknowledgement, repeats, printable result report, outside requests |
| Pharmacy | Allergy warnings, controlled medicines (EFDA 1121/2025), batch choice, register |
| Billing | Tax per service/medicine (default 0), refunds approved by a second person, clinic TIN on receipts, lab billing point setting |
| Chart | Diagnoses, referrals and certificates, appointments, payments and refunds tabs |
| Notifications | Prescription waiting, low stock (once), daily reminders: near expiry, tomorrow's appointments, unbooked follow-ups (`send_daily_reminders`, systemd timer) |
| Ethiopian calendar | Shown beside Gregorian dates (dashboard, appointments, birth date, printed documents) when enabled in Clinic settings |
| Reports | OPD morbidity by sex, new/repeat visit and age band (clinic grouping) |
| Tests | 120 backend tests, 12 frontend unit tests (including calendar conversion over 12 years), 5 browser scenarios in `e2e/` |

Left out on request: Amharic and Afaan Oromo translation files (all strings already go through `t()`).
Still open: encrypted backups (see `docs/security-review.md`), ESV-ICD-11 mapping, and the
unverified legal points above.
