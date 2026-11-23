# ADR 0008 — Dental terminology: FDI numbering, ICD-10 diagnoses, local finding vocabulary

Date: 2026-11-23 · Status: accepted for development; **clinical content pending dentist review**

## Decision

- **Tooth numbering:** FDI two-digit notation (ISO 3950), validated in `apps/dental/teeth.py`. Chart orientation:
  the patient's right on the viewer's left (as when facing the patient), upper arch on top, 18→11 | 21→28 and
  48→41 | 31→38; primary teeth 55→51 | 61→65 and 85→81 | 71→75 in a separate row.
- **Diagnoses:** WHO ICD-10, the system already used for medical diagnoses. A starter list from chapter XI
  (K00–K14) plus S02.5 (fracture of tooth) is seeded into `DentalDiagnosisTerm` with `source_version` "WHO ICD-10
  (2019)" and `review_status` "pending". Each diagnosis row copies code system, code, term and version, so a later
  catalogue change does not alter past records. No invented codes. No SNODENT or other conformance is claimed.
- **Chart findings and procedures:** a configurable local vocabulary (`FindingType`, `DentalProcedure`) with
  starter entries marked pending review. Clinics edit names, symbols, prices and availability in the catalogue.

## Consequences

- A clinic can import further ICD-10 codes or add a second code system (e.g. a licensed SNODENT subset) without
  schema changes (`code_system` is a field).
- The starter vocabularies must be approved by practising dentists before any pilot (review log).
