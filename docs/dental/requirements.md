# Dental MRS — requirements matrix

Traces the implementation specification (`Dental MRS — Product and implementation specification`) to the code and
the evidence. **Status** meanings:

- **Built**: implemented, enforced on the server, reachable from the UI and covered by an automated test.
- **Built, review pending**: implemented, but the clinical content still needs a dentist's sign-off
  ([clinical-review-log.md](clinical-review-log.md)).
- **Not done**: outstanding; the reason is given.

Tests: `backend/apps/dental/tests/` (API and service tests, PostgreSQL), `e2e/test_dental.py` (browser),
`frontend/src/lib/teeth.test.ts`, `deploy/scripts/test-backup-restore.sh` (CI).

## Shared platform (spec §1–2, §4–5)

| Requirement | Where | Evidence | Status |
| --- | --- | --- | --- |
| One patient identity and MRN, reused; no dental MRN | `patients` app, unchanged | e2e scenario 1 | Built |
| Duplicate detection and merge | `patients` app, unchanged | `patients/tests/test_merge.py` | Built |
| Modular monolith, no new services or frameworks | ADR 0005; one `apps/dental` app | — | Built |
| Module switching with dependencies and open-work protection | `core/modules.py` (`periodontal`, `dental_imaging`, `dental_lab`, `recalls`) | `test_module_off_refused_with_open_work`, `test_perio_module_off`, `test_imaging_module_off` | Built |
| Dental installation defaults (triage, laboratory, pharmacy off) | `manage.py apply_dental_defaults` | `test_dental_defaults_command` | Built |
| Configurable appointment types (length, chair, category) | `scheduling.AppointmentType` | `test_appointment_types_and_chair_conflicts` | Built |
| Chair (room) clash prevention, several chairs and dentists | `scheduling/services._check_slot` | same | Built |
| Walk-ins, queue, rescheduling and cancellation with reason | `scheduling` (shared) | e2e scenario 1; `scheduling/tests` | Built |
| Appointment ≠ visit ≠ examination ≠ plan ≠ procedure ≠ invoice line | separate tables with links ([data-model.md](data-model.md)) | `test_plan_item_links_to_appointments_without_completing` | Built |

## Clinical records (spec §4.2–6, §9)

| Requirement | Where | Evidence | Status |
| --- | --- | --- | --- |
| Dental profile (history, habits, anxiety, tobacco) separate from encounters | `DentalProfile` | `test_risk_review_and_profile` | Built |
| Medical risk review: who, when, whether changed; no automatic decision | `RiskReview` | same | Built, review pending (R-08) |
| Dental examination: complaint, pain, extraoral/intraoral, assessment, plan, discussion, follow-up | `DentalEncounter` | `test_start_sign_and_visit_flow`, e2e 1 | Built, review pending (R-01, R-10) |
| Draft → signed; amendments with reason keep the original | `services/encounters.py` | `test_only_author_edits_and_signs`, amendment tests | Built |
| Optimistic locking on concurrent edits | `version` fields | `test_concurrent_note_edits_conflict` | Built |
| Unsaved typing is never silently lost (tab change, reload after saving materials) | `Workspace.tsx`, `Procedures.tsx` | e2e 1 | Built |
| Dental diagnoses linked to tooth / surfaces / region / mouth; certainty; code system and version kept | `DentalDiagnosis`, `DiagnosisTerm` | `test_diagnosis_snapshot_and_location` | Built, review pending (R-05) |
| No invented code system, no conformance claims | ICD-10 K00–K14 starter list, labelled pending review | — | Built |

## Odontogram (spec §7, §19.2–19.3)

| Requirement | Where | Evidence | Status |
| --- | --- | --- | --- |
| FDI numbering, permanent, primary and mixed dentition | `teeth.py`, `lib/teeth.ts` | `test_fdi_numbering_and_surfaces`, `test_primary_and_mixed_dentition`, `teeth.test.ts` | Built |
| Surface validation per tooth type (O vs I) | same | same | Built |
| Dated findings, many per tooth, never overwritten (ADR 0006) | `ToothFinding` | `test_findings_history_and_reconstruction` | Built |
| Chart as of an examination; history per tooth; compare two examinations | `services/chart.py`; `ChartView.tsx` | same; e2e 1 (comparison) | Built |
| Corrections traceable (resolve, entered in error with reason) | `services/chart.py` | `test_void_needs_amend_permission_and_reason` | Built |
| Symbols and text, not colour alone; legend; grayscale print | `Odontogram.tsx`, `styles.css` | e2e 1 (symbols) | Built |
| Keyboard and tablet touch targets (≥ 42 × 74 px buttons) | `styles.css` | — | Built, usability test pending |
| Finding vocabulary | `starter_data.FINDING_TYPES` | — | Built, review pending (R-03) |

## Periodontal chart (spec §8)

| Requirement | Where | Evidence | Status |
| --- | --- | --- | --- |
| Six sites per tooth: PD, gingival margin, bleeding, plaque, suppuration; mobility, furcation | `PeriodontalExam`, `PerioSite` | `test_perio_entry_validation_and_calculations` | Built, review pending (R-04) |
| Not-measured and missing explicit; plausible-range validation without changing values | `services/perio.py` | same | Built |
| CAL = PD + GM, documented, raw values kept | [periodontal-chart.md](periodontal-chart.md) | same | Built, review pending (R-04) |
| Comparison with an earlier chart; print | `perio/compare/`, `Perio.tsx` | `test_perio_comparison` | Built |
| New chart starts with teeth the dental chart records as missing | `Perio.tsx` | e2e 1 | Built |

## Treatment and procedures (spec §10–12)

| Requirement | Where | Evidence | Status |
| --- | --- | --- | --- |
| Plans with many items, statuses, revisions with reasons | `TreatmentPlan`, `TreatmentPlanRevision` | `test_plan_lifecycle_partial_acceptance_and_revisions` | Built |
| Accepted / declined / deferred items stay visible; deferred work keeps the plan open | `services/plans.py` | `test_deferred_item_keeps_the_plan_open_until_decided`, e2e 1 | Built |
| Estimate separate from invoice | plan estimate vs `billing` | `test_filling_flow_with_stock_billing_and_no_double_billing`, e2e 1 | Built |
| Patient decision recorded; not a consent form | plan decision | — | Built, legal review pending (R-07) |
| Configurable procedure catalogue: price, duration, tooth requirement, sessions, billing mode, follow-up | `DentalProcedure` | catalogue tests | Built, review pending (R-06) |
| Procedure record: performer, assistant, notes, anaesthesia (free text, no suggested doses), complications, instructions | `ProcedureRecord` | `test_filling_flow…` | Built, review pending (R-14) |
| Multi-session and partial completion; per-session billing where configured | `services/procedures.py` | `test_root_canal_over_three_sessions_billed_per_session` | Built |
| Not performed: reason required, never billed | same | `test_not_performed_is_not_billed_and_needs_reason` | Built |
| Materials through the stock ledger at signing; instruments never consumed | same | `test_filling_flow…` | Built |
| Prescriptions with and without an internal pharmacy; printed for outside pharmacies | shared `clinical.Prescription` (ADR 0009) | `test_dental_prescription_with_and_without_pharmacy` | Built, review pending (R-09) |
| No hard-coded doses or regimens | — | — | Built |

## Imaging, inventory, billing, recalls (spec §13–16)

| Requirement | Where | Evidence | Status |
| --- | --- | --- | --- |
| Local file storage, opaque keys, no public URLs, content checks, SHA-256, previews | `services/imaging.py` (ADR 0007) | `test_image_upload_view_audit_and_withdraw`, `test_image_content_checks`, `test_16_bit_radiograph_preview` | Built |
| Image views audited; never silently replaced | same | `test_replacement_upload_withdraws_the_original` | Built |
| Images in backup, restore and verification | `backup.sh`, `restore.sh`, `verify-backup.sh`, `verify_dental_images` | `test-backup-restore.sh` (CI), `test_verify_images_command_detects_tampering` | Built |
| DICOM | — | — | Not done (not claimed) |
| Dental inventory categories and pack sizes | `inventory` | — | Built |
| Instrument sterilisation and reprocessing | — | — | Not done: needs its own reviewed workflow (spec §14) |
| Procedure charges once per billable execution | `billing` pull-charges | `test_filling_flow…`, e2e 1 | Built |
| Consultation fee setting for dental visits | clinic settings | `test_consultation_fee_setting_for_dental_visits` | Built |
| Follow-ups and recalls: due list, booking, contact log, postponed/declined/unreachable | `Recall`, `RecallContact` | `test_recall_worklist_book_and_attend` | Built, review pending (R-11) |
| SMS or email reminders to patients | — | — | Not done: needs consent and legal review (spec §16) |
| Dental laboratory cases (crowns, bridges, dentures) | `DentalLabCase` | `test_lab_case_flow_and_technician_scope` | Built |

## Orthodontics (added after the specification; see [orthodontics.md](orthodontics.md))

| Requirement | Where | Evidence | Status |
| --- | --- | --- | --- |
| Orthodontic assessment in the examination, locked on signing, version-checked | `OrthoAssessment` | `test_assessment_belongs_to_the_draft_examination`, e2e package scenario | Built, review pending (R-15) |
| Treatment course: planned → active → retention → completed, or discontinued with reason; one open case per patient | `OrthoCase`, `services/ortho.py` | `test_debond_retention_and_completion`, `test_discontinue_cancels_instalments_not_yet_invoiced` | Built |
| Visit record: wires, elastics, aligner number, breakages, hygiene, cooperation; next visit on the recall list | `OrthoVisit` | `test_per_visit_case_charges_each_visit_unless_reason`, e2e | Built, review pending (R-15) |
| Package price with deposit and instalments; collected when due, once; brought forward on request | `OrthoInstalment`, billing pull-charges | `test_package_case_schedule_billing_and_no_double_billing`, `test_invoice_without_visit_collects_due_instalments`, e2e | Built, policy review pending (R-16) |
| Per-visit charging, no-charge reason, extra charges | `OrthoVisit.charge`, `extra_charge` | `test_per_visit_case_charges_each_visit_unless_reason`, `test_void_visit_rules`, e2e | Built |
| Price or charging change with reason, keeping what was invoiced | `change_billing` | `test_change_billing_keeps_what_was_invoiced` | Built |
| Progress photos side by side | `Ortho.tsx` (uses dental images) | — | Built |
| Module switch with open-work protection; permissions; audited reads; reports | `core/modules.py`, `dental.ortho.manage`, reports | `test_module_off_and_open_work`, `test_patient_ortho_view_is_audited_and_scoped`, `test_ortho_reports` | Built |

## Access control, audit, reports, documents (spec §3, §17–18, §22)

| Requirement | Where | Evidence | Status |
| --- | --- | --- | --- |
| Dental roles and permissions; API enforces them | `accounts/catalog.py`, [permissions.md](permissions.md) | `test_default_roles_follow_the_permission_matrix`, `test_access_boundaries` | Built |
| Reception cannot read clinical details | role defaults | `test_access_boundaries`, e2e scenario 11 | Built |
| Assistant cannot sign diagnoses, plans or procedures | role defaults | `test_discard_draft_and_role_policy`, e2e scenario 10 | Built |
| System administrator has no dental access | role defaults | `test_sysadmin_has_no_dental_access` | Built, review pending (R-12 for hygienist scope) |
| Audit in the same transaction; sensitive reads audited | services | `test_encounters_and_chart.py`, `test_perio_imaging_lab_modules.py` (audit assertions) | Built |
| Dental reports with permissions, date filters, audited CSV | `dental/reports.py` | `test_dental_reports_run_and_respect_permissions` | Built |
| Printed chart, periodontal chart, plan estimate, procedure report, examination report, prescription | print views | — | Built |

## Not done, or outside the software (spec §1.3, §25.4, §26 Phase 0 and 8)

| Item | Why it is open |
| --- | --- |
| Interviews with practising dentists; sign-off of every item in the clinical review log | Needs people, not code. Nothing clinical has been reviewed yet |
| Performance measured with dental data on the 4 GB Core i3 target | `backend/perf/` seeds medical history only; a dental seed and a run on target hardware are still needed |
| Security review of the dental additions and independent penetration test | Not started |
| Ethiopian legal and regulatory review (consent, retention, imaging, data protection) | Not started |
| Controlled pilot | After the above |
| Amharic and Afaan Oromo | Clinical terms must not be translated without dental review (spec §21.5); the English strings are ready for it |
| Phone app for dental work | Deliberately left out of the first release (spec §24) |
| End-to-end browser scenarios 2–7, 12–18 of spec §25.3 | Covered by API tests and the CI backup test; browser versions still to be written |

The system must not be described as clinically validated or ready for real patients until the open items above are
closed.
