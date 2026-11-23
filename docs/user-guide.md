# User guide (short)

Full manuals for each role are in [manuals/](manuals/README.md).

Every staff member signs in with their own account. The menu on the left shows only what your role may use. Press `/` anywhere to search for a patient by name, phone number or MRN.

## A normal outpatient visit

1. **Reception** finds the patient (top search) or registers a new one (*Patients → Register a new patient*). New patients get a five-digit MRN. The birth date can be entered in the Gregorian or the Ethiopian calendar. If the system thinks the patient already exists it shows the matches; open the existing record instead of creating a second one. Then *Add to waiting list* (choose *See a doctor* or *Laboratory only*) or check in a booked appointment (*Appointments → Check in*). The patient gets a ticket number.
2. **Nurse** opens *Waiting list → Waiting for triage* and clicks *Triage*. Record the complaint and its duration, general appearance, vital signs and allergies, then choose *Triage to* (Adult EOPD, Pediatric EOPD, OPD 1, OPD 2 or Labour ward). *Urgent* or *Emergency* priority moves the patient to the top.
3. **Doctor** opens *Waiting list → Waiting for doctors* and clicks *Manage*. The visit page has four pages:
   - *Evaluation note*: history, past medical & surgical history, physical examination with system findings, the physician diagnosis (chosen from ICD-10) and the treatment plan. *Sign note* needs a diagnosis and a plan.
   - *Investigations*: tick the tests and send them to the laboratory.
   - *Prescription*: needs a diagnosis first. Frequency is chosen from Daily, BID, TID, QID, STAT, PRN, Nocte or Weekly; instructions are optional.
   - *Referral & certificates*.
   Investigations and prescriptions can be sent before or after signing, while the visit is open. A signed note is corrected only with *Amend*.
4. **Laboratory** works from the *Worklist*: *Collect*, *Enter result*, then *Verify*. Doctors see results only after verification. *Result report* prints the verified results for the patient.
5. **Pharmacy** opens *Pharmacy → To dispense* and dispenses each line. Stock is taken from the batch that expires first.
6. **Cashier** opens *Billing → New invoice*, chooses the patient and today's visit (consultation, tests and dispensed medicines are added), clicks *Issue invoice*, then *Take payment* and prints the receipt. telebirr, CBE Birr, bank and card payments need the transaction reference.
7. **Reception** completes the visit from *Waiting list → Completed visits*. The dialog lists anything still open (unsigned note, tests, medicines, unpaid balance) and asks how the visit ended.

## Laboratory only

A patient who brings a test request from another clinician: *Add to waiting list → Laboratory only*, copy the requesting clinician and facility, tick the tests. The patient goes straight to the laboratory and cashier; no consultation fee is charged.

## Duplicate records

If a patient was registered twice, the clinic administrator opens the record to keep and uses the merge button next to *Edit*. Everything moves to the kept record; the duplicate keeps its MRN and points to the kept record, so old paper files still lead to the right chart.

## Approvals (two-person rule)

Discounts, voiding an invoice, refunds and dispensing beyond recorded stock are requested by one person and approved by another with the right permission (by default the clinic administrator). Nobody can approve their own request. Approved requests can be used once.

## Email alerts

When the clinic has set up email (System › Email), staff get emails about important events and about changes to their own account. Choose how many under your name › **Security and alerts**: *Important only* (default), *Everything* or *None*. Emails never contain patient details, only a link to sign in. Your address is the one on your staff account; ask an administrator to change it.

## Light and dark mode

Open the menu under your name and choose **Light**, **Dark** or **Device** (follow the phone or computer's own setting, the default). The choice is remembered on that browser. Printed documents always use the light layout.

## Who administers what

Three roles share administration, and the server enforces the split (hiding menus is only a convenience).

| | System administrator | Clinic administrator | Clinic director |
| --- | --- | --- | --- |
| Purpose | Keeps the system running and secure | Runs the clinic day to day | Oversees money, policy and performance |
| Accounts | Any account, any role; roles and permissions | Adds and edits clinic staff with ordinary roles only; cannot touch administrator or director accounts | Views the staff list |
| Daily work | None | Queue, appointments, registration, departments, announcements, catalogues, services and fees | Approvals, announcements, clinic settings |
| Records | No patient records, invoices or clinic settings | Patient details only, never clinical notes | Patient details only |
| Reports | None | All, including staff activity | All, including staff activity |
| Audit log | Everything, including sign-ins and security events | Clinic work only | Clinic work only |
| System page | Server health, backups, error log, security rules, maintenance mode | — | — |

**Maintenance mode** (System › Security and maintenance): while it is on, only system administrators can use the system and everyone else sees your message, including on the sign-in page. Restoring a backup is never done from the browser; follow `docs/operations/restore.md`.

**Departments** (clinic administrator): staff belong to a department; departments marked as triage destinations are what the nurse chooses under *Triage to*. On the waiting list, doctors see the patients sent to their own department by default.

**Announcements** appear at the top of the dashboard for everyone, or only for chosen roles or one department, between the dates you set. Never put patient information in them.

**Clinic logo** (clinic administrator or system administrator): *Clinic settings › Clinic logo*. It
appears in the menu, on the sign-in page and on every printed document.

**Two people editing the same record**: the second save is refused with *Someone else saved this
record first*, naming who saved and when; nothing is overwritten. Click *Load the latest version*
and make the change again.

**Two-step sign-in**: after the password, a 6-digit code from an authenticator app on the phone (Google Authenticator, Microsoft Authenticator, Aegis). Required for administrators and the clinic director by default (System › Security). Set it up under your name › *Two-step sign-in*. Keep the recovery codes somewhere safe: each lets you sign in once if the phone is lost. If both are lost, a system administrator can reset it after checking who is asking.

**Unused accounts** are switched off automatically after 90 days without a sign-in (configurable); administrators are told who.

## End of day

- Cashier: the *Billing* page shows totals by payment method for the day; count cash against the *Cash* figure.
- Clinic administrator: *Reports* gives revenue, outstanding invoices, visits, common diagnoses, laboratory workload, stock and more. *CSV* downloads open in Excel; *Print or save as PDF* uses the browser's print dialog.

## When something goes wrong

Error messages end with a reference such as `Reference: 8f1c…`. Give that reference to the system administrator; it identifies the exact request in the server logs. If the server is unreachable, continue on paper forms and enter the records when it is back.
