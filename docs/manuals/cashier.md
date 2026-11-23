# Cashier manual

You prepare invoices, take payments, print receipts and balance the cash at the end of the day.
All amounts are in Ethiopian birr. Read [getting-started.md](getting-started.md) first.

Your menu: **Dashboard**, **Patients**, **Appointments**, **Billing**, **Approvals**, **Reports**.

## 1. Make the invoice

*Billing › **New invoice***

1. Find the patient.
2. **Visit**: choose today's visit. Linking the visit adds its consultation, laboratory tests and
   dispensed medicines automatically. For a counter sale or a service without a visit, choose
   **No visit**.
3. Click **Create invoice**.
4. Check the lines with the patient. To add something else, **Add a service…**, choose it, set the
   **Quantity** and click **Add**. If the visit gained charges after you created the invoice (for
   example a test the doctor added), click **Add visit charges** before issuing it.
5. A line added by mistake can be removed while the invoice is a draft.
6. Click **Issue invoice**. An issued invoice can no longer be edited, only paid, discounted (with
   approval) or voided (with approval).

Laboratory tests are charged at the point the clinic chose (when requested, collected or verified),
so patients are not charged for tests that were never done.

**Dental clinics.** Signed dental procedures on the visit are added the same way, each once. For orthodontic
patients:

- **Package (instalments).** Instalments that are due by today are added automatically, labelled with the case
  number, e.g. *Orthodontic treatment OC-2026-00012: Instalment 3 of 12*. A patient can pay an instalment with no
  visit: choose **No visit** and click **Add visit charges**. To take an instalment early, the dentist (or you,
  from the dental record if you can see it) uses **Take payment today**; it is then added like a due one.
- **Per visit.** Each orthodontic visit appears as *Orthodontic visit OC-…: Adjustment*, plus any extra charge
  the dentist recorded (e.g. a lost retainer).

## 2. Take payment

On the invoice click **Take payment**.

1. **Amount ETB**: the full balance, or part of it (the invoice becomes **Partly paid**).
2. **Method**: cash, telebirr, CBE Birr, bank transfer or card.
3. For anything other than cash, type the **Transaction reference** from the patient's phone,
   the transfer slip or the card terminal. It is required.
4. For cash, type **Cash received (optional)** to see the **Change to give**.
5. Click **Record payment**, then **Print receipt**. The receipt carries the clinic's details, TIN
   and logo.

## 3. Discounts, voids and refunds (two-person rule)

You request; another person with approval rights (by default the clinic administrator or director)
approves. Nobody can approve their own request, and each approval can be used once.

- **Discount**: **Request discount**, amount and reason, **Send for approval**. Once approved,
  **Apply discount** on the invoice.
- **Void**: for an invoice that should not exist (for example made for the wrong patient).
  **Request void**, reason. Once approved, **Void invoice**.
- **Refund**: on the receipt, **Request refund**, amount and reason (for example "test not done,
  patient left"). Once approved, **Pay out refund**; give the money back and the refund is recorded
  against the original payment.

*Approvals* shows your requests and their status. You get a notification when one is decided.

## 4. Lists

*Billing*: **Open invoices** (issued, not fully paid), **All invoices**, **Payments today**. Search
by invoice number, MRN or name.

## 5. End of the day (cash-up)

1. *Billing › **Payments today***: the summary shows **Collected today** and the totals by method.
2. Count the cash in the drawer. It must equal the **Cash** figure (plus your opening float).
3. Check the telebirr, CBE Birr, bank and card totals against the statements or the terminal's
   end-of-day slip.
4. If something does not match, do not change any records. Write down the difference and tell the
   clinic administrator; *Reports › **Revenue by day*** and the audit log help find it.
5. *Billing › **Open invoices***: follow up any patient who left without paying, as the clinic's
   procedure says.

## Reports

**Revenue by day**, **Revenue by category**, **Outstanding payments**.

## If the system is down

Write paper receipts from the numbered receipt book. When the system is back, make the invoices and
record the payments with the paper receipt number in the reference, so the day's totals are right.
