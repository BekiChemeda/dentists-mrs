# ADR 0005 — Dental MRS as a separate product on the Clinic MRS foundation

Date: 2026-11-23 · Status: accepted

## Decision

Dental MRS lives in its own repository (`BekiChemeda/dentists-mrs`), started from Clinic MRS at commit `03c146d`.
The shared platform (accounts, patients, scheduling, billing, inventory, audit, reports, deployment, backup) is
kept as it is and extended only where dental work needs it. Dental clinical concepts live in one new app,
`apps/dental`.

## Reasons

- The owner sells the dental product separately; a dental clinic should not see laboratory or triage concepts
  it does not use, and releases must not wait on medical changes.
- Rewriting the shared platform would throw away tested security, audit, backup and billing behaviour.

## Consequences

- Fixes to the shared platform must be copied between the two repositories. Keep changes to shared apps small and
  listed in `docs/dental/architecture.md` ("Shared tables extended") so they are easy to carry back.
- A later merge into one codebase with a "product" setting is possible because dental code is confined to
  `apps/dental`, a few hooks in shared apps, and frontend pages under `src/pages/dental*`.
- Shared-app changes made here: appointment types and chair booking (`scheduling`), dental item categories and
  pack sizes (`inventory`), prescriptions linked to a visit (`clinical`), dental charges and consultation-fee
  setting (`billing`, `core`), dental open work at visit completion (`scheduling.completion`), "clinician" =
  `clinical.write` **or** `dental.write` for queue and doctor lists.
