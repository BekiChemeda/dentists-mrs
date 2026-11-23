#!/usr/bin/env bash
# Clinic MRS guided installer for Ubuntu Server 24.04 LTS.
#
# Run from the unpacked application folder (normally /opt/mrs):
#     sudo deploy/install.sh              # asks a few questions, then installs
#     sudo deploy/install.sh --check      # only checks the server; changes nothing
#     sudo deploy/install.sh --yes        # no questions; uses the MRS_* values below or defaults
#
# No internet at the clinic: unpack an offline bundle (deploy/scripts/make-offline-bundle.sh); its
# offline/ folder is found automatically and Docker and the application are installed from it.
#
# Answers can be given in advance (useful for a second clinic with the same set-up):
#     MRS_ADDRESS=192.168.1.10  MRS_DNS_NAME=mrs.clinic.local  MRS_HTTPS=true|false
#     MRS_FACILITY_CODE=CLN  MRS_BACKUP_DIR=/var/backups/mrs  MRS_BACKUP_COPY_DIR=/media/backup
#     MRS_LOAD_CATALOG=yes|no  MRS_INSTALL_TIMERS=yes|no  MRS_HARDEN=yes|no  MRS_INSTALL_DOCKER=yes|no
#
# Safe to run again: an existing .env, its secrets, the certificates and the database are kept.
# The installer never prints secrets except the administrator's one-time password, which must be
# changed at first sign-in. Everything it does is written to the install log.
#
# See docs/operations/install.md for what each step does and how to do it by hand.

set -euo pipefail

MRS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$MRS_ROOT"

SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
LOG_FILE="${MRS_INSTALL_LOG:-/var/log/mrs-install.log}"
ASSUME_YES=false
CHECK_ONLY=false
WARNINGS=0
OFFLINE_DIR="$MRS_ROOT/offline"
OFFLINE=no
[[ -f "$OFFLINE_DIR/MANIFEST" ]] && OFFLINE=yes

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
    case "$arg" in
        --yes|-y) ASSUME_YES=true ;;
        --check) CHECK_ONLY=true ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $arg (see --help)" >&2; exit 2 ;;
    esac
done

# --------------------------------------------------------------------------- output helpers
if [[ -t 1 ]]; then BOLD=$'\e[1m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RED=$'\e[31m'; RESET=$'\e[0m'
else BOLD=""; GREEN=""; YELLOW=""; RED=""; RESET=""; fi

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
touch "$LOG_FILE" 2>/dev/null || LOG_FILE="$MRS_ROOT/install.log"
chmod 600 "$LOG_FILE" 2>/dev/null || true
logf() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG_FILE"; }

step() { printf '\n%s== %s%s\n' "$BOLD" "$*" "$RESET"; logf "STEP $*"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$RESET" "$*"; logf "OK $*"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$RESET" "$*"; logf "WARN $*"; WARNINGS=$((WARNINGS + 1)); }
fail() { printf '\n%sInstallation stopped:%s %s\n' "$RED" "$RESET" "$*" >&2
         printf 'Details are in %s. Fix the problem and run the installer again; finished steps are kept.\n' "$LOG_FILE" >&2
         logf "FAIL $*"; exit 1; }
# Run a command, keeping its output in the log; show the log tail if it fails.
run() {
    logf "RUN $*"
    if ! "$@" >>"$LOG_FILE" 2>&1; then
        tail -n 15 "$LOG_FILE" >&2 || true
        fail "this command failed: $*"
    fi
}

ask() {  # ask VAR "Question" "default"
    local var="$1" question="$2" default="$3" answer
    if [[ -n "${!var:-}" ]]; then return; fi
    if $ASSUME_YES || [[ ! -t 0 ]]; then printf -v "$var" '%s' "$default"; return; fi
    read -r -p "  $question [$default]: " answer
    printf -v "$var" '%s' "${answer:-$default}"
}
yes_no() {  # yes_no VAR "Question" yes|no
    local var="$1"
    ask "$@"
    case "${!var,,}" in y|yes|true) printf -v "$var" yes ;; *) printf -v "$var" no ;; esac
}

trap 'logf "ABORTED at line $LINENO"' ERR

# --------------------------------------------------------------------------- 1. checks
check_server() {
    step "1. Checking the server"
    if [[ "${MRS_SKIP_ROOT_CHECK:-}" != "1" && "$(id -u)" -ne 0 ]]; then
        fail "run the installer with sudo: sudo deploy/install.sh"
    fi
    ok "Running as administrator"

    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        if [[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]]; then ok "Ubuntu ${VERSION_ID}"
        else warn "Tested on Ubuntu Server 24.04; this is ${PRETTY_NAME:-unknown}. It may work, but is not supported."; fi
    fi

    local cpus mem_gb disk_gb
    cpus=$(nproc 2>/dev/null || echo 0)
    mem_gb=$(awk '/MemTotal/ {printf "%d", $2/1024/1024 + 0.5}' /proc/meminfo 2>/dev/null || echo 0)
    disk_gb=$(df -BG --output=avail "$MRS_ROOT" 2>/dev/null | tail -1 | tr -dc '0-9' || echo 0)
    if (( cpus >= 4 )); then ok "$cpus processor cores"; else warn "$cpus processor cores (4 or more recommended)"; fi
    if (( mem_gb >= 8 )); then ok "${mem_gb} GB memory"; else warn "${mem_gb} GB memory (8 GB recommended)"; fi
    if (( disk_gb >= 50 )); then ok "${disk_gb} GB free disk"; else warn "${disk_gb} GB free disk (at least 50 GB free recommended, 250 GB disk)"; fi

    local tz
    tz=$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo unknown)
    if [[ "$tz" == "Africa/Addis_Ababa" ]]; then ok "Time zone Africa/Addis_Ababa"
    elif $CHECK_ONLY; then warn "Time zone is $tz; the installer will set Africa/Addis_Ababa"
    else run timedatectl set-timezone Africa/Addis_Ababa; ok "Time zone set to Africa/Addis_Ababa (was $tz)"; fi

    for tool in openssl curl; do
        command -v "$tool" >/dev/null || fail "'$tool' is missing. Install it with: sudo apt install -y $tool"
    done
    ok "openssl and curl present"

    for f in docker-compose.yml .env.example deploy/scripts/make-certs.sh; do
        [[ -f "$f" ]] || fail "$f not found. Run the installer from the unpacked Clinic MRS folder."
    done
    ok "Application files in $MRS_ROOT"

    if [[ "$OFFLINE" == yes ]]; then
        local bundle_version
        bundle_version=$(grep -E '^version=' "$OFFLINE_DIR/MANIFEST" | cut -d= -f2)
        if (cd "$OFFLINE_DIR" && sha256sum --quiet -c SHA256SUMS >/dev/null 2>&1); then
            ok "Offline bundle $bundle_version complete (checksums match); no internet needed"
        else
            fail "the offline bundle is damaged or incomplete (checksums do not match). Copy it again from the USB stick."
        fi
        [[ "$(dpkg --print-architecture 2>/dev/null || echo amd64)" == amd64 ]] || fail "the offline bundle is for x86-64 (amd64) servers"
    fi

    DOCKER_READY=no
    if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
        local server_version
        server_version=$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)
        if [[ -n "$server_version" ]]; then
            ok "Docker $server_version with Compose"
            DOCKER_READY=yes
        else
            DOCKER_READY=stopped
            warn "Docker is installed but not running; the installer will start it"
        fi
    elif $CHECK_ONLY; then
        if [[ "$OFFLINE" == yes ]]; then ok "Docker is not installed; it will be installed from the offline bundle"
        else warn "Docker is not installed; the installer can install it (needs internet)"; fi
    fi

    for port in 80 443; do
        if command -v ss >/dev/null && ss -ltn "sport = :$port" 2>/dev/null | grep -q LISTEN; then
            if ! docker compose ps --status running 2>/dev/null | grep -q web; then
                warn "Port $port is already used by another program; stop it or change HTTP_PORT/HTTPS_PORT in .env"
            fi
        fi
    done
}

# --------------------------------------------------------------------------- 2. Docker
install_docker() {
    step "2. Docker"
    if [[ "$DOCKER_READY" == yes ]]; then ok "Already installed"; return; fi
    if [[ "$DOCKER_READY" == stopped ]]; then
        run systemctl enable --now docker
        docker version --format '{{.Server.Version}}' >/dev/null 2>&1 || fail "Docker would not start (see: systemctl status docker)"
        ok "Docker started"; return
    fi
    if [[ "$OFFLINE" == yes ]]; then
        # Packages downloaded by make-offline-bundle.sh from Docker's official repository.
        run dpkg -i "$OFFLINE_DIR"/debs/*.deb
        run systemctl enable --now docker
        docker version --format '{{.Server.Version}}' >/dev/null 2>&1 || fail "Docker would not start (see: systemctl status docker)"
        ok "Docker installed from the offline bundle"
        return
    fi
    yes_no MRS_INSTALL_DOCKER "Docker is not installed. Install it now from Docker's official repository? (needs internet)" yes
    [[ "$MRS_INSTALL_DOCKER" == yes ]] || fail "Docker is required. Install it (https://docs.docker.com/engine/install/ubuntu/) and run the installer again."
    # Docker's documented procedure for Ubuntu.
    run apt-get update
    run apt-get install -y ca-certificates curl
    run install -m 0755 -d /etc/apt/keyrings
    run curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    run chmod a+r /etc/apt/keyrings/docker.asc
    # shellcheck disable=SC1091
    local codename; codename=$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
        "$(dpkg --print-architecture)" "$codename" > /etc/apt/sources.list.d/docker.list
    run apt-get update
    run apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    run systemctl enable --now docker
    ok "Docker installed"
}

# --------------------------------------------------------------------------- 3. settings
detect_address() {
    ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}' \
        || hostname -I 2>/dev/null | awk '{print $1}'
}

secret() { openssl rand -base64 96 | tr -d '\n/+=' | cut -c1-64; }

set_env() {  # set_env KEY VALUE  (replace the line, or add it)
    local key="$1" value="$2" tmp
    tmp=$(mktemp)
    if grep -q "^${key}=" .env; then
        awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' .env > "$tmp"
    else
        cat .env > "$tmp"; printf '%s=%s\n' "$key" "$value" >> "$tmp"
    fi
    cat "$tmp" > .env; rm -f "$tmp"
}
env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2-; }

write_settings() {
    step "3. Settings (.env)"
    local default_ip; default_ip=$(detect_address); default_ip="${default_ip:-192.168.1.10}"

    if [[ -f .env ]]; then
        ok "Existing .env kept (secrets are not changed)"
        MRS_ADDRESS="${MRS_ADDRESS:-$(env_value DJANGO_ALLOWED_HOSTS | cut -d, -f1)}"
        MRS_DNS_NAME="${MRS_DNS_NAME:-$(env_value DJANGO_ALLOWED_HOSTS | cut -d, -f2)}"
        MRS_HTTPS="${MRS_HTTPS:-$(env_value MRS_HTTPS)}"
        if [[ "$(env_value DJANGO_SECRET_KEY)" == CHANGE-ME* ]]; then
            set_env DJANGO_SECRET_KEY "$(secret)"; ok "Placeholder secret key replaced"
        fi
        if [[ "$(env_value POSTGRES_PASSWORD)" == CHANGE-ME* ]]; then
            if docker volume ls -q 2>/dev/null | grep -q pgdata; then
                fail ".env still has the placeholder database password but a database already exists. Put the real password in .env."
            fi
            set_env POSTGRES_PASSWORD "$(secret)"; ok "Placeholder database password replaced"
        fi
    else
        echo "  A few questions. Press Enter to accept the suggestion in brackets."
        ask MRS_ADDRESS "Fixed IP address of this server (set a DHCP reservation in the router)" "$default_ip"
        ask MRS_DNS_NAME "Local name staff may type instead of the address" "mrs.clinic.local"
        yes_no MRS_HTTPS "Use HTTPS? (strongly recommended; 'no' only for a trial with synthetic data)" yes
        ask MRS_FACILITY_CODE "Short clinic code (letters, used in record numbers)" "CLN"
        ask MRS_BACKUP_DIR "Folder for backups on this server" "/var/backups/mrs"
        ask MRS_BACKUP_COPY_DIR "Mounted external drive for a second backup copy (leave empty for none)" ""

        [[ "$MRS_ADDRESS" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || fail "'$MRS_ADDRESS' is not an IPv4 address like 192.168.1.10"
        [[ "$MRS_FACILITY_CODE" =~ ^[A-Za-z]{2,6}$ ]] || fail "The clinic code must be 2 to 6 letters"

        local scheme=https; [[ "$MRS_HTTPS" == yes ]] || scheme=http
        umask 077
        cp .env.example .env
        chmod 600 .env
        set_env DJANGO_DEBUG false
        set_env DJANGO_SECRET_KEY "$(secret)"
        set_env POSTGRES_PASSWORD "$(secret)"
        set_env DJANGO_ALLOWED_HOSTS "${MRS_ADDRESS},${MRS_DNS_NAME},localhost"
        set_env DJANGO_CSRF_TRUSTED_ORIGINS "${scheme}://${MRS_ADDRESS},${scheme}://${MRS_DNS_NAME}"
        set_env MRS_HTTPS "$([[ "$MRS_HTTPS" == yes ]] && echo true || echo false)"
        set_env MRS_FACILITY_CODE "${MRS_FACILITY_CODE^^}"
        set_env BACKUP_DIR "$MRS_BACKUP_DIR"
        set_env BACKUP_COPY_DIR "$MRS_BACKUP_COPY_DIR"
        ok ".env written with new random secrets (readable by administrators only)"
    fi
    chmod 600 .env
    MRS_HTTPS_ON=$([[ "$(env_value MRS_HTTPS)" == "false" ]] && echo no || echo yes)
    if [[ "$MRS_HTTPS_ON" == no ]]; then
        warn "HTTPS is off: passwords cross the network unencrypted. Use only for a trial with synthetic data."
    fi
}

# --------------------------------------------------------------------------- 4. certificates
make_certificates() {
    step "4. HTTPS certificate"
    if [[ "$MRS_HTTPS_ON" == no ]]; then ok "Skipped (HTTPS off)"; return; fi
    if [[ -f deploy/certs/server.crt && -f deploy/certs/server.key ]]; then
        ok "Existing certificate kept (expires $(openssl x509 -enddate -noout -in deploy/certs/server.crt | cut -d= -f2))"
        return
    fi
    run deploy/scripts/make-certs.sh "${MRS_ADDRESS}" "${MRS_DNS_NAME:-mrs.clinic.local}"
    ok "Certificate created for ${MRS_ADDRESS} and ${MRS_DNS_NAME:-mrs.clinic.local}"
}

# The phone app trusts this certificate through the activation QR code, without asking staff to compare
# fingerprints. Runs every time so a renewed certificate is picked up.
pin_certificate_for_phones() {
    [[ "$MRS_HTTPS_ON" == yes && -f deploy/certs/server.crt ]] || return 0
    set_env MOBILE_TLS_CERT_SHA256 "$(openssl x509 -noout -fingerprint -sha256 -in deploy/certs/server.crt | cut -d= -f2)"
    ok "Certificate fingerprint recorded for phone activation"
}

# --------------------------------------------------------------------------- 5. start
health_url() {
    if [[ "$MRS_HTTPS_ON" == yes ]]; then echo "https://localhost:$(env_value HTTPS_PORT | sed 's/^$/443/')/api/v1/health/"
    else echo "http://localhost:$(env_value HTTP_PORT | sed 's/^$/80/')/api/v1/health/"; fi
}

start_application() {
    step "5. Building and starting the application (first time: 5 to 15 minutes)"
    if [[ "$OFFLINE" == yes ]]; then
        local bundle_version
        bundle_version=$(grep -E '^version=' "$OFFLINE_DIR/MANIFEST" | cut -d= -f2)
        run docker load -i "$OFFLINE_DIR/images.tar.gz"
        set_env MRS_VERSION "$bundle_version"
        ok "Images $bundle_version loaded from the offline bundle"
    else
        run docker compose build
        ok "Images built"
    fi
    run docker compose up -d db
    local i
    for i in $(seq 1 60); do
        docker compose exec -T db pg_isready -q >/dev/null 2>&1 && break
        sleep 2
        if (( i == 60 )); then fail "the database did not start within 2 minutes (see: docker compose logs db)"; fi
    done
    ok "Database running"
    run docker compose run --rm api python manage.py migrate --noinput
    ok "Database tables up to date"
    run docker compose up -d --no-build
    local url; url=$(health_url)
    for i in $(seq 1 60); do
        if curl -fsk --max-time 5 "$url" 2>/dev/null | grep -q '"status": *"ok"'; then ok "Application answering at $url"; return; fi
        sleep 3
    done
    fail "the application did not become healthy within 3 minutes (see: docker compose ps; docker compose logs api)"
}

# --------------------------------------------------------------------------- 6. first data
first_data() {
    step "6. First administrator and starter catalogue"
    local out
    if out=$(docker compose exec -T api python manage.py bootstrap_admin 2>&1); then
        ADMIN_MESSAGE=$(printf '%s\n' "$out" | grep -E "Created|Temporary password" || true)
        logf "bootstrap_admin: administrator created (password not logged)"
        ok "System administrator account 'admin' created"
    elif grep -q "already exists" <<<"$out"; then
        ADMIN_MESSAGE=""
        ok "A system administrator already exists; nothing changed"
    else
        logf "$out"; fail "could not create the first administrator"
    fi
    yes_no MRS_LOAD_CATALOG "Load the starter catalogue (example services, laboratory tests and medicines, no stock)?" yes
    if [[ "$MRS_LOAD_CATALOG" == yes ]]; then
        run docker compose exec -T api python manage.py load_starter_catalog
        ok "Starter catalogue loaded. Review every price before use."
    fi
}

# --------------------------------------------------------------------------- 7. scheduled jobs
install_timers() {
    step "7. Scheduled jobs (backups, verification, reminders, email)"
    yes_no MRS_INSTALL_TIMERS "Install the nightly backup and daily jobs?" yes
    if [[ "$MRS_INSTALL_TIMERS" != yes ]]; then warn "Scheduled jobs not installed: there will be NO automatic backups"; return; fi
    local backup_dir; backup_dir=$(env_value BACKUP_DIR); backup_dir="${backup_dir:-/var/backups/mrs}"
    run mkdir -p "$backup_dir"
    run chmod 700 "$backup_dir"
    local unit
    for unit in mrs-backup mrs-backup-verify mrs-reminders mrs-email mrs-visits mrs-payments; do
        for kind in service timer; do
            [[ -f "deploy/systemd/$unit.$kind" ]] || continue
            # The unit files assume /opt/mrs; point them at wherever this copy lives.
            sed "s#/opt/mrs#${MRS_ROOT}#g" "deploy/systemd/$unit.$kind" > "$SYSTEMD_DIR/$unit.$kind"
        done
    done
    run systemctl daemon-reload
    run systemctl enable --now mrs-backup.timer mrs-backup-verify.timer mrs-reminders.timer mrs-email.timer mrs-visits.timer mrs-payments.timer
    ok "Timers installed: nightly backup, backup check, daily reminders, email sender, finished-visit closing"

    local file
    if file=$(deploy/scripts/backup.sh manual 2>>"$LOG_FILE"); then
        run deploy/scripts/verify-backup.sh "$file"
        ok "First backup made and checked: $file"
    else
        fail "the first backup failed"
    fi
}

# --------------------------------------------------------------------------- 8. hardening
harden() {
    step "8. Server security"
    yes_no MRS_HARDEN "Apply the recommended server security settings now (firewall, automatic security updates, SSH)?" yes
    if [[ "$MRS_HARDEN" == yes && -x deploy/scripts/harden-server.sh ]]; then
        run env LAN_CIDR="${MRS_LAN_CIDR:-${MRS_ADDRESS%.*}.0/24}" deploy/scripts/harden-server.sh
        ok "Server hardened (see docs/operations/security-checklist.md)"
    else
        warn "Hardening skipped. Run deploy/scripts/harden-server.sh before real patients are registered."
    fi
    if [[ -x deploy/scripts/security-check.sh ]]; then
        if deploy/scripts/security-check.sh >>"$LOG_FILE" 2>&1; then ok "Security check passed"
        else warn "Security check found items to fix; run deploy/scripts/security-check.sh to see them"; fi
    fi
}

# --------------------------------------------------------------------------- summary
summary() {
    local scheme=https; [[ "$MRS_HTTPS_ON" == yes ]] || scheme=http
    printf '\n%sClinic MRS is installed.%s\n\n' "$BOLD$GREEN" "$RESET"
    printf '  Open:            %s://%s\n' "$scheme" "$MRS_ADDRESS"
    if [[ -n "${MRS_DNS_NAME:-}" ]]; then
        printf '                   %s://%s (after the name is set up in the router)\n' "$scheme" "$MRS_DNS_NAME"
    fi
    if [[ -n "${ADMIN_MESSAGE:-}" ]]; then
        printf '\n  %sFirst sign-in%s (write this down now; it is not shown again):\n' "$BOLD" "$RESET"
        printf '  Username:        admin\n'
        printf '  %s\n' "$(grep 'Temporary password' <<<"$ADMIN_MESSAGE" | sed 's/.*: //;s/^/Password:        /')"
        printf '  You must choose a new password and set up two-step sign-in at first sign-in.\n'
    fi
    if [[ "$MRS_HTTPS_ON" == yes ]]; then
        printf '\n  Install %s/deploy/certs/clinic-ca.crt on every computer that will use the system\n' "$MRS_ROOT"
        printf '  (docs/operations/install.md, step 4). Keep clinic-ca.key on offline storage.\n'
    fi
    local iid
    if iid=$(docker compose exec -T api python manage.py show_installation_id 2>/dev/null); then
        printf '\n  Phone app:       send this installation ID to your supplier for the app licence:\n'
        printf '                   %s\n' "$iid"
    fi
    printf '\n  Next: create a named account for every staff member, set the clinic details and logo,\n'
    printf '  review prices, and plug in the external backup drive. See docs/manuals/clinic-administrator.md.\n'
    if (( WARNINGS > 0 )); then
        printf '\n  %s%d warning(s) above.%s Install log: %s\n' "$YELLOW" "$WARNINGS" "$RESET" "$LOG_FILE"
    fi
    printf '\n'
}

# --------------------------------------------------------------------------- main
logf "==== installer started in $MRS_ROOT (check-only=$CHECK_ONLY, yes=$ASSUME_YES, offline=$OFFLINE)"
printf '%sClinic MRS installer%s  (log: %s)\n' "$BOLD" "$RESET" "$LOG_FILE"
check_server
if $CHECK_ONLY; then
    printf '\nCheck finished with %d warning(s). Nothing was changed.\n' "$WARNINGS"
    exit 0
fi
install_docker
write_settings
make_certificates
pin_certificate_for_phones
start_application
first_data
install_timers
harden
summary
logf "==== installer finished with $WARNINGS warning(s)"
