"""Nightly database dump to object storage, retention, and restore tests (NFR-REL-4).

Run as `python -m listenup.ops.backup <command>` (ADR 0032, docs/runbooks/backups.md):

- `schedule`: the `backup` container's command. Dumps once a day at
  LISTENUP_BACKUP_HOUR_UTC:LISTENUP_BACKUP_MINUTE_UTC, then removes dumps older than
  LISTENUP_BACKUP_RETENTION_DAYS (14).
- `dump`: one dump and prune now.
- `list`: the dumps in storage, newest first.
- `restore-test`: restores a dump (the newest by default) into a new scratch
  database on the same server, checks every table's row count against the dump's
  manifest, reports the time taken against the 4 h RTO, and drops the scratch
  database.
- `restore`: restores a dump into an existing empty database, for a real recovery.

A dump is `pg_dump --format=custom` taken from an exported snapshot. The row counts in
its manifest are read in the same snapshot, so a restore must match them exactly.
Database-level settings (`search_path`, `timezone`), which pg_dump leaves out without
`--create`, are recorded in the manifest and applied after a restore.

`--local-dir DIR` uses a directory instead of the bucket, for drills on a machine
without object storage.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from listenup.ops.store import BackupStore, DirectoryBackupStore, S3BackupStore
from listenup.platform.config import Settings, get_settings
from listenup.platform.log import configure_logging
from listenup.platform.telemetry import (
    configure_telemetry,
    record_backup_success,
    shutdown_telemetry,
)

logger = logging.getLogger(__name__)

STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
DUMP_NAME = "listenup.dump"
MANIFEST_NAME = "manifest.json"
RTO = timedelta(hours=4)  # stage 0 (System Design 11.2)
RETRY_AFTER_FAILURE = timedelta(minutes=30)
_STAMP = re.compile(r"(\d{8}T\d{6}Z)/")

TABLES = """
SELECT n.nspname, c.relname
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind IN ('r', 'p')
   AND n.nspname NOT IN ('pg_catalog', 'information_schema')
   AND n.nspname NOT LIKE 'pg\\_toast%' AND n.nspname NOT LIKE 'pg\\_temp%'
 ORDER BY 1, 2
"""

DATABASE_SETTINGS = """
SELECT unnest(s.setconfig)
  FROM pg_db_role_setting s
  JOIN pg_database d ON d.oid = s.setdatabase
 WHERE d.datname = current_database() AND s.setrole = 0
"""


@dataclass
class Manifest:
    stamp: str
    created_at: str
    database: str
    server_version: str
    alembic_revision: str | None
    dump_key: str
    dump_bytes: int
    dump_sha256: str
    dump_seconds: float
    row_counts: dict[str, int]
    database_settings: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
        return cls(**json.loads(text))


@dataclass
class RestoreReport:
    stamp: str
    database: str
    restore_seconds: float
    tables: int
    rows: int
    mismatches: dict[str, tuple[int, int | None]]  # table: (in manifest, restored)
    alembic_revision: str | None

    @property
    def ok(self) -> bool:
        return not self.mismatches

    @property
    def within_rto(self) -> bool:
        return self.restore_seconds < RTO.total_seconds()


def backup_url(settings: Settings) -> str:
    return settings.backup_database_url or settings.database_url


# libpq connection parameters and the environment variable that carries each, so
# pg_dump and pg_restore connect the way psycopg does (certificates, options, timeouts).
_LIBPQ_ENV = {
    "host": "PGHOST",
    "hostaddr": "PGHOSTADDR",
    "port": "PGPORT",
    "dbname": "PGDATABASE",
    "user": "PGUSER",
    "password": "PGPASSWORD",
    "passfile": "PGPASSFILE",
    "service": "PGSERVICE",
    "options": "PGOPTIONS",
    "application_name": "PGAPPNAME",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "channel_binding": "PGCHANNELBINDING",
    "sslmode": "PGSSLMODE",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "sslrootcert": "PGSSLROOTCERT",
    "sslcrl": "PGSSLCRL",
    "sslcrldir": "PGSSLCRLDIR",
    "sslsni": "PGSSLSNI",
    "ssl_min_protocol_version": "PGSSLMINPROTOCOLVERSION",
    "ssl_max_protocol_version": "PGSSLMAXPROTOCOLVERSION",
    "gssencmode": "PGGSSENCMODE",
    "krbsrvname": "PGKRBSRVNAME",
    "requirepeer": "PGREQUIREPEER",
    "target_session_attrs": "PGTARGETSESSIONATTRS",
}


def _pg_env(url: str) -> dict[str, str]:
    """libpq variables for pg_dump and pg_restore, so no password shows in `ps`.

    The container's own PG* variables stay (psycopg honours them too); what the URL
    sets wins over them.
    """
    params = psycopg.conninfo.conninfo_to_dict(url)
    env = dict(os.environ)
    env.update(
        {_LIBPQ_ENV[k]: str(v) for k, v in params.items() if k in _LIBPQ_ENV and v is not None}
    )
    return env


def _run(command: list[str], url: str) -> None:
    """Run a PostgreSQL client tool against `url`; its error output names the failure."""
    result = subprocess.run(command, env=_pg_env(url), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{command[0]} failed: {result.stderr.strip()[-2000:]}")


def _with_dbname(url: str, dbname: str) -> str:
    return psycopg.conninfo.make_conninfo(url, dbname=dbname)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_rows(conn: psycopg.Connection[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for schema, table in conn.execute(TABLES).fetchall():
        query = sql.SQL("SELECT count(*) FROM {}.{}").format(
            sql.Identifier(schema), sql.Identifier(table)
        )
        row = conn.execute(query).fetchone()
        counts[f"{schema}.{table}"] = int(row[0]) if row else 0
    return counts


def _alembic_revision(conn: psycopg.Connection[Any]) -> str | None:
    exists = conn.execute("SELECT to_regclass('public.alembic_version')").fetchone()
    if not exists or exists[0] is None:
        return None
    row = conn.execute("SELECT version_num FROM public.alembic_version").fetchone()
    return str(row[0]) if row else None


RLS_EXPOSED_TABLES = """
SELECT count(*)
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind IN ('r', 'p')
   AND c.relrowsecurity
   AND n.nspname NOT IN ('pg_catalog', 'information_schema')
   AND NOT (pg_has_role(current_user, c.relowner, 'USAGE') AND NOT c.relforcerowsecurity)
   AND NOT (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user)
"""


def _require_full_access(conn: psycopg.Connection[Any]) -> None:
    """Refuse a role that row-level security hides rows from, such as `listenup_api`.

    With such a role pg_dump aborts, and the manifest's row counts would read 0, so
    LISTENUP_BACKUP_DATABASE_URL must name the database owner.
    """
    row = conn.execute(RLS_EXPOSED_TABLES).fetchone()
    if row and row[0]:
        raise RuntimeError(
            f"database role {conn.info.user!r} is subject to row-level security on "
            f"{row[0]} table(s) and cannot take a complete dump; set "
            "LISTENUP_BACKUP_DATABASE_URL to the database owner"
        )


def _keys(prefix: str, stamp: str) -> tuple[str, str]:
    return f"{prefix}{stamp}/{DUMP_NAME}", f"{prefix}{stamp}/{MANIFEST_NAME}"


def dump(settings: Settings, store: BackupStore, now: datetime | None = None) -> Manifest:
    """Dump the database to `store` and return the manifest stored beside it."""
    started = time.monotonic()
    now = now or datetime.now(UTC)
    stamp = now.strftime(STAMP_FORMAT)
    dump_key, manifest_key = _keys(settings.backup_prefix, stamp)
    url = backup_url(settings)
    with tempfile.TemporaryDirectory(prefix="listenup-backup-") as scratch:
        path = Path(scratch) / DUMP_NAME
        with psycopg.connect(url) as conn:
            # One snapshot for the counts and the dump, held open until pg_dump is done.
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            conn.read_only = True
            # The connection sits idle while pg_dump runs; a role timeout must not end it.
            conn.execute("SET idle_in_transaction_session_timeout = 0")
            _require_full_access(conn)
            snapshot_row = conn.execute("SELECT pg_export_snapshot()").fetchone()
            assert snapshot_row is not None
            database = str(conn.info.dbname)
            server_version = str(conn.info.server_version)
            row_counts = _count_rows(conn)
            revision = _alembic_revision(conn)
            database_settings = [str(row[0]) for row in conn.execute(DATABASE_SETTINGS)]
            _run(
                [
                    "pg_dump",
                    "--format=custom",
                    "--compress=6",
                    f"--snapshot={snapshot_row[0]}",
                    f"--file={path}",
                ],
                url,
            )
            conn.commit()
        manifest = Manifest(
            stamp=stamp,
            created_at=now.isoformat(),
            database=database,
            server_version=server_version,
            alembic_revision=revision,
            dump_key=dump_key,
            dump_bytes=path.stat().st_size,
            dump_sha256=_sha256(path),
            dump_seconds=round(time.monotonic() - started, 3),
            row_counts=row_counts,
            database_settings=database_settings,
        )
        store.upload(dump_key, path)
        # The manifest goes last: a dump without one is incomplete and never restored.
        manifest_path = Path(scratch) / MANIFEST_NAME
        manifest_path.write_text(json.dumps(asdict(manifest), indent=2))
        store.upload(manifest_key, manifest_path)
    logger.info(
        "database dump stored",
        extra={
            "backup": stamp,
            "bytes": manifest.dump_bytes,
            "tables": len(row_counts),
            "seconds": manifest.dump_seconds,
        },
    )
    return manifest


def stamps(store: BackupStore, prefix: str) -> list[str]:
    """Complete backups (those with a manifest), newest first."""
    found = set()
    for item in store.list_files(prefix):
        match = _STAMP.match(item.key[len(prefix) :])
        if match and item.key.endswith(f"/{MANIFEST_NAME}"):
            found.add(match.group(1))
    return sorted(found, reverse=True)


def prune(
    store: BackupStore, prefix: str, retention_days: int, now: datetime | None = None
) -> list[str]:
    """Delete backups older than `retention_days`; returns the removed stamps.

    The newest complete backup is always kept, even when it is older, so a broken
    nightly job never leaves storage empty. Unfinished uploads (no manifest) older
    than the retention go too.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=retention_days)
    complete = stamps(store, prefix)
    keep_newest = complete[0] if complete else None
    by_stamp: dict[str, list[str]] = {}
    for item in store.list_files(prefix):
        match = _STAMP.match(item.key[len(prefix) :])
        if match:
            by_stamp.setdefault(match.group(1), []).append(item.key)
    removed = []
    for stamp, keys in sorted(by_stamp.items()):
        taken = datetime.strptime(stamp, STAMP_FORMAT).replace(tzinfo=UTC)
        if taken < cutoff and stamp != keep_newest:
            store.delete(keys)
            removed.append(stamp)
    if removed:
        logger.info("old database dumps removed", extra={"removed": removed})
    return removed


def read_manifest(store: BackupStore, prefix: str, stamp: str) -> Manifest:
    _, manifest_key = _keys(prefix, stamp)
    with tempfile.TemporaryDirectory(prefix="listenup-restore-") as scratch:
        path = Path(scratch) / MANIFEST_NAME
        store.download(manifest_key, path)
        return Manifest.from_json(path.read_text())


def _restore_into(url: str, path: Path, manifest: Manifest) -> None:
    dbname = str(psycopg.conninfo.conninfo_to_dict(url)["dbname"])
    _run(
        [
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--single-transaction",
            f"--dbname={dbname}",  # the name only; the connection details are in the env
            str(path),
        ],
        url,
    )
    with psycopg.connect(url, autocommit=True) as conn:
        for setting in manifest.database_settings:
            name, value = setting.split("=", 1)
            # `value` is how PostgreSQL stored it, e.g. `procrastinate, public`.
            conn.execute(
                sql.SQL("ALTER DATABASE {} SET {} TO {}").format(
                    sql.Identifier(dbname),
                    sql.Identifier(name),
                    sql.SQL(", ").join(
                        sql.Literal(part.strip().strip('"')) for part in value.split(",")
                    )
                    if name == "search_path"
                    else sql.Literal(value),
                )
            )


@contextmanager
def _downloaded(store: BackupStore, manifest: Manifest) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="listenup-restore-") as scratch:
        path = Path(scratch) / DUMP_NAME
        store.download(manifest.dump_key, path)
        if _sha256(path) != manifest.dump_sha256:
            raise RuntimeError(f"dump {manifest.stamp} does not match its manifest checksum")
        yield path


def restore(settings: Settings, store: BackupStore, stamp: str, target_url: str) -> Manifest:
    """Restore backup `stamp` into the existing, empty database at `target_url`."""
    manifest = read_manifest(store, settings.backup_prefix, stamp)
    with _downloaded(store, manifest) as path:
        _restore_into(target_url, path, manifest)
    return manifest


def restore_test(
    settings: Settings,
    store: BackupStore,
    stamp: str | None = None,
    keep: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> RestoreReport:
    """Restore a backup into a scratch database and compare row counts.

    The scratch database is created on the server of the backup database URL, so the
    roles the dump grants to already exist there, and dropped afterwards unless `keep`.
    """
    prefix = settings.backup_prefix
    if stamp is None:
        available = stamps(store, prefix)
        if not available:
            raise RuntimeError(f"no complete backup under {prefix!r}")
        stamp = available[0]
    manifest = read_manifest(store, prefix, stamp)
    admin_url = backup_url(settings)
    scratch = f"listenup_restore_{stamp.lower()}_{uuid.uuid4().hex[:6]}"
    started = clock()
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch)))
    try:
        scratch_url = _with_dbname(admin_url, scratch)
        with _downloaded(store, manifest) as path:
            _restore_into(scratch_url, path, manifest)
        with psycopg.connect(scratch_url) as conn:
            restored = _count_rows(conn)
            revision = _alembic_revision(conn)
        elapsed = clock() - started
    finally:
        if not keep:
            with psycopg.connect(admin_url, autocommit=True) as conn:
                conn.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(scratch)
                    )
                )
    mismatches: dict[str, tuple[int, int | None]] = {
        table: (expected, restored.get(table))
        for table, expected in manifest.row_counts.items()
        if restored.get(table) != expected
    }
    if revision != manifest.alembic_revision:
        mismatches["alembic_version"] = (0, None)
    report = RestoreReport(
        stamp=stamp,
        database=scratch,
        restore_seconds=round(elapsed, 3),
        tables=len(manifest.row_counts),
        rows=sum(manifest.row_counts.values()),
        mismatches=mismatches,
        alembic_revision=revision,
    )
    log = logger.info if report.ok and report.within_rto else logger.error
    log(
        "restore test finished",
        extra={
            "backup": stamp,
            "ok": report.ok,
            "within_rto": report.within_rto,
            "seconds": report.restore_seconds,
            "tables": report.tables,
            "rows": report.rows,
            "mismatches": mismatches,
        },
    )
    return report


def next_run(now: datetime, hour: int, minute: int) -> datetime:
    """The next daily run time at hour:minute UTC strictly after `now`."""
    run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return run if run > now else run + timedelta(days=1)


def _report_latest(store: BackupStore, prefix: str) -> None:
    """Tell the BackupMissing alert when the newest backup in storage was taken."""
    available = stamps(store, prefix)
    if available:
        taken = datetime.strptime(available[0], STAMP_FORMAT).replace(tzinfo=UTC)
        record_backup_success(taken.timestamp())


def run_once(settings: Settings, store: BackupStore) -> Manifest:
    manifest = dump(settings, store)
    record_backup_success(datetime.fromisoformat(manifest.created_at).timestamp())
    try:
        prune(store, settings.backup_prefix, settings.backup_retention_days)
    except Exception:
        # The dump is stored; failing here would make the scheduler dump again.
        logger.exception("pruning old database dumps failed; they stay until the next run")
    return manifest


def schedule(
    settings: Settings,
    store: BackupStore,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    runs: int | None = None,
) -> None:
    """Dump daily at the configured time; a failure is retried after 30 minutes."""
    try:
        _report_latest(store, settings.backup_prefix)
    except Exception:
        # Storage may be briefly unreachable at start; the next dump reports itself.
        logger.exception("could not read the newest backup from storage")
    due = next_run(now(), settings.backup_hour_utc, settings.backup_minute_utc)
    done = 0
    while runs is None or done < runs:
        sleep(max(0.0, (due - now()).total_seconds()))
        try:
            run_once(settings, store)
            due = next_run(now(), settings.backup_hour_utc, settings.backup_minute_utc)
        except Exception:
            logger.exception("database dump failed; retrying in 30 minutes")
            due = now() + RETRY_AFTER_FAILURE
        done += 1


def _store(settings: Settings, local_dir: str | None) -> BackupStore:
    return DirectoryBackupStore(Path(local_dir)) if local_dir else S3BackupStore(settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m listenup.ops.backup")
    parser.add_argument("--local-dir", help="use this directory instead of the bucket")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schedule", help="dump daily at the configured UTC time")
    commands.add_parser("dump", help="dump now, then remove expired dumps")
    commands.add_parser("list", help="list complete dumps, newest first")
    test = commands.add_parser("restore-test", help="restore into a scratch database")
    test.add_argument("--stamp", help="the backup to test (default: the newest)")
    test.add_argument("--keep", action="store_true", help="keep the scratch database")
    real = commands.add_parser("restore", help="restore into an existing empty database")
    real.add_argument("--stamp", required=True)
    real.add_argument("--target-url", required=True, help="postgresql:// URL of the target")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    store = _store(settings, args.local_dir)
    if args.command == "schedule":
        configure_telemetry(settings, "backup")
        try:
            schedule(settings, store)
        finally:
            shutdown_telemetry()
        return 0
    if args.command == "dump":
        manifest = run_once(settings, store)
        print(json.dumps(asdict(manifest)))
        return 0
    if args.command == "list":
        for stamp in stamps(store, settings.backup_prefix):
            print(stamp)
        return 0
    if args.command == "restore-test":
        report = restore_test(settings, store, args.stamp, keep=args.keep)
        print(json.dumps({**asdict(report), "ok": report.ok, "within_rto": report.within_rto}))
        return 0 if report.ok and report.within_rto else 1
    restore(settings, store, args.stamp, args.target_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
