# Off-site backup

Local backups (`backup.sh`, the USB copy) do not survive a fire, theft or ransomware in the clinic.
Off-site backup sends an **encrypted** copy of the database to storage outside the clinic every
1, 2, 3, 6, 12 or 24 hours.

## How it protects the data

- The copy is encrypted **on the clinic's server** with a key derived from the **owner's secret
  phrase** (restic: AES-256, scrypt key stretching) before it is uploaded.
- The phrase is typed by the owner once on the server and kept in a root-only file
  (`/etc/mrs/offsite.key`). It is never stored in the database, shown in the browser or sent to
  the storage provider.
- The storage provider holds only unreadable files. **Whoever knows the storage address and the
  phrase can recover the data on any machine. Without the phrase, nobody can, including the IT
  provider.** The owner must keep the phrase written down in a sealed envelope away from the clinic.
- Uploads after the first one send only what changed, so they are small enough for a mobile-data
  connection.
- If the internet is down, the copy waits on the server and is sent at the next check (every 15
  minutes). If no copy succeeds for two intervals plus an hour, system administrators get a
  notification and the System page shows it as overdue.

## Who can do what

| Action | Where | Who |
| --- | --- | --- |
| Switch on/off, choose how often | System › Off-site backup | `backups.manage` (system administrator) |
| See status and upload history | System › Off-site backup, System › Health | `system.health.view` or `backups.manage` |
| Set the secret phrase, storage address | Server command line | Technician with root, owner types the phrase |
| Recover / import | Server command line | Technician with root, owner types the phrase |

Switching off stops new uploads at the next check. Copies already sent are **not** deleted.

## Setup (once per clinic)

1. Install restic on the server: `sudo apt install restic` (0.14 or newer).
2. Storage: any restic-supported service. Recommended: a provider (or your own server) **in
   Ethiopia**, using restic's REST server in **append-only** mode, so the clinic's server can add
   copies but cannot delete them, and ransomware on it cannot wipe the history. Health data falls
   under the Personal Data Protection Proclamation No. 1321/2024; have the storage location and the
   data-processing agreement reviewed by a lawyer before offering this commercially.
3. In `.env`:
   ```
   OFFSITE_REPOSITORY=rest:https://clinic-a:<upload-password>@backup.example.et/clinic-a/
   OFFSITE_KEY_FILE=/etc/mrs/offsite.key
   OFFSITE_PRUNE=false
   ```
4. With the owner present: `sudo deploy/scripts/offsite-backup.sh init`. The owner types the secret
   phrase twice (at least 4 words or 16 characters) and writes it down.
5. Install the timer:
   ```
   sudo cp deploy/systemd/mrs-offsite-backup.{service,timer} /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now mrs-offsite-backup.timer
   ```
6. In the System page, open **Off-site backup**, switch it on and choose how often. The first
   upload starts within 15 minutes; `sudo deploy/scripts/offsite-backup.sh run --force` starts it now.

## Retention

With append-only storage, old copies are removed by the provider with its own credentials, for
example daily: `restic forget --keep-hourly 48 --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune`.
(`OFFSITE_PRUNE=true` makes the clinic's server do this itself, which only works on storage that
allows deletion and gives up the ransomware protection.)

## Getting the data back

On the existing server or a newly installed one (install the system first, see `install.md`):

```
# .env needs OFFSITE_REPOSITORY. No key file is needed: the owner types the phrase.
sudo deploy/scripts/offsite-backup.sh list                     # copies available
sudo deploy/scripts/offsite-backup.sh restore latest           # download and check only
sudo deploy/scripts/offsite-backup.sh restore latest --import  # download, check, and load it
```

`--import` hands the file to `restore.sh`, which asks you to type `RESTORE`, keeps a safety copy of
the current database, and replaces it. A wrong phrase opens nothing.

## Checks

- Monthly: `sudo deploy/scripts/offsite-backup.sh verify` reads part of the stored data to prove it
  is complete and readable.
- Quarterly, with the owner: recover the latest copy onto a spare machine (`restore latest
  --import`) and open a few patient records. A backup nobody has restored is not proven.
- Automated test (staging only): `deploy/scripts/test-offsite-backup.sh` covers off/on, the
  interval, an offline upload that is retried, recovery with only the phrase, and a wrong phrase
  being refused.
