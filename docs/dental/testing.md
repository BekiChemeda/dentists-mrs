# Dental MRS — testing

Synthetic data only. Never load real patient records into a development, test or demo system.

## What runs where

| Suite | Command | What it covers |
| --- | --- | --- |
| Backend (pytest, PostgreSQL) | `cd backend && python -m pytest` | All apps, including `apps/dental/tests/`: tooth and surface rules, dentitions, chart history and reconstruction, signing and amendments, concurrent edits, periodontal validation and calculations, plan lifecycle (partial acceptance, deferral, revisions), multi-session procedures, billing without duplicates, stock at signing, prescriptions with and without a pharmacy, image checks and audit, recalls, lab cases, module switching, role boundaries, dental reports |
| Migrations | `python manage.py makemigrations --check --dry-run` | Models and migrations agree |
| Frontend | `cd frontend && npm test && npm run typecheck && npm run format:check` | Includes `src/lib/teeth.test.ts` (FDI rows, surfaces, orientation) |
| Backup and restore | `deploy/scripts/test-backup-restore.sh` (CI) | Database and dental image files: backup, verification, corrupt-file rejection, restore, rotation, encrypted external copy |
| Off-site backup | `deploy/scripts/test-offsite-backup.sh` (CI) | Encrypted upload, offline retry, recovery with the phrase |
| Audit chain | `python manage.py verify_audit_chain` | Hash chain intact after the cycles |
| Images on disk | `python manage.py verify_dental_images` | Every image row has its file, unchanged (SHA-256) |
| Browser (Playwright) | `pytest e2e/test_dental.py` | See below |

## Browser scenarios

`e2e/test_dental.py` runs against a dental installation with the demo staff:

```bash
# backend (second terminal: frontend `npm run build && npx vite preview --port 4173`)
createdb -O mrs mrs_demo
export DJANGO_DEBUG=true POSTGRES_PASSWORD=<dev password> POSTGRES_DB=mrs_demo
python manage.py migrate
python manage.py bootstrap_admin
python manage.py apply_dental_defaults          # triage, laboratory and pharmacy off
python manage.py seed_demo --with-staff --with-stock --patients 150
python manage.py runserver 8000

pip install playwright pytest
E2E_CHROME=/usr/bin/google-chrome pytest e2e/test_dental.py -q
```

Demo accounts (password `Demo-Clinic-2026`): `reception`, `dentist`, `dentist2`, `assistant`, `hygienist`,
`dentaltech`, `imaging`, `cashier`, `store`. `manager` and `director` need two-step sign-in.

| Spec §25.3 scenario | Browser test | Also covered by |
| --- | --- | --- |
| 1 Toothache → examination → diagnosis → plan → filling → invoice → follow-up | `test_toothache_to_filling_invoice_and_follow_up` | `test_filling_flow_with_stock_billing_and_no_double_billing` |
| 2 Child with primary and permanent teeth | — | `test_primary_and_mixed_dentition` |
| 3 Several teeth and surfaces | scenario 1 (36 OD, 46, 37 O) | `test_findings_history_and_reconstruction` |
| 4 Periodontal examination and later comparison | scenario 1 (missing teeth carried over) | `test_perio_comparison` |
| 5 Root canal over several visits | — | `test_root_canal_over_three_sessions_billed_per_session` |
| 6 Extraction with post-operative review | — | `test_recall_worklist_book_and_attend` |
| 7 Crown preparation and fitting on separate visits | — | `test_lab_case_flow_and_technician_scope`, multi-session tests |
| 8 Patient declines or defers one item | scenario 1 (implant deferred) | `test_deferred_item_keeps_the_plan_open_until_decided` |
| 9 Amending a signed note | — | `test_start_sign_and_visit_flow` |
| 10 Assistant outside their permissions | `test_assistant_cannot_sign_an_examination` | `test_access_boundaries` |
| 11 Receptionist and the clinical chart | `test_receptionist_cannot_open_the_dental_chart` | `test_access_boundaries` |
| 12 No internal pharmacy | (the default dental installation) | `test_dental_prescription_with_and_without_pharmacy` |
| 13 Imaging module off | — | `test_imaging_module_off` |
| 14 Inventory consumed by a procedure | — | `test_filling_flow_with_stock_billing_and_no_double_billing` |
| 15 Partial payment | — | `billing` tests |
| 16 Two staff edit the same record | — | `test_concurrent_note_edits_conflict` |
| 17 Server restart during work | — | `deploy/scripts/test-resilience.py` (medical data) |
| 18 Backup and restore with images | — | `test-backup-restore.sh` |

Orthodontics: `test_orthodontic_package_with_instalments` (assessment, case with deposit and 9 instalments,
braces fitted, deposit invoiced and paid, an instalment taken early) and `test_orthodontic_case_charged_per_visit`
(fitting not charged with a reason, adjustment on the invoice). Backend: `apps/dental/tests/test_orthodontics.py`.

Scenario 1 also checks two data-loss cases found while testing:

- Text typed on *Examination* survives a visit to another tab, and signing is blocked while it is
  unsaved.
- Procedure notes typed before *Save materials* survive the save and are the ones signed.

The medical scenarios in `e2e/test_scenarios.py` need triage, laboratory and pharmacy switched on; run them on a
separate database without `apply_dental_defaults`.

## Still to do

- Browser versions of scenarios 2, 4–7, 9, 13–18.
- Performance with dental data on the 4 GB Core i3 target: a dental seed for `backend/perf/` (encounters, findings,
  periodontal sites, procedures, image metadata over several years), then the measurements in
  `docs/performance.md`.
- Usability testing of the chart and periodontal screens with dentists on clinic monitors and tablets.
