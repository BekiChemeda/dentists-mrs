# Dental MRS — orthodontics

Orthodontic treatment (braces, aligners, retainers) runs for one to three years over many visits, so it has its
own record on top of the ordinary dental examination. It is the module **Orthodontics**, switched on by default
and switchable by the system administrator. Clinical lists are starter lists pending review
([clinical-review-log.md](clinical-review-log.md), R-15 and R-16).

Code: `backend/apps/dental/models.py` (Ortho*), `services/ortho.py`, `api/ortho_views.py`,
`frontend/src/pages/dental/Ortho.tsx`. Tests: `apps/dental/tests/test_orthodontics.py`, `e2e/test_dental.py`.

## What is recorded

| Record | What it holds | Rules |
| --- | --- | --- |
| **Orthodontic assessment** (`OrthoAssessment`) | Molar and canine relationship each side (Angle Class I–III), incisor relationship (Class I, II div 1, II div 2, III), overjet and overbite in mm (negative = reverse overjet / open bite), crowding and spacing per arch (none–severe), midlines, crossbite, other findings, skeletal pattern, profile, habits, TMJ, oral hygiene, problem list, objectives, options discussed, planned extractions | One per dental examination, on its *Orthodontics* tab. Only the examining dentist edits it, only while the examination is a draft; signing locks it. Version-checked against concurrent edits |
| **Orthodontic case** (`OrthoCase`) | Number `OC-YYYY-NNNNN`, appliance, arches, dentist, objectives, expected months, status and dates, retainers, how it is charged | One open case per patient (database rule). Status changes and price changes are kept as case events with who and why |
| **Orthodontic visit** (`OrthoVisit`) | What was done (records, braces fitted, adjustment, aligner change, emergency, braces removed, retainer fitted, retention review), upper and lower archwire, elastics, aligner number, breakages, hygiene, wear and cooperation, notes, next visit in weeks, charges | Linked to the clinic visit (and the examination when recorded from one). Never edited; a mistake is marked *entered in error* with a reason, unless it is already invoiced |
| **Instalment** (`OrthoInstalment`) | Label, due date, amount | Billing state comes from the invoice line that charged it |

## Status

```
planned ──(braces fitted / first aligners, or "Start treatment")──▶ active
active ──(braces removed / retainer fitted, or "Move to retention")──▶ retention
active, retention ──("Complete case")──▶ completed
planned, active, retention ──("Discontinue…", reason required)──▶ discontinued
```

Visit types allowed: *planned* — records, fitting, aligners, other; *active* — adjustment, aligner, emergency,
braces removed, retainer fitted, records, other; *retention* — retention review, retainer fitted, emergency,
records, other. Anything else is refused with a hint ("Record the fitting of the braces first").

When a visit gives *Next visit in (weeks)*, a recall *Orthodontic adjustment* is added to the recall list; recording
the next orthodontic visit closes the open one as attended.

## Charging: two ways, chosen per case

| | Package price, paid in instalments | Charged per visit |
| --- | --- | --- |
| Set up | Price, optional deposit, number of instalments (1–60), every N days (7–92), first payment date. The deposit is due on the first date, the rest is split equally (the last instalment takes the rounding) | Price per visit |
| Visits | Not charged | Charged at the case's per-visit price. Adjustment, aligner, emergency and retention review are ticked by default; not charging needs a reason. Fitting and removing braces, records and retainers are normally separate procedures from the catalogue (*OR-BOND*, *OR-DEBOND*, *OR-REC*, *OR-RET*) |
| Extra charges | Either way, a visit can carry an extra charge with its reason (lost retainer, broken appliance) | |
| Invoicing | The cashier's *pull charges* collects instalments due by the invoice date — on the visit's invoice, or on an invoice with no visit. *Take payment today* brings an instalment forward | Pulled from the visit like dental procedures |
| Changing | *Change price or payment* (reason required): what is already invoiced stays; instalments not yet invoiced are cancelled and the new price minus what was invoiced is rescheduled. The price cannot go below what was invoiced. Switching to per-visit cancels instalments not yet invoiced | Same action; the new price applies to later visits |
| Discontinued | Instalments not yet invoiced are cancelled; issued invoices stay as they are | — |

Nothing is charged twice: every invoice line records the instalment or visit it came from, with a database rule
that one source is billed at most once on live invoices (`invoice_line_source_once`). The case page shows each
instalment as scheduled, due today, overdue, invoiced, part paid, paid or cancelled, with the invoice number.

## API

| Endpoint | Methods and permissions |
| --- | --- |
| `dental/encounters/<id>/ortho-assessment/` | GET `dental.view`; PUT `dental.ortho.manage` (examining dentist, draft only; `row_version`) |
| `dental/patients/<id>/ortho/` | GET `dental.view` — cases and assessments, audited |
| `dental/patients/<id>/ortho/cases/` | POST `dental.ortho.manage` |
| `dental/ortho/cases/` | GET `dental.view` — open cases (`?status=`, `?mine=1`), paginated |
| `dental/ortho/cases/<id>/` | GET `dental.view` (audited); PATCH `dental.ortho.manage` (details, `row_version`) |
| `dental/ortho/cases/<id>/visits/` | POST `dental.ortho.manage` |
| `dental/ortho/cases/<id>/billing/` | POST `dental.ortho.manage` (reason required) |
| `dental/ortho/cases/<id>/start/`, `…/retention/`, `…/complete/`, `…/discontinue/` | POST `dental.ortho.manage` |
| `dental/ortho/visits/<id>/void/` | POST `dental.ortho.manage` or `dental.amend` (the recorder, or someone who can amend) |
| `dental/ortho/instalments/<id>/bring-forward/` | POST `dental.ortho.manage` or `billing.invoice` |

Reports: **Orthodontic patients** (`dental_ortho_cases`, clinical) — open cases, months in treatment, last visit,
next visit due; **Orthodontic instalments** (`dental_ortho_instalments`, financial) — instalments due in the
period and earlier ones still owed, with their invoice state.

## Not included

- Cephalometric tracing or measurements (upload the cephalogram as an image).
- Treatment-need indices such as IOTN (R-15 asks whether to add one).
- Aligner ordering from manufacturers.
- Interest or late fees on instalments.
