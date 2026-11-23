# System administrator manual

You keep Clinic MRS running and secure: the server, accounts and roles, security rules, backups,
email, health monitoring and upgrades. You do **not** see patient records, invoices or clinical
notes, and you do not change clinic settings other than the logo. This separation is enforced by
the server.

This manual brings the operations guides together. Detailed procedures are linked where they exist:
[install](../operations/install.md), [restore](../operations/restore.md),
[upgrade](../operations/upgrade.md), [off-site backup](../operations/offsite-backup.md),
[email](../operations/email.md), [security checklist](../operations/security-checklist.md).

Your account needs two-step sign-in. Commands below are run on the server in the application folder
(normally `/opt/mrs`) with `sudo` where shown.

---

## 1. How the system is built

- One server in the clinic runs everything in Docker: `db` (PostgreSQL), `api` (the application,
  Django) and `web` (Nginx, serving the pages and HTTPS). Only ports 80 and 443 are open to the
  network; the database is not reachable from other computers.
- Staff use a web browser on any computer on the clinic network. No internet is needed for daily
  work; internet is used only for installation, updates, optional email and optional off-site backup.
- Scheduled jobs (systemd timers) run the backups, the daily reminders and checks, and the email
  sender.
- Settings and secrets are in `.env` (readable by root only). The database holds everything else,
  including the clinic logo.

See [architecture.md](../architecture.md) for more.

## 2. Installation

Use the guided installer on a fresh Ubuntu Server 24.04 (with disk encryption chosen during the
Ubuntu installation):

```bash
sudo mkdir -p /opt/mrs && sudo chown "$USER" /opt/mrs
# copy or clone the application into /opt/mrs, then:
cd /opt/mrs
sudo deploy/install.sh --check     # checks the server, changes nothing
sudo deploy/install.sh             # asks a few questions and installs
```

It checks the hardware, installs Docker if needed (internet required), writes `.env` with new random
secrets, creates the HTTPS certificate, builds and starts the application, creates the first
administrator (`admin`, one-time password shown once on screen), loads the starter catalogue,
installs the scheduled jobs, makes and checks a first backup, and applies the server security
settings. It can be run again safely: settings, secrets, certificates and data are kept. Everything
is logged to `/var/log/mrs-install.log` (passwords and secrets are never written there).

For a second clinic with the same set-up, give the answers in advance:

```bash
sudo MRS_ADDRESS=192.168.1.10 MRS_DNS_NAME=mrs.clinic.local MRS_FACILITY_CODE=ABC deploy/install.sh --yes
```

Manual steps, and what each installer step does, are in [install.md](../operations/install.md).

### After installation

1. Sign in as `admin` with the one-time password; choose a new password; set up two-step sign-in.
2. Create a named system administrator account for yourself and stop using `admin`
   (deactivate it once your own account works).
3. Create the clinic administrator's account (role *Clinic administrator*) and the director's
   (*Clinic director*). They set up the rest of the clinic (see
   [clinic-administrator.md](clinic-administrator.md#1-first-set-up-of-a-new-clinic)).
4. Run `sudo deploy/scripts/security-check.sh` and fix anything marked FAIL before real patients
   are registered.

### HTTPS certificate

The clinic acts as its own certificate authority, because public authorities cannot issue
certificates for private addresses. Install `deploy/certs/clinic-ca.crt` once on every computer
that uses the system:

- Windows: double-click › Install Certificate › Local Machine › *Trusted Root Certification Authorities*.
- Ubuntu: copy to `/usr/local/share/ca-certificates/clinic-ca.crt`, run `sudo update-ca-certificates`.
- Firefox: Settings › Privacy & Security › Certificates › Import.

Keep `deploy/certs/clinic-ca.key` on offline storage; it is needed to renew the server certificate,
which is valid for 825 days. Renew with `deploy/scripts/make-certs.sh <ip> <name>` and
`docker compose restart web` before it expires (`security-check.sh` warns 30 days ahead).

## 3. Accounts, roles and permissions

*Staff accounts* and *Roles & permissions*.

### Built-in roles

| Role | Purpose |
| --- | --- |
| System administrator | Technical administration (this manual). No patient data, money or clinic settings. |
| Clinic administrator | Day-to-day clinic administration; adds staff with ordinary roles only. |
| Clinic director | Oversight: reports, approvals, policy. Treated as a protected account. |
| Receptionist, Nurse, Doctor, Laboratory technician, Pharmacist, Cashier, Inventory manager | Their daily work. |
| Accountant | Read-only finance: invoices, payments, financial reports, stock value. |

A person can hold several roles. Their permissions are the sum of the roles.

### Rules the server enforces

- Only holders of *users.manage* (system administrators) can create or change administrator and
  director accounts, or give privileged roles.
- Nobody can change their own roles, reset their own two-step sign-in from the admin pages, or
  deactivate themselves.
- The system refuses any change that would leave no active account able to manage users and roles.
- Every change is in the audit log.

### Custom roles

*Roles & permissions*: create a role (for example *Laboratory supervisor*) and tick its permissions.
Built-in roles can be adjusted too; upgrades never remove permissions a clinic has customised.
Changes apply on each person's next request. Give the fewest permissions that let people do their
job. If two administrators edit the same role at once, the second save is refused with
**Someone else saved this record first**; reload and check before saving again.

### Account requests you will get

- **Forgotten password**: check who is asking (in person, or by calling back a known number),
  then **Reset password** and hand the temporary password over in person.
- **Lost phone for two-step sign-in**: if they still have a recovery code they can sign in; then
  **Reset 2-step** so they enrol the new phone. Without codes, check identity in person first.
- **Locked out**: **Unlock** (the lock also ends by itself after the lock time).
- **Someone left**: **Deactivate** on their last day. **Sign out everywhere** ends sessions at once.

Unused accounts are switched off automatically (default 90 days, *System › Security and
maintenance*) and administrators are told who.

### Permission matrix

**Edit permissions** opens the role as a matrix: areas of work down the side (patients, consultations,
laboratory, pharmacy and so on), kinds of action across the top (view, create or request, do the work,
approve or verify, export, set up and manage). Click an area name to tick or clear its whole row.
Permissions marked **Sensitive** are administrative and can only be given by you. Rows for a switched-off
module are greyed: those permissions do nothing until the module is on again. **List** shows the older
grouped list.

### One person, several jobs

In small clinics one person often does several jobs. In **New account** the buttons above the role list
set common combinations in one click: *Doctor + Laboratory technician*, *Doctor + Laboratory +
Pharmacist*, *Receptionist + Cashier*, *Receptionist + Cashier + Pharmacist*, *Nurse + Laboratory
technician*. They only tick the roles; you can still adjust them. The person sees the menus of all their
roles and the home page of the first one in this order: administrator, director, doctor, nurse,
receptionist, laboratory, pharmacy, cashier.

## 3a. Modules

*System › Modules* lists the parts of the system a clinic can switch off when it does not use them.
Only you can switch them; the clinic administrator sees the list read-only in *Clinic settings*.

| Module | What changes while it is off |
| --- | --- |
| Triage (nurse step) | New patients go straight to the doctors' waiting list. The *Triage* page and queue lane are hidden. Doctors can still record vital signs. |
| Appointments and calendar | Walk-in visits only. Doctors write the return date in the plan instead of booking it. |
| Laboratory | No test requests in the system and no *Laboratory only* visits. Earlier results stay in the records. |
| Stock (inventory) | No stock records. Pharmacy needs stock, so it goes off too. |
| Pharmacy | Doctors still prescribe. The prescription is marked *Printed for an outside pharmacy* and the doctor prints it from the consultation (**View / print**). Closing a visit no longer waits for dispensing. |
| Billing and payments | No invoices or payments (use the clinic's receipt book). Closing a visit no longer checks payment. Financial reports are hidden. |
| Reports | The *Reports* page and the home-page graphs are hidden. |

How it works:

- Switching a module off removes its permissions from everyone at once, whatever their roles say, and
  the menus follow. Roles are not changed, so switching it back on restores exactly what people had.
- If someone opens a switched-off page or calls its API, the answer is *This part of the system is
  switched off* rather than a permission error.
- You cannot switch a module off while it has unfinished work (for example patients waiting for triage
  or prescriptions waiting to be dispensed). The list of what is open is shown; finish or cancel it first,
  for example at the end of the day.
- You cannot switch Pharmacy on while Stock is off.
- Records already made are always kept. Every switch is in the audit log (`system.module_on`,
  `system.module_off`).

### Example: a two-person clinic

One receptionist who also takes money, one doctor who also does the laboratory, no pharmacy:

1. *System › Modules*: switch off **Triage**, **Pharmacy** (and **Stock** if no stock is kept).
2. Receptionist account: preset **Receptionist + Cashier**.
3. Doctor account: preset **Doctor + Laboratory technician**, with the professional registration number
   filled in (it is printed on prescriptions).
4. Ask the clinic administrator to fill in *Clinic settings › Document notes › Prescription* (for
   example opening hours) so it prints at the bottom of each prescription.

## 4. Security settings and maintenance mode

*System › **Security and maintenance***:

- **Minimum password length** (the server's `.env` sets the floor), **Failed attempts before
  lock**, **Lock lasts (minutes)**, **Sign out after inactivity (minutes)**. Sessions also end
  after 12 hours regardless.
- **Two-step sign-in required for**: nobody / administrators and the director (default) / everyone.
- **Switch off accounts unused for (days)** (0 = never).
- **Maintenance mode**: only system administrators can use the system; everyone else, including
  on the sign-in page, sees your **Message for staff**. Use it during upgrades and restores.

Do not run the server in debug mode or without HTTPS with real patients; `security-check.sh` fails
both.

## 5. Monitoring

*System › **Health*** (also on your dashboard): disk, memory, processor load, database response and
size, pending database updates, newest backup and its age, off-site copy status, sign-ins, failed
sign-ins, locked accounts and server errors in the last 24 hours. Items needing attention are marked.

Once a day (16:30) the daily job sends administrators a notification if something needs attention:
low disk, old backup, overdue off-site copy, errors, or an audit-log integrity problem.

*System › **Error log***: server errors with the time, the page and a **reference**. When a user
reports an error, ask for the reference shown in their message and search for it here; the same
reference is in the server log (`docker compose logs api | grep <reference>`).

Useful commands:

```bash
docker compose ps                         # all three should be "healthy"
docker compose logs --since 1h api        # application log
curl -k https://localhost/api/v1/health/  # {"status": "ok", "database": "ok"}
systemctl list-timers 'mrs-*'             # when the scheduled jobs last ran and run next
journalctl -u mrs-backup --since today    # backup log (likewise mrs-reminders, mrs-email)
df -h /var/backups/mrs /                  # free space
```

## 6. Backups

| What | When | Kept |
| --- | --- | --- |
| Database backup with checksum (`mrs-backup.timer`) | Every night at 22:00 | 14 daily, 8 weekly |
| Encrypted copy to the external drive (if `BACKUP_COPY_DIR` is mounted) | With each backup | As the drive allows |
| Full restore test into a scratch database (`mrs-backup-verify.timer`) | Sundays 23:00 | — |
| Off-site encrypted copy (optional) | Every 1–24 hours | By the storage provider |
| Manual backup: `deploy/scripts/backup.sh manual` | Before any risky change | Until you delete it |

Backups are in `/var/backups/mrs` (`daily/`, `weekly/`, `manual/`). The logo and all records are in
the database backup; there are no separate files to back up. Also keep a sealed copy of `.env` and of
`deploy/certs/clinic-ca.key` with the owner, away from the server.

**External drive**: use two drives and swap them weekly, keeping one away from the clinic.

### Other scheduled jobs

| Job | When | What |
| --- | --- | --- |
| `mrs-email.timer` | Every minute | Sends queued emails (does nothing while email is off) |
| `mrs-reminders.timer` | Daily | Appointment reminders, account review, health alerts, audit chain check |
| `mrs-visits.timer` | Every 5 minutes | Closes finished visits, only if the clinic switched it on (*Clinic settings › Waiting list*) |

### Patient attachments

Scans and photos attached to patient records are stored in the database, so the normal backup carries
them. Each is limited to 10 MB. Watch the database size on *System › Health*: a clinic that scans
every paper can add several GB a year, which also makes each nightly backup larger.

### What happens when something crashes

`deploy/scripts/test-resilience.py` kills the application and then the database while staff are saving,
on a TEST installation with synthetic data. Results on 2026-11-22: nothing the server had confirmed was
lost; while the database was down every screen got a clear "database is not responding" message within
a fraction of a second; the application recovered by itself when the database came back, and people
stayed signed in; MRNs stayed unique and the audit chain stayed intact. Run it again after major
upgrades (see the script's header for the commands).

Docker restarts a crashed container automatically (`restart: unless-stopped`). After a power cut, the
server starts Docker and the application by itself; check *System › Health* once it is back.

**Check**: *System › Health* shows the newest backup; `deploy/scripts/verify-backup.sh <file>`
checks one by hand.

**Restore**: only from the command line, never from the browser, because it replaces the whole
database. Follow [restore.md](../operations/restore.md): turn on maintenance mode, run
`deploy/scripts/restore.sh <file>`, type `RESTORE` when asked. A safety backup of the current
database is taken first. Everything entered after the backup is lost, so collect the paper records
for that period.

**Drill**: once a quarter, restore the latest backup onto a spare computer and check that it opens
and the last records are there. A backup that has never been restored is not proven.

### Off-site backup

Optional, switched on and off in *System › **Off-site backup*** (every 1, 2, 3, 6, 12 or 24 hours).
The copy is encrypted on the server with the owner's secret phrase before it leaves; the storage
provider cannot read it, and without the phrase nobody can recover it. Setting up the storage and
the phrase is done once at the server; see [offsite-backup.md](../operations/offsite-backup.md),
including how the owner recovers the data on a new machine.

## 7. Email

Optional. *System › **Email***: send staff alerts through the clinic's own email (cPanel) or a
sending service such as Brevo. Fill in the details, **Send test email**, then switch email on.
*Sent and waiting* shows the outbox; emails are retried when the internet is down. Emails never
contain patient details. See [email.md](../operations/email.md).

## 8. Clinic logo

You and the clinic administrator can change the logo in *Clinic settings › **Clinic logo***. The
other clinic details are the clinic administrator's.

## 9. Audit log

*Audit log* shows every sign-in, record view and change, with person, time, address and outcome.
Entries cannot be edited or deleted: the database refuses it, and each entry is chained to the
previous one with a hash, so removing or changing one is detected.

The daily job checks the chain and writes an *anchor* (sequence number and hash) to the system
journal, outside the database. To prove later that nothing was removed since a given day:

```bash
journalctl -u mrs-reminders | grep anchor                        # find an earlier anchor
docker compose exec -T api python manage.py verify_audit_chain --expect SEQ:HASH
```

Copy an anchor to paper or another system monthly.

## 10. Upgrades

Follow [upgrade.md](../operations/upgrade.md), outside clinic hours:

1. Tell staff; switch on maintenance mode.
2. `deploy/scripts/backup.sh pre-upgrade` and verify it.
3. Get the new version, compare `.env.example` with `.env` for new settings.
4. `docker compose build`, run the migrations and `sync_permissions`, `docker compose up -d`.
5. Check health, sign in, open a few pages; switch maintenance mode off.

Rollback needs the code **and** the pre-upgrade backup, because upgrades change the database.

## 11. Server security

Run `sudo deploy/scripts/harden-server.sh` once (the installer offers it): firewall (web from the
clinic network, SSH only from the clinic network), automatic security updates, brute-force
protection, time synchronisation (two-step sign-in needs the correct time), and SSH keys only once
keys are installed.

Run `sudo deploy/scripts/security-check.sh` after installation, after upgrades and monthly. It
checks disk encryption, firewall, updates, SSH, `.env` permissions, debug mode, HTTPS, the
certificate's expiry, backups and that the database is not exposed. Work through
[security-checklist.md](../operations/security-checklist.md) for each clinic.

Never put real patient data on a test or training system; use the demo data
(`manage.py seed_demo`) there.

## 12. Command reference

Run inside the application with `docker compose exec -T api python manage.py <command>`:

| Command | Use |
| --- | --- |
| `bootstrap_admin` | Create the first system administrator (only when none exists) |
| `sync_permissions` | Add new permissions and roles after an upgrade |
| `load_starter_catalog` | Example services, tests and medicines (prices to review) |
| `send_daily_reminders`, `review_accounts`, `health_alerts`, `verify_audit_chain` | The daily jobs, by hand |
| `send_email_outbox` | Send queued email now |
| `offsite check`, `offsite record`, `offsite status` | Off-site backup scheduling (used by the off-site script) |

Routine tasks by day, week, month and year are listed in
[maintenance-and-support.md](maintenance-and-support.md). When something breaks, start with
[troubleshooting.md](troubleshooting.md).
