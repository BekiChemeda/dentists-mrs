# Backup and restore

## What runs automatically

| Timer | When | What |
| --- | --- | --- |
| `mrs-backup.timer` | Nightly 22:00 | `pg_dump` custom format → SHA-256 → `pg_restore --list` check → keep 14 daily + 8 weekly (Sundays) → copy to `BACKUP_COPY_DIR` if mounted |
| `mrs-backup-verify.timer` | Sundays 23:00 | Checksum, full restore of the newest daily backup into a scratch database, sanity checks (users, permissions, audit trigger), then drop the scratch database |

Backups live in `BACKUP_DIR` (default `/var/backups/mrs`): `daily/`, `weekly/`, `manual/`. Manual and pre-restore backups are never rotated away automatically.

Off-site copy: rotate two external drives weekly and keep one away from the clinic (fire, theft). Whether copies may leave Ethiopia is a legal question; keep them in-country until it is answered.

## Restore the whole database

Use when the database is lost or corrupted, or to roll back a failed upgrade. **All changes made after the backup are lost.** Write down what was entered since then so it can be re-entered from paper.

```bash
cd /opt/mrs
ls -lt /var/backups/mrs/daily/ | head                       # choose the backup
deploy/scripts/verify-backup.sh /var/backups/mrs/daily/mrs-daily-YYYYMMDD-HHMMSS.dump
deploy/scripts/restore.sh       /var/backups/mrs/daily/mrs-daily-YYYYMMDD-HHMMSS.dump
```

`restore.sh` checks the checksum, asks you to type `RESTORE`, takes a safety backup of the current database into `manual/`, stops `api` and `web`, recreates the database, restores, and starts the application again. Staff must sign in again afterwards.

After restoring: sign in as an administrator, open the audit log and confirm the latest events match the backup time; check a few recent records with the people who entered them.

## Restore onto a new server

1. Install as in [install.md](install.md) up to step 4, with the same `.env` values (keep a sealed copy of `.env` with the backups).
2. `docker compose up -d db`
3. `deploy/scripts/restore.sh <backup.dump>`
4. `docker compose up -d`

## Testing the procedure

`deploy/scripts/test-backup-restore.sh` runs backup → verify → corrupt-file rejection → restore → rotation against a **test** database and is part of CI. Run it on a staging copy, never on the live database.
