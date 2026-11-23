#!/usr/bin/env bash
# Automated test of the backup -> verify -> restore cycle against a real PostgreSQL.
# Used in CI and runnable on a staging server. NEVER point it at a production database:
# it overwrites the target database.
#
#   DB_EXEC="env PGHOST=localhost PGPASSWORD=..." POSTGRES_DB=mrs_test \
#       deploy/scripts/test-backup-restore.sh
set -euo pipefail
[[ -n "${DB_EXEC:-}" ]] || { echo "Set DB_EXEC explicitly; this test must not run against the live container." >&2; exit 2; }
BACKUP_DIR="$(mktemp -d)"
export BACKUP_DIR
export BACKUP_COPY_DIR="" MRS_RESTORE_CONFIRM=yes MRS_SKIP_PRE_RESTORE_BACKUP=yes STOP_API=true START_API=true
here="$(dirname "$0")"
POSTGRES_DB="${POSTGRES_DB:-mrs}"; POSTGRES_USER="${POSTGRES_USER:-mrs}"
q() { $DB_EXEC psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$1"; }

before_users="$(q 'SELECT count(*) FROM accounts_user')"
before_audit="$(q 'SELECT count(*) FROM audit_event')"

file="$("$here/backup.sh" manual | tail -n 1)"
[[ -s "$file" && -s "$file.sha256" ]] || { echo "FAIL: backup file or checksum missing"; exit 1; }
"$here/verify-backup.sh" "$file"

# Change data after the backup; the restore must undo it.
q "INSERT INTO accounts_user (id, password, username, first_name, last_name, email, phone, job_title,
     registration_number, mfa_secret_encrypted, email_alerts, row_version, is_active, must_change_password,
     failed_login_count, created_at, updated_at)
   VALUES (gen_random_uuid(), '!', 'restore.marker', 'Restore', 'Marker', '', '', '', '', '', 'off', 1, true, true, 0,
     now(), now())" >/dev/null
[[ "$(q "SELECT count(*) FROM accounts_user WHERE username='restore.marker'")" == "1" ]]

# Corrupt-file check: a truncated dump must be rejected by verification.
head -c 2000 "$file" > "$BACKUP_DIR/broken.dump"
if "$here/verify-backup.sh" "$BACKUP_DIR/broken.dump" >/dev/null 2>&1; then
    echo "FAIL: truncated backup passed verification"; exit 1
fi

"$here/restore.sh" "$file"

[[ "$(q "SELECT count(*) FROM accounts_user WHERE username='restore.marker'")" == "0" ]] \
    || { echo "FAIL: post-backup change survived restore"; exit 1; }
[[ "$(q 'SELECT count(*) FROM accounts_user')" == "$before_users" ]] || { echo "FAIL: user count differs"; exit 1; }
[[ "$(q 'SELECT count(*) FROM audit_event')" == "$before_audit" ]] || { echo "FAIL: audit count differs"; exit 1; }
[[ "$(q "SELECT count(*) FROM pg_trigger WHERE tgname='audit_event_no_update'")" == "1" ]] \
    || { echo "FAIL: audit trigger missing after restore"; exit 1; }
# Rotation keeps the newest N dumps and never touches unrelated files.
mkdir -p "$BACKUP_DIR/daily"
for d in 01 02 03 04 05; do : > "$BACKUP_DIR/daily/mrs-daily-202601${d}-010000.dump"; done
: > "$BACKUP_DIR/daily/do-not-delete.txt"
BACKUP_KEEP_DAILY=3 "$here/backup.sh" daily >/dev/null
kept="$(ls "$BACKUP_DIR"/daily/*.dump | wc -l)"
[[ "$kept" == "3" ]] || { echo "FAIL: rotation kept $kept dumps, expected 3"; exit 1; }
[[ -f "$BACKUP_DIR/daily/do-not-delete.txt" ]] || { echo "FAIL: rotation deleted an unrelated file"; exit 1; }
[[ ! -f "$BACKUP_DIR/daily/mrs-daily-20260101-010000.dump" ]] || { echo "FAIL: oldest dump not rotated"; exit 1; }

# External drive copy is encrypted when a key exists, and restore.sh can decrypt it.
BACKUP_COPY_DIR="$(mktemp -d)"
BACKUP_COPY_KEY_FILE="$(mktemp)"
export BACKUP_COPY_DIR BACKUP_COPY_KEY_FILE
printf 'mango river seven lantern' > "$BACKUP_COPY_KEY_FILE"
enc_src="$("$here/backup.sh" manual | tail -n 1)"
enc="$BACKUP_COPY_DIR/$(basename "$enc_src").enc"
[[ -s "$enc" && ! -e "$BACKUP_COPY_DIR/$(basename "$enc_src")" ]] || { echo "FAIL: external copy not encrypted"; exit 1; }
! grep -qa "accounts_user" "$enc" || { echo "FAIL: encrypted copy contains readable data"; exit 1; }
"$here/restore.sh" "$enc" >/dev/null 2>&1 || { echo "FAIL: restore from encrypted copy"; exit 1; }
printf 'wrong phrase\n' | BACKUP_COPY_KEY_FILE=/nonexistent "$here/restore.sh" "$enc" >/dev/null 2>&1 \
    && { echo "FAIL: wrong phrase accepted"; exit 1; }
rm -rf "$BACKUP_COPY_DIR" "$BACKUP_COPY_KEY_FILE"

rm -rf "$BACKUP_DIR"
echo "PASS: backup, verification, corrupt-file rejection, restore, rotation and encrypted external copy all behaved correctly"
