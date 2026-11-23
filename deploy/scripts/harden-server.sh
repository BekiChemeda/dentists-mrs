#!/usr/bin/env bash
# One-time hardening of a clinic server (Ubuntu Server 24.04). Run as root after installing the system.
# Safe to run again. Prints what it changes. See docs/operations/security-checklist.md.
#
#   sudo LAN_CIDR=192.168.1.0/24 deploy/scripts/harden-server.sh
#
# LAN_CIDR: the clinic network allowed to reach SSH (default: the server's own /24).
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root (sudo)." >&2; exit 1; }
MRS_ROOT="${MRS_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
say() { printf '\n== %s\n' "$*"; }

default_cidr() { ip -o -4 addr show scope global | awk '{print $4}' | head -n1 | sed -E 's#\.[0-9]+/[0-9]+$#.0/24#'; }
LAN_CIDR="${LAN_CIDR:-$(default_cidr)}"
[[ -n "$LAN_CIDR" ]] || { echo "Could not work out the LAN; set LAN_CIDR." >&2; exit 1; }

say "Packages: automatic security updates, firewall, brute-force protection, time sync"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q unattended-upgrades ufw fail2ban chrony >/dev/null
# Two-step sign-in codes depend on correct time; chrony keeps the clock right.
systemctl enable --now chrony >/dev/null
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
echo "Security updates install automatically every day."

say "Firewall: web from anywhere on the LAN, SSH only from $LAN_CIDR, nothing else in"
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow from "$LAN_CIDR" to any port 22 proto tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ufw status verbose | sed 's/^/  /'
echo "Note: the database and API containers publish no ports (docker-compose.yml), so Docker's own"
echo "firewall rules do not expose them."

say "SSH"
mkdir -p /etc/ssh/sshd_config.d
keys_present=false
for d in /root /home/*; do [[ -s "$d/.ssh/authorized_keys" ]] && keys_present=true; done
{
    echo "# Clinic MRS hardening"
    echo "PermitRootLogin no"
    echo "MaxAuthTries 4"
    echo "X11Forwarding no"
    echo "LoginGraceTime 30"
    if $keys_present; then echo "PasswordAuthentication no"; echo "KbdInteractiveAuthentication no"; fi
} > /etc/ssh/sshd_config.d/60-mrs.conf
sshd -t && systemctl reload ssh 2>/dev/null || systemctl reload sshd
if $keys_present; then
    echo "SSH: keys only, no root login."
else
    echo "WARNING: no SSH keys found, so password sign-in is still allowed (to avoid locking you out)."
    echo "         Add a key to ~/.ssh/authorized_keys and run this script again."
fi
cat > /etc/fail2ban/jail.d/mrs.local <<'EOF'
[sshd]
enabled = true
maxretry = 5
bantime = 1h
EOF
systemctl enable --now fail2ban >/dev/null && systemctl restart fail2ban
echo "fail2ban blocks addresses after 5 failed SSH sign-ins."

say "Secrets and backups: owner-only permissions"
for f in "$MRS_ROOT/.env" /etc/mrs/offsite.key; do
    [[ -e "$f" ]] && chmod 600 "$f" && echo "  600 $f"
done
for d in "${BACKUP_DIR:-/var/backups/mrs}" "$MRS_ROOT/deploy/certs"; do
    [[ -d "$d" ]] && chmod 700 "$d" && echo "  700 $d"
done

say "Kernel network settings"
cat > /etc/sysctl.d/60-mrs.conf <<'EOF'
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.all.rp_filter = 1
net.ipv4.tcp_syncookies = 1
kernel.dmesg_restrict = 1
EOF
sysctl -q --system
echo "Applied."

say "Done. Now run: deploy/scripts/security-check.sh"
