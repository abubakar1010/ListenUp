# Database backups and restore runbook

Data is backed up daily and can be restored (NFR-REL-4). At stage 0 the targets are an RPO of 24 hours and an RTO of 4 hours (System Design 11.2). Design and reasons: ADR 0032. Times are UTC.

## What is backed up

| Layer | What | Kept | Status |
| --- | --- | --- | --- |
| Nightly dump | `pg_dump --format=custom` of the whole database, taken by the `backup` service at 02:30 | 14 days in object storage under `backups/postgres/<stamp>/` | Built (#97) |
| Managed backups | The managed PostgreSQL provider's own daily backups or point-in-time recovery | The provider's free-tier retention | **To do with the deployment (#112)**: no managed database exists yet |
| Media | Not backed up: media can be re-derived or re-uploaded (Architecture 11) | | Out of scope |

Each backup is two objects: `listenup.dump` and `manifest.json`. The manifest holds the dump's SHA-256 and size, the Alembic revision, the server version, the database-level settings (`search_path`, `timezone`) and the row count of every table, read in the same snapshot as the dump. A backup without a manifest is unfinished and never restored or listed.

Settings (environment, ADR 0032): `LISTENUP_BACKUP_DATABASE_URL` (the database owner; defaults to `LISTENUP_DATABASE_URL`), `LISTENUP_BACKUP_BUCKET` (defaults to the media bucket; a separate bucket is better in production), `LISTENUP_BACKUP_PREFIX` (`backups/postgres/`), `LISTENUP_BACKUP_RETENTION_DAYS` (14), `LISTENUP_BACKUP_HOUR_UTC` and `LISTENUP_BACKUP_MINUTE_UTC` (02:30), and the `LISTENUP_S3_*` storage credentials. Dumps are encrypted at rest by the storage provider; turn on its server-side encryption for the bucket if it is not the default.

## Daily operation

- The `backup` container (`infra/docker/backend.Dockerfile --target backup`) runs `python -m listenup.ops.backup schedule`. Locally it is opt-in: `docker compose --profile backup up backup`.
- After each dump it removes backups older than 14 days. The newest backup is never removed, even when it is older, so a broken nightly job cannot empty the bucket.
- A failed dump is logged (`database dump failed`) and retried 30 minutes later.
- The service reports the time of the newest backup as `listenup_backup_last_success_timestamp_seconds`; the **BackupMissing** alert fires when it is over 26 hours old or missing (see `alerts.md`).

Commands (inside the `backup` container, or from `apps/api` with `uv run`):

```sh
python -m listenup.ops.backup dump            # dump and prune now
python -m listenup.ops.backup list            # complete backups, newest first
python -m listenup.ops.backup restore-test    # restore the newest into a scratch database and check it
python -m listenup.ops.backup restore-test --stamp 20261004T023000Z --keep
python -m listenup.ops.backup restore --stamp <stamp> --target-url postgresql://...
```

Add `--local-dir DIR` before the command to use a directory instead of the bucket (drills on a machine without object storage).

## Monthly restore test

Database Design 12.3 asks for a restore test every month. On the first working day of the month:

1. On the server (or any machine with network access to the database and the bucket), run `docker compose run --rm backup python -m listenup.ops.backup restore-test`.
2. The command creates `listenup_restore_<stamp>_<random>` on the same server (so the `listenup_api`, `listenup_worker` and `listenup_readonly` roles the dump grants to exist), checks the dump's checksum, restores it with `pg_restore --exit-on-error --single-transaction`, re-applies the database settings, compares the Alembic revision and every table's row count with the manifest, and drops the scratch database. It needs the CREATEDB right.
3. It prints one JSON line with `ok`, `within_rto`, `restore_seconds`, `tables`, `rows` and `mismatches`, and exits with 1 unless the restore matched and took under 4 hours.
4. Record the result in the log at the end of this file. If it failed, treat it as an incident: the backups cannot be trusted until a restore test passes.

## Restoring after data loss

Use this when the production database is lost or damaged. Decide first which backup to use: the newest one before the damage (`list`), or the managed provider's point-in-time recovery once #112 sets it up, which loses less data than a nightly dump.

1. **Stop writers.** `docker compose stop api worker worker-media backup` so nothing writes to the database during the restore. Learners see the API as unavailable; the web app keeps drafts locally (NFR-REL-1).
2. **Prepare an empty database** on the target server, owned by the migration user, with the roles in place. On a new server, create the roles first: run the `ROLES` block of `apps/api/migrations/versions/20261003_0001_baseline.py` as an administrator (it only creates `listenup_api`, `listenup_worker` and `listenup_readonly` and their timeouts). Then `CREATE DATABASE listenup_restored OWNER listenup;`.
3. **Restore.** `docker compose run --rm backup python -m listenup.ops.backup restore --stamp <stamp> --target-url postgresql://listenup:<password>@<host>:5432/listenup_restored`. It checks the dump's checksum, restores it in one transaction (all or nothing) and applies the database settings from the manifest.
4. **Check it.** Compare row counts with the manifest (`manifest.json` in the backup's folder): `SELECT count(*) FROM identity.users;` and a few other tables, and `SELECT version_num FROM alembic_version;` equals the manifest's `alembic_revision`. Then run `alembic upgrade head` from the current release's `migrate` container, in case the dump is older than the code.
5. **Switch over.** Point `LISTENUP_DATABASE_URL` (and the backup URL) at the restored database, or rename it: `ALTER DATABASE listenup RENAME TO listenup_damaged; ALTER DATABASE listenup_restored RENAME TO listenup;` (no connections may be open). Start everything again with `docker compose up -d`.
6. **After.** Run a `dump` so a fresh backup of the restored state exists, and record what happened and how long it took (the RTO is 4 hours).

Jobs that were queued after the dump are lost with the rest of that day's data; jobs in the dump run again when the workers start, which is safe because every job is idempotent (System Design 11.3).

## Rebuilding the stage 0 server

If the VM itself is lost (System Design 11.1, detected by the external uptime monitor), the managed database and the bucket survive it. Rebuild on any host: install Docker, copy the Compose files and the environment (secrets from the host's secret store, never the repository), pull the release's images and start them with `docker compose up -d`; migrations run as the one-off `migrate` container first. No restore is needed unless the database was lost too. The exact steps, and the managed backup settings, belong to the deployment story (#112), which is not done yet.

## Restore test log

| Date | Backup | Where | Tables | Rows | Restore time | Result | By |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-04 | `20261004T040253Z` (112 KB dump, taken in 0.14 s) | First test, during #97: a throwaway database `wt_s_backup_drill` on the local PostgreSQL 16.14 server, migrated to `0011` and filled with `scripts/seed_dev.py`; dumps in a local directory (`--local-dir`), as no object storage was running. The throwaway database was dropped afterwards. | 19 | 46 | 0.28 s (0.8 s for the whole command) | Passed: every row count and the Alembic revision matched; scratch database dropped; well within the 4 h RTO | #97 implementation |
| 2026-10-05 | `20261005T095713Z` (116 KB dump, taken in 0.19 s) | Re-run on the branch after merging `main`: a throwaway database migrated to `0012` and filled with `scripts/seed_dev.py`; dumps in a local directory (`--local-dir`), as no object storage ran in this environment. Dropped afterwards. | 20 | 47 | 0.30 s (0.8 s for the whole command) | Passed: every row count and the Alembic revision matched; scratch database dropped; exit code 0, within the 4 h RTO | #97 implementation |

The first production restore test is due once the stage 0 deployment (#112) runs the `backup` service against the managed database and the bucket.
