# Security checks

Automated checks run on 2026-11-22 against the code in this repository. They catch known vulnerable
packages and common coding mistakes. They are **not** a penetration test or an independent security
review; get one before the system holds a clinic's real records.

## Results

| Check | Tool | Result | Action taken |
| --- | --- | --- | --- |
| Python dependencies with known vulnerabilities | pip-audit | Pillow 12.3 had 42 published vulnerabilities (image parsing) | Upgraded to Pillow 13; now none found |
| Frontend runtime dependencies | npm audit (production) | None | — |
| Frontend build and test tools | npm audit (all) | Vitest 3 and its worker pool: 2 critical, 1 moderate. Test tooling only, not shipped to clinics | Upgraded to Vitest 5; now none found |
| Python code patterns | bandit | 7 low-severity notes, no medium or high | Reviewed, all acceptable: the demo password and development-only key are refused in production, one `except: pass` closes a mail connection, the rest are false positives |
| Django deployment settings | `manage.py check --deploy` | 3 notes | Acceptable: nginx redirects HTTP to HTTPS (so `SECURE_SSL_REDIRECT` stays off), and HSTS subdomain/preload options do not apply to clinic LAN host names |
| Request limits across server processes | review | Sign-in and request limits were kept per Gunicorn worker in memory, so 3 workers allowed 3× the limit and a restart reset it | Moved to a cache shared through PostgreSQL (migration core 0012). Account lockout after wrong passwords was already stored in the database and was not affected |
| Database outage handling | `deploy/scripts/test-resilience.py` | Errors outside views came back as Django's HTML error page | API now answers `503 database_unavailable` in JSON; screens show a clear message |

## In continuous integration

Every push runs pip-audit, npm audit (runtime at moderate, all packages at high), bandit (medium and
above), shellcheck, a secrets scan and a container image scan. See `.github/workflows/ci.yml`.

## Already in the design

Server-side permission checks on every endpoint (tested route by route), Argon2id password hashing,
lockout after wrong passwords, two-step sign-in, session limits, HttpOnly and SameSite cookies, CSRF
protection, a strict Content-Security-Policy, an append-only hash-chained audit log, encrypted off-site
backups, containers without root privileges or write access to their own code.

## Not yet done

- Penetration test by an independent tester.
- Review against Ethiopian health-data and records-retention requirements.
- Security review of a real clinic installation (network, Wi-Fi, who holds the server passwords).
