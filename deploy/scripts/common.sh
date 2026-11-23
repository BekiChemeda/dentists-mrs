#!/usr/bin/env bash
# Shared settings for MRS operations scripts. Sourced, not executed.
set -euo pipefail

CALLER_PWD="$PWD"
MRS_ROOT="${MRS_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$MRS_ROOT"

if [[ -f .env ]]; then
    # shellcheck disable=SC1091
    set -a; . ./.env; set +a
fi

POSTGRES_DB="${POSTGRES_DB:-mrs}"
POSTGRES_USER="${POSTGRES_USER:-mrs}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/mrs}"
BACKUP_COPY_DIR="${BACKUP_COPY_DIR:-}"
# Encrypt copies on the external drive: auto (when a key exists), yes (required), no.
BACKUP_COPY_ENCRYPT="${BACKUP_COPY_ENCRYPT:-auto}"
BACKUP_COPY_KEY_FILE="${BACKUP_COPY_KEY_FILE:-${OFFSITE_KEY_FILE:-/etc/mrs/offsite.key}}"
BACKUP_KEEP_DAILY="${BACKUP_KEEP_DAILY:-14}"
BACKUP_KEEP_WEEKLY="${BACKUP_KEEP_WEEKLY:-8}"
# Dental image files (ADR 0007): written once by the application, never changed, so backups mirror them.
IMAGE_DIR="${IMAGE_DIR:-/var/lib/mrs/images}"

# How to run PostgreSQL client tools. Default: inside the db container.
# Tests override this, e.g. DB_EXEC="env PGHOST=localhost PGPASSWORD=..."
DB_EXEC="${DB_EXEC:-docker compose exec -T db}"

# Logs go to stderr so scripts can print results (e.g. the backup path) on stdout.
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# Resolve a path given on the command line relative to where the user ran the script.
abspath() { [[ -z "$1" || "$1" = /* ]] && printf '%s' "$1" || printf '%s/%s' "$CALLER_PWD" "$1"; }

sha256_of() { sha256sum "$1" | awk '{print $1}'; }

# Copy image files that are not yet in the mirror. Files never change, so an existing name is never copied again.
# Usage: mirror_images SRC DEST [encrypt-key-file]   Prints the number of files copied.
mirror_images() {
    local src="$1" dest="$2" key="${3:-}" n=0 f target
    [[ -d "$src" ]] || { echo 0; return 0; }
    mkdir -p "$dest"; chmod 700 "$dest"
    while IFS= read -r -d '' f; do
        f="${f#./}"
        target="$dest/$f"; [[ -n "$key" ]] && target="$target.enc"
        [[ -e "$target" ]] && continue
        mkdir -p "$(dirname "$target")"
        if [[ -n "$key" ]]; then
            openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass "file:$key" -in "$src/$f" -out "$target.partial" \
                && mv "$target.partial" "$target" || { rm -f "$target.partial"; return 1; }
        else
            cp -p "$src/$f" "$target.partial" && mv "$target.partial" "$target" || { rm -f "$target.partial"; return 1; }
        fi
        chmod 600 "$target"
        n=$((n + 1))
    done < <(cd "$src" && find . -type f ! -name '.*' -print0)
    echo "$n"
}
