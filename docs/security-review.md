# Security review

First review: 2026-11-20 (Phase 5). Updated 2026-11-24 after the dental modules were added; see
[Dental modules](#dental-modules-2026-11-24) below.

Date of first review: 2026-11-20. Method: design and code review against OWASP ASVS 4.0 level 2 areas most relevant to this system, plus automated tests. This is an internal review by the development team, **not** an independent penetration test; commission one before selling to clinics.

| Area | Status | Evidence |
| --- | --- | --- |
| Authentication | Implemented | Argon2id; lockout after 5 failures; generic errors; login CSRF enforced; throttled per IP (tests in `apps/accounts/tests`) |
| Session management | Implemented | Server-side sessions, HttpOnly/SameSite/Secure cookies, 30-min idle and 12-h absolute limits, revocation on deactivation and password change |
| Access control | Implemented | Every endpoint declares permissions, missing methods are refused; denied access is audited; tests per role. Unverified lab results hidden from clinicians server-side |
| Input validation | Implemented | Serializer validation on every write; database CHECK constraints for vitals ranges, money and quantities |
| Injection | Implemented | ORM only; one raw SQL statement (counter UPSERT) uses bound parameters |
| XSS / clickjacking | Implemented | React escaping, strict CSP (no inline script), `X-Frame-Options: DENY` |
| Sensitive data exposure | Implemented | `Cache-Control: no-store` on API; secrets only in `.env`; audit refuses password fields; record views audited |
| Audit and integrity | Implemented | Append-only audit table enforced by trigger; signed notes, results, dispensing and payments never edited or deleted |
| Two-person rule | Implemented | Discounts, voids and stock overrides need a second approver (DB constraint prevents self-approval) |
| Data protection by design | Partly | Local hosting, least privilege and minimal fields done; consent capture, retention and patient access requests await legal advice |
| MFA for administrators | Implemented | TOTP with recovery codes; required for administrator roles by default (`MFA_DEFAULT_POLICY=admins`), can be required for everyone; secret stored encrypted |
| Encryption at rest | Installation step | Full-disk encryption (LUKS) is the first item of `operations/security-checklist.md`; off-site and external-drive backups, including dental images, are encrypted |
| Dependency scanning | Implemented | pip-audit, npm audit, bandit, secrets scan and image scan run in CI (`security-checks.md`) |
| Penetration test | **Not done** | Required before commercial release |

## Residual risks the clinic must manage

- Anyone with physical access to the server can copy the disk unless it is encrypted.
- The clinic CA key (`deploy/certs/clinic-ca.key`) can impersonate the server; keep it offline.
- Shared or written-down passwords defeat individual accountability; the audit log only proves which *account* acted.

## Dental modules (2026-11-24)

Checked after the dental workspace, imaging, laboratory, recalls and orthodontics were added.

| Check | Result |
| --- | --- |
| Every API route refuses anonymous requests and writes without a CSRF token | Pass (route walk in `apps/core/tests/test_attack_surface.py`; dental routes included automatically) |
| A signed-in account with no role reaches only its own account and clinic reference data, never patient records | Pass (new test in the same file) |
| Role separation on a real patient, demo data | Reception and cashier: demographics only, no dental notes, chart, plans or images. Dental technician: only laboratory cases assigned to them, with name and MRN. Imaging staff: images, no notes. Store: no patient data |
| Dental image files | Served only through a permission check, every view audited, `nosniff`, sandboxed CSP, `no-store`; file names cleaned on upload; type, size and pixel limits; DICOM refused |
| pip-audit, npm audit (runtime and all), bandit on `apps/dental` (medium and above) | No findings |
| `manage.py check --deploy` | The same 3 notes as before, accepted (HTTPS redirect is done by nginx; HSTS subdomain/preload do not apply to clinic LAN names) |

Business controls to note (not software defects):

- Dentists with the orthodontics permission set package prices, per-visit charges and extra charges for their
  own cases. Each change is audited and needs a reason once anything is invoiced, but there is no second
  approver. If the clinic wants one, discounts and voids already have a two-person rule that could be extended.
- Any clinician with `dental.view` can open any patient's dental record, as is usual in a small clinic. Every
  view is recorded in the audit log; the clinic should review it.
