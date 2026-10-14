"""Durable writers survive loss of the connection that holds the account row."""

import asyncio
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from listenup.modules.identity import jobs as identity_jobs
from listenup.modules.identity import service as identity
from listenup.platform.config import Settings
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps
from listenup.platform.storage import S3Storage, StorageWriteUncertain, use_storage
from listenup.platform.storage_fence import StorageWriteInProgress, storage_transaction
from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import FakeStorage
from tests.integration.test_storage import storage as storage


@pytest.mark.anyio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_uncertain_upload_failure_keeps_the_durable_fence(
    migrated_url: str, learner: uuid.UUID, monkeypatch: pytest.MonkeyPatch, cancelled: bool
) -> None:
    from listenup.platform.cancellation import finish_on_cancel

    storage = S3Storage(Settings())
    started, release = threading.Event(), threading.Event()

    def failed_upload(**kwargs: Any) -> None:
        started.set()
        assert release.wait(5)
        raise TimeoutError("client did not receive upload completion")

    monkeypatch.setattr(storage._client, "put_object", failed_upload)
    database = Database(conninfo_to_url(migrated_url))

    async def write() -> None:
        async with storage_transaction(
            database, learner, identity.hold_account_for_storage, timedelta(minutes=10)
        ) as (_, writable):
            assert writable
            await finish_on_cancel(storage.put(f"users/{learner}/uncertain", b"data", "audio/mp4"))

    task = asyncio.create_task(write())
    try:
        assert await asyncio.to_thread(started.wait, 5)
        if cancelled:
            task.cancel()
            await asyncio.sleep(0.02)
        release.set()
        with pytest.raises(asyncio.CancelledError if cancelled else StorageWriteUncertain):
            await task
        with psycopg.connect(migrated_url) as conn:
            assert conn.execute(
                "SELECT count(*) FROM ops.storage_writes WHERE subject_user_id = %s", [learner]
            ).fetchone() == (1,)
    finally:
        release.set()
        await database.dispose()
        with psycopg.connect(migrated_url, autocommit=True) as conn:
            conn.execute("DELETE FROM ops.storage_writes WHERE subject_user_id = %s", [learner])


@pytest.mark.anyio
async def test_connection_loss_keeps_the_committed_storage_fence(
    migrated_url: str, learner: uuid.UUID
) -> None:
    database = Database(conninfo_to_url(migrated_url))
    try:
        with pytest.raises(DBAPIError, match=r"terminat|closed"):
            async with storage_transaction(
                database, learner, identity.hold_account_for_storage, timedelta(minutes=10)
            ) as (session, writable):
                assert writable
                pid = await session.scalar(text("SELECT pg_backend_pid()"))
                with psycopg.connect(migrated_url, autocommit=True) as conn:
                    assert conn.execute(
                        "SELECT count(*) FROM ops.storage_writes WHERE subject_user_id = %s",
                        [learner],
                    ).fetchone() == (1,)
                    conn.execute("SELECT pg_terminate_backend(%s)", [pid])
                    # A lost row lock cannot remove the durable fence.
                    assert conn.execute(
                        "SELECT count(*) FROM ops.storage_writes WHERE subject_user_id = %s",
                        [learner],
                    ).fetchone() == (1,)
                await session.execute(text("SELECT 1"))
        with psycopg.connect(migrated_url) as conn:
            assert conn.execute(
                "SELECT count(*) FROM ops.storage_writes WHERE subject_user_id = %s", [learner]
            ).fetchone() == (0,)
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_worker_login_can_wait_for_an_upload_longer_than_its_idle_timeout(
    migrated_url: str,
    learner: uuid.UUID,
    storage: S3Storage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use the actual login role, not SET ROLE: role defaults apply at login only.
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("ALTER ROLE listenup_worker LOGIN PASSWORD 'worker-test'")
    params = psycopg.conninfo.conninfo_to_dict(migrated_url)
    params.update(user="listenup_worker", password="worker-test")
    url = conninfo_to_url(psycopg.conninfo.make_conninfo(**params))  # type: ignore[arg-type]
    database = Database(url, pool_size=1)
    try:
        async with database.transaction() as session:
            assert await session.scalar(text("SHOW idle_in_transaction_session_timeout")) == "30s"
        async with storage_transaction(
            database, learner, identity.hold_account_for_storage, timedelta(minutes=10)
        ) as (session, writable):
            assert writable
            path = tmp_path / "upload"
            path.write_bytes(b"worker upload after 30 seconds")
            original = storage._client.upload_file

            def slow_upload(*args: object, **kwargs: object) -> None:
                time.sleep(31)
                original(*args, **kwargs)

            monkeypatch.setattr(storage._client, "upload_file", slow_upload)
            await storage.put_file(f"users/{learner}/worker-test", path, "audio/mp4")
            assert await session.scalar(text("SELECT 42")) == 42
        async with database.transaction() as session:
            assert await session.scalar(text("SHOW idle_in_transaction_session_timeout")) == "30s"
    finally:
        await database.dispose()
        with psycopg.connect(migrated_url, autocommit=True) as conn:
            conn.execute("ALTER ROLE listenup_worker NOLOGIN PASSWORD NULL")


@pytest.mark.anyio
@pytest.mark.parametrize("disabled_before_registration", [False, True])
async def test_export_rechecks_eligibility_before_uploading(
    migrated_url: str, learner: uuid.UUID, disabled_before_registration: bool
) -> None:
    calls = 0

    async def hold(session: Any, user: uuid.UUID) -> bool:
        nonlocal calls
        calls += 1
        if disabled_before_registration or calls == 2:
            with psycopg.connect(migrated_url, autocommit=True) as conn:
                conn.execute(
                    "UPDATE identity.users SET status = 'pending_deletion', "
                    "deletion_scheduled_at = now() + interval '7 days' WHERE id = %s",
                    [user],
                )
        return await identity.hold_active_account(session, user)

    database = Database(conninfo_to_url(migrated_url))
    try:
        async with storage_transaction(database, learner, hold, timedelta(minutes=45)) as (
            _,
            writable,
        ):
            assert not writable
        with psycopg.connect(migrated_url) as conn:
            assert conn.execute(
                "SELECT count(*) FROM ops.storage_writes WHERE subject_user_id = %s", [learner]
            ).fetchone() == (0,)
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_abandoned_writer_blocks_purge_until_reconciled(
    migrated_url: str, learner: uuid.UUID, api_role_url: str
) -> None:
    writer, request = uuid.uuid4(), uuid.uuid4()
    prefix = f"users/{learner}/"
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE identity.users SET status = 'pending_deletion', "
            "deletion_scheduled_at = now() - interval '1 day' WHERE id = %s",
            [learner],
        )
        conn.execute(
            "INSERT INTO ops.deletion_requests "
            "(id, subject_user_id, scope, storage_prefixes, requested_at, due_at) "
            "VALUES (%s, %s, 'account', %s, now() - interval '8 days', "
            "now() - interval '1 day')",
            [request, learner, [prefix]],
        )
        conn.execute(
            "INSERT INTO ops.storage_writes (id, subject_user_id, owner, created_at) "
            "VALUES (%s, %s, 'stopped-worker:1', now() - interval '30 days')",
            [writer, learner],
        )
    # API callers cannot forge a writer, read operational ownership or clear a fence.
    with psycopg.connect(api_role_url, autocommit=True) as conn:
        for query in (
            "SELECT * FROM ops.storage_writes",
            "DELETE FROM ops.storage_writes",
            "INSERT INTO ops.storage_writes (id, subject_user_id, owner) "
            "VALUES (gen_random_uuid(), gen_random_uuid(), 'forged')",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(query)
    storage = FakeStorage()
    storage.arrive(prefix + "data", 4, data=b"kept")
    use_storage(storage)
    database = Database(conninfo_to_url(migrated_url))
    try:
        with pytest.raises(StorageWriteInProgress):
            await identity_jobs.purge_account(JobDeps(database, None, 1), str(request))
        assert prefix + "data" in storage.objects
        with psycopg.connect(migrated_url, autocommit=True) as conn:
            assert conn.execute(
                "SELECT status FROM ops.deletion_requests WHERE id = %s", [request]
            ).fetchone() == ("pending",)
            # Operator reconciliation, only after the former writer is known stopped.
            conn.execute("DELETE FROM ops.storage_writes WHERE id = %s", [writer])
        await identity_jobs.purge_account(JobDeps(database, None, 1), str(request))
        assert not storage.objects
        with psycopg.connect(migrated_url) as conn:
            assert conn.execute(
                "SELECT status FROM ops.deletion_requests WHERE id = %s", [request]
            ).fetchone() == ("completed",)
    finally:
        use_storage(None)
        await database.dispose()
        with psycopg.connect(migrated_url, autocommit=True) as conn:
            conn.execute("DELETE FROM ops.storage_writes WHERE id = %s", [writer])
