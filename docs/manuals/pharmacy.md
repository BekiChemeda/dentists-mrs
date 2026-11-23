# Pharmacy manual

You dispense prescriptions, keep stock right and keep the controlled-medicine register. Read
[getting-started.md](getting-started.md) first.

Your menu: **Dashboard**, **Patients**, **Pharmacy**, **Inventory**, **Approvals**,
**Prices & catalogue** (medicines), **Reports**.

## 1. Dispense

*Pharmacy › **To dispense*** lists prescriptions waiting, with each medicine, directions and how
much remains to give.

1. Check the patient (name, MRN, age) against the person in front of you.
2. Click **Dispense** on the line.
3. **Catalogue medicine to give**: for a medicine written as free text, choose the matching stock
   item.
4. **Batch**: the earliest-expiring batch is used automatically. Choosing another needs a reason.
   Expired batches are never offered.
5. **Quantity**: up to what remains on the prescription line. You can give part now and the rest
   later.
6. Tick **The patient was counselled on dose, duration and risks**, and click **Dispense**.

**Allergy override**: if the doctor prescribed despite a recorded allergy, the line is marked and
the doctor's reason is shown. Read it and check with the doctor if in doubt.

The system does not check drug–drug interactions. Check them yourself, especially for patients on
several medicines.

### Not enough stock recorded

If the system shows less stock than you physically have, the stock records are wrong: fix them with
an adjustment (section 3, ask the inventory manager). If you must dispense now, use **Request override approval** with the
reason. A clinic administrator approves it in *Approvals*; then **Dispense with override** works
once. Correct the stock afterwards.

## 2. Today's work

*Pharmacy › **Dispensed today*** lists what was dispensed, by whom.

## 3. Stock

*Inventory*:

- **Stock**: every item with usable stock, reorder level and price; **Low** marks items below
  their reorder level. Click an item to see its batches.
- **Alerts**: **Low stock** and batches **Expiring within 90 days**. You also get a daily reminder.
- **Receive stock**: supplier, date, supplier invoice number, then one line
  per batch with **Batch no.**, expiry, quantity and unit cost. **Record receipt**.
- **Adjust** (on a batch): **Count correction (+/−)** after a stock count, or **Expired or damaged
  write-off**, with a reason. Every adjustment is recorded with your name and the reason.
- **Movements**: every receipt, dispensing and adjustment, for checking.

Stock on hand is always calculated from those records; it cannot be typed in directly. With the
built-in roles, receiving stock and adjustments are done by the inventory manager or the clinic
administrator; the pharmacist sees stock and reports differences to them. Your clinic may have
given your account these permissions too.

## 4. Controlled medicines

Narcotic and psychotropic medicines (EFDA Directive 1121/2025) need the special prescription form,
whose serial number the doctor enters. When dispensing one, check the paper form and tick that you
checked it. *Pharmacy › **Controlled register*** shows, per medicine,
every movement with prescriber, form number and running balance. **Download CSV** gives a copy for
inspection. Check the register balance against the physical count regularly.

## 5. Medicine catalogue

*Prices & catalogue* or *Inventory › **New item*** / **Edit**: name, generic and brand name, dosage
form, strength, counting unit, route, category, **Controlled classification**, **Allergy groups**
(for example "Penicillin, Beta-lactam": these are matched against patients' allergies), warnings
printed for the patient, reorder level and selling price.

If you see **Someone else saved this record first**, another person changed the item while you were
editing. Click **Load the latest version** and make your change again.

## Reports

**Pharmacy stock**, **Medicines dispensed**, **Inventory valuation**.

## If the system is down

Dispense from the paper prescription and record it in the paper register. When the system is back,
dispense against the prescription in the system so stock and the patient's record are right.
