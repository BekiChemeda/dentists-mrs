# Accountant manual

The Accountant role gives read-only access to the clinic's money: invoices, payments, refunds,
financial reports and stock value. It cannot take payments, change invoices, approve discounts,
voids or refunds, or see clinical notes or patient records beyond what appears on invoices. This
keeps checking separate from handling money. Read [getting-started.md](getting-started.md) first.

Your menu: **Dashboard**, **Inventory**, **Billing**, **Reports**.

## Daily and monthly checks

- **Dashboard**: today's collections by payment method.
- *Billing › **Payments today*** and ***All invoices***: every invoice with total, paid, balance and
  status; open one to see its lines, payments, discounts and refunds, with who approved and who paid
  each.
- *Reports* (choose a date range):
  - **Revenue by day**: payments received per day and method. Compare with bank, telebirr, CBE Birr
    and card statements.
  - **Revenue by category**: invoiced amounts by charge type (consultation, laboratory, medicines,
    procedures).
  - **Outstanding payments**: issued invoices with a balance due.
  - **Inventory valuation**: stock on hand by batch at cost.
  - **Pharmacy stock**, **Medicines dispensed**, **Visits** and other operational reports.

Every report can be printed or saved as PDF (**Print or save as PDF**) or downloaded as CSV for
Excel. Downloads are recorded in the audit log.

## Things to look for

- Cash collected each day matches what was banked.
- Discounts, voids and refunds: each has a reason, a requester and a different approver. Ask about
  any that look unusual.
- Old outstanding invoices.
- Stock write-offs (expired or damaged) in *Inventory › Movements*.

If you find a mistake, report it to the clinic administrator or director; corrections are made by
the people with those rights, and every correction is recorded.

The role's permissions can be adjusted by the system administrator if the clinic needs more or less.
