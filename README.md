# Clinic MRS — Medical Records System

A locally hosted clinic management and medical records system for medium-sized private clinics in Ethiopia (10–30 staff, 5–15 computers, up to tens of thousands of patients). It runs on one Ubuntu server in the clinic and is used from web browsers on the clinic network. The internet is not needed for daily work.

> **Status: Phases 1–5 built and tested on synthetic data.** Every module in the brief works end to end through the API and the UI. It has **not** yet been piloted in a real clinic, independently penetration-tested, or reviewed by an Ethiopian lawyer. Do not use it for real patients until those are done (see [docs/security-review.md](docs/security-review.md)).

## What it does

| Department | Features |
| --- | --- |
| Reception | Patient registration (Ethiopian naming, estimated age, phone normalisation), duplicate detection, search by name/phone/MRN/ID, appointments with clash and same-day duplicate checks, check-in, walk-ins, a live queue with ticket numbers |
| Nursing | Triage with vital signs (plausibility checks, BMI), priority that reorders the queue |
| Doctors | Consultation workspace: structured note, ICD-10 diagnoses (common codes seeded, full list importable), prescriptions from the medicine catalogue, lab requests, signing; corrections by amendment that preserve the original |
| Laboratory | Test catalogue with reference ranges, accession numbers, specimen collection, result entry with automatic High/Low/Abnormal flags, verification, corrections with history, doctor notifications |
| Pharmacy | Dispensing against prescriptions, earliest-expiry-first batches, refusal beyond stock unless a second person approves an override |
| Inventory | Items, suppliers, receipts with batches and expiry, adjustments and write-offs, a movement ledger, low-stock and expiry alerts |
| Billing | Invoices that pull visit charges without double billing, payments (cash, telebirr, CBE Birr, bank, card, insurance), receipts, discounts and voids with approval, daily summary |
| Management | 12 reports with date filters, CSV export (audited) and print-to-PDF; approvals inbox; price list and lab catalogue |
| Security | Individual accounts, 9 editable roles over 41 permissions enforced by the API, lockout, session limits, append-only audit trail including record views |

## Repository layout

```
backend/            Django 5.2 + Django REST Framework API (modular monolith)
  config/           settings (environment-driven), URLs, WSGI
  apps/core/        error format, request IDs, permission classes, health check
  apps/accounts/    users, roles, permissions, sessions, login attempts
  apps/audit/       append-only audit trail
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
python manage.py seed_demo --with-staff --with-stock --patients 200   # optional synthetic demo data
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

On Ubuntu Server 24.04, from the application folder: `sudo deploy/install.sh` (guided; `--check` only checks the server). It installs Docker if needed, writes `.env` with random secrets, creates the HTTPS certificate, starts the application, creates the first administrator and installs the backup and daily jobs. Manual steps: [docs/operations/install.md](docs/operations/install.md).

## Documentation

- [Architecture and Phase 1 plan](docs/architecture.md)
- [Architecture decision records](docs/adr/)
- [Manuals for each role](docs/manuals/README.md) (receptionist, nurse, doctor, laboratory, pharmacy, cashier, accountant, clinic and system administrators, troubleshooting, maintenance and support)
- [User guide](docs/user-guide.md) · [Security review](docs/security-review.md) · [Performance test](docs/performance.md)
- [Installation](docs/operations/install.md) · [Backup and restore](docs/operations/restore.md) · [Upgrades](docs/operations/upgrade.md)

## Compliance note

The design follows the principles of Ethiopia's Personal Data Protection Proclamation No. 1321/2024 (local hosting, least privilege, audit, data minimisation). This does **not** mean the software or any clinic using it is compliant. Open legal questions are listed in [docs/architecture.md](docs/architecture.md#legal-and-regulatory-questions); a qualified Ethiopian lawyer must review them before go-live. The system does not claim HL7 FHIR conformance.
