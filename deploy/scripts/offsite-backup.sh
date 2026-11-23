#!/usr/bin/env bash
# Off-site backup with the clinic owner's secret phrase.
#
# Every copy is encrypted ON THIS SERVER with a key derived from the owner's secret phrase
# (restic: AES-256, key stretched with scrypt) before it is uploaded. The storage provider only ever
# holds unreadable files and never receives the phrase. Whoever knows the storage address and the
# phrase can recover the data on any machine; without the phrase, nobody can, including us.
#
#   offsite-backup.sh init               set the secret phrase and prepare the storage (once)
#   offsite-backup.sh run                upload if switched on and due (the systemd timer calls this)
#   offsite-backup.sh run --force        upload now, even if not due (still requires "on")
#   offsite-backup.sh list               list the copies held off site
#   offsite-backup.sh verify             check the off-site copies are complete and readable
#   offsite-backup.sh restore [ID|latest] [--import]
#                                        download a copy; with --import, load it into this system
#                                        (asks for the secret phrase if this server has no key file)
#
# Settings (.env): OFFSITE_REPOSITORY (e.g. rest:https://user:pass@backup.example.et/clinic-a/),
# OFFSITE_KEY_FILE (default /etc/mrs/offsite.key), and any provider credentials restic needs
# (e.g. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY for S3-compatible storage).
# Switch on/off and choose how often in the System page (Off-site backup tab).
source "$(dirname "$0")/common.sh"

OFFSITE_REPOSITORY="${OFFSITE_REPOSITORY:-}"
OFFSITE_KEY_FILE="${OFFSITE_KEY_FILE:-/etc/mrs/offsite.key}"
OFFSITE_HOST_TAG="${OFFSITE_HOST_TAG:-$(hostname -s)}"
# Leave false when the storage is append-only (recommended: then ransomware on this server cannot
# delete old copies). Retention is applied by the storage provider with its own credentials.
OFFSITE_PRUNE="${OFFSITE_PRUNE:-false}"
RESTIC="${RESTIC:-restic}"
# How to run Django management commands. Default: inside the api container.
API_EXEC="${API_EXEC:-docker compose exec -T api python manage.py}"
SPOOL="$BACKUP_DIR/offsite"

command -v "${RESTIC%% *}" >/dev/null || die "restic is not installed (apt install restic)"
[[ -n "$OFFSITE_REPOSITORY" ]] || die "Set OFFSITE_REPOSITORY in .env first (see docs/operations/offsite-backup.md)"
export RESTIC_REPOSITORY="$OFFSITE_REPOSITORY"
# Never let restic read a phrase from a stray environment variable or ask interactively during a scheduled run.
unset RESTIC_PASSWORD RESTIC_PASSWORD_COMMAND

# Address without credentials, for logs and the System page.
safe_target() { printf '%s' "$OFFSITE_REPOSITORY" | sed -E 's#//[^/@]*@#//#; s#\?.*$##'; }

use_key_file() {
    [[ -r "$OFFSITE_KEY_FILE" ]] || die "No key file at $OFFSITE_KEY_FILE. Run '$0 init' first."
    export RESTIC_PASSWORD_FILE="$OFFSITE_KEY_FILE"
}

# Asks for the phrase without echoing it. Kept only in memory for this command.
ask_phrase() {
    local p
    read -r -s -p "Secret phrase: " p; echo >&2
    [[ -n "$p" ]] || die "No phrase entered"
    export RESTIC_PASSWORD="$p"
}

phrase_strong_enough() {
    local p="$1" words
    words="$(printf '%s' "$p" | wc -w)"
    (( ${#p} >= 16 )) || (( words >= 4 && ${#p} >= 12 ))
}

cmd_init() {
    if [[ -s "$OFFSITE_KEY_FILE" ]]; then
        log "A key file already exists at $OFFSITE_KEY_FILE; checking it opens the storage"
        export RESTIC_PASSWORD_FILE="$OFFSITE_KEY_FILE"
        if $RESTIC cat config >/dev/null 2>&1; then log "Storage is ready."; return 0; fi
        $RESTIC init >/dev/null && log "Storage prepared at $(safe_target)." && return 0
        die "The existing key does not open $(safe_target)."
    fi
    cat >&2 <<'EOT'
Choose the clinic's SECRET PHRASE for off-site backups.

 - Use at least 4 unrelated words or 16 characters, e.g. "mango river seven lantern".
 - It is the ONLY way to open the off-site copies. If it is lost, the copies cannot be
   recovered by anyone, including your IT provider.
 - Write it on paper and keep it in a sealed envelope in a safe place away from the clinic.
EOT
    local p1 p2
    read -r -s -p "Secret phrase: " p1; echo >&2
    read -r -s -p "Type it again: " p2; echo >&2
    [[ "$p1" == "$p2" ]] || die "The two entries do not match"
    phrase_strong_enough "$p1" || die "Too short: use at least 4 words or 16 characters"
    install -d -m 700 "$(dirname "$OFFSITE_KEY_FILE")"
    (umask 077; printf '%s' "$p1" > "$OFFSITE_KEY_FILE")
    export RESTIC_PASSWORD_FILE="$OFFSITE_KEY_FILE"
    if $RESTIC cat config >/dev/null 2>&1; then
        log "Storage already prepared and the phrase opens it."
    else
        $RESTIC init >/dev/null || { rm -f "$OFFSITE_KEY_FILE"; die "Could not prepare storage at $(safe_target)"; }
        log "Storage prepared at $(safe_target)."
    fi
    log "Key saved to $OFFSITE_KEY_FILE (readable by root only). Now switch off-site backup on in the System page."
}

# Newest dump in the spool that has not been uploaded yet (an earlier upload may have failed offline).
pending_dump() {
    shopt -s nullglob
    local f files=("$SPOOL"/mrs-offsite-*.dump)
    shopt -u nullglob
    for f in $(printf '%s\n' "${files[@]}" | sort -r); do
        [[ -e "$f.uploaded" ]] || { printf '%s' "$f"; return 0; }
    done
}

make_dump() {
    local stamp file tmp
    stamp="$(date '+%Y%m%d-%H%M%S')"
    mkdir -p "$SPOOL"; chmod 700 "$SPOOL"
    file="$SPOOL/mrs-offsite-$stamp.dump"; tmp="$file.partial"
    # Uncompressed custom format: restic compresses and, unlike a compressed dump, can skip the
    # unchanged parts, so each upload after the first is small.
    $DB_EXEC pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=0 --no-owner > "$tmp" \
        || { rm -f "$tmp"; return 1; }
    $DB_EXEC pg_restore --list < "$tmp" > /dev/null || { rm -f "$tmp"; return 1; }
    mv "$tmp" "$file"; chmod 600 "$file"
    printf '%s' "$file"
}

record() {  # status started [snapshot bytes dump message]
    $API_EXEC offsite record --status "$1" --started "$2" --snapshot "${3:-}" ${4:+--bytes "$4"} \
        --dump "${5:-}" --target "$(safe_target)" --message "${6:-}" >/dev/null \
        || log "WARNING: could not record the result in the application"
}

cmd_run() {
    local force="${1:-}" decision started file out summary snap added
    set +e; decision="$($API_EXEC offsite check 2>/dev/null)"; local rc=$?; set -e
    case "$rc:$decision" in
        3:*) log "Off-site backup is switched off in the System page; nothing to do."; return 0 ;;
        4:*) [[ "$force" == "--force" ]] || { log "Not due yet."; return 0; } ;;
        0:due) ;;
        *) die "Could not ask the application whether a backup is due (is it running?)" ;;
    esac
    started="$(date -Iseconds)"
    if [[ ! -r "$OFFSITE_KEY_FILE" ]]; then
        record failure "$started" "" "" "" "No key file on the server; run offsite-backup.sh init"
        die "No key file at $OFFSITE_KEY_FILE"
    fi
    export RESTIC_PASSWORD_FILE="$OFFSITE_KEY_FILE"

    file="$(pending_dump)"
    if [[ -n "$file" ]]; then
        log "Uploading earlier copy that was not sent yet: $(basename "$file")"
    else
        file="$(make_dump)" || { record failure "$started" "" "" "" "Database copy failed"; die "pg_dump failed"; }
        log "Database copied to $(basename "$file")"
    fi

    set +e
    out="$($RESTIC backup --json --quiet --host "$OFFSITE_HOST_TAG" --tag mrs --tag offsite "$file" 2>&1)"
    rc=$?
    set -e
    if (( rc != 0 )); then
        local reason; reason="$(printf '%s' "$out" | grep -v '^{' | tail -n 1 | cut -c1-200)"
        record failure "$started" "" "" "$(basename "$file")" "Upload failed: ${reason:-no connection?}. Will retry."
        die "Upload failed (the copy is kept and will be sent on the next run): $reason"
    fi
    summary="$(printf '%s\n' "$out" | grep '"message_type":"summary"' | tail -n 1)"
    snap="$(printf '%s' "$summary" | sed -nE 's/.*"snapshot_id":"([0-9a-f]+)".*/\1/p')"
    added="$(printf '%s' "$summary" | sed -nE 's/.*"data_added":([0-9]+).*/\1/p')"
    touch "$file.uploaded"
    record success "$started" "${snap:0:64}" "$added" "$(basename "$file")" ""
    log "Uploaded snapshot ${snap:0:8} ($(numfmt --to=iec "${added:-0}" 2>/dev/null || echo "${added:-0} B") new data) to $(safe_target)"

    # Keep only the newest local spool file; history lives off site.
    shopt -s nullglob
    local old
    for old in $(printf '%s\n' "$SPOOL"/mrs-offsite-*.dump | sort -r | tail -n +2); do
        [[ -e "$old.uploaded" ]] && rm -f -- "$old" "$old.uploaded"
    done
    shopt -u nullglob

    if [[ "$OFFSITE_PRUNE" == "true" ]]; then
        $RESTIC forget --host "$OFFSITE_HOST_TAG" --tag offsite --keep-hourly 48 --keep-daily 14 \
            --keep-weekly 8 --keep-monthly 12 --prune --quiet || log "WARNING: pruning old copies failed"
    fi
}

cmd_list() {
    [[ -r "$OFFSITE_KEY_FILE" ]] && use_key_file || ask_phrase
    $RESTIC snapshots --tag offsite
}

cmd_verify() {
    [[ -r "$OFFSITE_KEY_FILE" ]] && use_key_file || ask_phrase
    # Reads a 5% sample of the stored data as well as the structure.
    $RESTIC check --read-data-subset=5% && log "Off-site copies are complete and readable."
}

cmd_restore() {
    local snap="latest" import="" arg dest dump
    for arg in "$@"; do
        case "$arg" in --import) import=yes ;; *) snap="$arg" ;; esac
    done
    # On a replacement machine there is no key file: the owner types the phrase.
    if [[ -r "$OFFSITE_KEY_FILE" ]]; then use_key_file; else
        echo "Enter the clinic's secret phrase for off-site backups." >&2
        ask_phrase
    fi
    $RESTIC cat config >/dev/null 2>&1 || die "The phrase does not open $(safe_target) (wrong phrase or address)."
    dest="$BACKUP_DIR/restored/$(date '+%Y%m%d-%H%M%S')"
    mkdir -p "$dest"; chmod 700 "$BACKUP_DIR/restored" "$dest"
    log "Downloading copy '$snap' from $(safe_target)"
    $RESTIC restore "$snap" --tag offsite --target "$dest" --quiet || die "Download failed"
    dump="$(find "$dest" -type f -name 'mrs-offsite-*.dump' | sort | tail -n 1)"
    [[ -n "$dump" ]] || die "The copy contains no database file"
    $DB_EXEC pg_restore --list < "$dump" > /dev/null || die "The downloaded file is damaged"
    sha256_of "$dump" > "$dump.sha256"
    log "Downloaded and checked: $dump"
    if [[ -n "$import" ]]; then
        "$(dirname "$0")/restore.sh" "$dump"
    else
        echo "$dump"
        log "To load it into this system: deploy/scripts/restore.sh $dump"
    fi
}

action="${1:-}"; shift || true
case "$action" in
    init) cmd_init ;;
    run) cmd_run "${1:-}" ;;
    list) cmd_list ;;
    verify) cmd_verify ;;
    restore) cmd_restore "$@" ;;
    *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
