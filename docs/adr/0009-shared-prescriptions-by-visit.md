# ADR 0009 — Prescriptions are shared between medical and dental encounters and follow the visit

Date: 2026-11-23 · Status: accepted

## Decision

`clinical.Prescription` keeps one table for all prescriptions. It gains a required `visit` and an optional
`dental_encounter`; the medical `encounter` becomes optional; a check constraint requires exactly one of the two.
Pharmacy dispensing, billing and visit completion look prescriptions up by `visit`.

## Reasons

The pharmacy queue, dispensing with FEFO and allergy warnings, controlled-medicine rules, printing and billing are
already correct and tested. A second dental prescription table would duplicate all of it (spec §29.2).

## Consequences

- Dental prescriptions reuse the allergy check against the shared allergy list.
- Controlled (narcotic or psychotropic) medicines are refused on dental prescriptions in this version: the EFDA
  special-prescription checks depend on the medical encounter's diagnosis and the vital signs. The dentist uses
  the paper special prescription. Revisit after dentist and pharmacist review (review log R-09).
- Migration back-fills `visit` from the existing encounter.
