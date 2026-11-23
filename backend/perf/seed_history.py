"""
Fill a TEST database with a year of synthetic clinic activity, so the load test runs against realistic table
sizes instead of an empty clinic. Never run it on a clinic's live database.

    POSTGRES_DB=mrs_perf USER_THROTTLE_RATE=100000/min python perf/seed_history.py --visits 3000

Prerequisite on the same database: `manage.py migrate` and
`manage.py seed_demo --patients 20000 --with-staff --with-stock --i-understand-this-is-not-production`.

Each visit goes through the real API in-process (the same code paths staff use): walk-in check-in, vital
signs, consultation note, diagnosis, laboratory request for about a third of visits with results entered
and verified, signing, and closing the visit. Afterwards the visits are spread over the past year, so
date-filtered screens and reports see a realistic distribution.
"""
import argparse
import datetime
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

PASSWORD = "Demo-Clinic-2026"
COMPLAINTS = ["Fever and headache", "Cough for a week", "Abdominal pain", "Back pain", "Burning urination",
              "Diarrhoea", "Follow-up of hypertension", "Joint pain", "Skin rash", "Dizziness"]
DIAGNOSES = ["B54", "J06.9", "A09", "N39.0", "I10", "M54.5", "K29.7", "L30.9", "R51", "E11.9"]


def client(username: str) -> APIClient:
    c = APIClient(SERVER_NAME="localhost")
    r = c.post("/api/v1/auth/login/", {"username": username, "password": PASSWORD}, format="json")
    if r.status_code != 200:
        sys.exit(f"Cannot sign in as {username}: {r.status_code} {r.content[:200]!r}")
    return c


def ok(response, *codes):
    if response.status_code not in (codes or (200, 201)):
        raise RuntimeError(f"{response.status_code}: {response.content[:300]!r}")
    return response.json() if response.content else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--visits", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    if "perf" not in settings.DATABASES["default"]["NAME"] and "test" not in settings.DATABASES["default"]["NAME"]:
        sys.exit("Refusing to run: the database name must contain 'perf' or 'test' (synthetic data only).")
    rng = random.Random(args.seed)

    from apps.laboratory.models import LabTest
    from apps.patients.models import Patient
    from apps.scheduling.models import Visit

    rc, nurse, dr, lab = client("reception"), client("nurse"), client("doctor"), client("lab")
    patient_ids = list(Patient.objects.values_list("id", flat=True))
    tests = {t.code: str(t.pk) for t in LabTest.objects.filter(code__in=["BF", "HGB", "WBC", "GLU", "UA"])}
    lab_values = {"BF": "Negative", "HGB": "13.1", "WBC": "7.2", "GLU": "96", "UA": "Normal"}
    started, created = time.time(), []
    for n in range(args.visits):
        patient_id = str(rng.choice(patient_ids))
        try:
            visit = ok(rc.post("/api/v1/visits/", {"patient_id": patient_id}, format="json"), 201)
        except RuntimeError:
            continue  # this patient already has an open visit today; pick another next time
        vid = visit["id"]
        ok(nurse.post(f"/api/v1/visits/{vid}/vitals/", {
            "systolic": rng.randint(100, 150), "diastolic": rng.randint(60, 95), "temperature_c": f"{rng.uniform(36.2, 39.0):.1f}",
            "heart_rate": rng.randint(60, 110), "respiratory_rate": rng.randint(12, 22), "spo2": rng.randint(94, 99),
            "weight_kg": str(rng.randint(45, 90)), "chief_complaint": rng.choice(COMPLAINTS)}, format="json"), 201)
        enc = ok(dr.post(f"/api/v1/visits/{vid}/encounters/"), 201)
        enc = ok(dr.patch(f"/api/v1/encounters/{enc['id']}/", {
            "version": enc["version"], "chief_complaint": rng.choice(COMPLAINTS),
            "history_present_illness": "Synthetic history for performance testing.",
            "physical_examination": "Synthetic examination findings.", "plan": "Synthetic plan."}, format="json"))
        ok(dr.post(f"/api/v1/encounters/{enc['id']}/diagnoses/", {"icd_code": rng.choice(DIAGNOSES),
                                                                    "certainty": "confirmed"}, format="json"), 201)
        if tests and rng.random() < 0.35:
            chosen = rng.sample(sorted(tests), k=min(2, len(tests)))
            order = ok(dr.post(f"/api/v1/encounters/{enc['id']}/lab-orders/", {"test_ids": [tests[c] for c in chosen]},
                               format="json"), 201)
            for item in order["items"]:
                code = item["test"]["code"]
                ok(lab.post(f"/api/v1/lab/items/{item['id']}/collect/"))
                ok(lab.post(f"/api/v1/lab/items/{item['id']}/result/", {"value": lab_values.get(code, "1")}, format="json"))
                ok(lab.post(f"/api/v1/lab/items/{item['id']}/verify/"))
        ok(dr.post(f"/api/v1/encounters/{enc['id']}/sign/"))
        ok(rc.post(f"/api/v1/visits/{vid}/complete/", {"outcome": "completed", "acknowledge_outstanding": True,
                                                       "note": "Synthetic visit closed by the performance seed."},
                   format="json"))
        created.append(vid)
        if (n + 1) % 100 == 0:
            rate = (n + 1) / (time.time() - started)
            print(f"{n + 1} visits ({rate:.1f}/s)", flush=True)

    # Spread every visit in this test database over the past year (newest last), so date filters see a
    # realistic distribution. Covers visits from earlier, interrupted runs too (`--visits 0` only spreads).
    ids = list(Visit.objects.order_by("arrived_at").values_list("id", flat=True))
    now = timezone.now()
    for i, vid in enumerate(ids):
        when = now - datetime.timedelta(days=365 * (len(ids) - i) / max(len(ids), 1), hours=rng.randint(0, 8))
        Visit.objects.filter(pk=vid).update(visit_date=timezone.localdate(when), arrived_at=when,
                                            completed_at=when + datetime.timedelta(hours=2))
    print(f"Done: {len(created)} visits in {time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
