# Clinical review log

Nothing in this system has been reviewed by a practising dentist yet. Every item below must be reviewed and
signed off (name, registration, date, decision) before a pilot. Until then, all seeded clinical content carries
`review_status = "pending"` and the UI shows *Starter list — pending clinical review* on catalogue screens.

| ID | Item | Where | Question for the reviewer | Status |
| --- | --- | --- | --- | --- |
| R-01 | Overall visit workflow | `clinical-workflows.md` | Does the order (history → complaint → examination → chart → diagnosis → plan → procedure → sign) match how your clinic works? What is done by assistants? | Open |
| R-02 | Chart orientation and FDI | ADR 0008, odontogram screen | Is the viewer-facing orientation correct for your team? Is FDI the notation used? | Open |
| R-03 | Finding vocabulary | `starter_data.py` `FINDING_TYPES` | Which findings are needed, their names, symbols; which are "existing work" vs "condition" vs "state"? Retained primary, impacted, supernumerary handling? | Open |
| R-04 | Periodontal protocol | `periodontal-chart.md` | Six sites per tooth? Gingival margin sign convention and CAL = PD + GM? Mobility and furcation grading scales (0–3)? Plaque and bleeding as % of measured sites? | Open |
| R-05 | Diagnosis list | `starter_data.py` `DIAGNOSIS_TERMS` (ICD-10 K00–K14) | Is ICD-10 acceptable for your clinic and for reporting? Which codes to add or remove? | Open |
| R-06 | Procedure catalogue | `starter_data.py` `PROCEDURES` | Names, categories, default durations, sessions, follow-up days, which roles may perform each, billing mode (per session or on completion). Prices are placeholders set to 0. | Open |
| R-07 | Consent | Treatment plan decision | The system records the discussion and the patient's decision only. What consent form, signature and witness are legally required, and should a signed consent be attached (attachments) before treatment? Legal review needed. | Open |
| R-08 | Medical risk review questions | `starter_data.py` `RISK_QUESTIONS` | Are these the right questions? Any to add (e.g. bisphosphonates, radiotherapy to head/neck, infective endocarditis risk)? | Open |
| R-09 | Controlled medicines on dental prescriptions | ADR 0009 | Dental prescriptions currently refuse narcotic/psychotropic items. Confirm with a pharmacist and the EFDA directive whether dental clinics may prescribe them and with what checks. | Open |
| R-10 | Examination sign rule | `services/encounters.py` | Signing needs a chief complaint and a diagnosis **or** an assessment. Is that the right minimum? | Open |
| R-11 | Recall kinds and default intervals | `Recall.Kind`, procedure follow-up days | Correct kinds? Default intervals per procedure? | Open |
| R-12 | Hygienist scope | `permissions.md` | What may a hygienist record and sign in your clinic? | Open |
| R-13 | Image types | `DentalImage.Kind` | Correct list? Any modality you would need DICOM for? | Open |
| R-14 | Anaesthesia record | Procedure record | Free text today (agent, amount, technique written by the dentist). Should it be structured? No doses are suggested by the system. | Open |
| R-15 | Orthodontic assessment and visits | `OrthoAssessment`, `OrthoVisit.Kind`, `OrthoCase.Appliance`, `OrthoCase.Retainer` ([orthodontics.md](orthodontics.md)) | Are the fields (Angle class per side, incisor relationship, overjet/overbite in mm, crowding and spacing grades, skeletal pattern, profile) what the clinic records? Are the visit types, appliance and retainer lists right? Should an index such as IOTN be added? | Open |
| R-16 | Orthodontic charging | `OrthoCase` billing, instalments | Clinic policy, not clinical: package with deposit and instalments, or per visit; which visit types are charged per visit by default (adjustment, aligner, emergency, retention review); what happens to the balance when treatment is discontinued (today: instalments not yet invoiced are cancelled, issued invoices stay). | Open |

## Sign-off

| Reviewer | Registration | Date | Items | Decision / notes |
| --- | --- | --- | --- | --- |
| | | | | |
