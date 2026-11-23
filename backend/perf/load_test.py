"""
Concurrent load test against a running MRS instance with synthetic data only. Standard library only.

    python perf/load_test.py --base http://localhost:8000 --users 30 --seconds 60 --think 2

Each virtual user signs in with a demo account (`seed_demo --with-staff`) and works like that role:
reception searches, registers patients and adds walk-ins; nurses record vital signs for waiting
patients; doctors open charts and their consultations; the laboratory, pharmacy and cashier open their
worklists; the manager runs reports. `--think` is the pause between actions (real staff: several
seconds; 0 = stress test). Prints latency percentiles per action, saves per second and errors.
For realistic table sizes first run `seed_demo --patients 20000` and `perf/seed_history.py`.
"""

import argparse
import http.cookiejar
import json
import random
import statistics
import string
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict

NAMES = ["almaz", "kebede", "hirut", "dawit", "meron", "tesfaye", "selam", "bekele", "chaltu", "gemechu"]
PASSWORD = "Demo-Clinic-2026"
# How many virtual users of each role per 10 (roughly a medium clinic's staff mix).
ROLE_MIX = ["reception", "reception", "nurse", "nurse", "doctor", "doctor", "doctor", "lab", "pharmacy", "cashier",
            "manager"]


class Client:
    def __init__(self, base: str, username: str, computer: str):
        self.base = base
        # Each virtual user works at its own computer. Without nginx in front (testing the API directly),
        # send the address nginx would add; through nginx this header is overwritten anyway.
        self.computer = computer
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.opener.open(urllib.request.Request(f"{base}/api/v1/auth/csrf/", headers={"X-Real-IP": computer}),
                         timeout=30).read()
        status, _ = self.call("POST", "/api/v1/auth/login/", {"username": username, "password": PASSWORD})
        if status != 200:
            raise RuntimeError(f"sign-in failed for {username}: {status}")

    def call(self, method: str, path: str, body=None):
        token = next((c.value for c in self.jar if c.name == "mrs_csrftoken"), "")
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "X-CSRFToken": token,
                                              "Referer": self.base + "/", "X-Real-IP": self.computer})
        try:
            with self.opener.open(req, timeout=30) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            exc.read()
            return exc.code, {}


def actions_for(role: str, c: Client, rng: random.Random):
    """Actions this role does, each returning (name, method, path, body) when run."""
    def search():
        return "patient_search", "GET", f"/api/v1/patients/?q={rng.choice(NAMES)}", None

    def queue():
        return "queue_today", "GET", "/api/v1/visits/?open=true", None

    def register():
        name = "Load" + "".join(rng.choices(string.ascii_lowercase, k=7))
        return "register_patient", "POST", "/api/v1/patients/", {
            "first_name": name, "last_name": "Synthetic", "sex": rng.choice(["female", "male"]),
            "birth_date": f"19{rng.randint(50, 99)}-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}"}

    table = {
        "reception": [(search, 5), (queue, 4), (register, 1)],
        "nurse": [(queue, 6), (search, 2)],
        "doctor": [(queue, 3), (search, 2),
                   (lambda: ("my_consultations", "GET", "/api/v1/encounters/?mine=true", None), 2)],
        "lab": [(lambda: ("lab_worklist", "GET", "/api/v1/lab/orders/?status=open", None), 6), (search, 1)],
        "pharmacy": [(lambda: ("pharmacy_worklist", "GET", "/api/v1/prescriptions/?status=active,partial", None), 6),
                     (lambda: ("stock_list", "GET", "/api/v1/inventory/items/?category=medicine", None), 2)],
        "cashier": [(lambda: ("invoices", "GET", "/api/v1/billing/invoices/", None), 5), (queue, 2)],
        "manager": [(lambda: ("report_visits", "GET", "/api/v1/reports/visits/", None), 2), (queue, 2)],
    }
    weighted = [fn for fn, w in table[role] for _ in range(w)]
    return lambda: rng.choice(weighted)()


def worker(base, role, computer, deadline, think, results, errors, saves, lock):
    rng = random.Random()
    time.sleep(rng.random() * 3)  # staff do not all sign in at the same instant
    try:
        c = Client(base, role, computer)
    except Exception as exc:  # noqa: BLE001
        with lock:
            errors["sign_in"] += 1
        print("sign-in failed", role, exc)
        return
    pick = actions_for(role, c, rng)
    my_visits = []
    while time.time() < deadline:
        name, method, path, body = pick()
        start = time.perf_counter()
        status, data = c.call(method, path, body)
        elapsed = (time.perf_counter() - start) * 1000
        with lock:
            if status in (200, 201):
                results[name].append(elapsed)
                if method == "POST":
                    saves[0] += 1
            elif status != 403:  # 403: this role cannot use that screen; expected
                errors[f"{name} {status}"] += 1
        # Reception: add the new patient to the waiting list; nurse: record vital signs for a waiting visit.
        if role == "reception" and name == "register_patient" and status == 201:
            start = time.perf_counter()
            s2, visit = c.call("POST", "/api/v1/visits/", {"patient_id": data["id"]})
            with lock:
                if s2 == 201:
                    results["walk_in_check_in"].append((time.perf_counter() - start) * 1000)
                    saves[0] += 1
                else:
                    errors[f"walk_in_check_in {s2}"] += 1
        if role == "nurse" and name == "queue_today" and status == 200:
            rows = data.get("results", data) if isinstance(data, dict) else data
            waiting = [v for v in rows if v.get("status") == "waiting_triage" and v["id"] not in my_visits]
            if waiting:
                v = rng.choice(waiting)
                my_visits.append(v["id"])
                start = time.perf_counter()
                s3, _ = c.call("POST", f"/api/v1/visits/{v['id']}/vitals/", {
                    "systolic": rng.randint(100, 140), "diastolic": rng.randint(60, 90), "heart_rate": rng.randint(60, 100),
                    "temperature_c": "36.8", "spo2": 98, "chief_complaint": "Synthetic load test"})
                with lock:
                    if s3 == 201:
                        results["record_vitals"].append((time.perf_counter() - start) * 1000)
                        saves[0] += 1
                    elif s3 not in (409,):  # 409: another nurse took this patient first
                        errors[f"record_vitals {s3}"] += 1
        if think:
            time.sleep(rng.uniform(think * 0.5, think * 1.5))


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--users", type=int, default=30)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--think", type=float, default=0, help="seconds between a user's actions (0 = stress)")
    args = parser.parse_args()
    results, errors, saves, lock = defaultdict(list), defaultdict(int), [0], threading.Lock()
    deadline = time.time() + args.seconds + 3
    threads = [threading.Thread(target=worker, args=(args.base, ROLE_MIX[i % len(ROLE_MIX)], f"192.168.1.{100 + i}", deadline, args.think,
                                                      results, errors, saves, lock)) for i in range(args.users)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = sum(len(v) for v in results.values())
    print(f"{args.users} users, think {args.think}s, {args.seconds}s: {total} requests "
          f"({total / args.seconds:.1f}/s), {saves[0]} saves")
    print(f"{'action':22} {'n':>6} {'p50 ms':>8} {'p95 ms':>8} {'max ms':>8}")
    for name, values in sorted(results.items()):
        print(f"{name:22} {len(values):6} {statistics.median(values):8.0f} {pct(values, 0.95):8.0f} {max(values):8.0f}")
    print("errors:", dict(errors) or 0)


if __name__ == "__main__":
    main()
