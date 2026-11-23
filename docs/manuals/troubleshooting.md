# Troubleshooting

Start with the first section that matches what you see. Staff: try the steps marked **Anyone**, then
call the system administrator with the **reference** from the error message if there is one.
Administrators: the steps marked **Admin** need the server.

Keep the paper forms ready. If the system is down for more than a few minutes, switch to paper and
enter the records afterwards (each manual says how for that role).

---

## The system does not open

**Anyone**

1. Does any other clinic computer open it? If yes, the problem is this computer: check its network
   cable or Wi-Fi, restart the browser, then the computer.
2. Type the address exactly as given (for example `https://192.168.1.10`). Bookmarks are safest.
3. If no computer can open it, the server or network is down: tell the administrator.

**Admin**

1. Is the server on? (Power, UPS.) Does it answer `ping <address>` from another computer?
2. On the server: `docker compose ps`. All of `db`, `api`, `web` should be *running (healthy)*.
   If not: `docker compose up -d`, wait a minute, check again.
3. `docker compose logs --tail 100 api` and `... web`: look for the first error.
4. Disk full? `df -h`. Free space by removing old manual backups you no longer need (never the only
   copy), then `docker compose up -d`.
5. After a power cut, PostgreSQL recovers by itself on start; give it a few minutes. If `db` keeps
   restarting, see "Database will not start" below.
6. Network: the server's address must not have changed (set a DHCP reservation in the router).

## "Your connection is not private" / certificate warning

The clinic's certificate is not installed on this computer, or has expired. Do not click through.
**Admin**: install `clinic-ca.crt` on the computer
([system-administrator.md](system-administrator.md#https-certificate)); if it expired, renew it.

## Cannot sign in

| Message or situation | What to do |
| --- | --- |
| Wrong username or password | Check Caps Lock and the keyboard language (Amharic keyboard on?). |
| Account locked | Wait for the lock time (15 minutes by default), or ask an administrator to **Unlock**. |
| Account inactive | Ask an administrator. Accounts unused for 90 days are switched off automatically. |
| Forgot password | An administrator issues a temporary password, in person. |
| Two-step code refused | Set the phone's date and time to automatic and try the newest code. Or use a recovery code. |
| Lost phone and recovery codes | An administrator resets two-step sign-in after checking who you are. |
| "Maintenance" message | The administrator is working on the system. Use paper until it ends. |

## Signed out unexpectedly

Normal after 30 minutes without activity, or 12 hours after signing in, or when an administrator
reset your password or ended your sessions. Sign in again. Unsaved typing in a form may be lost; the
doctor's evaluation note saves itself as you type.

## "Someone else saved this record first"

Another person changed the same record while you had it open. Nothing was overwritten. Click
**Load the latest version**, check their change, and make yours again if still needed. If it happens
again and again on the same record, two people are working on it at the same time; agree who does it.

## "This note was changed elsewhere"

The same evaluation note is open on two computers or in two browser tabs. Click **Reload note**,
check it, and continue in one place only.

## A page shows an error with a reference

**Anyone**: try again once. If it happens again, note what you did and the **reference**, and tell
the administrator. **Admin**: find the reference in *System › Error log* or with
`docker compose logs api | grep <reference>`.

## The system is slow

**Anyone**: is it slow for everyone or one computer? One computer: close other programs and tabs,
restart the browser.

**Admin**: *System › Health* (processor load, memory, disk, database response time). Check the
network (a failing switch or cable causes slowness for a group of computers). `docker compose stats`
shows resource use. Restarting the application (`docker compose restart api web`) is safe outside
busy times; staff stay signed in.

## Printing

- Use the **Print** button on the document, not the browser menu, so only the document prints.
- In the print dialog choose the right printer and paper size (A4), margins *Default*, and tick
  *Background graphics* if the logo or shading does not print.
- **Save as PDF** is a printer choice in the same dialog.
- Documents always print in the light layout, even when the screen is in dark mode.

## A patient cannot be found

Search by phone number or MRN instead of the name (names are spelled in different ways). Check
whether the record was merged: the old MRN still finds it. Only then register a new record.

## Prices, stock or reports look wrong

- Stock: *Inventory › Movements* for the item shows every receipt, dispensing and adjustment.
- Prices: the audit log shows who changed a price and when. Issued invoices keep the price at the
  time they were made.
- Reports: check the date range, and close visits still open from earlier days (the waiting list
  warns about them) so that visit reports are complete.

## Email alerts do not arrive

**Admin**: *System › Email* shows whether email is on and the last test result; *Sent and waiting*
shows the queue and errors. Without internet, emails wait and are sent later. Check the person's
email address on their account and their *Email alerts* choice. See
[email.md](../operations/email.md#problems) for server messages.

## Backup problems

**Admin**

- *System › Health* says the newest backup is over a day old: `journalctl -u mrs-backup -n 50`.
  Common causes: disk full, the database container not running, the timer not installed
  (`systemctl list-timers 'mrs-*'`). Run `deploy/scripts/backup.sh manual` to test.
- External drive copy missing: the drive is not mounted at `BACKUP_COPY_DIR`, or is full.
- Off-site copy overdue: internet down (it retries every 15 minutes) or the storage credentials
  changed. *System › Off-site backup* shows the last error.

## Database will not start

**Admin**: `docker compose logs db`. Disk full is the usual cause; free space and start again. If the
database files are damaged, restore the newest good backup
([restore.md](../operations/restore.md)). Do not delete the `pgdata` volume.

## Audit log integrity warning

**Admin**: a notification "Audit log tampering detected" means the audit log's hash chain no longer
matches. Treat it as a security incident: do not change anything on the server, record the time,
and run `manage.py verify_audit_chain` to see the first broken entry. Compare with the anchors in
the system journal. Involve the clinic director.

## After an upgrade something does not work

**Admin**: check `docker compose ps`, `docker compose logs api`, and that migrations ran
(*System › Health* shows pending database updates). If it cannot be fixed quickly, roll back
([upgrade.md](../operations/upgrade.md#rolling-back)).

## When to call for outside support

Call the support provider when: the server does not start after the steps above; data looks wrong
or missing; a restore is needed; an audit integrity warning appears; or a security incident is
suspected (lost or stolen computer, someone using another person's account). Give them the time it
started, what you saw, and any error references. Never send passwords or patient information in
the message.
