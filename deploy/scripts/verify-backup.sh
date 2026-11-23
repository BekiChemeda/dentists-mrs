#!/usr/bin/env bash
# Proves a backup can actually be restored: checksum, restore into a scratch database,
# sanity queries, then drop the scratch database. Run weekly (systemd timer) and before upgrades.
# Usage: deploy/scripts/verify-backup.sh [path-to-dump]   (defaults to the newest daily backup)
source "$(dirname "$0")/common.sh"

file="${1:-$(ls -1t "$BACKUP_DIR"/daily/*.dump 2>/dev/null | head -n 1 || true)}"
file="$(abspath "$file")"
[[ -n "$file" && -f "$file" ]] || die "No backup file found to verify"
scratch="${POSTGRES_DB}_verify"

if [[ -f "$file.sha256" ]]; then
    [[ "$(sha256_of "$file")" == "$(cat "$file.sha256")" ]] || die "Checksum mismatch for $file"
    log "Checksum OK"
else
    log "WARNING: no checksum file for $file"
fi

cleanup() { $DB_EXEC dropdb -U "$POSTGRES_USER" --if-exists "$scratch" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
$DB_EXEC createdb -U "$POSTGRES_USER" "$scratch"
$DB_EXEC pg_restore -U "$POSTGRES_USER" -d "$scratch" --no-owner --exit-on-error < "$file" \
    || die "Restore into scratch database failed"

q() { $DB_EXEC psql -U "$POSTGRES_USER" -d "$scratch" -tAc "$1"; }
users="$(q 'SELECT count(*) FROM accounts_user')"
perms="$(q 'SELECT count(*) FROM accounts_permission')"
audit="$(q 'SELECT count(*) FROM audit_event')"
migrations="$(q 'SELECT count(*) FROM django_migrations')"
trigger="$(q "SELECT count(*) FROM pg_trigger WHERE tgname = 'audit_event_no_update'")"

[[ "$users" -ge 1 ]] || die "Restored database has no users"
[[ "$perms" -ge 1 ]] || die "Restored database has no permissions"
[[ "$trigger" == "1" ]] || die "Audit protection trigger missing after restore"
# Dental images: every image row in the restored database must have its file in the backup mirror, unchanged.
images="$(q "SELECT count(*) FROM information_schema.tables WHERE table_name = 'dental_image'")"
if [[ "$images" == "1" ]]; then
    missing=0; checked=0
    while IFS='|' read -r key sum; do
        [[ -n "$key" ]] || continue
        checked=$((checked + 1))
        f="$BACKUP_DIR/images/$key"
        if [[ ! -f "$f" || "$(sha256_of "$f")" != "$sum" ]]; then
            missing=$((missing + 1)); log "Image missing or changed in the backup: $key"
        fi
    done < <(q "SELECT storage_key, sha256 FROM dental_image")
    (( missing == 0 )) || die "$missing of $checked dental image file(s) missing or damaged in $BACKUP_DIR/images"
    log "Dental images verified: $checked file(s)"
fi
log "Restore verified: users=$users permissions=$perms audit_events=$audit migrations=$migrations"
log "VERIFY OK: $file"
