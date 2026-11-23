# Receptionist manual

You register patients, book appointments, run the waiting list and close visits at the end. Read
[getting-started.md](getting-started.md) first.

Your menu: **Dashboard**, **Patients**, **Waiting list**, **Appointments**, **Calendar**, **Billing**,
**Approvals**, **Reports**.

## 1. Find the patient first

Before registering anyone, search for them: press `/` and type part of the name, the phone number
or the MRN (5-digit medical record number). Search also finds old MRNs of records that were merged.

- Found: open the record and go to step 3.
- Not found: register (step 2).

Registering someone twice splits their history across two records, which is a patient-safety risk.

## 2. Register a new patient

*Patients › **Register a new patient***

1. **Identity**: **Given name**, **Father's name**, **Grandfather's name**, **Sex**.
2. **Date of birth**: type it in the Gregorian calendar, or use **or in the Ethiopian calendar**.
   If the patient does not know it, tick **Date of birth unknown: enter age** and type the age;
   the record shows the birth date as estimated.
3. **Phone** (and **Second phone**), **National ID** if they have one.
4. **Address**: **Region**, **City / town**, **Sub-city / woreda**, **Kebele**, **House number**.
5. **Medical background** if the patient knows it: blood group, **Known allergies** (separate with
   commas; leave empty if none known), chronic illness, past history, current medications.
6. **Emergency contact**: name, relationship, phone.
7. Click **Register patient**.

If the system shows **This patient may already be registered**, look at the matches with the patient:

- Same person: click **Open this record**. Do not register again.
- Different person (for example a namesake): click **It is a different person: register**.

The new record gets an MRN. Write it on the patient's card.

### Correcting details

Open the record and click **Edit details** (pencil icon), change what is wrong and click
**Save changes**. Every change is kept in the record's change history (**Show change history**).

If you see **Someone else saved this record first**, another person changed the record while you
were editing. Click **Load the latest version**, check their change, and edit again if needed.

### Allergies

On the patient's record: **Add allergy**, type the substance, reaction and severity. Allergies are
checked when a doctor prescribes, so record every one the patient mentions. To remove an allergy
that was recorded by mistake, use **Remove** and give the reason; it stays in the history.

### Duplicate records

If you find that a patient has two records, tell the clinic administrator. Only they can merge
records (see [clinic-administrator.md](clinic-administrator.md#merge-duplicate-patient-records)).

## 3. Send the patient to the waiting list

From the patient's record click **Add to waiting list**, or from *Waiting list* click **Add walk-in**
and pick the patient.

- **Visit type › See a doctor**: choose a **Doctor** or **First available doctor**, and a
  **Priority** (Routine, Urgent, Emergency). The patient goes to triage.
- **Visit type › Laboratory only**: for a patient who brings a request from another clinician.
  Fill in **Requested by (clinician)**, **Facility**, any **Clinical notes for the lab**, tick the
  tests and click **Send to laboratory**. No consultation fee is charged.

The patient gets a ticket number. Emergencies go to the top of the list automatically.

## 4. Appointments

*Appointments* shows one day at a time (**Previous day**, **Next day**, **Today**, or pick a **Date**;
filter by **Doctor**).

**Book**: from the patient's record or the Appointments page, click **Book appointment**, choose the
doctor, date, time, length and service, and add **Notes for the clinic** if useful (for example
"fasting required"). The *Calendar* page shows how busy each day is and the holidays.

When the patient arrives, click **Mark arrived**: they go onto the waiting list with a ticket number.

Other actions (the **⋯** button on the appointment):

- **Confirm**: the patient confirmed by phone.
- **Reschedule…**: choose the new date and time. The appointment shows how many times it moved.
- **Mark no-show**: the patient did not come.
- **Cancel appointment…**: give the reason.

Appointments marked **Follow-up booked by the doctor** were booked from a consultation.

## 5. Run the waiting list

*Waiting list* has four tabs: **Waiting for triage**, **Waiting for doctors**, **Being managed**,
**Completed visits**. Each row shows the ticket, name, MRN, age, sex and waiting time.

Actions on a row:

- **Call**: shows the patient as called (with the time).
- **Skip…**: the patient is not there; give the reason. They stay in the queue, at the end.
- **Return to queue**: undo a skip.
- **Assign doctor…**: send to a specific doctor.
- **Send to doctor without triage**: only when the clinic's procedure allows it.
- **Set priority**: Routine, Urgent or Emergency.
- **Remove from queue…**: the patient left; give the reason.

If the page warns that visits from earlier days are still open, close them (section 6) so that the
day's reports are correct.

## 6. Close the visit

When the patient has finished (seen by the doctor, tests done, medicines given, paid):

1. *Waiting list › **Being managed*** or ***Completed visits***, click **Complete visit**.
2. The dialog lists anything still open: **Unsigned notes**, **Laboratory not finished**,
   **Medicines not dispensed**, **Not yet invoiced**, and any **Unpaid balance**. An unsigned note
   must be signed by the doctor before the visit can close; ask the doctor.
3. Choose **How did the visit end?**: Care completed; Completed, follow-up booked; Referred
   elsewhere; Left before completion. Add a note where asked (for example where the patient was
   referred).
4. Click **Complete visit**.

If the clinic switched on *Close finished visits automatically*, visits with nothing left open close
by themselves some time after the doctor signs; you only close the ones that still have something open.

A visit closed by mistake today can be reopened from the patient's record (**Visits › Reopen**,
with a reason).

### Patient card

*Patient record*, the card button at the top: prints a bank-card size card with the clinic's name, the
MRN and the patient's name. It shows no diagnoses. Give it at registration; ask for it at every visit.

### Papers the patient brings

A referral letter or an outside result: *patient record › Attached documents › Attach a document*. You
can attach and see the list; only clinical staff can open the files.

## 7. Invoices

Your role can create invoices, but payments are taken by the cashier. See [cashier.md](cashier.md)
if you also work at the cash desk.

## End of the day

- No patient left on **Waiting for triage** or **Waiting for doctors** who has gone home: remove
  them with the reason.
- Every visit of the day is completed with an outcome.
- Tomorrow's appointments: look at *Appointments* for tomorrow and call patients if your clinic
  confirms by phone.

## If the system is down

Use the paper registration and queue forms. When the system is back, register the patients and
record their visits; write "entered late from paper" in the notes where possible.
