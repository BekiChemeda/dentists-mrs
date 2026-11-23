# Laboratory manual

You collect specimens, enter results and verify them. Doctors see a result only after it is
verified. Read [getting-started.md](getting-started.md) first.

Your menu: **Dashboard**, **Patients**, **Laboratory**, **Prices & catalogue** (tests), **Reports**.

## 1. The worklist

*Laboratory › **Worklist*** shows every patient with tests waiting, oldest first, urgent first. Each
order has an accession number; search by accession number, MRN or name. **Completed** shows
finished orders.

Each test moves through: awaiting specimen → collected → resulted → verified.

## 2. Collect

When the specimen is taken, click **Collect** on the test (or **Collect all** for the whole order).
Write the accession number and the patient's name on the tube or container; the system does not yet
print labels.

## 3. Enter the result

Click **Enter result**.

- Number results: type the value. The reference range for the patient's age and sex is shown, and
  the result is flagged **High**, **Low** or normal as you type.
- Positive/negative and list results: choose from the list.
- Text results: type the finding.
- **Comment (optional)** for anything the clinician should know (for example "specimen slightly
  haemolysed").

Click **Save result**. You can **Edit** a result until it is verified.

### Critical results

If the value is in the critical range, the form says so. After saving:

1. Verify it with **Verify critical…** and record in **Clinician informed** who you told and how
   (for example "Dr. Abebe by phone 10:40").
2. Phone or tell the requesting clinician immediately. The system also notifies the doctor, who
   must acknowledge the result.

## 4. Verify

A second look before the doctor sees the result. Check the value, units and patient, then click
**Verify** (or **Verify all** for the order). The result now appears in the patient's chart and to
the doctor, and lab charges are added to the invoice if the clinic charges at verification.

## 5. Corrections, repeats and cancellations

- **Correct** (on a verified result): enter the corrected value and the **Reason for correction**.
  The original value is kept and the report shows **Corrected**. The doctor is notified.
- **Repeat test…**: when the specimen is unsuitable or the result is questioned; give the reason.
  A repeat is not charged again.
- **Cancel test…**: when the test cannot be done (for example the patient left); give the reason.
  Cancelled tests are not charged.

## 6. Result report

Click **Result report** on the order to print the verified results with the clinic letterhead
(and logo, if set). Tests still in progress are listed as not yet on the report. Sign and stamp the
printed copy. Use the browser's print dialog to print or save as PDF.

## 7. Laboratory-only patients

Patients who bring a request from another clinician come straight to the worklist with the
requesting clinician and facility shown. Work them exactly the same way; give them the printed
report.

## 8. Test catalogue

*Prices & catalogue › Laboratory tests* (if your account has permission to manage it): add or edit
tests, units, price, reference ranges (also by age and sex), list choices, and critical limits.
Changed reference ranges apply to new requests; results already ordered keep the range they had.

## Reports

*Reports › **Laboratory requests*** and ***Laboratory results*** (workload, abnormal and critical
results by test) for any date range.

## If the system is down

Use the paper request and result forms and the paper register. When the system is back, enter and
verify the results so they are in the patient's record.
