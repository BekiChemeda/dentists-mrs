# Browser end-to-end scenarios

Each test follows one synthetic patient through the clinic, signing in as a different demo staff
member for each step, the way the clinic works:

| Test | What it covers |
| --- | --- |
| `test_outpatient_visit_through_every_role` | Registration, triage (sent to OPD 1), evaluation note with ICD-10 diagnosis, sign, investigations, prescription, laboratory, pharmacy, payment, visit completion, timeline |
| `test_laboratory_only_visit` | Tests requested by an outside clinician: no triage or consultation, printed result report, no consultation fee |
| `test_patient_leaves_before_seeing_the_doctor` | Removing a waiting patient with a reason |
| `test_refund_needs_a_second_person` | Cashier asks for a refund, the manager approves, the cashier pays it out |
| `test_merge_duplicate_records` | Merging a duplicate registration; the retired record points to the kept one |

The tests above need triage, laboratory and pharmacy switched on (a medical installation). The dental scenarios in
`test_dental.py` need a dental installation (`manage.py apply_dental_defaults`): run the two groups against separate
demo databases.

| Dental test (`test_dental.py`) | What it covers |
| --- | --- |
| `test_toothache_to_filling_invoice_and_follow_up` | History review, complaint (unsaved text kept across tabs, signing blocked until saved), chart findings on teeth and surfaces, periodontal chart starting from the chart's missing teeth, diagnosis, plan with one item deferred, procedure record (notes kept through a materials save), signing, recall, invoice paid once, visit completion, a return visit and the chart comparison |
| `test_receptionist_cannot_open_the_dental_chart` | No dental record link for reception, and the API refuses the chart |
| `test_assistant_cannot_sign_an_examination` | No Sign button for the dental assistant, and the API refuses it |

See [docs/dental/testing.md](../docs/dental/testing.md) for how they map to the specification's scenarios.

## Running

1. Start the stack and load the demo staff (development only, never on a server with real data):
   `python manage.py seed_demo` (the demo accounts share the password in `E2E_PASSWORD`).
2. Install the browser driver once: `pip install pytest playwright && playwright install chromium`.
3. Run: `E2E_BASE_URL=http://localhost:4173 pytest e2e -q`

The scenarios sign in about 25 times a minute from one computer, more than the production limit of
20 per computer per minute. Start the test server with `LOGIN_THROTTLE_RATE=300/min` (test servers only).
The run tops up demo medicine stock through the store account when it runs low.

Optional: `E2E_CHROME=/usr/bin/google-chrome` to use an installed Chrome. Each run creates new synthetic
patients (names carry the time of day), so it can run repeatedly against the same demo database.
