# Dentist manual

You examine patients, record the dental chart and the periodontal chart, make diagnoses, plan treatment, carry out
and sign procedures, prescribe, and book reviews. Read [getting-started.md](getting-started.md) first.

Your menu: **Dashboard**, **Patients**, **Waiting list**, **Appointments**, **Calendar**, **My dental
examinations**, **Recalls**, **Orthodontics**, **Dental laboratory**, **Reports**.

> The clinical lists in this version (chart findings, diagnoses, procedures, medical history questions) are
> starter lists **pending clinical review**. Tell the clinic administrator what to change.

## 1. Your patients

- *Waiting list › **Waiting for dentists***: patients sent to your department, patients not sent anywhere yet, and
  anyone booked with you. Emergencies and urgent patients are first.
- *Dashboard*: who is waiting, **Your unsigned examinations** (with **Continue writing**), and today's appointments.
- *My dental examinations*: your examinations with the patient's name, complaint and diagnoses. It opens on those not
  signed yet; choose *Signed* or *All examinations* to see the rest.
- **Start examination** on the waiting list starts it; **Continue examination** opens one you already started.
  **Call next** calls the next patient assigned to you or to any dentist; patients assigned to another dentist
  are left for them.
- If you try to leave a page, or sign out, with typing that is not saved, the system asks first.

The page header shows the patient (name, MRN, sex, age) and an **Alerts** line: allergies, any *yes* answers from the
medical history, and when it was last reviewed. The line is red only when there is something to warn about. It stays on every tab.

## 2. The examination, tab by tab

| Tab | What you do |
| --- | --- |
| **History** | Go through the medical history questions with the patient (heart, diabetes, bleeding, immune, pregnancy, reactions to anaesthetic, surgery…), tick *Allergies checked* and *Current medicines checked*, and **Record review**. The system records who reviewed and when; it does **not** decide whether treatment is safe. On the right: allergies and conditions from the patient record, and the patient's dental history (**Edit**). |
| **Examination** | Chief complaint, history, the patient's own words, pain (teeth, severity 0–10, pattern, sensitivity, onset, triggers), extraoral and intraoral findings, assessment, proposed treatment, discussion, consent notes, follow-up instructions. **Mark the rest normal** writes *Normal* in every extraoral or intraoral field you left empty; change any that are not. **Save** (the tab shows • while something is unsaved; you cannot sign until it is saved). |
| **Chart** | The dental chart (see §3). |
| **Periodontal** | Six sites per tooth (see §4). Only if the clinic uses it. |
| **Diagnoses** | Search a term (for example *K02*, *caries*, *pulpitis*) and click it in the list. The button then names it (**Add K04.0 Pulpitis**), so you can see what will be added. Choose where (tooth, surfaces, region, whole mouth), certainty, notes. |
| **Treatment plan** | Plans and estimates (see §5). |
| **Procedures** | Procedure records for this visit (see §6). |
| **Prescriptions** | Medicines from the catalogue: dose, frequency, days, quantity, instructions. If the clinic has no pharmacy the prescription is printed for an outside pharmacy. The system never suggests doses. |
| **Images** | Radiographs and photographs (see §7). |
| **Sign** | The checklist (complaint, a diagnosis or an assessment, history reviewed), unsigned procedure records, and **Sign**. Below it: **Follow-up / recall**, the kind of review and its due date, then **Add to recall list**. |

Signing does not close the visit: the cashier and reception still finish it. After signing, a correction is made
with **Amend** on the summary: choose the field, write the corrected text and the reason. The original stays
visible. Only the dentist who signed a record can amend it; if that dentist no longer works at the clinic (their
account is switched off), another dentist can.

When you sign a procedure record, the panel shows what the patient will be charged (the catalogue price) and the
estimate the patient accepted. If the procedure has no price, or the price is not the accepted estimate, you must
tick the confirmation before **Sign** works: the price cannot be changed after signing. While a procedure record
for a plan item is unsigned, the patient's decision on that item cannot be changed to declined or deferred; sign
or discard the record first.

If two people change the same record, the second save is refused with *changed elsewhere*. Reload and make the
change again; nothing is overwritten.

## 3. The dental chart

- Upper teeth on top; the patient's right is on your left (FDI: 18…11 | 21…28 above 48…41 | 31…38).
  **Permanent / Primary / Mixed** switches the teeth shown; children open in *Mixed*.
- Each tooth shows its number, a five-part diagram (M, D, O or I, B, L) and the symbols of its findings.
  A **filled** surface is a current condition (e.g. caries), a **hatched** surface is existing work (e.g. a
  restoration), a **cross** is a missing or extracted tooth. The legend under the chart explains every symbol.
- Click a tooth: its current findings and history appear on the right. To record: **Whole tooth** or
  **Surfaces** (choose the surfaces), the finding, an optional diagnosis link and note, **Record finding**.
- **Whole mouth and regions** records findings that are not about one tooth.
- Nothing is overwritten. When a finding no longer applies (restored, extracted) use **No longer present** with a
  note; a mistake is **Entered in error** with a reason. Both stay in the tooth's history.
- **Now** / *As at examination of…* shows the chart as it was at an earlier examination (read only).
  **Compare with an earlier examination** lists what was added and what is no longer present.
- **Print** prints the chart with the legend; it stays readable in black and white.

## 4. Periodontal chart

For each tooth: missing, mobility, furcation (molars, and upper first premolars), and for each of the six sites
(MB, B, DB, ML, L, DL) the probing depth and gingival margin in whole millimetres, **B** bleeding and **P** plaque.
Leave a site blank if not measured. Teeth recorded as missing on the dental chart start ticked as missing; check
them. **Save**. The summary (bleeding %, sites ≥ 4 mm and ≥ 6 mm) and CAL (= probing depth + gingival margin) are
calculated from what you entered; your values are never changed. **Compare** shows the change against an earlier
chart.

## 5. Treatment plans

1. **New treatment plan**: title, clinical reason, the diagnoses it treats.
2. **Add to plan**: procedure (with the catalogue price), tooth or surfaces or region, estimate, priority,
   diagnosis. Repeat for each item.
3. **Print estimate** gives the patient a copy. It says clearly that it is an estimate, not an invoice.
4. **Present to patient**, then **Record decision**: each item accepted, declined or deferred. This records the
   discussion; it is not a signed consent form.
5. After presentation, every change needs a reason and is kept under **Revisions**.

A deferred item keeps the plan *In progress* so it can be accepted later; decline or cancel it to finish the plan.
Booking an appointment for an item (**Book appointment**) never marks it done; only a signed procedure record does.

## 6. Procedure records

**Record a procedure**: *From the treatment plan* (choose the item) or *Not planned* (emergency, examination,
radiograph; choose the procedure and the tooth). Then fill in findings before, procedure notes, anaesthesia as
given, findings after, complications, post-procedure instructions and follow-up, and the materials used (search the
stock list; instruments are never consumed). **Save**.

Sign with one of: **Procedure completed**, **This session done, more needed** (root canal, crown preparation…)
or **Not performed** (reason required; never billed). Only the person who performed it can sign. Stock is taken
from the earliest-expiring batch when you sign, and the cashier sees the charge on the visit, once.

## 7. Images

**Upload**: choose the file (JPEG, PNG or TIFF), the kind (periapical, bitewing, panoramic, photograph…), the teeth
or region and the capture time. Click an image to view it (zoom, download the original). Every view is recorded in
the audit log. A wrong image is **withdrawn** with a reason, never deleted. DICOM files are not supported.

## 8. Recalls and the dental laboratory

- *Recalls*: reviews and recalls that are due, overdue or booked. Book an appointment from a recall, log contact
  attempts, postpone, or mark declined or unreachable.
- *Dental laboratory*: send crowns, bridges and dentures to the laboratory (**New laboratory case** on the dental
  record), follow their status and record delivery.

## 9. Orthodontics

**Assessment.** In the examination, open the **Orthodontics** tab: molar and canine relationship on each side,
incisor relationship, overjet and overbite in millimetres (negative for a reverse overjet or an open bite),
crowding and spacing per arch, midlines, crossbite, skeletal pattern, profile, habits, problem list, objectives
and options discussed. **Save assessment**. It locks when you sign the examination.

**Start a case.** **Start orthodontic case**: appliance, arches, expected length, objectives (taken from the
assessment), and how the treatment is charged:

- **Package, paid in instalments**: package price, deposit, number of instalments and how often. The preview shows
  the schedule. The cashier collects each instalment when it is due; **Take payment today** lets a patient pay one
  early. Visits are not charged.
- **Charged per visit**: the price per visit. Each visit is charged unless you untick it and say why. Charge the
  fitting, removal, records and retainers as procedures from the catalogue.

**Each visit.** **Record orthodontic visit**: what was done (braces fitted, adjustment, aligner change, emergency,
braces removed, retainer fitted, retention review…), upper and lower archwire, elastics, aligner number,
breakages, hygiene, wear and cooperation, notes, an extra charge with its reason (e.g. a lost retainer), and
**Next visit in (weeks)**, which puts the patient on the recall list. Fitting the braces starts the treatment;
removing them or fitting the retainer moves the case to retention.

**Later.** **Change price or payment** (with a reason) keeps what is already invoiced and replaces the rest of the
schedule. **Complete case** at the end; **Discontinue…** with a reason cancels instalments not yet invoiced.
The case page also compares progress photos from two dates (upload them on the **Images** tab).
*Orthodontics* in the menu lists all patients in treatment or retention, with their last visit.
