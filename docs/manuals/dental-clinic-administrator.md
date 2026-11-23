# Dental clinic administrator manual

Everything in the [clinic administrator manual](clinic-administrator.md) applies: staff, departments,
announcements, reports, the operational audit log. This page covers the dental set-up. You see patient details,
never dental notes, charts or images.

## Before the first patient

1. **Departments, chairs and rooms** (*Administration › Departments*): create the dental department and one entry
   per dental chair (*Chair 1*, *Chair 2*…). Staff belong to the dental department.
2. **Staff**: give each person their own account and role: Dentist, Dental assistant, Dental hygienist, Dental
   technician, Imaging staff, Receptionist, Cashier, Inventory manager. One person may hold several roles in a
   small clinic. The system administrator manages roles themselves.
3. **Dental catalogue** (*Management › Dental catalogue*). Everything is a starter list, **pending clinical
   review**. Go through it with the lead dentist:
   - **Procedures and prices**: the starter prices are 0. Set every price you charge. Switch off what the clinic
     does not offer. For each procedure: default length, whether a tooth (and surfaces) is required, usual number
     of sessions, how it is billed (on completion or per session), the usual follow-up, and default materials.
   - **Chart findings**: names and symbols on the chart.
   - **Diagnoses**: the diagnosis list (ICD-10 K00–K14 to start).
   - **Appointment types**: names, usual length, default chair.
4. **Inventory**: dental items with their category (restorative material, anaesthetic, endodontic, impression,
   prosthetic, sterilisation, infection control, instrument…), pack size and minimum stock. Instruments are never
   consumed by procedures.
5. **Clinic settings**: whether the consultation fee is also charged on dental visits (off by default: dental
   visits are billed by procedure).

Price changes apply to new charges only. Issued invoices keep the price they were issued with.

## Modules

The system administrator switches modules under *System › Modules*. A new dental installation starts with
triage, laboratory (medical) and pharmacy off. The dental options are:

| Module | When off |
| --- | --- |
| Periodontal chart | The tab is hidden; earlier charts stay readable |
| Dental imaging | No uploads or viewing; files stay on the server and in backups |
| Dental laboratory | No laboratory cases |
| Recalls | No recall list |

A module cannot be switched off while it has unfinished work (for example a laboratory case not yet delivered).
Nothing is deleted when a module is switched off.

## Reports

Under *Reports*, the dental reports: treatment plans by status, pending plan items, procedures by dentist and
category, follow-ups due, imaging workload, common diagnoses, revenue by procedure and by dentist, material use,
estimates against invoices, and chair use. CSV downloads are recorded in the audit log. Keep exports on clinic
computers only.

## Clinical review

Before real patients, the lead dentist must review and sign off every item in
`docs/dental/clinical-review-log.md` (workflow, chart conventions, findings, periodontal protocol, diagnoses,
procedures, consent, medical history questions, prescribing, recall intervals, hygienist scope, image types,
anaesthesia record).
