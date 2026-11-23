#!/usr/bin/env python3
"""
Resilience test: what happens to patient records when the application or the database dies mid-work.

Run it against a TEST installation with synthetic data only, never a clinic's live server:
it registers synthetic patients and kills services with SIGKILL, like a power cut would.

    MRS_URL=http://localhost  MRS_USER=reception  MRS_PASSWORD=...  python3 test-resilience.py

How services are killed and started is configurable (defaults suit the Docker Compose install):
    APP_KILL   docker compose kill -s KILL api        APP_START  docker compose start api
    DB_KILL    docker compose kill -s KILL db         DB_START   docker compose start db

What it checks
  1. Application crash while staff are saving: every patient the server confirmed (HTTP 201) is in the
     database afterwards, complete, with a unique MRN. Nothing confirmed is lost.
  2. Database crash while staff are saving: during the outage the API answers quickly with a clear
     "database not responding" message (HTTP 503, JSON), never a hang or an HTML error page. When the
     database is back, the application recovers on its own, without being restarted.
  3. After both crashes, PostgreSQL's own consistency and the audit trail's hash chain are intact.
Exit code 0 means every check passed.
"""
from __future__ import annotations

import json
import os
import random
import shlex
import string
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

URL = os.environ.get("MRS_URL", "http://localhost").rstrip("/")
API = f"{URL}/api/v1"
USER = os.environ.get("MRS_USER", "reception")
PASSWORD = os.environ.get("MRS_PASSWORD")
APP_KILL = os.environ.get("APP_KILL", "docker compose kill -s KILL api")
APP_START = os.environ.get("APP_START", "docker compose start api")
DB_KILL = os.environ.get("DB_KILL", "docker compose kill -s KILL db")
DB_START = os.environ.get("DB_START", "docker compose start db")
# Runs a SQL statement and prints the result; used for the final consistency checks.
SQL = os.environ.get("SQL", "docker compose exec -T db psql -U mrs -d mrs -At -c")
AUDIT_CHECK = os.environ.get("AUDIT_CHECK", "docker compose exec -T api python manage.py verify_audit_chain")
WRITERS = int(os.environ.get("WRITERS", "4"))
# Seconds each writer waits between saves; keeps one account under the per-user request limit.
PACE = float(os.environ.get("PACE", "0.5"))

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(("  PASS  " if ok else "  FAIL  ") + message)
    if not ok:
        failures.append(message)


def run(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True).stdout.strip()


class Client:
    """A signed-in browser-like session: cookies plus the CSRF header on writes."""

    def __init__(self) -> None:
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _csrf(self) -> str:
        return next((c.value for c in self.jar if c.name.endswith("csrftoken")), "")

    def call(self, method: str, path: str, body: dict | None = None, timeout: float = 15) -> tuple[int, dict, str]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{API}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json", "X-CSRFToken": self._csrf(),
                                              "Referer": URL + "/"})
        try:
            with self.opener.open(req, timeout=timeout) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw else {}), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = {"raw": raw[:200]}
            return e.code, parsed, e.headers.get("Content-Type", "")

    def sign_in(self) -> None:
        self.call("GET", "/auth/csrf/")
        status, body, _ = self.call("POST", "/auth/login/", {"username": USER, "password": PASSWORD})
        if status != 200 or "mfa_required" in body:
            sys.exit(f"Could not sign in as {USER} (status {status}). Use an account without two-step sign-in.")
        self.call("GET", "/auth/csrf/")


def synthetic_name() -> str:
    return "Resil" + "".join(random.choices(string.ascii_lowercase, k=8))


class Writers:
    """Several receptionists registering synthetic patients as fast as they can."""

    def __init__(self) -> None:
        self.confirmed: dict[str, str] = {}  # patient id -> MRN, only for HTTP 201 answers
        self.outcomes: dict[str, int] = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.threads = [threading.Thread(target=self._loop, daemon=True) for _ in range(WRITERS)]

    def _loop(self) -> None:
        client = Client()
        signed_in = False
        time.sleep(random.random() * 2)  # do not all sign in in the same instant
        while not self.stop.is_set():
            try:
                if not signed_in:
                    client.sign_in()
                    signed_in = True
                status, body, _ = client.call("POST", "/patients/", {
                    "first_name": synthetic_name(), "last_name": "Synthetic", "sex": random.choice(["female", "male"]),
                    "birth_date": f"19{random.randint(50, 99)}-0{random.randint(1, 9)}-1{random.randint(0, 9)}",
                    "city": "Adama"}, timeout=10)
                key = str(status)
                time.sleep(PACE)
                if status == 201:
                    with self.lock:
                        self.confirmed[body["id"]] = body["mrn"]
                elif status == 401:
                    signed_in = False  # session lost with the server; sign in again
            except SystemExit:
                key = "sign-in failed"
                time.sleep(0.5)
            except Exception as e:  # connection refused/reset while a service is down
                key = type(e).__name__
                time.sleep(0.2)
            with self.lock:
                self.outcomes[key] = self.outcomes.get(key, 0) + 1

    def __enter__(self):
        for t in self.threads:
            t.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        for t in self.threads:
            t.join(timeout=20)


def wait_healthy(seconds: int) -> float | None:
    start = time.time()
    while time.time() - start < seconds:
        try:
            with urllib.request.urlopen(f"{API}/health/", timeout=3) as r:
                if r.status == 200:
                    return time.time() - start
        except Exception:
            pass
        time.sleep(0.5)
    return None


def confirmed_records_present(writers: Writers, label: str) -> None:
    ids = list(writers.confirmed)
    if not ids:
        check(False, f"{label}: no patient was saved at all during the test")
        return
    quoted = ",".join(f"'{i}'" for i in ids)
    found = int(run(f"{SQL} {shlex.quote(f'SELECT count(*) FROM patients_patient WHERE id IN ({quoted})')}"))
    check(found == len(ids), f"{label}: all {len(ids)} confirmed patients are in the database (found {found})")
    mrns = run(f"{SQL} {shlex.quote(f'SELECT mrn FROM patients_patient WHERE id IN ({quoted})')}").split()
    check(sorted(mrns) == sorted(writers.confirmed.values()), f"{label}: each has the MRN the server confirmed")


def main() -> None:
    if not PASSWORD:
        sys.exit("Set MRS_PASSWORD (test installation, synthetic data only).")
    print(f"Resilience test against {URL} as {USER}, {WRITERS} writers\n")
    if wait_healthy(10) is None:
        sys.exit("The server is not healthy before the test; fix that first.")

    print("1. Application killed (SIGKILL) while patients are being saved")
    with Writers() as w:
        time.sleep(4)
        run(APP_KILL)
        killed_at = time.time()
        time.sleep(2)
        run(APP_START)
        took = wait_healthy(90)
        check(took is not None, f"application answers again after restart ({(time.time() - killed_at):.1f} s after the kill)")
        time.sleep(4)
    print(f"     outcomes: {w.outcomes}")
    check(w.outcomes.get("201", 0) > 0, "patients were being saved before and after the crash")
    confirmed_records_present(w, "after application crash")

    print("\n2. Database killed (SIGKILL) while patients are being saved; application left running")
    probe = Client()
    probe.sign_in()
    with Writers() as w2:
        time.sleep(4)
        run(DB_KILL)
        time.sleep(1.5)
        t0 = time.time()
        status, body, ctype = probe.call("GET", "/patients/?search=Resil", timeout=20)
        elapsed = time.time() - t0
        check(status == 503, f"reads during the outage answer 503 (got {status})")
        check("json" in ctype, f"the answer is JSON the screens can show (got {ctype or 'no content type'})")
        check(body.get("error", {}).get("code") == "database_unavailable", "the error code is database_unavailable")
        check(elapsed < 10, f"the answer comes quickly, no hang ({elapsed:.1f} s)")
        status, body, ctype = probe.call("POST", "/patients/", {"first_name": synthetic_name(), "last_name": "Synthetic",
                                                                 "sex": "female", "birth_date": "1990-01-01"})
        check(status == 503 and "json" in ctype, f"saves during the outage answer 503 JSON (got {status})")
        try:
            with urllib.request.urlopen(f"{API}/health/", timeout=10) as r:
                health = r.status
        except urllib.error.HTTPError as e:
            health = e.code
        check(health == 503, f"the health check reports the database down (got {health})")
        time.sleep(3)
        run(DB_START)
        took = wait_healthy(120)
        check(took is not None, "the application recovers on its own when the database is back (no restart)")
        status, _, _ = probe.call("GET", "/patients/?search=Resil")
        check(status == 200, f"a session signed in before the outage still works afterwards (got {status})")
        time.sleep(4)
    print(f"     outcomes: {w2.outcomes}")
    confirmed_records_present(w2, "after database crash")

    print("\n3. Consistency after both crashes")
    dup = run(f"{SQL} {shlex.quote('SELECT count(*) FROM (SELECT mrn FROM patients_patient GROUP BY mrn HAVING count(*) > 1) d')}")
    check(dup == "0", "no duplicate MRNs")
    no_mrn = "SELECT count(*) FROM patients_patient WHERE coalesce(mrn, '') = ''"
    blank = run(f"{SQL} {shlex.quote(no_mrn)}")
    check(blank == "0", "no patient without an MRN")
    try:
        out = run(AUDIT_CHECK)
        check(True, f"audit trail hash chain intact ({out.splitlines()[-1] if out else 'ok'})")
    except subprocess.CalledProcessError as e:
        check(False, f"audit trail hash chain check failed: {(e.stdout or e.stderr).strip()[-200:]}")

    print(f"\n{'All checks passed.' if not failures else f'{len(failures)} check(s) failed.'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
