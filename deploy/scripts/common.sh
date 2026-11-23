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

# How to run PostgreSQL client tools. Default: inside the db container.
# Tests override this, e.g. DB_EXEC="env PGHOST=localhost PGPASSWORD=..."
DB_EXEC="${DB_EXEC:-docker compose exec -T db}"

# Logs go to stderr so scripts can print results (e.g. the backup path) on stdout.
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# Resolve a path given on the command line relative to where the user ran the script.
abspath() { [[ -z "$1" || "$1" = /* ]] && printf '%s' "$1" || printf '%s/%s' "$CALLER_PWD" "$1"; }

sha256_of() { sha256sum "$1" | awk '{print $1}'; }
