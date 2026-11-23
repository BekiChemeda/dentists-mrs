#!/usr/bin/env bash
# Nightly backup: pg_dump (custom format) + checksum + integrity listing + rotation.
# Usage: deploy/scripts/backup.sh [label]     (label defaults to "daily"; Sundays also keep a weekly copy)
source "$(dirname "$0")/common.sh"

label="${1:-daily}"
stamp="$(date '+%Y%m%d-%H%M%S')"
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly" "$BACKUP_DIR/manual"
chmod 700 "$BACKUP_DIR"

case "$label" in
    daily|manual|pre-upgrade) dest_dir="$BACKUP_DIR/${label/pre-upgrade/manual}" ;;
    *) die "Unknown label '$label' (use daily, manual or pre-upgrade)" ;;
esac
file="$dest_dir/mrs-$label-$stamp.dump"
tmp="$file.partial"

log "Starting backup of database '$POSTGRES_DB' to $file"
$DB_EXEC pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=6 --no-owner > "$tmp" \
    || { rm -f "$tmp"; die "pg_dump failed"; }

# A dump that pg_restore cannot list is corrupt.
$DB_EXEC pg_restore --list < "$tmp" > /dev/null || { rm -f "$tmp"; die "Backup failed integrity listing"; }

mv "$tmp" "$file"
chmod 600 "$file"
sha256_of "$file" > "$file.sha256"
size="$(du -h "$file" | cut -f1)"
log "Backup complete: $file ($size)"

# Weekly copy every Sunday.
if [[ "$label" == "daily" && "$(date +%u)" == "7" ]]; then
    cp -p "$file" "$file.sha256" "$BACKUP_DIR/weekly/"
fi

# Second copy to an external drive if configured and mounted.
if [[ -n "$BACKUP_COPY_DIR" ]]; then
    if [[ -d "$BACKUP_COPY_DIR" && -w "$BACKUP_COPY_DIR" ]]; then
        # A USB drive is easy to lose or take home, so the copy on it is encrypted whenever a key
        # exists (by default the owner's off-site secret phrase). Plain copies only if asked for.
        if [[ "$BACKUP_COPY_ENCRYPT" != "no" && -r "$BACKUP_COPY_KEY_FILE" ]]; then
            dest="$BACKUP_COPY_DIR/$(basename "$file").enc"
            openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass "file:$BACKUP_COPY_KEY_FILE" \
                -in "$file" -out "$dest.partial" && mv "$dest.partial" "$dest" \
                && cp -p "$file.sha256" "$BACKUP_COPY_DIR/" && log "Encrypted copy written to $dest" \
                || { rm -f "$dest.partial"; log "WARNING: encrypted external copy failed"; }
        elif [[ "$BACKUP_COPY_ENCRYPT" == "yes" ]]; then
            log "WARNING: BACKUP_COPY_ENCRYPT=yes but no key at $BACKUP_COPY_KEY_FILE; external copy skipped"
        else
            cp -p "$file" "$file.sha256" "$BACKUP_COPY_DIR/" && log "Copied (NOT encrypted) to $BACKUP_COPY_DIR"
        fi
    else
        log "WARNING: BACKUP_COPY_DIR '$BACKUP_COPY_DIR' is not mounted or not writable; external copy skipped"
    fi
fi

# Rotation (only daily and weekly; manual and pre-upgrade backups are kept until deleted by hand).
prune() {
    local dir="$1" keep="$2" old
    local -a files=()
    shopt -s nullglob
    files=("$dir"/mrs-*.dump)
    shopt -u nullglob
    (( ${#files[@]} > keep )) || return 0
    # Names embed the timestamp (mrs-<label>-YYYYMMDD-HHMMSS.dump), so a reverse
    # lexical sort is newest first. Only files matching that pattern are ever removed.
    mapfile -t files < <(printf '%s\n' "${files[@]}" | sort -r)
    for old in "${files[@]:$keep}"; do
        [[ "$(basename "$old")" =~ ^mrs-[a-z-]+-[0-9]{8}-[0-9]{6}\.dump$ ]] || continue
        rm -f -- "$old" "$old.sha256"; log "Removed old backup $old"
    done
}
prune "$BACKUP_DIR/daily" "$BACKUP_KEEP_DAILY"
prune "$BACKUP_DIR/weekly" "$BACKUP_KEEP_WEEKLY"

echo "$file"
