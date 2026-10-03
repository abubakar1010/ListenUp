"""Job lanes with real Procrastinate workers (#28; System Design 4, 11.1, 11.3).

Each test runs workers with wait=False: they take every job that is ready, then stop.
"""

import importlib.metadata
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import procrastinate
import psycopg
import pytest
from procrastinate import schema
from sqlalchemy import text

from listenup.platform.database import Database
from listenup.platform.jobs import (
    JobDeps,
    Lane,
    PermanentError,
    SpeechBacklogGate,
    app,
    configure_runtime,
    enqueue,
    failed_jobs,
    job,
    set_gate,
)
from listenup.platform.log import current_request_id, request_id_bound
from tests.integration.conftest import conninfo_to_url

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

calls: list[dict[str, Any]] = []


@job(Lane.BACKGROUND, "test.record")
async def record(deps: JobDeps, **args: Any) -> None:
    calls.append({"job": "record", "args": args, "request_id": current_request_id()})


@job(Lane.BACKGROUND, "test.first_step")
async def first_step(deps: JobDeps, item: str) -> None:
    calls.append({"job": "first_step", "item": item})
    async with deps.database.transaction() as session:
        await enqueue(session, "test.second_step", item=item)


@job(Lane.BACKGROUND, "test.second_step")
async def second_step(deps: JobDeps, item: str) -> None:
    calls.append({"job": "second_step", "item": item})


@job(Lane.BACKGROUND, "test.always_fails", max_attempts=3)
async def always_fails(deps: JobDeps) -> None:
    calls.append({"job": "always_fails", "attempt": deps.attempt})
    raise ConnectionError("provider unreachable")


@job(Lane.BACKGROUND, "test.bad_input")
async def bad_input(deps: JobDeps) -> None:
    calls.append({"job": "bad_input"})
    raise PermanentError("the gist is empty")


@job(Lane.BACKGROUND, "test.too_slow", timeout=timedelta(milliseconds=50))
async def too_slow(deps: JobDeps) -> None:
    import asyncio

    calls.append({"job": "too_slow"})
    await asyncio.sleep(5)


@job(Lane.SPEECH_INTERACTIVE, "test.speech")
async def speech(deps: JobDeps) -> None:
    calls.append({"job": "speech"})


@job(Lane.INTAKE, "test.intake")
async def intake(deps: JobDeps, clip: str) -> None:
    calls.append({"job": "intake", "clip": clip})


@pytest.fixture
async def queue(migrated_url: str) -> AsyncIterator[Database]:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("DELETE FROM procrastinate.procrastinate_jobs")
    calls.clear()
    database = Database(conninfo_to_url(migrated_url), pool_size=2)
    configure_runtime(database)
    connector = procrastinate.PsycopgConnector(conninfo=migrated_url)
    with app.replace_connector(connector):
        async with app.open_async():
            yield database
    set_gate(Lane.INTAKE, None)
    await database.dispose()


async def work(*lanes: Lane) -> None:
    await app.run_worker_async(
        queues=[lane.value for lane in lanes], wait=False, install_signal_handlers=False
    )


async def jobs(database: Database) -> list[dict[str, Any]]:
    async with database.transaction() as session:
        rows = await session.execute(
            text(
                "SELECT id, task_name, status::text AS status, attempts, args, scheduled_at "
                "FROM procrastinate.procrastinate_jobs ORDER BY id"
            )
        )
        return [dict(row) for row in rows.mappings()]


async def make_due(database: Database) -> None:
    """Skip the backoff wait so the next worker run picks retried jobs up."""
    async with database.transaction() as session:
        await session.execute(
            text(
                "UPDATE procrastinate.procrastinate_jobs SET scheduled_at = now() "
                "WHERE status = 'todo'"
            )
        )


@pytest.mark.anyio
async def test_a_rolled_back_change_never_enqueues_its_job(queue: Database) -> None:
    with pytest.raises(RuntimeError):
        async with queue.transaction() as session:
            await enqueue(session, "test.record", note="rolled back")
            raise RuntimeError("the data change failed")

    assert await jobs(queue) == []


@pytest.mark.anyio
async def test_a_queued_job_runs_with_the_request_id(queue: Database) -> None:
    with request_id_bound("req-42"):
        async with queue.transaction() as session:
            job_id = await enqueue(session, "test.record", note="hello")

    await work(Lane.BACKGROUND)

    assert job_id is not None
    assert calls == [{"job": "record", "args": {"note": "hello"}, "request_id": "req-42"}]
    assert (await jobs(queue))[0]["status"] == "succeeded"


@pytest.mark.anyio
async def test_two_enqueues_with_the_same_unique_key_run_once(queue: Database) -> None:
    async with queue.transaction() as session:
        first = await enqueue(session, "test.record", unique_key="grade_round:1", n=1)
    async with queue.transaction() as session:
        second = await enqueue(session, "test.record", unique_key="grade_round:1", n=2)
        # The duplicate did not spoil the rest of this transaction.
        await session.execute(text("SELECT 1"))

    await work(Lane.BACKGROUND)

    assert first is not None
    assert second is None
    assert [c["args"] for c in calls] == [{"n": 1}]


@pytest.mark.anyio
async def test_a_job_chains_the_next_step(queue: Database) -> None:
    async with queue.transaction() as session:
        await enqueue(session, "test.first_step", item="clip-1")

    await work(Lane.BACKGROUND)

    assert calls == [
        {"job": "first_step", "item": "clip-1"},
        {"job": "second_step", "item": "clip-1"},
    ]


@pytest.mark.anyio
async def test_a_job_that_uses_up_its_attempts_is_failed_and_listed(queue: Database) -> None:
    async with queue.transaction() as session:
        job_id = await enqueue(session, "test.always_fails")

    for _ in range(5):
        await work(Lane.BACKGROUND)
        await make_due(queue)

    assert [c["attempt"] for c in calls] == [1, 2, 3]
    assert (await jobs(queue))[0]["status"] == "failed"
    async with queue.transaction() as session:
        listed = await failed_jobs(session)
    assert [(row["id"], row["name"], row["attempts"]) for row in listed] == [
        (job_id, "test.always_fails", 3)
    ]
    assert listed[0]["failed_at"] is not None


@pytest.mark.anyio
async def test_retries_wait_with_backoff(queue: Database) -> None:
    async with queue.transaction() as session:
        await enqueue(session, "test.always_fails")

    await work(Lane.BACKGROUND)

    [state] = await jobs(queue)
    assert state["status"] == "todo"
    async with queue.transaction() as session:
        wait = await session.scalar(
            text(
                "SELECT extract(epoch FROM scheduled_at - now()) "
                "FROM procrastinate.procrastinate_jobs"
            )
        )
    assert 5 <= float(wait) <= 12  # about 10 s, give or take 20%


@pytest.mark.anyio
async def test_a_validation_error_fails_without_retrying(queue: Database) -> None:
    async with queue.transaction() as session:
        await enqueue(session, "test.bad_input")

    await work(Lane.BACKGROUND)
    await make_due(queue)
    await work(Lane.BACKGROUND)

    assert len(calls) == 1
    assert (await jobs(queue))[0]["status"] == "failed"


@pytest.mark.anyio
async def test_a_job_over_its_timeout_is_stopped_and_retried(queue: Database) -> None:
    async with queue.transaction() as session:
        await enqueue(session, "test.too_slow")

    await work(Lane.BACKGROUND)

    [state] = await jobs(queue)
    assert (state["status"], state["attempts"]) == ("todo", 1)


async def backdate_speech_jobs(database: Database, seconds: int) -> None:
    async with database.transaction() as session:
        await session.execute(
            text(
                "UPDATE procrastinate.procrastinate_events e "
                "SET at = now() - make_interval(secs => :s) "
                "FROM procrastinate.procrastinate_jobs j "
                "WHERE e.job_id = j.id AND j.queue_name = 'speech-interactive'"
            ),
            {"s": seconds},
        )


@pytest.mark.anyio
async def test_intake_pauses_while_speech_work_waits_and_resumes_when_it_drains(
    queue: Database,
) -> None:
    set_gate(Lane.INTAKE, SpeechBacklogGate())
    async with queue.transaction() as session:
        await enqueue(session, "test.speech")
        await enqueue(session, "test.intake", clip="a")
    await backdate_speech_jobs(queue, 31)

    await work(Lane.INTAKE)

    assert calls == []  # intake did not start
    waiting = [
        j for j in await jobs(queue) if j["task_name"] == "test.intake" and j["status"] == "todo"
    ]
    assert len(waiting) == 1
    assert waiting[0]["attempts"] == 0  # waiting did not use up an attempt
    assert waiting[0]["args"] == {"clip": "a"}

    await work(Lane.SPEECH_INTERACTIVE)  # the speech lane drains
    await make_due(queue)
    await work(Lane.INTAKE)

    assert calls == [{"job": "speech"}, {"job": "intake", "clip": "a"}]


@pytest.mark.anyio
async def test_a_short_speech_wait_does_not_pause_intake(queue: Database) -> None:
    set_gate(Lane.INTAKE, SpeechBacklogGate())
    async with queue.transaction() as session:
        await enqueue(session, "test.speech")
        await enqueue(session, "test.intake", clip="b")
    await backdate_speech_jobs(queue, 5)

    await work(Lane.INTAKE)

    assert calls == [{"job": "intake", "clip": "b"}]


@pytest.mark.anyio
async def test_the_api_role_can_enqueue(queue: Database) -> None:
    async with queue.transaction() as session:
        await session.execute(text("SET LOCAL ROLE listenup_api"))
        job_id = await enqueue(session, "test.record", by="api")
    assert job_id is not None


@pytest.mark.anyio
async def test_unknown_jobs_are_refused(queue: Database) -> None:
    async with queue.transaction() as session:
        with pytest.raises(KeyError):
            await enqueue(session, "test.nope")


def test_the_vendored_queue_schema_matches_the_installed_library() -> None:
    version = importlib.metadata.version("procrastinate")
    vendored = MIGRATIONS / "sql" / f"procrastinate-{version}.sql"
    assert vendored.exists(), (
        f"Procrastinate {version} is installed but its schema is not vendored: add a "
        "migration that applies Procrastinate's own migration files, and vendor the new schema"
    )
    assert vendored.read_text() == schema.SchemaManager.get_schema()


def test_new_connections_find_the_queue_schema(migrated_url: str) -> None:
    with psycopg.connect(migrated_url) as conn:
        path = conn.execute("SHOW search_path").fetchone()
        found = conn.execute(
            "SELECT relnamespace::regnamespace::text FROM pg_class "
            "WHERE oid = to_regclass('procrastinate_jobs')"
        ).fetchone()
    assert path is not None and "procrastinate" in str(path[0])
    assert found == ("procrastinate",)
