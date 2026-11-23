#!/usr/bin/env bash
# Tests deploy/install.sh without Docker or root: runs it in a throw-away copy of the application with
# stand-in `docker`, `curl`, `systemctl` and `timedatectl` commands, and checks what it wrote.
#
#   deploy/scripts/test-install.sh
#
# It checks: secrets are random and private, nothing secret reaches the install log, certificates and
# scheduled jobs are set up, a second run keeps everything, --check changes nothing, bad answers stop it.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
pass=0
ok() { printf '  PASS  %s\n' "$*"; pass=$((pass + 1)); }
bad() { printf '  FAIL  %s\n' "$*"; exit 1; }

make_copy() {
    local dir="$1"
    mkdir -p "$dir/deploy/certs" "$dir/deploy/scripts"
    cp "$SRC/docker-compose.yml" "$SRC/.env.example" "$dir/"
    cp "$SRC/deploy/install.sh" "$dir/deploy/"
    cp -r "$SRC/deploy/systemd" "$dir/deploy/"
    cp "$SRC/deploy/scripts/make-certs.sh" "$dir/deploy/scripts/"
    # Operations scripts that need a real database are replaced by stand-ins.
    printf '#!/usr/bin/env bash\nf="%s/backups/manual/test.dump"; mkdir -p "${f%%/*}"; echo dump > "$f"; echo "$f"\n' "$WORK" \
        > "$dir/deploy/scripts/backup.sh"
    printf '#!/usr/bin/env bash\necho "verified $1"\n' > "$dir/deploy/scripts/verify-backup.sh"
    printf '#!/usr/bin/env bash\necho "hardened LAN=$LAN_CIDR" >> "%s/calls"\n' "$WORK" > "$dir/deploy/scripts/harden-server.sh"
    printf '#!/usr/bin/env bash\necho "PASS all"\n' > "$dir/deploy/scripts/security-check.sh"
    chmod +x "$dir"/deploy/scripts/*.sh "$dir/deploy/install.sh"
}

# Stand-in commands, recording every call.
BIN="$WORK/bin"; mkdir -p "$BIN"
cat > "$BIN/docker" <<EOF
#!/usr/bin/env bash
echo "docker \$*" >> "$WORK/calls"
# Offline test: Docker counts as not installed until the stand-in dpkg has "installed" it.
if [[ -f "$WORK/no-docker" ]]; then case "\$*" in "compose version"|"version --format"*) exit 1 ;; esac; fi
case "\$*" in
  "compose version") echo "Docker Compose version v2.30" ;;
  "version --format"*) echo "27.3.1" ;;
  *"bootstrap_admin"*)
     if [[ -f "$WORK/admin-made" ]]; then echo "CommandError: An active system administrator already exists. Nothing done." >&2; exit 1; fi
     touch "$WORK/admin-made"
     echo "Created system administrator 'admin'."
     echo "Temporary password (shown once, must be changed at first sign-in): Tmp-Test-Secret-9931" ;;
  "volume ls -q") ;;
  *) ;;
esac
EOF
cat > "$BIN/curl" <<EOF
#!/usr/bin/env bash
echo "curl \$*" >> "$WORK/calls"
echo '{"status": "ok", "database": "ok"}'
EOF
cat > "$BIN/dpkg" <<EOF
#!/usr/bin/env bash
echo "dpkg \$*" >> "$WORK/calls"
[[ "\$1" == "--print-architecture" ]] && { echo amd64; exit 0; }
rm -f "$WORK/no-docker"
EOF
cat > "$BIN/apt-get" <<EOF
#!/usr/bin/env bash
echo "apt-get \$*" >> "$WORK/calls"
EOF
chmod +x "$BIN/dpkg" "$BIN/apt-get"
cat > "$BIN/systemctl" <<EOF
#!/usr/bin/env bash
echo "systemctl \$*" >> "$WORK/calls"
EOF
cat > "$BIN/timedatectl" <<'EOF'
#!/usr/bin/env bash
[[ "$1" == show ]] && echo "Africa/Addis_Ababa"
EOF
chmod +x "$BIN"/*
export PATH="$BIN:$PATH" MRS_SKIP_ROOT_CHECK=1

run_installer() {  # run_installer DIR [extra args...]
    local dir="$1"; shift
    SYSTEMD_DIR="$dir/systemd-units" MRS_INSTALL_LOG="$dir/install.log" "$dir/deploy/install.sh" "$@"
}

echo "Fresh installation"
APP="$WORK/app"; make_copy "$APP"; mkdir -p "$APP/systemd-units"
out=$(MRS_ADDRESS=192.168.20.15 MRS_DNS_NAME=mrs.test.local MRS_HTTPS=yes MRS_FACILITY_CODE=abc \
      MRS_BACKUP_DIR="$WORK/backups" MRS_BACKUP_COPY_DIR="" MRS_LOAD_CATALOG=yes MRS_INSTALL_TIMERS=yes MRS_HARDEN=yes \
      run_installer "$APP" --yes 2>&1) || { echo "$out"; bad "installer failed"; }

[[ -f "$APP/.env" ]] && ok ".env created" || bad ".env missing"
[[ "$(stat -c %a "$APP/.env")" == 600 ]] && ok ".env readable by owner only" || bad ".env permissions $(stat -c %a "$APP/.env")"
key=$(grep '^DJANGO_SECRET_KEY=' "$APP/.env" | cut -d= -f2-)
dbpw=$(grep '^POSTGRES_PASSWORD=' "$APP/.env" | cut -d= -f2-)
[[ ${#key} -ge 50 && "$key" != CHANGE-ME* ]] && ok "secret key random, ${#key} characters" || bad "weak secret key"
[[ ${#dbpw} -ge 32 && "$dbpw" != CHANGE-ME* && "$dbpw" != "$key" ]] && ok "database password random and different" || bad "weak db password"
grep -q '^DJANGO_ALLOWED_HOSTS=192.168.20.15,mrs.test.local,localhost$' "$APP/.env" && ok "allowed hosts set" || bad "allowed hosts"
grep -q '^DJANGO_CSRF_TRUSTED_ORIGINS=https://192.168.20.15,https://mrs.test.local$' "$APP/.env" && ok "trusted origins use https" || bad "origins"
grep -q '^MRS_FACILITY_CODE=ABC$' "$APP/.env" && ok "clinic code upper-cased" || bad "facility code"
grep -q '^DJANGO_DEBUG=false$' "$APP/.env" && ok "debug off" || bad "debug"
if grep -qF -e "$key" -e "$dbpw" -e "Tmp-Test-Secret-9931" "$APP/install.log"; then bad "a secret reached the install log"
else ok "no secret in the install log"; fi
grep -q "Tmp-Test-Secret-9931" <<<"$out" && ok "one-time admin password shown on screen once" || bad "admin password not shown"
if grep -qF -e "$key" -e "$dbpw" <<<"$out"; then bad "a secret was printed"; else ok "secrets not printed"; fi
openssl x509 -in "$APP/deploy/certs/server.crt" -noout -ext subjectAltName 2>/dev/null | grep -q "IP Address:192.168.20.15" \
    && ok "certificate covers the server address" || bad "certificate SAN"
[[ "$(stat -c %a "$APP/deploy/certs/server.key")" == 600 ]] && ok "certificate key private" || bad "key permissions"
grep -q "WorkingDirectory=$APP" "$APP/systemd-units/mrs-backup.service" && ok "scheduled jobs point at this folder" || bad "unit path"
grep -q "/opt/mrs" "$APP"/systemd-units/* && bad "unit still refers to /opt/mrs" || ok "no stale /opt/mrs paths"
grep -q "systemctl enable --now mrs-backup.timer" "$WORK/calls" && ok "backup timer enabled" || bad "timers"
grep -q "migrate --noinput" "$WORK/calls" && ok "database migrated" || bad "migrate"
grep -q "load_starter_catalog" "$WORK/calls" && ok "starter catalogue loaded" || bad "catalogue"
grep -q "hardened LAN=192.168.20.0/24" "$WORK/calls" && ok "hardening limited SSH to the clinic network" || bad "harden"
grep -q "verified $WORK/backups/manual/test.dump" "$APP/install.log" && ok "first backup made and checked" || bad "first backup"

echo "Running again keeps everything"
env_hash=$(sha256sum "$APP/.env"); crt_hash=$(sha256sum "$APP/deploy/certs/server.crt")
: > "$WORK/calls"
out2=$(MRS_LOAD_CATALOG=no MRS_INSTALL_TIMERS=yes MRS_HARDEN=no run_installer "$APP" --yes 2>&1) || { echo "$out2"; bad "second run failed"; }
[[ "$(sha256sum "$APP/.env")" == "$env_hash" ]] && ok ".env and its secrets unchanged" || bad ".env changed"
[[ "$(sha256sum "$APP/deploy/certs/server.crt")" == "$crt_hash" ]] && ok "certificate unchanged" || bad "cert changed"
grep -q "already exists" <<<"$out2" && ok "existing administrator left alone" || bad "admin handling"
grep -q "Tmp-Test-Secret" <<<"$out2" && bad "password shown again" || ok "no new password on re-run"

echo "--check changes nothing"
CHK="$WORK/check"; make_copy "$CHK"; mkdir -p "$CHK/systemd-units"
run_installer "$CHK" --check >/dev/null 2>&1 || bad "--check failed"
[[ ! -f "$CHK/.env" && -z "$(ls "$CHK/systemd-units")" && ! -f "$CHK/deploy/certs/server.crt" ]] && ok "no files written" || bad "--check wrote files"

echo "Bad answers stop the installer"
BAD="$WORK/bad"; make_copy "$BAD"; mkdir -p "$BAD/systemd-units"
if msg=$(MRS_ADDRESS=clinic-server MRS_INSTALL_TIMERS=no run_installer "$BAD" --yes 2>&1); then bad "accepted a bad address"
else grep -q "not an IPv4 address" <<<"$msg" && ok "bad address refused with a clear message" || bad "unclear message: $msg"; fi
[[ ! -f "$BAD/.env" ]] && ok "nothing written after a refused answer" || bad ".env written"

echo "Trial mode without HTTPS"
HTTP="$WORK/http"; make_copy "$HTTP"; mkdir -p "$HTTP/systemd-units"
outh=$(MRS_ADDRESS=10.0.0.5 MRS_HTTPS=no MRS_INSTALL_TIMERS=no MRS_HARDEN=no MRS_LOAD_CATALOG=no run_installer "$HTTP" --yes 2>&1) \
    || { echo "$outh"; bad "http install failed"; }
grep -q '^MRS_HTTPS=false$' "$HTTP/.env" && ok "HTTPS off when asked" || bad "https flag"
grep -q "unencrypted" <<<"$outh" && ok "warned that passwords are unencrypted" || bad "no warning"
grep -q "NO automatic backups" <<<"$outh" && ok "warned when backups are not scheduled" || bad "no backup warning"

echo "Offline bundle: no internet at the clinic"
OFF="$WORK/offline"; make_copy "$OFF"; mkdir -p "$OFF/systemd-units" "$OFF/offline/debs"
printf 'version=1.4.0\ncommit=abc\nubuntu=24.04\narch=amd64\n' > "$OFF/offline/MANIFEST"
echo "image layers" > "$OFF/offline/images.tar.gz"
echo "deb" > "$OFF/offline/debs/docker-ce.deb"
(cd "$OFF/offline" && find . -type f ! -name SHA256SUMS -printf '%P\n' | sort | xargs sha256sum > SHA256SUMS)
: > "$WORK/calls"; touch "$WORK/no-docker"; rm -f "$WORK/admin-made"
outo=$(MRS_ADDRESS=10.0.0.9 MRS_HTTPS=no MRS_INSTALL_TIMERS=no MRS_HARDEN=no MRS_LOAD_CATALOG=no run_installer "$OFF" --yes 2>&1) \
    || { echo "$outo"; bad "offline install failed"; }
grep -q "Offline bundle 1.4.0 complete" <<<"$outo" && ok "bundle checksums verified before use" || bad "bundle not verified"
grep -q "dpkg -i $OFF/offline/debs/docker-ce.deb" "$WORK/calls" && ok "Docker installed from the bundle's packages" || bad "docker debs"
grep -q "docker load -i $OFF/offline/images.tar.gz" "$WORK/calls" && ok "images loaded from the bundle" || bad "docker load"
grep -q "docker compose build" "$WORK/calls" && bad "tried to build images (needs internet)" || ok "no image build"
grep -qE "^(apt-get|curl) .*(download|update|https://download)" "$WORK/calls" && bad "tried to download" || ok "nothing downloaded"
grep -q '^MRS_VERSION=1.4.0$' "$OFF/.env" && ok "uses the bundle's image version" || bad "MRS_VERSION"

echo "Damaged offline bundle is refused"
DMG="$WORK/damaged"; cp -r "$OFF" "$DMG"; rm -f "$DMG/.env"; echo "corrupt" >> "$DMG/offline/images.tar.gz"
if msg=$(MRS_ADDRESS=10.0.0.9 MRS_INSTALL_TIMERS=no run_installer "$DMG" --yes 2>&1); then bad "accepted a damaged bundle"
else grep -q "damaged or incomplete" <<<"$msg" && ok "damaged bundle refused with a clear message" || bad "unclear: $msg"; fi
[[ ! -f "$DMG/.env" ]] && ok "nothing written from a damaged bundle" || bad ".env written"

printf '\nAll %d installer checks passed.\n' "$pass"
