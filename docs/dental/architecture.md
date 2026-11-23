# Dental MRS — architecture

This repository is the Dental MRS. It started as a copy of Clinic MRS (`BekiChemeda/mrs`, commit `03c146d`)
and adds a dental clinical domain on the same foundation. See [ADR 0005](../adr/0005-dental-product-on-mrs-foundation.md)
for why it is a separate repository and how fixes move between the two.

## Shape

Unchanged from Clinic MRS: one Ubuntu server in the clinic, Docker Compose, Nginx serving the React app and
proxying `/api/` to Django + DRF (Gunicorn), PostgreSQL 16 on an internal network. Daily work needs no internet.

```
Clinic PCs / tablets ──HTTPS──▶ web: Nginx ──/api/──▶ api: Django + DRF ──▶ db: PostgreSQL 16
                                                         │
                                                         └──▶ /var/lib/mrs/images  (dental image files, local disk)
```

The one new moving part is a local directory for dental image files (ADR 0007). It is mounted into the `api`
container only, never served by Nginx directly, and is mirrored by the nightly backup.

## What is shared and what is dental

| Shared (existing apps, unchanged meaning) | Dental (new `apps/dental`) |
| --- | --- |
| `patients`: identity, MRN, search, duplicates, merge, allergies, emergency contacts | Dental profile (dental history, habits, anxiety) |
| `scheduling`: appointments, visits, queue, completion; **new:** appointment types and chair (room) booking | Medical risk review before treatment |
| `accounts`, `audit`, `core`, `notifications`, `approvals` | Dental examination (encounter) with pain assessment, extraoral and intraoral examination, sign and amend |
| `billing`: invoices, payments, receipts, discounts, voids, refunds | Odontogram: dated tooth and surface findings |
| `inventory`: items, batches, ledger; **new:** dental item categories and pack sizes | Periodontal examination with site measurements |
| `clinical.Prescription` (shared by medical and dental encounters) | Dental diagnoses linked to teeth, surfaces or regions |
| `reports`: registry and CSV export; **new:** dental reports | Treatment plans, plan items, revisions, patient decisions |
| | Procedure catalogue and procedure execution, materials through the stock ledger |
| | Dental images (local files), dental laboratory cases, recalls |

The medical modules (triage, laboratory, the doctor's consultation) are still in the code. A dental clinic
switches off what it does not use from *System › Modules*; `manage.py apply_dental_defaults` (run by the
installer on a new installation) switches off triage, laboratory and pharmacy as a starting point.

## Module boundaries inside `apps/dental`

One Django app, split by file rather than by app, because the dental concepts reference each other constantly
(a procedure points at a plan item, a tooth, a diagnosis and an encounter) and separate apps would mean
circular imports and migrations for no gain (spec §2.3: split only with independent ownership).

```
apps/dental/
  teeth.py          FDI numbers, dentitions, surfaces, regions: validation shared by every model
  models.py         all tables and database constraints
  services/         the only code that changes data (ActorContext, transaction.atomic, audit in the same transaction)
    profile.py      dental profile, medical risk review
    encounters.py   dental examination: start, update, sign, amend, diagnoses
    chart.py        odontogram findings, resolution, correction, chart as of a date
    perio.py        periodontal examination
    plans.py        treatment plans, items, revisions, patient decisions
    procedures.py   procedure execution, materials, signing, billing source
    imaging.py      image files and metadata
    labcases.py     dental laboratory cases
    recalls.py      follow-ups and recalls
    catalog.py      procedures, finding types, diagnosis terms, appointment types
  api/              HTTP only: validate, call a service, serialise
  reports.py        read-only dental reports, registered in apps.reports
  starter_data.py   starter catalogues (clinic must review; marked "pending clinical review")
```

Rules are the same as the rest of the system (`docs/architecture.md`): views never write to models, services take
an `ActorContext`, signed records are never edited in place, foreign keys `PROTECT`, money is `Decimal`, stock
changes only through the ledger, every change and every sensitive read is audited in the same transaction.

## How dental work joins the shared visit

- Reception checks the patient in exactly as before (walk-in or appointment). There is no separate dental MRN.
- A dentist (permission `dental.write`) opens the patient from the waiting list and starts a **dental examination**.
  The visit moves to *In consultation*, exactly like a medical consultation. Signing the examination moves the
  visit to *After consultation*; signing never closes the visit.
- Procedures, prescriptions and images recorded on that visit stay linked to it. Billing pulls signed procedure
  records from the visit; visit completion lists unsigned dental examinations and procedure records as open work.
- A treatment plan belongs to the **patient**, not a visit. Its items are carried out on many visits; each
  procedure record names the plan item it carried out.

Appointment ≠ visit ≠ examination ≠ treatment plan ≠ procedure ≠ invoice line. Each is its own record with
explicit links (see [data-model.md](data-model.md)).

## Modules a dental clinic can switch off

In addition to the existing modules:

| Module | Permissions removed while off | When off |
| --- | --- | --- |
| `periodontal` | — (feature flag) | The periodontal chart tab is hidden and new periodontal examinations are refused. Earlier charts stay readable. |
| `dental_imaging` | `dental.imaging.view`, `dental.imaging.upload`, `dental.imaging.manage` | No image upload or viewing. Files stay on disk and in backups. |
| `dental_lab` | `dental.labcase.manage`, `dental.labcase.work` | No laboratory cases; the technician role has nothing to do. |
| `recalls` | `dental.recall.manage` | No recall list; dentists write the review date in the note. |

Dental examinations, the odontogram, diagnoses, treatment plans and procedure records are the core of the product
and are not modules.
