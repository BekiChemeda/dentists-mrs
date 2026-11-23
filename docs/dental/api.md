# Dental MRS — dental API

All endpoints follow the existing conventions (`docs/architecture.md`): base path `/api/v1/`, JSON, cookie session
plus CSRF header, the standard error shape (`{"error": {"code", "message", "fields", "request_id"}}`) and
permission checks on every method. A method that is not listed is refused. Where several permissions are listed
for one method, **any one** of them is enough. Some services then narrow access further, for example only the
author may edit a draft, and a technician sees only the cases assigned to them.

Source: `backend/apps/dental/urls.py` and `api/views.py`. Shared endpoints (patients, visits, appointments,
billing, inventory, reports) are unchanged from Clinic MRS. The dental additions to them are listed at the end.

## Catalogues (no patient data)

| Endpoint | Methods and permissions | Notes |
| --- | --- | --- |
| `dental/catalog/` | GET `dental.view`, `dental.catalog.manage`, `dental.recall.manage`, `dental.labcase.work`, `dental.imaging.view`, `appointments.view` | Everything the dental screens need for choices: finding types, procedures, categories, risk questions, regions |
| `dental/finding-types/` | GET `dental.view`, `dental.catalog.manage`; POST `dental.catalog.manage` | Chart vocabulary (code, symbol, kind, allowed scope) |
| `dental/finding-types/<id>/` | PATCH `dental.catalog.manage` | |
| `dental/diagnosis-terms/` | GET `dental.view`, `dental.catalog.manage`, `reports.clinical`; POST `dental.catalog.manage` | `?q=` search; code system, code, display term, source/version kept |
| `dental/diagnosis-terms/<id>/` | PATCH `dental.catalog.manage` | |
| `dental/procedures/` | GET `dental.view`, `dental.catalog.manage`, `billing.view`; POST `dental.catalog.manage` | Procedure catalogue with price, tooth requirement, surfaces, sessions, billing mode, follow-up |
| `dental/procedures/<id>/` | PATCH `dental.catalog.manage` | Optimistic locking with `row_version`; price changes never alter issued invoices |
| `dental/procedures/<id>/materials/` | PUT `dental.catalog.manage` | Default materials per procedure |
| `dental/clinicians/` | GET `dental.view`, `dental.plan.manage` | Staff who can perform or assist |
| `dental/technicians/` | GET `dental.labcase.manage` | |

## Patient-level records

| Endpoint | Methods and permissions | Notes |
| --- | --- | --- |
| `dental/patients/<id>/summary/` | GET `dental.view` | Alerts, shared history (allergies, conditions, medicines), examinations, plans, recalls. Audited as a record view |
| `dental/patients/<id>/profile/` | GET `dental.view`; PATCH `dental.write` | Dental history and habits; `If-Match` row version |
| `dental/patients/<id>/risk-reviews/` | GET `dental.view`; POST `dental.write` | Medical history review: who, when, answers, whether anything changed since the last review |
| `dental/patients/<id>/chart/` | GET `dental.view` | Current chart, or `?as_of=<time>` / `?encounter=<id>` to rebuild the chart as it was |
| `dental/patients/<id>/chart/history/` | GET `dental.view` | `?tooth=36`: every finding on that tooth, including resolved and voided ones |
| `dental/patients/<id>/chart/compare/` | GET `dental.view` | `?from=<exam>&to=<exam>`: what changed between two examinations |
| `dental/patients/<id>/diagnoses/` | GET `dental.view` | |
| `dental/patients/<id>/perio/` | GET `dental.view` | Periodontal examinations with summaries |
| `dental/patients/<id>/plans/` | GET `dental.view`; POST `dental.plan.manage` | |
| `dental/patients/<id>/images/` | GET `dental.imaging.view`; POST `dental.imaging.upload` | Upload is multipart; JPEG, PNG and TIFF are checked by content (not by file name) |
| `dental/patients/<id>/recalls/` | GET `dental.recall.manage`, `dental.view`; POST `dental.recall.manage`, `dental.write` | |
| `dental/patients/<id>/lab-cases/` | POST `dental.labcase.manage` | |

## Examinations (dental encounters)

| Endpoint | Methods and permissions | Notes |
| --- | --- | --- |
| `dental/visits/<visit_id>/encounters/` | POST `dental.write` | Start an examination on today's visit; the visit moves to *In consultation* |
| `dental/encounters/` | GET `dental.view` | `?patient=`, `?visit=`, `?mine=1`, `?status=`, paginated |
| `dental/encounters/<id>/` | GET `dental.view`; PATCH `dental.write` | PATCH needs `version` (409 on conflict) and is allowed only for the author of a draft |
| `dental/encounters/<id>/sign/` | POST `dental.write` | Author only; needs a chief complaint and a diagnosis or assessment. The visit moves to *After consultation* |
| `dental/encounters/<id>/amendments/` | POST `dental.amend` | Signed examination: field, corrected text, reason. The original text is kept |
| `dental/encounters/<id>/diagnoses/` | POST `dental.write` | Term or free text, tooth/surfaces/region/whole mouth, certainty |
| `dental/diagnoses/<id>/remove/` | POST `dental.write` | Draft only, and not while a plan uses the diagnosis |
| `dental/diagnoses/<id>/resolve/` | POST `dental.write` | |
| `dental/encounters/<id>/findings/` | POST `dental.chart.record` | Chart finding in an open examination |
| `dental/findings/<id>/` | DELETE `dental.chart.record` | Only a slip in the same open examination; audited |
| `dental/findings/<id>/resolve/` | POST `dental.chart.record` | No longer present (restored, extracted…), with a note |
| `dental/findings/<id>/void/` | POST `dental.amend` | Entered in error, with a reason; stays in the history |
| `dental/encounters/<id>/perio/` | GET `dental.view`; PUT `dental.chart.record` | Whole periodontal chart for this examination, with `version` |
| `dental/perio/compare/` | GET `dental.view` | `?a=<exam>&b=<exam>`: site-by-site changes |
| `dental/encounters/<id>/procedures/` | POST `dental.procedure.record` | Start a procedure record, from a plan item or straight from the catalogue |
| `dental/encounters/<id>/prescriptions/` | POST `prescriptions.create` | Shared `clinical.Prescription`, linked to the visit; printable for an outside pharmacy |

## Treatment plans

| Endpoint | Methods and permissions | Notes |
| --- | --- | --- |
| `dental/plans/<id>/` | GET `dental.view`; PATCH `dental.plan.manage` | |
| `dental/plans/<id>/revisions/` | GET `dental.view` | A snapshot every time a presented plan changes, with the reason |
| `dental/plans/<id>/items/` | POST `dental.plan.manage` | Add an item: procedure, location, estimate, priority, diagnosis |
| `dental/plans/<id>/present/` | POST `dental.plan.manage` | |
| `dental/plans/<id>/decision/` | POST `dental.plan.manage` | `{"decisions": {item_id: "accepted"/"declined"/"deferred"}}`. This records the discussion; it is not a consent form |
| `dental/plans/<id>/cancel/`, `…/expire/` | POST `dental.plan.manage` | With a reason |
| `dental/plan-items/<id>/` | PATCH `dental.plan.manage` | After presentation, a change needs a reason and creates a revision |
| `dental/plan-items/<id>/remove/` | POST `dental.plan.manage` | Draft plans only |
| `dental/plan-items/<id>/cancel/` | POST `dental.plan.manage` | With a reason |
| `dental/plan-items/<id>/appointments/` | POST `dental.plan.manage` | Link a booked appointment; booking never completes an item |

## Procedure records

| Endpoint | Methods and permissions | Notes |
| --- | --- | --- |
| `dental/procedure-records/` | GET `dental.view` | `?patient=`, `?visit=`, `?encounter=`, `?status=`, `?mine=1`, paginated |
| `dental/procedure-records/<id>/` | GET `dental.view`; PATCH `dental.procedure.record` | Notes, anaesthesia, findings before/after, complications, instructions (draft only, with `version`) |
| `dental/procedure-records/<id>/materials/` | PUT `dental.procedure.record` | Materials used; stock moves only when the record is signed |
| `dental/procedure-records/<id>/sign/` | POST `dental.procedure.sign` | Performer only. `outcome`: `completed`, `session_completed` (more sessions) or `not_performed` (reason required, never billed) |
| `dental/procedure-records/<id>/discard/` | POST `dental.procedure.record` | Draft only, with a reason |
| `dental/procedure-records/<id>/amendments/` | POST `dental.amend` | Signed record: field, corrected text, reason |

## Images

| Endpoint | Methods and permissions | Notes |
| --- | --- | --- |
| `dental/images/<id>/` | GET `dental.imaging.view`; PATCH `dental.imaging.manage` | Details (kind, teeth, region, capture time); a correction needs a reason |
| `dental/images/<id>/file/` | GET `dental.imaging.view` | The bytes, only after the permission check, `?preview=1` for the JPEG preview, `?download=1` for the original (TIFF is always downloaded). Every view is audited. No public path exists |
| `dental/images/<id>/withdraw/` | POST `dental.imaging.manage` | Uploaded in error: hidden from normal views, the file is kept |

There is no DICOM support. Uploads are ordinary image files.

## Recalls and laboratory cases

| Endpoint | Methods and permissions | Notes |
| --- | --- | --- |
| `dental/recalls/` | GET `dental.recall.manage`, `dental.view` | Worklist: due soon, overdue, booked |
| `dental/recalls/<id>/book/` | POST `dental.recall.manage` | Link an appointment |
| `dental/recalls/<id>/contact/` | POST `dental.recall.manage` | Log a contact attempt (reached, unreachable…) |
| `dental/recalls/<id>/status/` | POST `dental.recall.manage` | Postponed (new date), declined, unreachable, attended |
| `dental/lab-cases/` | GET `dental.labcase.manage`, `dental.labcase.work` | Technicians see only their own cases, with name and MRN only |
| `dental/lab-cases/<id>/` | GET / POST `dental.labcase.manage`, `dental.labcase.work` | |
| `dental/lab-cases/<id>/move/`, `…/assign/` | POST `dental.labcase.manage`, `dental.labcase.work` | Status: requested → in progress → ready for fitting → delivered, or cancelled |

## Orthodontics

See [orthodontics.md](orthodontics.md#api): assessment per examination, cases, visits, status changes, price
changes, instalments brought forward.

## Dental additions to shared endpoints

- `visits/`: each visit carries `dental_encounters` (id, dentist, status), so the waiting list can open the right
  workspace.
- `appointment-types/` and `rooms/` (chairs): appointment type sets the default length and chair; booking refuses
  a second appointment on the same chair at the same time.
- `billing/invoices/<id>/pull-charges/`: also pulls orthodontic per-visit and extra charges, and package instalments
  due by the invoice date (on an invoice without a visit, only those instalments). It pulls signed dental procedure records from the visit, each one once.
  Plan estimates are never billed.
- `inventory/items/` (read): also open to `dental.procedure.record` and `dental.catalog.manage`, so staff can pick
  materials.
- `reports/`: dental reports (`dental_plans`, `dental_pending_items`, `dental_procedures`,
  `dental_procedure_categories`, `dental_follow_ups`, `dental_imaging`, `dental_diagnoses`,
  `dental_revenue_procedure`, `dental_revenue_dentist`, `dental_materials`, `dental_estimates`, `dental_chairs`, `dental_ortho_cases`, `dental_ortho_instalments`)
  with the usual date filters and audited CSV export.
