# Upgrading

Upgrade outside clinic hours. Expect 10–20 minutes of downtime.

```bash
cd /opt/mrs
deploy/scripts/backup.sh pre-upgrade                         # prints the backup path; note it
deploy/scripts/verify-backup.sh <that path>
git fetch && git checkout <release-tag>                      # or unpack the release archive
diff .env.example .env                                       # add any new settings to .env
docker compose build
docker compose run --rm api python manage.py migrate
docker compose run --rm api python manage.py sync_permissions
docker compose up -d
docker compose ps                                            # all healthy?
```

Then sign in and check the dashboard, a staff account page and the audit log.

### Upgrading from an offline bundle

Make a new bundle for the release (see install.md), copy it to the server, then:

```bash
cd /opt/mrs
deploy/scripts/backup.sh pre-upgrade && deploy/scripts/verify-backup.sh <that path>
sha256sum -c /media/usb/mrs-offline-1.5.0.tar.sha256
tar -xf /media/usb/mrs-offline-1.5.0.tar -C /tmp
rsync -a --exclude .env --exclude deploy/certs /tmp/mrs-1.5.0/ /opt/mrs/   # keeps settings and certificates
(cd offline && sha256sum --quiet -c SHA256SUMS)
docker load -i offline/images.tar.gz
sed -i 's/^MRS_VERSION=.*/MRS_VERSION=1.5.0/' .env
docker compose run --rm api python manage.py migrate
docker compose run --rm api python manage.py sync_permissions
docker compose up -d --no-build
```

The previous version's images stay on the server, so rolling back means setting `MRS_VERSION` back
and restoring the pre-upgrade backup.

## Rolling back

Migrations may change the database, so rolling back the code alone is not enough:

```bash
git checkout <previous-tag>
docker compose build
deploy/scripts/restore.sh <pre-upgrade backup path>
```

Anything entered after the upgrade is lost by a rollback.

## Release rules for developers

- Every release passes CI (backend tests on PostgreSQL, backup/restore test, frontend checks, image builds).
- Migrations must apply to the previous release's schema with data; destructive changes (dropping columns or tables) happen at least one release after the code stops using them.
- New permissions are added to `apps/accounts/catalog.py`; `sync_permissions` adds them without overwriting roles a clinic has customised.
