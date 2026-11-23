# Architecture

This is the in-repository summary of the Phase 1 plan. The full plan (technology comparison, ER diagram, permission matrix, API design, roadmap) is kept in the project design document; this file records what the code relies on.

## Shape

A **modular monolith**: one Django process, one PostgreSQL database, one Nginx, on the clinic's own Ubuntu server.

```
Clinic PCs (browsers) ──HTTPS──▶ web: Nginx ──/api/──▶ api: Django + DRF (Gunicorn) ──▶ db: PostgreSQL 16
                                   │ serves React SPA                                     ▲
                                   └ security headers, TLS                                 └ nightly pg_dump + weekly restore test
```

Only `web` is published to the LAN. `api` and `db` share an internal Docker network with no route outside.

## Request path

Browser → Nginx (TLS, headers, request ID) → Django middleware (request ID, session, CSRF, session-revocation check) → DRF view (authentication, `HasRequiredPermissions`, input validation) → **service function** (business rules inside `transaction.atomic()`, audit event written in the same transaction) → PostgreSQL. If the audit insert fails, the change rolls back.

## Module rules

Each module is a Django app under `backend/apps/` with:

- `models.py` — tables and database constraints
- `services.py` — the only place that changes data; takes an `ActorContext` (who, from where), never an HTTP request
- `views.py` / `api.py` + `serializers.py` — HTTP only: validate, call a service, serialise
- `tests/`

Modules talk to each other through services. Views never write to models directly.

| Module | Owns |
| --- | --- |
| core | error format, request IDs, permission classes, counters (MRN, queue, invoice, receipt numbers), health, catalogue and demo commands |
| accounts | users, roles, permissions, sessions, login attempts |
| audit | audit events |
| notifications | in-app notices (lab results, approvals) |
| approvals | two-person approvals for stock overrides, discounts, voids |
| patients | demographics, emergency contacts, allergies, duplicate detection |
| scheduling | appointments, visits, the daily queue |
| clinical | vital signs (triage), encounters, amendments, ICD-10 codes, diagnoses, prescriptions |
| laboratory | test catalogue, orders, specimens, results, verification, corrections |
| inventory | items, suppliers, purchases, batches, stock ledger, alerts |
| pharmacy | dispensing |
| billing | price list, invoices, lines, payments, daily summary |
| reports | read-only report queries and CSV export |

Triage and terminology, listed separately in the Phase 1 plan, live inside `clinical`. Multi-branch `facility_id` columns were deferred: UUID keys keep a later merge of branch databases possible.

## Data rules

- UUID primary keys; human-readable numbers (MRN, invoice numbers) from PostgreSQL sequences.
- `created_at`/`updated_at` on mutable records; `version` for optimistic locking on clinical records (Phase 3).
- Foreign keys use `PROTECT`; nothing cascades into clinical or financial data.
- Signed clinical notes, results, dispensations, invoices and payments are never updated in place or deleted; corrections are new records that reference the original, with author, time and reason.
- Stock quantity is the sum of a movement ledger, not an editable number.
- The audit table is append-only, enforced by a database trigger.

## Authorisation

Permission codes live in `apps/accounts/catalog.py` and are seeded by migration. Roles group permissions and are editable at runtime. Each view declares `required_permissions = {"GET": (...), "POST": (...)}`; a method not listed is refused. The frontend hides links the user cannot use, but that is cosmetic: the API is the boundary.

Safeguards: users cannot change their own roles or deactivate themselves; no change may leave the system without an active user holding both `users.manage` and `roles.manage`; the system administrator role has no patient-data permissions by default.

## API conventions

`/api/v1/`, JSON, cookie session + CSRF header. Errors always look like:

```json
{"error": {"code": "validation_error", "message": "Invalid input.", "fields": {"phone": ["..."]}, "request_id": "..."}}
```

Codes: `validation_error` 400, `invalid_credentials` 400, `not_authenticated` 401, `permission_denied` / `csrf_failed` / `password_change_required` 403, `not_found` 404, `conflict` 409, `account_locked` 423, `throttled` 429, `server_error` 500.

## Security summary

Argon2id passwords · lockout · login CSRF protection · HttpOnly/SameSite/Secure cookies · idle and absolute session limits · revocation on deactivation and password change · CSP, frame, sniffing and referrer headers from Nginx · `Cache-Control: no-store` on API responses · ORM-only queries · no secrets in the frontend · append-only audit · secrets only in a root-readable `.env`.

## Legal and regulatory questions

Ethiopia's Personal Data Protection Proclamation No. 1321/2024 (in force since 24 July 2024) treats health data as sensitive and contains local-storage provisions. Questions for qualified local legal and Ministry of Health review before go-live:

1. Lawful basis for processing clinical records; whether written consent is needed for registration, photographs or SMS reminders.
2. Whether the clinic must register as a data controller, and whether the vendor is a processor needing a written agreement.
3. Mandatory retention period for medical records and rules for destruction.
4. Patients' rights to copies and corrections, and response deadlines.
5. Breach-notification duties and deadlines.
6. Whether cloud hosting or off-site backup outside Ethiopia is permitted, and conditions.
7. Ministry of Health EMR standards, facility licensing and reporting duties (e.g. notifiable diseases, DHIS2).
8. Which identifiers (e.g. Fayda national ID) may be stored and under what safeguards.

## Interoperability

HL7 FHIR R4 read façades (Patient, Encounter, Observation, Condition, MedicationRequest, DiagnosticReport) are planned after Phase 5. The internal model is shaped to map onto them, but **no FHIR conformance is claimed** until those resources are implemented and validated against the specification.
