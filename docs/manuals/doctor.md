# Doctor manual

You see patients, write and sign the evaluation note, request tests, prescribe, refer, issue
certificates and book follow-ups. Read [getting-started.md](getting-started.md) first.

Your menu: **Dashboard**, **Patients**, **Waiting list**, **Appointments**, **Calendar**, **Triage**,
**My visits**, **Reports**.

## 1. Your patients

- *Waiting list › **Waiting for doctors***: patients sent to your department (switch **Show** to
  **Everyone** or **My patients**). Emergencies and urgent patients are first.
- *My visits*: **Waiting for you**, your **Unsigned notes**, and **Recently signed** notes.
- The **Dashboard** shows critical laboratory results you have not yet acknowledged.

Click **Start examination** (or **Continue examination**) to open the visit. The patient banner at the top (name, MRN, age, sex, allergies)
stays on every page of the visit, so you always know whose record you are in.

## 2. The visit page

The visit has four pages: **Evaluation note**, **Investigations**, **Prescription**,
**Referral & certificates**. On the right are the triage findings, allergies and the patient's
history (previous consultations, diagnoses, recent results and prescriptions). **Full chart** opens
the complete record.

### Evaluation note

1. **Presenting complaint** (from triage; complete it), **History of present illness**.
2. **Past medical & surgical history**, family history, medication history, allergy notes.
3. **Physical examination**: general appearance and the system findings (HEENT, lymph glands,
   respiratory, cardiovascular, abdomen, genito-urinary, central nervous system).
4. **Physician diagnosis**: search **ICD-10** by code or name and add one or more diagnoses
   (primary or secondary; provisional or confirmed). A diagnosis is required before prescribing
   and before signing.
5. **Treatment plan**, non-drug treatment and follow-up instructions. **Follow-up date** and
   **Book follow-up appointment** books the return visit directly.

The note saves as you work (**All changes saved**). **Save draft** saves immediately.

If the page says the note was changed elsewhere (for example you have the same note open on two
computers), click **Reload note** before continuing, so you do not overwrite your own other copy.

### Sign the note

Click **Sign note**. It needs the main complaint, a diagnosis and a plan; anything missing is shown.
After signing, the note can no longer be edited. To correct it, use **Amend** on the section: the
signed text is kept unchanged, and your correction, name, time and reason are recorded beside it.

Tests and prescriptions can still be sent after signing, while the visit is open.

### Investigations

Tick the tests, choose the **Priority**, add **Clinical notes for the lab** and click **Request**.
Results appear on this page and in the chart **only after the laboratory has verified them**.
Abnormal results are flagged (High, Low, Abnormal); critical results are also sent to you as a
notification and must be acknowledged (**Review** on the dashboard).

### Prescription

1. Search the medicine catalogue (**Search medicine**). Stock is shown (**In stock**, **low stock**).
   A medicine not in the catalogue can be written as free text.
2. **Dose**, **Frequency** (Daily, BID, TID, QID, STAT, PRN, Nocte, Weekly), **Days**,
   **Quantity to dispense**, **Route**, **Instructions** (optional).
3. **Add another medicine** for more lines, then **Save prescription**.

Safety checks:

- If a medicine matches a recorded allergy, the system stops and shows **Matches a recorded
  allergy**. Change the medicine, or give a **Reason to prescribe anyway**; the pharmacist sees
  your reason.
- **Controlled medicines** (narcotic and psychotropic, EFDA Directive 1121/2025) need the serial
  number of the special prescription form and the patient's weight. A medium clinic cannot
  prescribe narcotics; the system refuses them.
- The system does **not** check drug–drug interactions. Check interactions yourself.

### Referral & certificates

- **Refer**: facility, department, urgency, reason, clinical summary (pre-filled from the note),
  treatment given. **Issue referral**, then **Print**.
- **Certificate**: sick leave (from, to) or fitness. The diagnosis is printed only if you tick the
  option, with the patient's agreement. **Issue certificate**, then **Print**.

Your registration number from your staff account is printed on referrals, certificates and
controlled-medicine prescriptions. If it is missing or wrong, ask the clinic administrator.

A document issued by mistake is cancelled with **Cancel document** and a reason; it stays in the
record marked CANCELLED.

### Your room

At the top of the waiting list, **My room** sets the room you work in today. When you call a patient,
the waiting list shows "Called to Room 3" so reception can direct them. Choose it once at the start of
your shift; leave it on *Not set* if the clinic does not use rooms.

### Printouts for the patient

- **Prescription**: *Prescription* tab, **View / print** beside each prescription. It carries the number,
  your name and registration number. When the clinic has no pharmacy in the system, the prescription
  says *Printed for an outside pharmacy*: print it and give it to the patient.
- **Summary for the patient**: after signing, the button at the top of the visit page prints the reason
  for the visit, examination, diagnosis, verified results, medicines, plan and follow-up.

### Attached documents

Results and letters the patient brings from elsewhere: *patient record › Attached documents › Attach a
document* (PDF, JPEG or PNG, up to 10 MB). Photos taken with a phone are fine; the system removes hidden
details such as the phone's location. A wrong attachment is removed with a reason; it is kept for the
record but no longer shown.

## 3. Finishing

When you have finished with the patient, make sure the note is signed. Reception closes the visit;
an unsigned note stops them, and they will ask you to sign it. Before you leave for the day, check
*My visits › Unsigned notes* is empty.

## 4. Reviewing another doctor's patient

You can open any patient's chart. Opening a visit that another doctor started shows a notice, and
the audit log records who viewed the record. Only the doctor who started a draft note can edit it.

## Reports

*Reports* gives you **Doctor consultations**, **Common diagnoses**, **OPD morbidity**, laboratory
and visit reports for a date range.

## If the system is down

Write on the paper consultation form and prescription pad. When the system is back, enter the note
for the visit (with "entered late from paper" in the history) and sign it.
