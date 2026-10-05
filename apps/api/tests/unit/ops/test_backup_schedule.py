"""Retention and the daily schedule of database dumps (#97, ADR 0032)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from listenup.ops import backup
from listenup.ops.backup import next_run, prune, schedule, stamps
from listenup.ops.store import DirectoryBackupStore
from listenup.platform.config import Settings
from tests.telemetry_helpers import capture

PREFIX = "backups/postgres/"
NOW = datetime(2026, 10, 20, 2, 30, tzinfo=UTC)


def put(store: DirectoryBackupStore, taken: datetime, manifest: bool = True) -> str:
    stamp = taken.strftime(backup.STAMP_FORMAT)
    source = store.root.parent / "blob"
    source.write_text("x")
    store.upload(f"{PREFIX}{stamp}/{backup.DUMP_NAME}", source)
    if manifest:
        store.upload(f"{PREFIX}{stamp}/{backup.MANIFEST_NAME}", source)
    return stamp


@pytest.fixture
def store(tmp_path: Path) -> DirectoryBackupStore:
    return DirectoryBackupStore(tmp_path / "bucket")


def test_dumps_older_than_14_days_are_removed(store: DirectoryBackupStore) -> None:
    old = put(store, NOW - timedelta(days=15))
    edge = put(store, NOW - timedelta(days=13, hours=23))
    new = put(store, NOW - timedelta(hours=1))

    removed = prune(store, PREFIX, 14, now=NOW)

    assert removed == [old]
    assert stamps(store, PREFIX) == [new, edge]
    assert not any(old in item.key for item in store.list_files(PREFIX))


def test_the_newest_dump_is_kept_even_when_expired(store: DirectoryBackupStore) -> None:
    older = put(store, NOW - timedelta(days=40))
    newest = put(store, NOW - timedelta(days=20))

    assert prune(store, PREFIX, 14, now=NOW) == [older]
    assert stamps(store, PREFIX) == [newest]


def test_an_unfinished_dump_is_never_listed_and_expires(store: DirectoryBackupStore) -> None:
    done = put(store, NOW - timedelta(days=1))
    unfinished = put(store, NOW - timedelta(days=16), manifest=False)

    assert stamps(store, PREFIX) == [done]
    assert prune(store, PREFIX, 14, now=NOW) == [unfinished]


def test_other_keys_under_the_prefix_are_left_alone(store: DirectoryBackupStore) -> None:
    put(store, NOW - timedelta(days=30))
    source = store.root.parent / "notes"
    source.write_text("restore drill notes")
    store.upload(f"{PREFIX}README.txt", source)

    prune(store, PREFIX, 14, now=NOW)

    assert f"{PREFIX}README.txt" in [item.key for item in store.list_files(PREFIX)]


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 4, 1, 0, tzinfo=UTC), datetime(2026, 10, 4, 2, 30, tzinfo=UTC)),
        (datetime(2026, 10, 4, 2, 30, tzinfo=UTC), datetime(2026, 10, 5, 2, 30, tzinfo=UTC)),
        (datetime(2026, 10, 4, 23, 0, tzinfo=UTC), datetime(2026, 10, 5, 2, 30, tzinfo=UTC)),
    ],
)
def test_the_next_run_is_the_next_daily_time(now: datetime, expected: datetime) -> None:
    assert next_run(now, 2, 30) == expected


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


def test_the_schedule_dumps_daily_and_retries_a_failure(
    store: DirectoryBackupStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(store, datetime(2026, 10, 3, 2, 30, tzinfo=UTC))
    clock = Clock(datetime(2026, 10, 4, 1, 0, tzinfo=UTC))
    outcomes = iter([RuntimeError("pg_dump: connection refused"), None])
    ran_at: list[datetime] = []

    def fake_run_once(settings: Settings, store_: object) -> None:
        ran_at.append(clock.now)
        outcome = next(outcomes)
        if outcome is not None:
            raise outcome
        backup.record_backup_success(clock.now.timestamp())

    monkeypatch.setattr(backup, "run_once", fake_run_once)

    with capture() as captured:
        schedule(Settings(), store, sleep=clock.sleep, now=lambda: clock.now, runs=2)

    assert ran_at == [
        datetime(2026, 10, 4, 2, 30, tzinfo=UTC),
        datetime(2026, 10, 4, 3, 0, tzinfo=UTC),  # retried 30 minutes after the failure
    ]
    points = captured.points("listenup.backup.last_success_timestamp_seconds")
    assert points == [({}, datetime(2026, 10, 4, 3, 0, tzinfo=UTC).timestamp())]


def test_on_start_the_newest_backup_in_storage_is_reported(store: DirectoryBackupStore) -> None:
    put(store, datetime(2026, 10, 2, 2, 30, tzinfo=UTC))
    put(store, datetime(2026, 10, 3, 2, 30, tzinfo=UTC))

    with capture() as captured:
        schedule(Settings(), store, runs=0)

    points = captured.points("listenup.backup.last_success_timestamp_seconds")
    assert points == [({}, datetime(2026, 10, 3, 2, 30, tzinfo=UTC).timestamp())]


def test_the_client_tools_get_every_connection_setting_psycopg_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGPASSFILE", "/secrets/pgpass")
    monkeypatch.setenv("PGHOST", "ignored-by-the-url")

    env = backup._pg_env(
        "postgresql://owner:pw@db.example.com:6543/listenup"
        "?sslmode=verify-full&sslrootcert=/certs/ca.pem&connect_timeout=5&options=-c%20x%3D1"
    )

    assert env["PGHOST"] == "db.example.com"
    assert env["PGPORT"] == "6543"
    assert env["PGUSER"] == "owner"
    assert env["PGPASSWORD"] == "pw"
    assert env["PGDATABASE"] == "listenup"
    assert env["PGSSLMODE"] == "verify-full"
    assert env["PGSSLROOTCERT"] == "/certs/ca.pem"
    assert env["PGCONNECT_TIMEOUT"] == "5"
    assert env["PGOPTIONS"] == "-c x=1"
    assert env["PGPASSFILE"] == "/secrets/pgpass"  # the container's own setting stays


def test_the_schedule_survives_storage_being_down_at_start(
    store: DirectoryBackupStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(store_: object, prefix: str) -> None:
        raise ConnectionError("storage is down")

    monkeypatch.setattr(backup, "_report_latest", unreachable)
    clock = Clock(datetime(2026, 10, 4, 1, 0, tzinfo=UTC))
    ran: list[datetime] = []
    monkeypatch.setattr(backup, "run_once", lambda *_: ran.append(clock.now))

    schedule(Settings(), store, sleep=clock.sleep, now=lambda: clock.now, runs=1)

    assert ran == [datetime(2026, 10, 4, 2, 30, tzinfo=UTC)]


def test_a_failed_prune_does_not_make_the_dump_look_failed(
    store: DirectoryBackupStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = backup.Manifest(
        stamp="20261004T023000Z",
        created_at=datetime(2026, 10, 4, 2, 30, tzinfo=UTC).isoformat(),
        database="listenup",
        server_version="160000",
        alembic_revision=None,
        dump_key="k",
        dump_bytes=1,
        dump_sha256="0",
        dump_seconds=1.0,
        row_counts={},
    )
    monkeypatch.setattr(backup, "dump", lambda *_: manifest)

    def broken(*_: object) -> list[str]:
        raise RuntimeError("AccessDenied")

    monkeypatch.setattr(backup, "prune", broken)

    assert backup.run_once(Settings(), store) is manifest
