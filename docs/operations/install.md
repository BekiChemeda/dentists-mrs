# Installation (Ubuntu Server 24.04 LTS)

Time needed: about one hour. Needs internet **only during installation** (to download Docker and images); daily use does not. With an **offline bundle** (below) no internet is needed at the clinic at all.

## Guided installer (recommended)

After step 1 below (hardware, fixed address) and with the application in `/opt/mrs`:

```bash
cd /opt/mrs
sudo deploy/install.sh --check   # checks the server and changes nothing
sudo deploy/install.sh           # asks a few questions, then does steps 2 to 7 below
```

The installer checks the hardware, time zone and ports; installs Docker from Docker's official
repository if missing; writes `.env` with new random secrets (mode 600); creates the HTTPS
certificate; builds and starts the application and waits until it is healthy; creates the first
administrator and shows the one-time password once; optionally loads the starter catalogue; installs
the scheduled jobs and makes and checks a first backup; and offers to run `harden-server.sh`.

It is safe to run again: an existing `.env`, its secrets, certificates and the database are kept.
Answers can be given in advance for unattended installs (`MRS_ADDRESS`, `MRS_DNS_NAME`, `MRS_HTTPS`,
`MRS_FACILITY_CODE`, `MRS_BACKUP_DIR`, `MRS_BACKUP_COPY_DIR`, `MRS_LOAD_CATALOG`, `MRS_INSTALL_TIMERS`,
`MRS_HARDEN`, `MRS_INSTALL_DOCKER`) with `--yes`; see `deploy/install.sh --help`. The log is
`/var/log/mrs-install.log`; no secret is written to it.

## Installing without internet (offline bundle)

Many clinics have slow or no internet. Prepare a bundle in the office, carry it on a USB stick.

**In the office** (any Ubuntu 24.04 x86-64 machine with Docker and internet, in the application folder
at the commit you want to install):

```bash
deploy/scripts/make-offline-bundle.sh 1.4.0
# -> dist/mrs-offline-1.4.0.tar (about 1 GB) and dist/mrs-offline-1.4.0.tar.sha256
```

The bundle holds the application files, the three container images already built (API, web,
PostgreSQL 16), Docker Engine and Compose packages for Ubuntu 24.04 with their dependencies, a
manifest and checksums. Build a new bundle for each release; it is not updated in place.

**At the clinic** (fresh Ubuntu Server 24.04, after step 1 below):

```bash
sha256sum -c mrs-offline-1.4.0.tar.sha256          # the copy is not damaged
sudo tar -xf mrs-offline-1.4.0.tar -C /opt && sudo mv /opt/mrs-1.4.0 /opt/mrs
cd /opt/mrs && sudo deploy/install.sh
```

The installer finds the `offline/` folder by itself, checks every file against its checksum and stops
if anything is damaged, installs Docker from the packages, loads the images instead of building them,
and records the version in `.env` (`MRS_VERSION`). Everything else is the same as above.

The bundle builder needs Docker, so it is not run in CI; the installer's offline path is tested with
stand-in commands in `test-install.sh`. Try a new bundle on a spare machine with no network cable
before taking it to a clinic.

`deploy/scripts/test-install.sh` tests the installer (fresh install, re-run, `--check`, bad answers,
trial mode, offline bundle, damaged bundle) without Docker; it runs in CI.

The rest of this page describes the same steps done by hand.

## 1. Hardware and network

- Server: 4+ CPU cores, 8 GB RAM, SSD (250 GB+), UPS with ≥ 15 minutes runtime.
- Give the server a fixed address, e.g. `192.168.1.10`, by a DHCP reservation in the router.
- Optional: a local DNS name such as `mrs.clinic.local` on the router.
- An external USB drive for second backup copies.

## 2. Prepare the server

```bash
sudo apt update && sudo apt full-upgrade -y
sudo timedatectl set-timezone Africa/Addis_Ababa
sudo apt install -y ca-certificates curl git ufw unattended-upgrades postgresql-client
# Docker Engine (official repository): https://docs.docker.com/engine/install/ubuntu/
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable
```

Note: Docker manages its own firewall rules for published ports. Only ports 80 and 443 of the `web` container are published.

## 3. Get the application

```bash
sudo mkdir -p /opt/mrs && sudo chown "$USER" /opt/mrs
git clone <repository-url> /opt/mrs    # or unpack a release archive
cd /opt/mrs
cp .env.example .env && chmod 600 .env
```

Edit `.env`:

- `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD`: generate each with `openssl rand -base64 48 | tr -d '\n'`.
- `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`: the server IP and DNS name staff will type.

## 4. HTTPS certificate

```bash
deploy/scripts/make-certs.sh 192.168.1.10 mrs.clinic.local
```

Install `deploy/certs/clinic-ca.crt` on every client PC once:

- Windows: double-click the file → Install Certificate → Local Machine → "Trusted Root Certification Authorities".
- Ubuntu clients: copy to `/usr/local/share/ca-certificates/clinic-ca.crt` and run `sudo update-ca-certificates`.
- Firefox uses its own store: Settings → Privacy & Security → Certificates → Import.

Keep `deploy/certs/clinic-ca.key` secret and copy it to offline storage; it is needed to renew the server certificate (valid 825 days).

## 5. Start

```bash
docker compose build
docker compose run --rm api python manage.py migrate
docker compose up -d
docker compose ps                     # all three services should become "healthy"
docker compose exec api python manage.py bootstrap_admin
docker compose exec api python manage.py load_starter_catalog
```

`load_starter_catalog` creates example service prices, laboratory tests and medicines without stock. Review every price under *Prices & catalogue* and *Inventory* before use, then receive opening stock under *Inventory → Receive stock*.

The last command prints a one-time password for user `admin`. Open `https://192.168.1.10`, sign in, set a new password, then create named accounts for every staff member. Do not share accounts.

## 6. Backups

```bash
sudo mkdir -p /var/backups/mrs && sudo chown "$USER" /var/backups/mrs
deploy/scripts/backup.sh manual          # first backup
deploy/scripts/verify-backup.sh /var/backups/mrs/manual/<file>.dump
sudo cp deploy/systemd/mrs-backup*.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mrs-backup.timer mrs-backup-verify.timer
systemctl list-timers 'mrs-*'
```

If the services do not run as your user, add `User=` to the `.service` files. Check backup logs with `journalctl -u mrs-backup`.

Optional: email alerts to staff through the clinic's cPanel email or Brevo. See [email.md](email.md).

Optional: encrypted off-site copies every 1 to 24 hours, switched on and off in the System page. See [offsite-backup.md](offsite-backup.md).

## 7. Daily reminders

Once a day the system tells staff about medicines near expiry (90 days), tomorrow's appointments
(reception and each doctor) and follow-ups a doctor asked for that nobody has booked. The server's
timezone must be Africa/Addis_Ababa, or change the time in the timer.

```bash
sudo cp deploy/systemd/mrs-reminders.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mrs-reminders.timer
docker compose exec api python manage.py send_daily_reminders   # run once now to check
```

Running it more than once a day is harmless: a reminder is not repeated while the earlier one is unread.

## 8. Trial without HTTPS (not for real data)

Set `MRS_HTTPS=false` in `.env` and `docker compose up -d`. Passwords travel unencrypted on the network in this mode; use it only for a short demonstration with synthetic data.

## Logs and health

- `docker compose logs -f api` — application log; every line carries a `request_id`, also shown to users in error messages.
- `curl -k https://localhost/api/v1/health/` — `{"status":"ok","database":"ok"}`.

## Security

Follow [security-checklist.md](security-checklist.md) for every clinic: disk encryption at install,
`deploy/scripts/harden-server.sh`, and `deploy/scripts/security-check.sh` before go-live.
