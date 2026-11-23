# Dental MRS — permissions and roles

Permission codes are defined in `backend/apps/accounts/catalog.py` and enforced by every API view
(`required_permissions`). Roles are editable at runtime; the table shows the **defaults**.

## Dental permission codes

| Code | Allows |
| --- | --- |
| `dental.view` | Read dental examinations, chart, periodontal charts, diagnoses, treatment plans, procedure records, dental profile and risk reviews |
| `dental.write` | Start, write and sign dental examinations; record diagnoses and risk reviews; edit the dental profile |
| `dental.chart.record` | Record tooth findings and periodontal measurements in an open (draft) examination |
| `dental.amend` | Amend signed examinations and procedure records; mark chart findings as entered in error |
| `dental.plan.manage` | Create, present and revise treatment plans; record the patient's decision; plan appointments |
| `dental.procedure.record` | Prepare procedure records and their materials |
| `dental.procedure.sign` | Sign procedure records they performed |
| `dental.imaging.view` | View dental images (every view is audited) |
| `dental.imaging.upload` | Upload dental images |
| `dental.imaging.manage` | Correct image details; withdraw an image uploaded in error |
| `dental.labcase.manage` | Send work to the dental laboratory, follow it up, record delivery |
| `dental.labcase.work` | Work on laboratory cases assigned to oneself (name and MRN only) |
| `dental.catalog.manage` | Maintain dental procedures and prices, finding types, diagnosis terms, appointment types |
| `dental.recall.manage` | Recall list: book, postpone, log contact attempts |

Reused, not duplicated: `prescriptions.create` (prescribing), `reports.clinical` / `reports.operational` /
`reports.financial` (dental reports), `billing.*`, `inventory.*`, `appointments.*`, `queue.manage`,
`patients.*`.

## Default roles

| Permission | Dentist | Dental assistant | Dental hygienist | Dental technician | Imaging staff | Receptionist | Clinic admin |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| dental.view | ✓ | ✓ | ✓ | | | | |
| dental.write | ✓ | | | | | | |
| dental.chart.record | ✓ | ✓ | ✓ | | | | |
| dental.amend | ✓ | | | | | | |
| dental.plan.manage | ✓ | | | | | | |
| dental.procedure.record | ✓ | ✓ | ✓ | | | | |
| dental.procedure.sign | ✓ | | ✓ | | | | |
| prescriptions.create | ✓ | | | | | | |
| dental.imaging.view | ✓ | ✓ | ✓ | | ✓ | | |
| dental.imaging.upload | ✓ | ✓ | | | ✓ | | |
| dental.imaging.manage | ✓ | | | | ✓ | | |
| dental.labcase.manage | ✓ | | | | | | |
| dental.labcase.work | | | | ✓ | | | |
| dental.catalog.manage | | | | | | | ✓ |
| dental.recall.manage | ✓ | | ✓ | | | ✓ | |
| patients.view | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓ |
| queue.manage | ✓ | ✓ | ✓ | | | ✓ | ✓ |
| appointments.view | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓ |
| appointments.manage | ✓ | | | | | ✓ | ✓ |
| reports.clinical | ✓ | | | | | | ✓ |

The clinic director, cashier, accountant, inventory manager and system administrator roles are unchanged and get
no dental clinical permissions. A small clinic gives one person several roles.

A hygienist works within the clinic's approved scope. By default they can chart, record and sign their own
procedures (for example scaling) but cannot start or sign an examination or make a diagnosis; a clinic that
allows more adds `dental.write` to the role.

## Rules the server enforces beyond permissions

- Receptionists, cashiers and the director never see examination notes, chart, periodontal values or diagnoses:
  they lack `dental.view`. The recall list shows only the recall kind and due date.
- Only the dentist who started an examination edits or signs it. Others with `dental.chart.record` add findings to
  it while it is a draft; each finding records who entered it.
- A procedure record is signed only by the person recorded as performing it. A dental assistant cannot sign a
  diagnosis, a treatment plan decision or a procedure.
- If a procedure lists the roles allowed to perform it, the performer must hold one of those roles.
- Signed records are never edited: amendments and corrections need a reason.
- Nobody approves their own discount, void, refund or stock override (existing approvals rule).
- Image files are served only through the API after a permission check; every view is audited.
- A technician's case list and case detail include only cases assigned to them.
- The system administrator has no dental permissions by default.
