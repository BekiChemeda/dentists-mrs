# ADR 0007 — Dental image files on the server's disk, metadata in the database

Date: 2026-11-23 · Status: accepted

## Decision

Image bytes are written to `DENTAL_IMAGE_ROOT` (production: `/var/lib/mrs/images`, a host directory mounted into
the `api` container only). The file name is an opaque random key (`ab/<uuid>.<ext>`); the database row holds
patient, type, teeth, SHA-256, size and the key. Files are written once (temporary file, fsync, rename, mode
0600) and never overwritten or deleted by the application. A wrong image is *withdrawn* (hidden, reason kept);
a corrected image is a new upload that names the one it replaces.

Files are served only by the API view after permission checks, with `nosniff`, a sandboxing CSP and
`Cache-Control: no-store`. Nginx has no location that maps to the directory.

The original bytes are kept exactly as uploaded (no re-compression of radiographs). A JPEG preview is generated
for the browser. DICOM is **not** supported: DICOM files are refused with a message. Accepted: JPEG, PNG, TIFF.

## Backup

`backup.sh` mirrors new files into `$BACKUP_DIR/images/` after the database dump (copy-if-absent: files never
change, so the mirror grows but is never rewritten). `restore.sh` copies the mirror back. `verify-backup.sh` and
`manage.py verify_dental_images` check every database row has a file whose SHA-256 matches. Off-site backup
(restic) includes the mirror; restic de-duplicates, so only new images are uploaded.

## Reasons

- Clinic MRS stores scanned documents in the database. Radiograph sets (10–20 MB each, thousands a year) would
  bloat `pg_dump`, slow every nightly backup and the weekly restore test, and the 4 GB server's shared buffers.
- Content never changes, so incremental file backup is trivial and safe.

## Consequences

- A restore is now two parts (database + images); the scripts do both and the restore test checks both.
- Disk usage must be watched: the System page reports the image directory size.
