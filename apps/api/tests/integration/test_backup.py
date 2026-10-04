"""Dump a migrated database and restore it into a scratch database (#97, ADR 0032).

Runs pg_dump and pg_restore against the test server; the dumps go to a directory
standing in for the bucket. Skipped when the PostgreSQL client tools are missing,
unless LISTENUP_REQUIRE_DB=1 (CI installs them).
"""

import json
import os
import shutil
import uuid
from pathlib import Path

import psycopg
import pytest

from listenup.ops import backup
from listenup.ops.backup import dump, restore, restore_test, stamps
from listenup.ops.store import DirectoryBackupStore
from listenup.platform.config import Settings
from tests.integration.conftest import conninfo_to_url

PREFIX = "backups/postgres/"


@pytest.fixture(autouse=True)
def client_tools() -> None:
    if shutil.which("pg_dump") and shutil.which("pg_restore"):
        return
    if os.environ.get("LISTENUP_REQUIRE_DB") == "1":
        pytest.fail("pg_dump and pg_restore must be on the PATH")
    pytest.skip("pg_dump and pg_restore are not installed")


@pytest.fixture
def source(make_database: object) -> str:
    """A migrated database of its own with a few rows, so other tests cannot change it."""
    from alembic import command

    from tests.integration.conftest import alembic_config

    url: str = make_database()  # type: ignore[operator]
    command.upgrade(alembic_config(url), "head")
    with psycopg.connect(url, autocommit=True) as conn:
        for n in range(3):
            conn.execute(
                "INSERT INTO identity.users (id, email) VALUES (%s, %s)",
                [uuid.uuid4(), f"backup-{n}-{uuid.uuid4().hex}@example.com"],
            )
    return url


@pytest.fixture
def settings(source: str) -> Settings:
    return Settings(database_url=conninfo_to_url(source), backup_prefix=PREFIX)


@pytest.fixture
def store(tmp_path: Path) -> DirectoryBackupStore:
    return DirectoryBackupStore(tmp_path / "bucket")


def databases(url: str) -> set[str]:
    with psycopg.connect(url) as conn:
        return {row[0] for row in conn.execute("SELECT datname FROM pg_database")}


def test_a_dump_and_its_manifest_reach_storage(
    settings: Settings, store: DirectoryBackupStore
) -> None:
    manifest = dump(settings, store)

    keys = {item.key for item in store.list_files(PREFIX)}
    assert keys == {
        f"{PREFIX}{manifest.stamp}/{backup.DUMP_NAME}",
        f"{PREFIX}{manifest.stamp}/{backup.MANIFEST_NAME}",
    }
    assert stamps(store, PREFIX) == [manifest.stamp]
    assert manifest.row_counts["identity.users"] == 3
    assert "procrastinate.procrastinate_jobs" in manifest.row_counts
    assert manifest.alembic_revision is not None
    assert any(s.startswith("search_path=") for s in manifest.database_settings)
    stored = json.loads((store.root / f"{PREFIX}{manifest.stamp}/manifest.json").read_text())
    assert stored["dump_sha256"] == manifest.dump_sha256


def test_a_restore_test_restores_every_row_and_drops_the_scratch_database(
    settings: Settings, store: DirectoryBackupStore, source: str
) -> None:
    manifest = dump(settings, store)
    before = databases(source)

    report = restore_test(settings, store)

    assert report.ok, report.mismatches
    assert report.within_rto
    assert report.stamp == manifest.stamp
    assert report.tables == len(manifest.row_counts)
    assert report.alembic_revision == manifest.alembic_revision
    assert databases(source) == before  # the scratch database is gone


def test_a_restored_database_keeps_its_settings_and_grants(
    settings: Settings, store: DirectoryBackupStore, source: str, make_database: object
) -> None:
    manifest = dump(settings, store)
    target: str = make_database()  # type: ignore[operator]

    restore(settings, store, manifest.stamp, conninfo_to_url(target))

    with psycopg.connect(source) as conn:
        search_path = conn.execute("SHOW search_path").fetchone()
    with psycopg.connect(target) as conn:
        # Database settings come from the manifest: the queue's functions resolve.
        assert conn.execute("SHOW search_path").fetchone() == search_path
        assert conn.execute("SELECT to_regproc('procrastinate_defer_jobs_v1')").fetchone() != (
            None,
        )
        assert conn.execute("SHOW timezone").fetchone() == ("UTC",)
        users = conn.execute("SELECT count(*) FROM identity.users").fetchone()
        assert users == (3,)
        allowed = conn.execute(
            "SELECT has_table_privilege('listenup_api', 'identity.users', 'SELECT')"
        ).fetchone()
        assert allowed == (True,)


def test_a_count_that_does_not_match_fails_the_restore_test(
    settings: Settings, store: DirectoryBackupStore
) -> None:
    manifest = dump(settings, store)
    path = store.root / f"{PREFIX}{manifest.stamp}/{backup.MANIFEST_NAME}"
    edited = json.loads(path.read_text())
    edited["row_counts"]["identity.users"] = 4
    path.write_text(json.dumps(edited))

    report = restore_test(settings, store)

    assert not report.ok
    assert report.mismatches == {"identity.users": (4, 3)}


def test_a_damaged_dump_is_refused_before_restoring(
    settings: Settings, store: DirectoryBackupStore, source: str
) -> None:
    manifest = dump(settings, store)
    (store.root / manifest.dump_key).write_bytes(b"not a dump")
    before = databases(source)

    with pytest.raises(RuntimeError, match="checksum"):
        restore_test(settings, store)

    assert databases(source) == before


def test_the_cli_restore_test_reports_json_and_exit_code(
    settings: Settings,
    store: DirectoryBackupStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dump(settings, store)
    monkeypatch.setattr(backup, "get_settings", lambda: settings)

    code = backup.main(["--local-dir", str(store.root), "restore-test"])

    assert code == 0
    result = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (result["ok"], result["within_rto"], result["mismatches"]) == (True, True, {})
