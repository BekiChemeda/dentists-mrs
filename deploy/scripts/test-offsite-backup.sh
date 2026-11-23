#!/usr/bin/env bash
# Automated test of off-site backup: switched off -> nothing; on -> encrypted upload; offline -> kept
# and retried; recovery with only the address and the secret phrase; a wrong phrase opens nothing.
# Uses a temporary local restic repository. NEVER point it at a production database.
#
#   DB_EXEC="env PGHOST=localhost PGPASSWORD=..." API_EXEC="python backend/manage.py" \
#       deploy/scripts/test-offsite-backup.sh
set -euo pipefail
[[ -n "${DB_EXEC:-}" && -n "${API_EXEC:-}" ]] || { echo "Set DB_EXEC and API_EXEC explicitly." >&2; exit 2; }
here="$(cd "$(dirname "$0")" && pwd)"
work="$(mktemp -d)"; [[ -n "${KEEP:-}" ]] || trap 'rm -rf "$work"' EXIT
export BACKUP_DIR="$work/backups" OFFSITE_KEY_FILE="$work/key" OFFSITE_REPOSITORY="$work/repo"
PHRASE="mango river seven lantern"
api() { $API_EXEC shell -c "$1" 2>/dev/null | tail -n 1; }
set_offsite() { api "from apps.core.models import SystemSettings as S; S.get(); S.objects.filter(pk=1).update(offsite_enabled=$1, offsite_interval_hours=1); print('ok')" >/dev/null; }
runs() { api "from apps.core.models import OffsiteBackupRun as R; print(R.objects.filter(status='$1').count())"; }
fail() { echo "FAIL: $*" >&2; exit 1; }
# Run the script and keep its whole output (grepping a live pipe would cut it short).
run() { "$here/offsite-backup.sh" "$@" 2>&1 || true; }

api "from apps.core.models import OffsiteBackupRun as R; R.objects.all().delete(); print('ok')" >/dev/null
printf '%s' "$PHRASE" > "$OFFSITE_KEY_FILE"; chmod 600 "$OFFSITE_KEY_FILE"
RESTIC_PASSWORD_FILE="$OFFSITE_KEY_FILE" restic init --repo "$OFFSITE_REPOSITORY" >/dev/null

# 1. Switched off: no upload.
set_offsite False
grep -q "switched off" <<<"$(run run)" || fail "should do nothing when off"
[[ "$(runs success)" == "0" ]] || fail "uploaded while off"

# 2. Switched on: one encrypted upload, recorded.
set_offsite True
grep -q "Uploaded snapshot" <<<"$(run run)" || fail "upload did not happen"
[[ "$(runs success)" == "1" ]] || fail "success not recorded"
! grep -rqa "accounts_user" "$OFFSITE_REPOSITORY" || fail "repository contains readable data"

# 3. Not due again within the hour.
grep -q "Not due" <<<"$(run run)" || fail "should not upload twice within the interval"

# 4. Offline: failure recorded, dump kept, sent on the next run.
mv "$OFFSITE_REPOSITORY" "$work/repo-away"
"$here/offsite-backup.sh" run --force >/dev/null 2>&1 && fail "upload should fail while offline"
[[ "$(runs failure)" == "1" ]] || fail "failure not recorded"
ls "$BACKUP_DIR"/offsite/*.dump | while read -r f; do [[ -e "$f.uploaded" ]] || echo pending; done | grep -q pending \
    || fail "unsent copy was not kept"
mv "$work/repo-away" "$OFFSITE_REPOSITORY"
out="$(run run --force)"
grep -q "earlier copy that was not sent" <<<"$out" && grep -q "Uploaded snapshot" <<<"$out" || fail "pending copy not retried: $out"
[[ "$(runs success)" == "2" ]] || fail "retry not recorded"

# 5. Recovery on a "new machine": no key file, only the address and the phrase.
rm -f "$OFFSITE_KEY_FILE"
dump="$(printf '%s\n' "$PHRASE" | "$here/offsite-backup.sh" restore latest 2>/dev/null | tail -n 1)"
[[ -s "$dump" ]] || fail "recovery with the phrase did not produce a file"
grep -q "accounts_user" <<<"$($DB_EXEC pg_restore --list < "$dump")" || fail "recovered file is not the database"

# 6. A wrong phrase opens nothing.
printf 'wrong phrase entirely\n' | "$here/offsite-backup.sh" restore latest >/dev/null 2>&1 && fail "wrong phrase accepted"

set_offsite False
echo "PASS: off-site backup (off/on, interval, offline retry, recovery with phrase, wrong phrase refused)"
