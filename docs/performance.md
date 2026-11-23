# Performance test

Run on 2026-11-22 in a 2-CPU, 7 GB development container. That is smaller than the recommended clinic
server (4+ cores, SSD), and the load generator ran on the same 2 CPUs, so real servers should do better.
PostgreSQL 16, Gunicorn with 3 workers (the production default), API called directly.

## Data

A synthetic clinic with a year of history:

- 20,000 patients (`manage.py seed_demo --patients 20000 --with-staff --with-stock`)
- 1,674 complete visits spread over the past 12 months, each with vital signs, a signed consultation
  note and diagnosis, about a third with laboratory tests entered and verified
  (`perf/seed_history.py`, which uses the same API paths staff use)
- about 21,000 audit log entries

## Workload

`perf/load_test.py` simulates staff by role, in a medium clinic's mix (reception, nurses, doctors,
laboratory, pharmacy, cashier, manager), each at their own computer. Reception searches, registers
patients and adds them to the waiting list; nurses record vital signs for waiting patients; doctors
open the waiting list and their consultations; the departments open their worklists; the manager runs
a report.

## Results

**Normal day: 40 staff, about 3 seconds between actions** (`--users 40 --think 3 --seconds 90`)

| Action | n | p50 ms | p95 ms |
| --- | --- | --- | --- |
| Patient search (20,000 patients) | 307 | 96 | 177 |
| Today's waiting list | 449 | 39 | 106 |
| Register patient | 22 | 78 | 133 |
| Add walk-in to waiting list | 22 | 37 | 66 |
| Record vital signs | 23 | 44 | 878 |
| Doctor's consultations | 95 | 32 | 69 |
| Laboratory worklist | 78 | 22 | 560 |
| Pharmacy worklist | 65 | 23 | 136 |
| Invoices | 57 | 22 | 84 |

12.7 requests/second, 67 saves, 0 errors. The longest single waits (1.5–2 s) happened in the first
seconds, while all 40 accounts signed in at once.

**Stress: 60 users clicking with no pause at all** (`--users 60 --think 0`): 38 requests/second,
288 saves in 60 seconds, 0 errors; median response 1.3 s, 95th percentile 1.8 s. This is about
three times the load of 40 real staff, on a 2-CPU machine shared with the load generator. Response
times grow but nothing fails or is lost.

The server's limit on this machine is CPU. Most screens run a fixed 14–18 database queries regardless
of data size (no per-row queries), so growth in patients and visits does not slow them down much.

## Found and fixed by this test

All requests reach the API through nginx, so the API saw every computer as nginx's own address. The
sign-in limit (20 per minute) was therefore shared by the whole clinic: at the start of a shift, staff
were refused with "too many requests". Limits are now counted per computer, using the address nginx
passes on (`apps/core/throttling.py`, tested in `test_throttle_by_computer.py`).

## Re-running on the clinic's server

Use a copy of the installation with synthetic data only, never the live database:

```bash
POSTGRES_DB=mrs_perf python manage.py migrate
POSTGRES_DB=mrs_perf python manage.py seed_demo --patients 20000 --with-staff --with-stock --i-understand-this-is-not-production
POSTGRES_DB=mrs_perf USER_THROTTLE_RATE=100000/min python perf/seed_history.py --visits 3000
python perf/load_test.py --base http://<server> --users 40 --think 3 --seconds 90
```

Record the results here with the server's CPU, memory and disk.
