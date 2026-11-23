# Clinic administrator manual

You run the clinic day to day in the system: staff accounts, departments, prices and catalogues,
approvals, reports, announcements and the clinic's details and logo. You can see and correct
patients' details, but not clinical notes. Read [getting-started.md](getting-started.md) first.

Your menu includes **Patients**, **Waiting list**, **Appointments**, **Calendar**, **Inventory**,
**Billing**, **Approvals**, **Reports**, **Prices & catalogue**, **Announcements**, **Departments**,
**Clinic settings**, **Staff accounts**, **Roles & permissions** (view), **Audit log**.

Your account needs two-step sign-in (set it up at first sign-in, see getting-started).

## 1. First set-up of a new clinic

Do these once, in this order, before real patients are registered:

1. **Clinic settings**: facility name, level, licence number, TIN, address, phone; how laboratory
   tests are charged; Ethiopian calendar on or off. Upload the **Clinic logo**.
2. **Departments**: check the list; add or rename departments; mark the ones a nurse can send
   patients to after triage.
3. **Staff accounts**: one account for every person (section 2).
4. **Prices & catalogue**: review every service price, laboratory test and medicine. The starter
   catalogue has example prices only.
5. **Inventory**: the inventory manager receives the opening stock.
6. **Calendar**: add religious holidays set by moon sighting and clinic closure days.
7. A practice visit with invented patients, through every role, to check prices and the flow.

## 2. Staff accounts

*Staff accounts* lists everyone with role, status and last sign-in.

### Add a person

1. **New account**. Username (for example `abebe.k`), first and last name, email and phone
   (optional; email is used for alerts), **Job title**, **Professional registration number** for
   clinicians (printed on prescriptions, referrals and certificates), **Department**, **Start date**.
2. **Roles**: tick one or more. You can give the ordinary roles: receptionist, nurse, doctor,
   laboratory technician, pharmacist, cashier, accountant, inventory manager. Administrator and
   director roles are given only by the system administrator.
3. Save. The system shows a **temporary password once**. Give it to the person **in person**. They
   must change it at first sign-in.

### Day-to-day changes

On a person's row:

- **Edit**: details, department, roles.
- **Reset password**: issues a new temporary password and ends their sessions. Check who is asking
  before you do this; never send passwords by SMS, email or Telegram.
- **Unlock**: after too many wrong passwords.
- **Reset 2-step**: when they lost their phone and recovery codes. Check who they are in person.
- **Deactivate**: when someone leaves or is suspended. They are signed out immediately. Accounts are
  never deleted, because the records they made point to them. **Activate** brings one back.

You cannot change administrator or director accounts, or your own roles; ask the system administrator.

**Small-clinic combinations**: above the role list, buttons such as *Receptionist + Cashier* or *Doctor +
Laboratory technician* tick the roles one person needs when they do several jobs.

Accounts not used for 90 days are switched off automatically and the administrators are told.

When someone leaves the clinic, deactivate the account **on their last day**.

## 3. Departments

*Departments* also lists the **consultation rooms**. Add each room where doctors see patients (as
written on the door); doctors then choose their room each day and patients are called to it.
Your home page shows **Getting the clinic ready**, a checklist of what to set up before going live; it
disappears when you close it.

*Departments*: name, short code (fixed once created, because it is stored on triage records),
**receives triage** (offered to nurses under *Triage to*), active, order in lists. Staff are
assigned to a department on their account; doctors see their own department's patients by default.

## 4. Prices & catalogue

- **Services**: consultation, procedures and other services with price and tax rate. Leave the tax
  rate at 0 unless the clinic's tax adviser confirms a service is taxable. The service with code
  `CONSULT` is added automatically to every visit with a consultation.
- **Laboratory tests**: code, name, department, specimen, result type, unit, reference ranges
  (overall and by age and sex), critical limits, price. Changed ranges apply to new requests only.
- **Medicines**: see [pharmacy.md](pharmacy.md#5-medicine-catalogue). Allergy groups and the
  controlled classification matter for patient safety; check them carefully.

Prices changed today apply to invoices made from now on; issued invoices keep their prices.

If you see **Someone else saved this record first**, another person changed the same item while you
had it open. Click **Load the latest version**, look at their change, then make yours again.

## 5. Approvals

*Approvals › **Open*** shows requests waiting for you: discounts, invoice voids, refunds, and
dispensing beyond recorded stock. For each, read the reason, open the invoice or prescription if
needed, and **Approve** or **Reject** (with a reason). You cannot approve your own requests.
*History* shows past decisions. Approvals waiting also appear on your dashboard and as notifications.

## 6. Patients

You can register patients, correct details and manage the waiting list and appointments like
reception (see [receptionist.md](receptionist.md)).

### Merge duplicate patient records

When one person has two records:

1. Open the record to **keep** (usually the older one with more history).
2. Click **Merge a duplicate record into this one** (next to **Edit details**) and choose the
   duplicate.
3. Check with the patient or their documents that both are the same person; tick the confirmation
   and give the reason (for example "registered twice; same phone and national ID").
4. Click **Merge**. All visits, notes, results, prescriptions and invoices move to the kept record.
   The duplicate keeps its MRN and points to the kept record, so old paper files still find it.

A merge cannot be undone from the screen; be sure first.

## 7. Clinic settings and logo

*Clinic settings*:

- **Facility**: printed on every receipt, report, referral and certificate. **Facility level**
  decides which controlled medicines may be prescribed (EFDA Directive 1121/2025).
- **Charge laboratory tests**: when tests are requested, when the specimen is collected (default),
  or when the result is verified.
- **Clinic logo**: **Upload logo** (PNG or JPEG, up to 2 MB, at least 32 pixels each side). A square
  or wide logo on a plain background works best. The system shrinks it to 512 pixels and stores a
  cleaned copy. It appears in the menu, on the sign-in page and on every printed document. **Replace
  logo** or **Remove logo** at any time. The system administrator can also change the logo.

- **Waiting list**: highlight patients waiting longer than a number of minutes; whether reception may
  send a patient straight to the doctor; **Close finished visits automatically** (off by default): a
  visit closes by itself 15 minutes to 2 hours after the doctor signs, but only when tests are
  verified, medicines dispensed and the bill paid. Anything still open waits for staff as before.
- **Document notes**: a short line printed at the bottom of prescriptions, referral letters,
  certificates, laboratory reports, consultation summaries and patient cards.
- **Opening hours**: when switched on, appointments can only be booked inside them. Walk-ins are always
  accepted.
- **Modules**: which parts of the system the clinic uses (triage, appointments, laboratory, stock,
  pharmacy, billing, reports). You can see them here; only the system administrator switches them.
  When the pharmacy is off, doctors print prescriptions for an outside pharmacy, and the prescription
  note you set under document notes is printed at the bottom.

Every change is recorded in the audit log.

## 8. Announcements

*Announcements › **New announcement***: title, details, level (information or important), dates, and who sees it
(everyone, chosen roles, or one department). Shown at the top of the dashboard between the dates.
Never put patient information in an announcement.

## 9. Calendar

*Calendar* shows bookings per day and holidays. Fixed national holidays are built in. Add holidays
that depend on moon sighting (mark **Date not yet confirmed** until announced) and clinic days such
as staff training (**Add holiday**).

## 10. Reports and audit

*Reports*: registrations, visits, consultations, appointments, laboratory requests and results,
pharmacy stock, dispensing, revenue (by day and category), outstanding payments, inventory
valuation, OPD morbidity, common diagnoses, and **Staff activity** (work recorded per person).
Choose the dates; print, save as PDF, or download CSV for Excel. Downloads are recorded.

*Audit log*: who did what and when, for clinic work. Use it to answer questions such as "who changed
this price?" or "who voided this invoice?". Entries cannot be edited or deleted.

## Routines

**Daily**: approvals; open visits from earlier days (the waiting list warns about them); cash-up
differences reported by the cashier.

**Weekly**: low stock and expiring batches (*Inventory › Alerts*); outstanding invoices; staff who
left (deactivate them).

**Monthly**: reports for management; review staff accounts and roles (does everyone still need
their role?); prices.

Technical problems (server, backups, network, the system not opening) go to the system
administrator. See also [troubleshooting.md](troubleshooting.md).
