# ADR 0003 — Append-only audit table enforced in PostgreSQL

Date: 2026-11-20 · Status: accepted

## Decision

All important actions are written to `audit_event` by `apps.audit.services.record_event`, inside the same transaction as the change. A PostgreSQL trigger raises an error on any `UPDATE`, `DELETE` or `TRUNCATE` of that table.

## Reasons

- Application-level "no delete" rules can be bypassed by bugs, the Django admin, or anyone with the app's database credentials. A trigger cannot be bypassed without superuser rights and a visible schema change.
- Writing the audit event in the same transaction means a change without its audit record cannot be committed.

## Consequences

- The Django admin is not mounted.
- Tests must not use `TransactionTestCase` (its table flush uses TRUNCATE).
- Archiving very old events (years) will need a deliberate, documented superuser procedure; the table is indexed for date and object queries and is expected to stay well under PostgreSQL limits for a single clinic.
- Secrets are refused by `record_event` (passwords, tokens).
