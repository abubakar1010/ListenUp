# ADR 0032: Nightly pg_dump with a manifest, 14-day retention and scripted restore tests

- Status: Accepted
- Date: 2026-10-04
- Source: issue #97; [SRS NFR-REL-4](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd); [Software Architecture 11 (backups)](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13); [System Design 11.1 and 11.2 (RPO 24 h, RTO 4 h at stage 0)](https://claude.ai/code/artifact/98274889-96ba-4424-afad-c2cd056206e2); [Database Design 12.3 (managed backups plus a nightly pg_dump kept 14 days; a restore tested monthly)](https://claude.ai/code/artifact/ba05f7b3-f881-41e5-86d6-dcb94a509644); ADRs 0005, 0013 and 0031

## Context

The sources ask for the managed PostgreSQL tier's backups plus a nightly `pg_dump` to object storage kept for 14 days, a documented restore procedure, and a monthly restore test into a scratch database with a row-count check. Production is one free VM running Docker Compose with a managed database and S3-compatible storage (Architecture 11), but the deployment (#112) is not built: there is no managed database yet and no `compose.prod.yml`. The dump must run somewhere that has the PostgreSQL 16 client tools and the database owner's credentials.

## Decision

### A `backup` container with its own scheduler

The dump runs in a dedicated `backup` service built from the backend Dockerfile (`--target backup`, which adds `postgresql-client-16` from the PostgreSQL project's repository so the client matches the server). Its command, `python -m listenup.ops.backup schedule`, sleeps until 02:30 UTC, dumps, prunes, and repeats; a failure is retried after 30 minutes.

Rejected: a Procrastinate periodic job on the background lane. It would put the owner's credentials and the client tools into the worker image, tie backups to the health of the queue they back up, and a stuck background lane would silently stop backups. A host cron job is not reproducible from the repository. The container keeps the owner's credentials in one service and is the same on any host. Locally it is behind the `backup` Compose profile, so `docker compose up` is unchanged; production runs it always.

### What a backup is

- `pg_dump --format=custom --compress=6` from a snapshot exported by a repeatable-read transaction (`pg_export_snapshot()`). In the same snapshot the job counts every table's rows, reads the Alembic revision and the database-level settings. The counts therefore match the dump exactly, even while learners write.
- Two objects under `backups/postgres/<YYYYMMDDTHHMMSSZ>/` in `LISTENUP_BACKUP_BUCKET` (the media bucket by default; media deletion only touches `users/<id>/`): `listenup.dump`, then `manifest.json` with the checksum, size, revision, server version, settings and row counts. The manifest is written last; a folder without one is an unfinished upload and is never listed or restored.
- Database-level settings (`ALTER DATABASE ... SET search_path`, `timezone`, from migrations 0001 and 0003) are not in a custom-format dump unless it is restored with `--create`, which would force the original database name. The manifest records them and every restore applies them, so the job queue's functions resolve in a restored database.
- The libpq password goes to `pg_dump` and `pg_restore` through the environment, never the command line.

### Retention

After each dump, backups older than `LISTENUP_BACKUP_RETENTION_DAYS` (14) are deleted by the job itself, judged by the stamp in the key, which works the same on every S3-compatible provider. The newest complete backup is always kept, so a broken nightly job can never leave the bucket empty. A bucket lifecycle rule may be added as a second safety, but must allow at least 15 days.

### Restores and the restore test

- `restore --stamp S --target-url URL` restores into an existing empty database: checksum check, `pg_restore --exit-on-error --no-owner --single-transaction` (all or nothing; objects owned by the restoring owner), then the database settings. The roles the dump grants to must exist on the target server; on a new server the baseline migration's `ROLES` block is run first.
- `restore-test` restores the newest (or a chosen) backup into a new scratch database on the same server, compares the Alembic revision and every table's row count with the manifest, reports the time against the 4 h RTO, drops the scratch database, and exits non-zero on any mismatch or overrun. The integration tests run the same code against the test server (dump, restore, matching counts, settings and grants restored, a changed count and a damaged dump detected).
- The first restore test ran during this story against a throwaway database and is recorded in `docs/runbooks/backups.md`, with the monthly procedure and the recovery steps.

### Monitoring

The backup service reports the time of the newest backup in storage (on start, and after each dump) as `listenup_backup_last_success_timestamp_seconds` (ADR 0031). The BackupMissing alert fires when it is over 26 hours old, or when the service stops reporting.

## Consequences

- RPO at stage 0 is up to 24 hours from the dump alone; the managed provider's backups (and point-in-time recovery, if its free tier offers it) can only improve on that.
- **Not done here, because it depends on the deployment (#112):** enabling the managed provider's backups and recording their retention, the production bucket (separate from media, with server-side encryption), running the `backup` service on the server, and the first production restore test. The runbook lists these steps.
- Media is not backed up (Architecture 11); a restored database may point at media objects deleted after the dump.
- Restore tests need the CREATEDB right on the server they run on.
- The `backup` image build is checked in CI with the others; it could not be built in the development container for this change, which has no Docker daemon.
