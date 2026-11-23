# Security checklist for each clinic installation

The application enforces permissions, two-step sign-in, audit logging and encryption of backups.
Some protections can only be set on the server itself. Work through this list for every clinic, and
run `deploy/scripts/security-check.sh` at the end: it checks most of these items and reports PASS,
WARN or FAIL.

## Before installing

- [ ] **Encrypt the disk.** In the Ubuntu Server installer choose *Use an entire disk* and tick
      *Set up this disk as an LVM group* and *Encrypt the LVM group with LUKS*. Without this, anyone who
      takes the server can read every record. It cannot be added later without reinstalling.
      The disk passphrase is typed at each boot; keep it with the off-site backup phrase, sealed.
- [ ] Server in a locked room or cabinet; UPS attached.
- [ ] Clinic Wi-Fi for staff is separate from guest Wi-Fi.

## Installing

- [ ] Install as in `install.md`. Create `.env` from `.env.example` with a 50+ character
      `DJANGO_SECRET_KEY` and a 20+ character `POSTGRES_PASSWORD` (e.g. `openssl rand -base64 48`).
      `DJANGO_DEBUG=false`, `MRS_HTTPS=true`.
- [ ] **Never run `seed_demo` on a clinic server.** Demo accounts share a published password.
- [ ] `sudo LAN_CIDR=<clinic network>/24 deploy/scripts/harden-server.sh`: firewall, automatic
      security updates, SSH keys only, fail2ban, time sync, owner-only permissions on secrets.
      Put your SSH key on the server first, or password SSH stays on.
- [ ] HTTPS certificate in `deploy/certs/`; staff computers trust it (see `install.md`).
- [ ] Nightly backup timer, daily jobs timer (`mrs-reminders.timer`: reminders, unused-account review,
      audit-chain check) and, if sold, the off-site backup timer.
- [ ] External USB drive: set `BACKUP_COPY_DIR`. Copies on it are encrypted automatically once the
      off-site secret phrase is set (`BACKUP_COPY_ENCRYPT=auto`).

## First sign-in

- [ ] The first administrator signs in, changes the temporary password and sets up two-step sign-in
      (required by default for administrators and the clinic director). Print the recovery codes and
      store them with the owner, not in the server room.
- [ ] System › Security: review password length, lockout, idle timeout, "two-step sign-in required for"
      and "switch off accounts unused for".
- [ ] Create one personal account per staff member. Never share accounts.

## After installing

- [ ] `sudo deploy/scripts/security-check.sh` shows no FAIL.
- [ ] Record the audit anchor printed by `verify_audit_chain` (also in `journalctl -u mrs-reminders`)
      somewhere outside the server, e.g. monthly in the clinic's paper log.
- [ ] Test a restore (local backup) and, if used, an off-site recovery with the owner present.

## Every month

- [ ] `security-check.sh`; read WARN lines.
- [ ] System › Health: no warnings; backups recent; error log quiet.
- [ ] Staff accounts: remove people who left; check who has administrator roles.
- [ ] Audit log: look at failed sign-ins and access-denied events.

## Before real patient data (one-off)

- [ ] **Independent penetration test** by a security firm. Our own checks are not a substitute.
- [ ] Legal: registration with the Ethiopian Communications Authority under the Personal Data Protection
      Proclamation No. 1321/2024, a named data protection officer, a written breach procedure (72-hour
      notification), data-processing agreements with any off-site storage provider. Have a lawyer
      confirm the current requirements.
- [ ] Staff training: personal accounts, locking screens, phishing, what to do if a phone with the
      authenticator is lost.

## If something goes wrong

| Event | Do this |
| --- | --- |
| Staff member leaves | Staff accounts › Deactivate (sessions end at once). |
| Phone with authenticator lost | Confirm who is asking, then Staff accounts › Reset 2-step; they set it up again. |
| Suspected stolen password | Reset password, reset 2-step, review the audit log for that account. |
| "Audit log tampering detected" notification | Do not change anything. Keep the server as it is, call your IT provider; follow the breach procedure. |
| Server stolen or destroyed | New server, then `offsite-backup.sh restore latest --import` with the owner's phrase. |

## Known limits

- The application's database account owns the audit table, so someone with that password and a
  database console could switch off the append-only trigger. The hash chain and the daily anchor in the
  system journal make such changes detectable, not impossible. A separate database role for migrations
  would close this further.
- The container hardening in `docker-compose.yml` (read-only API filesystem, dropped privileges) is
  checked for valid configuration in CI; confirm the stack starts on the first real install.
