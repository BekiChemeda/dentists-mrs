# Security review (Phase 5)

Date: 2026-11-20. Method: design and code review against OWASP ASVS 4.0 level 2 areas most relevant to this system, plus automated tests. This is an internal review by the development team, **not** an independent penetration test; commission one before selling to clinics.

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
| MFA for administrators | **Not done** | Planned: TOTP for system and clinic administrators |
| Encryption at rest | **Not done** | Recommend full-disk encryption (LUKS) on the server and encrypted backup drives |
| Dependency scanning | **Not done** | Add `pip-audit` and `npm audit` to CI |
| Penetration test | **Not done** | Required before commercial release |

## Residual risks the clinic must manage

- Anyone with physical access to the server can copy the disk unless it is encrypted.
- The clinic CA key (`deploy/certs/clinic-ca.key`) can impersonate the server; keep it offline.
- Shared or written-down passwords defeat individual accountability; the audit log only proves which *account* acted.
