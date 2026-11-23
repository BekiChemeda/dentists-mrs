#!/usr/bin/env bash
# Restores a backup over the live database. DESTRUCTIVE: replaces all current data.
# Usage: deploy/scripts/restore.sh /var/backups/mrs/daily/mrs-daily-YYYYMMDD-HHMMSS.dump
# See docs/operations/restore.md before running.
source "$(dirname "$0")/common.sh"

file="$(abspath "${1:-}")"
[[ -n "$file" && -f "$file" ]] || die "Usage: $0 <backup.dump | backup.dump.enc>"

# Encrypted copy from the external drive: decrypt with the key file, or ask for the secret phrase.
if [[ "$file" == *.enc ]]; then
    plain="$(mktemp "${TMPDIR:-/tmp}/mrs-restore-XXXXXX.dump")"; chmod 600 "$plain"
    trap 'rm -f "$plain"' EXIT
    if [[ -r "$BACKUP_COPY_KEY_FILE" ]]; then
        pass="file:$BACKUP_COPY_KEY_FILE"
    else
        read -r -s -p "Secret phrase: " phrase; echo >&2
        export MRS_RESTORE_PHRASE="$phrase"; pass="env:MRS_RESTORE_PHRASE"
    fi
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass "$pass" -in "$file" -out "$plain" 2>/dev/null \
        || die "Could not decrypt $file (wrong phrase or damaged file)"
    unset MRS_RESTORE_PHRASE
    sums="${file%.enc}.sha256"
    [[ -f "$sums" ]] || die "Checksum file $sums is missing: cannot confirm the decrypted copy is intact"
    [[ "$(sha256_of "$plain")" == "$(cat "$sums")" ]] || die "Checksum mismatch after decryption: refusing to restore"
    file="$plain"
fi

if [[ -f "$file.sha256" ]]; then
    [[ "$(sha256_of "$file")" == "$(cat "$file.sha256")" ]] || die "Checksum mismatch: refusing to restore"
fi

if [[ "${MRS_RESTORE_CONFIRM:-}" != "yes" ]]; then
    echo "This will REPLACE all data in database '$POSTGRES_DB' with $file."
    read -r -p "Type RESTORE to continue: " answer
    [[ "$answer" == "RESTORE" ]] || die "Cancelled"
fi

# Safety net: keep a copy of the current state first.
if [[ "${MRS_SKIP_PRE_RESTORE_BACKUP:-}" != "yes" ]]; then
    log "Taking a safety backup of the current database"
    "$(dirname "$0")/backup.sh" manual >/dev/null
fi

STOP_API="${STOP_API:-docker compose stop api web}"
START_API="${START_API:-docker compose start api web}"
log "Stopping application containers"
$STOP_API

log "Recreating database '$POSTGRES_DB'"
$DB_EXEC dropdb -U "$POSTGRES_USER" --if-exists --force --maintenance-db=postgres "$POSTGRES_DB"
$DB_EXEC createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
$DB_EXEC pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error < "$file" \
    || die "pg_restore failed. The database may be incomplete; restore the safety backup in $BACKUP_DIR/manual."

# Dental image files: copy back any missing from the backup mirror (or MRS_RESTORE_IMAGES_FROM, e.g. an
# off-site download or the external drive, whose files end in .enc and are decrypted with the key or phrase).
images_from="${MRS_RESTORE_IMAGES_FROM:-$BACKUP_DIR/images}"
if [[ -d "$images_from" ]]; then
    mkdir -p "$IMAGE_DIR"
    restored=0
    while IFS= read -r -d '' f; do
        f="${f#./}"; target="$IMAGE_DIR/${f%.enc}"
        [[ -e "$target" ]] && continue
        mkdir -p "$(dirname "$target")"
        if [[ "$f" == *.enc ]]; then
            [[ -r "$BACKUP_COPY_KEY_FILE" ]] || die "Encrypted image copies need the key file $BACKUP_COPY_KEY_FILE"
            openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass "file:$BACKUP_COPY_KEY_FILE" \
                -in "$images_from/$f" -out "$target" 2>/dev/null || die "Could not decrypt $f"
        else
            cp -p "$images_from/$f" "$target"
        fi
        chmod 600 "$target"
        restored=$((restored + 1))
    done < <(cd "$images_from" && find . -type f ! -name '.*' -print0)
    chown -R "${IMAGE_OWNER:-10001:10001}" "$IMAGE_DIR" 2>/dev/null || true
    log "Dental images: $restored file(s) restored into $IMAGE_DIR"
else
    log "No dental image mirror at $images_from (nothing to restore for images)"
fi

log "Starting application containers"
$START_API
VERIFY_IMAGES="${VERIFY_IMAGES:-docker compose exec -T api python manage.py verify_dental_images}"
if [[ "${MRS_SKIP_IMAGE_VERIFY:-}" != "yes" ]]; then
    sleep "${RESTORE_SETTLE_SECONDS:-5}"
    $VERIFY_IMAGES || log "WARNING: some dental image files are missing or damaged (see above). Restore them from another copy."
fi
log "Restore complete from $file"
