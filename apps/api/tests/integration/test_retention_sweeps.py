"""Retention sweeps that do not depend on YouTube (#93, owner exception E1).

Handlers are called directly as the worker role would run them, against rows aged
with the owner connection. Shadow recordings use the fake storage.
"""

import asyncio
import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import pytest
from sqlalchemy import text

from listenup.ops import retention
from listenup.platform.config import Settings
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps
from listenup.platform.storage import use_storage
from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import FakeStorage
from tests.integration.seed import create_learner, seed_learner_data


@pytest.fixture
def storage() -> Iterator[FakeStorage]:
    fake = FakeStorage()
    use_storage(fake)
    yield fake
    use_storage(None)


def run(migrated_url: str, handler: Callable[..., Any], **args: Any) -> Any:
    async def go() -> Any:
        database = Database(conninfo_to_url(migrated_url), pool_size=2)
        try:
            return await handler(JobDeps(database, None, 1), **args)
        finally:
            await database.dispose()

    return asyncio.run(go())


def one(migrated_url: str, sql: str, *params: object) -> Any:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        row = conn.execute(sql, params).fetchone()  # type: ignore[arg-type]
    return row[0] if row else None


def execute(migrated_url: str, sql: str, *params: object) -> None:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(sql, params)  # type: ignore[arg-type]


# --- Shadow recordings (FR-SH-17, D7) ---------------------------------------------


def recorded_round(migrated_url: str, days_ago: int) -> tuple[uuid.UUID, str]:
    user = create_learner(migrated_url)
    world = seed_learner_data(migrated_url, user)
    key = one(
        migrated_url,
        "SELECT recording_key FROM practice.shadow_rounds WHERE id = %s",
        world.shadow_round_id,
    )
    # The trigger fixes recorded_at; ageing a recording for the test needs it off.
    with psycopg.connect(migrated_url) as conn:
        conn.execute("ALTER TABLE practice.shadow_rounds DISABLE TRIGGER USER")
        conn.execute(
            "UPDATE practice.shadow_rounds SET recorded_at = now() - make_interval(days => %s) "
            "WHERE id = %s",
            [days_ago, world.shadow_round_id],
        )
        conn.execute("ALTER TABLE practice.shadow_rounds ENABLE TRIGGER USER")
    return world.shadow_round_id, key


def test_recording_older_than_retention_is_removed_and_the_round_is_kept(
    migrated_url: str, storage: FakeStorage
) -> None:
    """A recording past 90 days leaves storage; the round row and its time stay."""
    round_id, key = recorded_round(migrated_url, 91)

    removed = run(migrated_url, retention.sweep_shadow_recordings)

    assert removed >= 1
    assert key in storage.deleted
    row = one(
        migrated_url,
        "SELECT (recording_key, recording_mime, recording_bytes, uploaded_at) IS NOT DISTINCT "
        "FROM (NULL::text, NULL::text, NULL::int, NULL::timestamptz) AND recorded_at IS NOT NULL "
        "FROM practice.shadow_rounds WHERE id = %s",
        round_id,
    )
    assert row is True


def test_recording_inside_retention_is_kept(migrated_url: str, storage: FakeStorage) -> None:
    round_id, key = recorded_round(migrated_url, 89)

    run(migrated_url, retention.sweep_shadow_recordings)

    assert key not in storage.deleted
    kept = one(
        migrated_url,
        "SELECT recording_key FROM practice.shadow_rounds WHERE id = %s",
        round_id,
    )
    assert kept == key


def test_recording_retention_reads_configuration(
    migrated_url: str, storage: FakeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 90 days is a setting (D7): a shorter one removes a younger recording."""
    _, key = recorded_round(migrated_url, 10)
    monkeypatch.setattr(
        retention, "get_settings", lambda: Settings(shadow_recording_retention_days=7)
    )

    run(migrated_url, retention.sweep_shadow_recordings)

    assert key in storage.deleted


def test_recording_sweep_preserves_all_nonrecording_round_data(
    migrated_url: str, storage: FakeStorage
) -> None:
    """Preserve every shipped round field; Shadow grades/labels are not shipped yet.

    This projection also picks up future columns, rather than claiming playback
    status alone establishes grade/label preservation.
    """
    round_id, _ = recorded_round(migrated_url, 120)
    query = (
        "SELECT to_jsonb(r) - ARRAY['recording_key','recording_mime',"
        "'recording_bytes','uploaded_at'] "
        "FROM practice.shadow_rounds r WHERE id=%s"
    )
    before = one(migrated_url, query, round_id)
    run(migrated_url, retention.sweep_shadow_recordings)
    assert one(migrated_url, query, round_id) == before


def test_recording_sweep_is_idempotent(migrated_url: str, storage: FakeStorage) -> None:
    _, _key = recorded_round(migrated_url, 100)

    run(migrated_url, retention.sweep_shadow_recordings)
    deleted = list(storage.deleted)
    again = run(migrated_url, retention.sweep_shadow_recordings)

    assert storage.deleted == deleted
    assert again == 0


def test_recording_sweep_retries_a_file_whose_row_was_not_cleared(
    migrated_url: str, storage: FakeStorage
) -> None:
    """The file goes first, so a crash between the two leaves a key pointing at nothing;
    the next sweep deletes again (deleting a missing file is not an error)."""
    round_id, key = recorded_round(migrated_url, 100)
    storage.deleted.append(key)  # the file is already gone

    run(migrated_url, retention.sweep_shadow_recordings)

    cleared = one(
        migrated_url,
        "SELECT recording_key IS NULL FROM practice.shadow_rounds WHERE id = %s",
        round_id,
    )
    assert cleared is True


def test_recording_sweep_works_in_batches(
    migrated_url: str, storage: FakeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = [recorded_round(migrated_url, 100) for _ in range(3)]
    monkeypatch.setattr(retention, "SHADOW_BATCH", 2)

    run(migrated_url, retention.sweep_shadow_recordings)

    for _, key in ids:
        assert key in storage.deleted


def test_shadow_trigger_still_fixes_other_recording_changes(
    migrated_url: str,
) -> None:
    """Only clearing the whole recording is allowed after it is recorded."""
    round_id, _ = recorded_round(migrated_url, 1)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "UPDATE practice.shadow_rounds SET recorded_at = now() WHERE id = %s",
                [round_id],
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "UPDATE practice.shadow_rounds SET recording_key = NULL WHERE id = %s",
                [round_id],
            )


def test_shadow_trigger_refuses_a_clear_that_also_moves_recorded_at(
    migrated_url: str,
) -> None:
    round_id, _ = recorded_round(migrated_url, 1)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "UPDATE practice.shadow_rounds SET recording_key = NULL, recording_mime = NULL, "
                "recording_bytes = NULL, uploaded_at = NULL, recorded_at = now() WHERE id = %s",
                [round_id],
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "UPDATE practice.shadow_rounds SET playback_status = 'ready' WHERE id = %s",
                [round_id],
            )


def test_one_failing_delete_does_not_block_newer_recordings(
    migrated_url: str, storage: FakeStorage
) -> None:
    """A storage error on the oldest key must not stop the others from expiring; the
    failed row keeps its key so the next run retries, and the run reports the failure."""
    old_id, old_key = recorded_round(migrated_url, 200)
    new_id, new_key = recorded_round(migrated_url, 100)
    real_delete = storage.delete

    async def delete(key: str) -> None:
        if key == old_key:
            raise OSError("storage unavailable")
        await real_delete(key)

    storage.delete = delete  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        run(migrated_url, retention.sweep_shadow_recordings)

    assert new_key in storage.deleted
    keys = {
        row_id: one(
            migrated_url,
            "SELECT recording_key FROM practice.shadow_rounds WHERE id = %s",
            row_id,
        )
        for row_id in (old_id, new_id)
    }
    assert keys == {old_id: old_key, new_id: None}


def test_shadow_trigger_refuses_clearing_recorded_at_to_null(migrated_url: str) -> None:
    round_id, _ = recorded_round(migrated_url, 100)
    with (
        psycopg.connect(migrated_url, autocommit=True) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        conn.execute(
            "UPDATE practice.shadow_rounds SET recording_key=NULL, recording_mime=NULL, "
            "recording_bytes=NULL, uploaded_at=NULL, recorded_at=NULL WHERE id=%s",
            [round_id],
        )


def test_recording_storage_calls_hold_no_database_transaction(
    migrated_url: str, storage: FakeStorage
) -> None:
    recorded_round(migrated_url, 100)

    async def go() -> None:
        database = Database(conninfo_to_url(migrated_url))

        class ObservedDatabase:
            active = 0

            @asynccontextmanager
            async def transaction(self):
                async with database.transaction() as session:
                    await session.execute(text("SET LOCAL ROLE listenup_worker"))
                    await session.execute(
                        text("SET LOCAL idle_in_transaction_session_timeout='30s'")
                    )
                    self.active += 1
                    try:
                        yield session
                    finally:
                        self.active -= 1

        observed = ObservedDatabase()
        original = storage.delete

        async def delete(key: str) -> None:
            assert observed.active == 0, "storage latency must not hold a DB transaction"
            await original(key)

        storage.delete = delete  # type: ignore[method-assign]
        try:
            await retention.sweep_shadow_recordings(JobDeps(observed, None, 1))  # type: ignore[arg-type]
        finally:
            await database.dispose()

    asyncio.run(go())


@pytest.mark.parametrize(
    ("offset", "removed"),
    [("-1 microsecond", True), ("0 seconds", False), ("1 microsecond", False)],
)
def test_recording_exact_retention_boundary(migrated_url, storage, offset, removed):
    round_id, key = recorded_round(migrated_url, 100)

    async def go():
        database = Database(conninfo_to_url(migrated_url))

        class BoundaryDatabase:
            first = True

            @asynccontextmanager
            async def transaction(self):
                async with database.transaction() as session:
                    if self.first:
                        self.first = False
                        await session.execute(
                            text("ALTER TABLE practice.shadow_rounds DISABLE TRIGGER USER")
                        )
                        await session.execute(
                            text(
                                "UPDATE practice.shadow_rounds SET recorded_at=now()"
                                "-interval '90 days' "
                                "+cast(:offset as interval) WHERE id=:id"
                            ),
                            {"id": round_id, "offset": offset},
                        )
                        await session.execute(
                            text("ALTER TABLE practice.shadow_rounds ENABLE TRIGGER USER")
                        )
                    yield session

        try:
            await retention.sweep_shadow_recordings(JobDeps(BoundaryDatabase(), None, 1))
        finally:
            await database.dispose()

    asyncio.run(go())
    assert (key in storage.deleted) is removed


def test_recording_database_rollback_keeps_key_for_retry(
    migrated_url: str, storage: FakeStorage
) -> None:
    round_id, key = recorded_round(migrated_url, 100)

    async def go() -> None:
        database = Database(conninfo_to_url(migrated_url))

        class RollbackOnce:
            failed = False

            @asynccontextmanager
            async def transaction(self):
                async with database.transaction() as session:
                    yield session
                    if key in storage.deleted and not self.failed:
                        self.failed = True
                        raise RuntimeError("crash before commit")

        try:
            with pytest.raises(RuntimeError, match="crash before commit"):
                await retention.sweep_shadow_recordings(JobDeps(RollbackOnce(), None, 1))  # type: ignore[arg-type]
            assert (
                one(
                    migrated_url,
                    "SELECT recording_key FROM practice.shadow_rounds WHERE id=%s",
                    round_id,
                )
                == key
            )
            await retention.sweep_shadow_recordings(JobDeps(database, None, 2))
            assert storage.deleted.count(key) == 2
            assert (
                one(
                    migrated_url,
                    "SELECT recording_key FROM practice.shadow_rounds WHERE id=%s",
                    round_id,
                )
                is None
            )
        finally:
            await database.dispose()

    asyncio.run(go())


def test_recording_overlap_does_not_lock_normal_traffic(
    migrated_url: str, storage: FakeStorage
) -> None:
    round_id, key = recorded_round(migrated_url, 100)

    async def go() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=3)
        entered, release = asyncio.Event(), asyncio.Event()
        original = storage.delete
        calls = 0

        async def delete(key: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
            await original(key)

        storage.delete = delete  # type: ignore[method-assign]
        first = asyncio.create_task(retention.sweep_shadow_recordings(JobDeps(database, None, 1)))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            async with database.transaction() as session:
                await session.execute(text("SET LOCAL lock_timeout = '100ms'"))
                await session.execute(
                    text(
                        "UPDATE practice.shadow_rounds SET playback_status=playback_status "
                        "WHERE id=:id"
                    ),
                    {"id": round_id},
                )
            second = await asyncio.wait_for(
                retention.sweep_shadow_recordings(JobDeps(database, None, 1)), 5
            )
            release.set()
            assert second + await first == 1
            assert key in storage.deleted
            assert (
                one(
                    migrated_url,
                    "SELECT recording_key FROM practice.shadow_rounds WHERE id=%s",
                    round_id,
                )
                is None
            )
        finally:
            release.set()
            await asyncio.gather(first, return_exceptions=True)
            await database.dispose()

    asyncio.run(go())


# --- Short-lived data -------------------------------------------------------------


def test_expired_login_sessions_are_removed(migrated_url: str, learner: uuid.UUID) -> None:
    old, live = uuid.uuid4(), uuid.uuid4()
    for session_id, offset in ((old, "-1 minute"), (live, "1 hour")):
        execute(
            migrated_url,
            "INSERT INTO identity.auth_sessions (id, user_id, token_hash, expires_at) "
            "VALUES (%s, %s, %s, now() + %s::interval)",
            session_id,
            learner,
            os.urandom(32),
            offset,
        )

    run(migrated_url, retention.sweep_login_sessions)

    assert one(migrated_url, "SELECT count(*) FROM identity.auth_sessions WHERE id=%s", old) == 0
    assert one(migrated_url, "SELECT count(*) FROM identity.auth_sessions WHERE id=%s", live) == 1


@pytest.mark.parametrize(
    ("used", "expires", "removed"),
    [
        ("-8 days", "-9 days", True),  # used 8 days ago
        (None, "-8 days", True),  # expired 8 days ago, never used
        ("-6 days", "-6 days", False),
        (None, "1 hour", False),  # still valid
    ],
)
def test_one_time_tokens_go_seven_days_after_use_or_expiry(
    migrated_url: str, learner: uuid.UUID, used: str | None, expires: str, removed: bool
) -> None:
    token_hash = os.urandom(32)
    execute(
        migrated_url,
        "INSERT INTO identity.one_time_tokens (token_hash, user_id, purpose, expires_at, used_at) "
        "VALUES (%s, %s, 'reset_password', now() + %s::interval, "
        "CASE WHEN %s::text IS NULL THEN NULL ELSE now() + %s::interval END)",
        token_hash,
        learner,
        expires,
        used,
        used,
    )

    run(migrated_url, retention.sweep_one_time_tokens)

    left = one(
        migrated_url,
        "SELECT count(*) FROM identity.one_time_tokens WHERE token_hash = %s",
        token_hash,
    )
    assert left == (0 if removed else 1)


def test_idempotency_keys_go_after_a_day(migrated_url: str, learner: uuid.UUID) -> None:
    for key, age in (("old-key", "25 hours"), ("fresh-key", "23 hours")):
        execute(
            migrated_url,
            "INSERT INTO ops.idempotency_keys (user_id, key, request_hash, created_at) "
            "VALUES (%s, %s, %s, now() - %s::interval)",
            learner,
            key,
            b"x",
            age,
        )

    run(migrated_url, retention.sweep_idempotency_keys)

    keys = {
        key
        for (key,) in psycopg.connect(migrated_url, autocommit=True).execute(
            "SELECT key FROM ops.idempotency_keys WHERE user_id = %s", [learner]
        )
    }
    assert keys == {"fresh-key"}


def test_rate_counters_older_than_a_day_are_removed(migrated_url: str) -> None:
    execute(
        migrated_url,
        "INSERT INTO ops.rate_counters (key, window_start, count) VALUES "
        "('retention:old', now() - interval '2 days', 1), "
        "('retention:new', now() - interval '1 hour', 1)",
    )

    run(migrated_url, retention.sweep_rate_counters)

    keys = {
        key
        for (key,) in psycopg.connect(migrated_url, autocommit=True).execute(
            "SELECT key FROM ops.rate_counters WHERE key LIKE 'retention:%'"
        )
    }
    assert keys == {"retention:new"}


def test_sweeps_are_safe_to_repeat(migrated_url: str) -> None:
    for sweep in (
        retention.sweep_login_sessions,
        retention.sweep_one_time_tokens,
        retention.sweep_idempotency_keys,
        retention.sweep_rate_counters,
    ):
        run(migrated_url, sweep)
        assert run(migrated_url, sweep) == 0


# --- Worker scratch files ---------------------------------------------------------


def test_scratch_sweep_does_nothing_without_a_configured_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The system temp directory is shared with other programs; never sweep it."""
    monkeypatch.setattr(retention, "get_settings", lambda: Settings(media_scratch_dir=None))

    assert asyncio.run(retention.sweep_scratch_files(JobDeps(None, None, 1))) == 0  # type: ignore[arg-type]


def test_sweeps_are_registered_and_scheduled() -> None:
    from listenup.platform.jobs import Lane, _registry

    names = {
        "ops.sweep_shadow_recordings": Lane.BACKGROUND,
        "ops.sweep_login_sessions": Lane.BACKGROUND,
        "ops.sweep_one_time_tokens": Lane.BACKGROUND,
        "ops.sweep_idempotency_keys": Lane.BACKGROUND,
        "ops.sweep_rate_counters": Lane.BACKGROUND,
        # Scratch files live on the media pool's disk, so its lane sweeps them.
        "ops.sweep_scratch_files": Lane.INTAKE,
        "ops.sweep_default_scratch_files": Lane.BACKGROUND,
    }
    for name, lane in names.items():
        assert _registry[name].lane == lane
        assert _registry[name].schedule is not None
