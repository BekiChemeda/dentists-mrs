# Maintenance and support procedures

What has to be done, how often, and by whom, so that the system stays safe and working. Tick the
lists in a paper logbook kept by the server, with the date and your initials.

Roles: **SA** system administrator (or the support provider), **CA** clinic administrator,
**Owner** clinic owner or director.

## Every day

| Who | Task |
| --- | --- |
| CA | Dashboard: approvals waiting; announcements still correct. |
| CA | Waiting list: no visits left open from earlier days. |
| Cashier, CA | Cash-up matches the system; differences reported the same day. |
| SA | Dashboard / *System › Health*: everything green; newest backup from last night. Act on any daily alert notification. |
| Anyone | The UPS shows mains power and a charged battery. |

## Every week

| Who | Task |
| --- | --- |
| SA | Swap the external backup drive; take the other one away from the clinic. |
| SA | Sunday's automatic restore test passed (`journalctl -u mrs-backup-verify -n 20`). |
| SA | *System › Error log*: any new errors? Find the cause of repeated ones. |
| SA | *System › Off-site backup* (if used): copies up to date, no failures. |
| CA | *Inventory › Alerts*: low stock and expiring medicines acted on. |
| CA | Staff who left this week are deactivated. |

## Every month

| Who | Task |
| --- | --- |
| SA | `sudo deploy/scripts/security-check.sh`: no FAIL; plan fixes for WARN. |
| SA | Disk space trend (*System › Health*): more than 30% free. |
| SA | Write the latest audit anchor (`journalctl -u mrs-reminders \| grep anchor \| tail -1`) in the logbook. |
| SA | Operating system updates applied (automatic security updates; reboot if `/var/run/reboot-required` exists, outside clinic hours). |
| CA, SA | Staff accounts review: everyone listed still works here and has only the roles they need. Administrator accounts especially. |
| CA | Prices and catalogue still right; reports sent to management. |
| Pharmacy, CA | Controlled-medicine register balances match the physical count. |

## Every three months

| Who | Task |
| --- | --- |
| SA | **Restore drill**: restore the latest backup on a spare computer; check the last day's records are there. Write the result in the logbook. |
| SA, Owner | Off-site recovery drill (if used): the owner types the phrase; the data comes back on a spare computer. |
| SA | Check for a new Clinic MRS release; plan the upgrade ([upgrade.md](../operations/upgrade.md)). |
| SA | After an upgrade: run the crash test (`deploy/scripts/test-resilience.py`) and the load test (`perf/load_test.py`) on a test copy with synthetic data, and compare with the last results. |
| CA | Remind staff about passwords, two-step sign-in, signing out, and not sharing accounts. |

## Every year

| Who | Task |
| --- | --- |
| SA | Certificate expiry date noted; renew at least a month before (valid 825 days). |
| SA | Server hardware: disk health (`sudo smartctl -a /dev/sda`), fans and dust, UPS battery test. Plan replacement after about 5 years. |
| Owner | Sealed copies (`.env`, `clinic-ca.key`, off-site phrase) are still in the safe place and readable. |
| Owner, CA | Who has which role; who holds the server passwords; who to call for support. Update this document's contact list. |

## Changes to the system

- Any change to the server (upgrade, restore, hardware, network) is done outside clinic hours, with
  maintenance mode on, after a fresh manual backup, and is written in the logbook.
- Upgrades follow [upgrade.md](../operations/upgrade.md). Test a new release on a spare computer with
  demo data first.
- Never test with real patient data, and never copy the clinic's database to a personal computer.

## How support works

### Levels

1. **Level 1, in the clinic** (CA or a trained staff member): passwords, locked accounts, printing,
   one computer that cannot connect, how to do something. Use the manuals and
   [troubleshooting.md](troubleshooting.md).
2. **Level 2, system administrator**: server not responding, backups, email, certificates, errors
   with a reference, upgrades.
3. **Level 3, software support / developer**: a fault in the software (wrong result, error that
   keeps coming back, data that looks wrong), security incidents.

### Reporting a problem

Give:

- what you were doing (page and button), what you expected and what happened;
- the time, the computer, and your username;
- the **reference** from the error message, if any;
- whether it affects one person or everyone.

Never send passwords, two-step codes, recovery codes or patient information by phone, SMS, email or
chat. Say "the patient with MRN 12345" only when the support person is authorised to see records,
and only through the clinic's agreed channel.

### Response targets (to agree with the support provider)

| Situation | Example | Target |
| --- | --- | --- |
| Critical | Nobody can use the system; data loss suspected; security incident | Start within 2 hours, clinic hours |
| High | One department cannot work; backups failing | Same working day |
| Normal | One user's problem; a report question | 2 working days |
| Request | New role, new report, training | Planned |

### Security incidents

A lost or stolen computer or phone, someone using another person's account, a ransomware message, an
audit integrity warning, or patient data seen by someone who should not have:

1. Tell the system administrator and the director immediately.
2. SA: deactivate affected accounts, end their sessions, reset two-step sign-in where a phone was
   lost. Do not wipe or restore anything yet; preserve evidence.
3. Write down times and what happened. Check the audit log for what the account did.
4. The director decides on notification of patients or authorities with legal advice
   (Personal Data Protection Proclamation No. 1321/2024).

## Contacts

Fill in and keep up to date:

| Role | Name | Phone | Hours |
| --- | --- | --- | --- |
| Clinic administrator | | | |
| System administrator | | | |
| Software support | | | |
| Owner / director | | | |
| Internet provider | | | |
| Electrician / UPS | | | |
