# Dental MRS — Dental Records System

A locally hosted clinic management and dental records system for medium-sized private dental clinics in Ethiopia (10–30 staff, 5–15 computers, up to tens of thousands of patients). It runs on one Ubuntu server in the clinic and is used from web browsers and tablets on the clinic network. The internet is not needed for daily work.

It is built on the Clinic MRS foundation (`BekiChemeda/mrs`): the same patients, appointments, waiting list, billing, inventory, reports, accounts, audit trail, backups and deployment. On top of these it adds a dental clinical domain (see [ADR 0005](docs/adr/0005-dental-product-on-mrs-foundation.md)).

> **Status: dental workflows built and tested on synthetic data only.** Nothing has yet been reviewed by a practising dentist (see the [clinical review log](docs/dental/clinical-review-log.md)), performance-tested with dental data on the target hardware, penetration-tested, legally reviewed or piloted. All clinical lists are starter lists pending clinical review. **Do not use it for real patients** until the open items in [docs/dental/requirements.md](docs/dental/requirements.md) are closed.

## What it does

| Area | Features |
| --- | --- |
| Reception | One patient record and MRN (Ethiopian naming, Ethiopian calendar dates, duplicate detection and merge), dental appointment types with default length and chair, dentist and chair clash checks, walk-ins, the waiting list, visit completion |
| Examination | Medical history review before treatment (who reviewed and when; no automatic decisions), dental profile, chief complaint and structured pain, extraoral and intraoral examination, assessment and discussion; draft → signed, amendments with a reason |
| Dental chart | FDI numbering, permanent, primary and mixed dentition, dated findings per tooth, surface, region or whole mouth; nothing overwritten; chart as at any earlier examination and comparison; symbols and legend that print in black and white |
| Periodontal chart | Six sites per tooth: probing depth, gingival margin, bleeding, plaque, suppuration, mobility, furcation; summary and CAL from the raw values; comparison with earlier charts |
| Diagnoses | Searchable terms (ICD-10 K00–K14 starter list) linked to teeth, surfaces or regions, with certainty |
| Treatment plans | Many items across many visits, printable estimates, presentation and the patient's decision per item (accepted, declined, deferred), revisions with reasons |
| Procedures | Configurable catalogue and prices; procedure records linked to plan item, tooth, performer and assistant; multi-session work; materials taken from stock at signing; never billed twice, never billed when not performed |
| Prescriptions | From the medicine catalogue; printed for an outside pharmacy when the clinic has none; no suggested doses |
| Images | Radiographs and photographs on the clinic server only, checked by content, served only after a permission check, every view audited; included in backup and restore. No DICOM |
| Recalls and laboratory | Follow-up and recall worklist with contact log; dental laboratory cases for crowns, bridges and dentures |
| Billing and stock | Invoices from signed procedures, cash and the existing payment methods, discounts, voids and refunds with two-person approval; dental item categories, pack sizes, batches and expiry |
| Management | Dental, operational and financial reports with audited CSV export; switchable modules (periodontal chart, imaging, dental laboratory, recalls) |
| Security | Individual accounts, editable roles (dentist, dental assistant, hygienist, technician, imaging staff and the clinic roles) enforced by the API, lockout, session limits, two-step sign-in, append-only hash-chained audit trail |

The medical modules of Clinic MRS (triage, laboratory, the doctor's consultation, pharmacy) are still present; a new dental installation switches triage, laboratory and pharmacy off, and the system administrator can switch them back on.

## Repository layout

```
backend/            Django 5.2 + Django REST Framework API (modular monolith)
  config/           settings (environment-driven), URLs, WSGI
  apps/core/        error format, request IDs, permission classes, health check
  apps/accounts/    users, roles, permissions, sessions, login attempts
  apps/audit/       append-only audit trail
  apps/dental/      dental domain: examinations, chart, periodontal chart, plans, procedures, images, recalls, lab cases
frontend/           React 18 + TypeScript + Vite single-page app, Nginx config
deploy/scripts/     backup, verify, restore, certificate and test scripts
deploy/systemd/     backup and verification timers
docs/               architecture, decisions (ADRs), operations guides, manuals per role
docker-compose.yml  production stack: web (Nginx) → api (Gunicorn) → db (PostgreSQL 16)
```

## Quick start (development)

Requirements: Python 3.12+, Node 22, PostgreSQL 16.

```bash
# Database
createuser -P mrs            # choose a dev password
createdb -O mrs mrs

# Backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DJANGO_DEBUG=true POSTGRES_PASSWORD=<your dev password>
python manage.py migrate
python manage.py bootstrap_admin          # prints a one-time password
python manage.py load_starter_catalog     # example prices, lab tests, medicines (review before use)
python manage.py load_dental_catalog      # starter dental procedures (price 0) and appointment types
python manage.py apply_dental_defaults    # a dental clinic: triage, laboratory and pharmacy off
python manage.py seed_demo --with-staff --with-stock --patients 200   # optional synthetic demo data and dental staff
python manage.py runserver 8000
python -m pytest                          # run the test suite

# Frontend (second terminal)
cd frontend
npm ci
npm run dev                               # http://localhost:5173
npm test && npm run typecheck
```

Use synthetic data only. Never load real patient records into a development or test system.

## Production installation

On Ubuntu Server 24.04, from the application folder: `sudo deploy/install.sh` (guided; `--check` only checks the server). It installs Docker if needed, writes `.env` with random secrets, creates the HTTPS certificate, starts the application, creates the first administrator, loads the starter catalogues, switches off the medical modules a dental clinic does not use, and installs the backup and daily jobs. Manual steps: [docs/operations/install.md](docs/operations/install.md).

## Documentation

- Dental: [requirements matrix](docs/dental/requirements.md) · [architecture](docs/dental/architecture.md) · [data model](docs/dental/data-model.md) · [API](docs/dental/api.md) · [clinical workflows](docs/dental/clinical-workflows.md) · [dental chart](docs/dental/odontogram.md) · [periodontal chart](docs/dental/periodontal-chart.md) · [permissions](docs/dental/permissions.md) · [testing](docs/dental/testing.md) · [clinical review log](docs/dental/clinical-review-log.md)
- [Architecture of the shared platform](docs/architecture.md)
- [Architecture decision records](docs/adr/)
- [Manuals for each role](docs/manuals/README.md) (dentist, dental assistant, dental receptionist, dental clinic administrator, and the shared receptionist, cashier, accountant, administrator, troubleshooting and maintenance manuals)
- [User guide](docs/user-guide.md) · [Security review](docs/security-review.md) · [Performance test](docs/performance.md)
- [Installation](docs/operations/install.md) · [Backup and restore](docs/operations/restore.md) · [Upgrades](docs/operations/upgrade.md)

## Compliance note

The design follows the principles of Ethiopia's Personal Data Protection Proclamation No. 1321/2024 (local hosting, least privilege, audit, data minimisation). This does **not** mean the software or any clinic using it is compliant. Open legal questions are listed in [docs/architecture.md](docs/architecture.md#legal-and-regulatory-questions); a qualified Ethiopian lawyer must review them before go-live. The system does not claim HL7 FHIR, DICOM or any dental terminology conformance, and it has no clinical validation.
