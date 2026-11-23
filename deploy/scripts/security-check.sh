#!/usr/bin/env bash
# Read-only security check of a clinic installation. Changes nothing. Exit code 1 if anything FAILS.
#   sudo deploy/scripts/security-check.sh
# Run after installation, after upgrades, and monthly. See docs/operations/security-checklist.md.
source "$(dirname "$0")/common.sh"
set +eu
API_EXEC="${API_EXEC:-docker compose exec -T api python manage.py}"
fails=0; warns=0
pass() { printf '  PASS  %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*"; warns=$((warns + 1)); }
fail() { printf '  FAIL  %s\n' "$*"; fails=$((fails + 1)); }
check() { local ok="$1"; shift; if [[ "$ok" == 0 ]]; then pass "$1"; else ${3:-fail} "$2"; fi; }
has() { command -v "$1" >/dev/null; }

echo "Server"
lsblk -rno TYPE 2>/dev/null | grep -qx crypt; check $? "Disk encryption (LUKS) in use" \
    "Disk is not encrypted: a stolen server exposes all patient data (reinstall with encryption)"
if has ufw; then ufw status 2>/dev/null | grep -q "Status: active"; check $? "Firewall active" "Firewall (ufw) is off"
else fail "ufw not installed (run harden-server.sh)"; fi
[[ -f /etc/apt/apt.conf.d/20auto-upgrades ]] && grep -q 'Unattended-Upgrade "1"' /etc/apt/apt.conf.d/20auto-upgrades
check $? "Automatic security updates" "Automatic security updates are off" warn
if has sshd; then
    sshd -T 2>/dev/null | grep -qi '^passwordauthentication no'; check $? "SSH: keys only" "SSH accepts passwords" warn
    sshd -T 2>/dev/null | grep -qi '^permitrootlogin no'; check $? "SSH: no root login" "SSH allows root login"
fi
timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -q yes
check $? "Clock synchronised (needed for two-step codes)" "Clock not synchronised: two-step codes may fail" warn
systemctl is-active --quiet fail2ban 2>/dev/null; check $? "fail2ban running" "fail2ban not running" warn

echo "Configuration (.env)"
if [[ -f .env ]]; then
    perm="$(stat -c %a .env)"; [[ "$perm" == "600" || "$perm" == "400" ]]
    check $? ".env readable by owner only" ".env permissions are $perm (should be 600)"
else fail ".env missing"; fi
[[ "${DJANGO_DEBUG:-false}" != "true" ]]; check $? "Debug mode off" "DJANGO_DEBUG=true on a real server"
[[ "${MRS_HTTPS:-true}" == "true" ]]; check $? "HTTPS on" "MRS_HTTPS is not true"
key="${DJANGO_SECRET_KEY:-}"; (( ${#key} >= 50 )); check $? "Secret key is long" "DJANGO_SECRET_KEY shorter than 50 characters"
pw="${POSTGRES_PASSWORD:-}"; (( ${#pw} >= 20 )); check $? "Database password is long" "POSTGRES_PASSWORD shorter than 20 characters"
cert="deploy/certs/server.crt"
if [[ -f "$cert" ]]; then
    openssl x509 -checkend $((30 * 86400)) -noout -in "$cert" >/dev/null
    check $? "Certificate valid for 30+ days" "Certificate expires within 30 days" warn
else warn "No certificate at $cert"; fi
grep -q '"5432:' docker-compose.yml; [[ $? != 0 ]]; check $? "Database port not published" "Database port is published"

echo "Application"
status="$($API_EXEC shell -c "
from apps.core.models import SystemSettings as S
from apps.accounts.models import User
s = S.get()
print('mfa', s.mfa_required_for)
print('dormant', s.dormant_account_days)
print('maint', s.maintenance_mode)
demo = ['reception','nurse','doctor','lab','pharmacy','cashier','store','manager','director']
print('demo', User.objects.filter(username__in=demo, is_active=True).count())
" 2>/dev/null)"
if [[ -n "$status" ]]; then
    [[ "$(awk '/^mfa/{print $2}' <<<"$status")" != "off" ]]
    check $? "Two-step sign-in required for administrators" "Two-step sign-in is optional for everyone"
    [[ "$(awk '/^dormant/{print $2}' <<<"$status")" != "0" ]]; check $? "Unused accounts switched off automatically" "Unused-account review is off" warn
    [[ "$(awk '/^demo/{print $2}' <<<"$status")" == "0" ]]; check $? "No demo accounts" "Demo accounts exist (shared demo password): deactivate them"
    $API_EXEC verify_audit_chain --quiet >/dev/null 2>&1; check $? "Audit log chain intact" "Audit log chain is BROKEN"
    $API_EXEC check --deploy --fail-level ERROR >/dev/null 2>&1; check $? "Django deployment check" "Django deployment check reports errors"
else
    fail "Could not reach the application (is it running?)"
fi

echo "Backups"
systemctl is-enabled --quiet mrs-backup.timer 2>/dev/null; check $? "Nightly backup timer enabled" "Nightly backup timer not enabled"
newest="$(find "$BACKUP_DIR" -name 'mrs-*.dump' -mtime -2 2>/dev/null | head -n1)"
[[ -n "$newest" ]]; check $? "A local backup from the last 2 days exists" "No local backup in the last 2 days"
if [[ -n "${BACKUP_COPY_DIR:-}" ]]; then
    ls "$BACKUP_COPY_DIR"/*.dump >/dev/null 2>&1; [[ $? != 0 ]]
    check $? "External-drive copies are encrypted" "Unencrypted backups on the external drive" warn
fi
off="$($API_EXEC offsite status 2>/dev/null)"
grep -q '"enabled": true' <<<"$off"; check $? "Off-site backup on" "Off-site backup is off (fire/theft would lose everything)" warn
grep -q '"overdue": true' <<<"$off"; [[ $? != 0 ]]; check $? "Off-site backup not overdue" "Off-site backup is overdue"

echo
echo "Result: $fails failure(s), $warns warning(s)."
(( fails == 0 ))
