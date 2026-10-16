"""Story #45: committed intake work, shared cache and gated service reads."""

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from listenup.modules.practice import service as practice
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError
from listenup.platform.jobs import JobDeps, Reschedule
from tests.integration.conftest import conninfo_to_url
from tests.integration.seed import add_clip
from tests.unit.test_transcript_packing import result


@pytest.fixture
def clip(migrated_url, learner):
    media, content, _ = add_clip(migrated_url, learner)
    with psycopg.connect(migrated_url) as conn:
        conn.execute("UPDATE content.media_objects SET duration_ms=600000 WHERE id=%s", [media])
    return media, content


async def start(database, learner, content, left=10000, right=190000):
    async with database.transaction(learner) as db:
        return await practice.start_plan(db, learner, content, left, right, practice.Entry.BLIND)


@pytest.fixture
def boundary(monkeypatch):
    from listenup.modules.transcript import jobs

    calls = []

    class Storage:
        async def download(self, key, target):
            target.write_bytes(b"audio")
            return object()

    async def extract(source, target, span):
        calls.append(span)
        target.write_bytes(b"window")

    class Gateway:
        async def transcribe(self, audio, language="en"):
            assert Path(audio).exists()
            return result()

    monkeypatch.setattr(jobs, "get_storage", lambda: Storage())
    monkeypatch.setattr(jobs, "get_gateway", lambda: Gateway())
    monkeypatch.setattr(jobs, "extract", extract)
    return calls


@pytest.mark.anyio
async def test_selection_queues_intake_transactionally(api_role_url, migrated_url, learner, clip):
    database = Database(api_role_url)
    try:
        session = await start(database, learner, clip[1])
        with psycopg.connect(migrated_url) as conn:
            row = conn.execute(
                "SELECT queue_name, args FROM procrastinate.procrastinate_jobs WHERE "
                "task_name='transcript.transcribe_passage' AND args->>'session_id'=%s",
                [str(session.id)],
            ).fetchone()
            assert row is not None
            assert row[0] == "intake"
            assert row[1]["user_id"] == str(learner)
        with pytest.raises(RuntimeError):
            async with database.transaction(learner) as db:
                rolled = await practice.start_plan(
                    db, learner, clip[1], 0, 30000, practice.Entry.BLIND
                )
                raise RuntimeError("rollback")
        with psycopg.connect(migrated_url) as conn:
            assert (
                conn.execute(
                    "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE "
                    "args->>'session_id'=%s",
                    [str(rolled.id)],
                ).fetchone()[0]
                == 0
            )
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_passage_reaches_transcribed_and_provenance_round_trip(
    migrated_url, learner, clip, boundary
):
    from listenup.modules.transcript import jobs, service

    database = Database(conninfo_to_url(migrated_url))
    try:
        session = await start(database, learner, clip[1])
        await jobs.transcribe_passage(JobDeps(database, None, 1), str(session.id), str(learner))
        assert boundary == [(5000, 195000)]
        async with database.transaction(learner) as db:
            state = await practice.require_step(db, session.id, practice.Step.BLIND)
            await practice.complete_step(db, state, practice.Step.BLIND)
        async with database.transaction(learner) as db:
            data = await service.read_passage(db, database, learner, session.id)
        # This fixture's words are in the leading padding and must not leak into passage reads.
        assert data.words == []
        with psycopg.connect(migrated_url) as conn:
            row = conn.execute(
                "SELECT words, start_ms, end_ms, confidence, sentence_starts, origin, "
                "provider_info, status FROM content.passage_transcripts WHERE media_object_id=%s",
                [clip[0]],
            ).fetchone()
            assert row[:6] == (
                ["Hello.", "Again."],
                [6125, 8000],
                [6900, 9000],
                [987, 800],
                [0, 1],
                "generated",
            )
            assert row[6] == {"provider": "test", "model": "speech", "version": "v1"}
            assert row[7] == "ready"
        await jobs.transcribe_passage(JobDeps(database, None, 2), str(session.id), str(learner))
        assert len(boundary) == 1
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_overlap_reuses_cache_and_retry_keeps_completed_spans(
    migrated_url, learner, clip, boundary, monkeypatch
):
    from listenup.modules.transcript import jobs

    database = Database(conninfo_to_url(migrated_url))
    try:
        first = await start(database, learner, clip[1], 10000, 190000)
        await jobs.transcribe_passage(JobDeps(database, None, 1), str(first.id), str(learner))
        second = await start(database, learner, clip[1], 150000, 330000)
        await jobs.transcribe_passage(JobDeps(database, None, 1), str(second.id), str(learner))
        assert boundary == [(5000, 195000), (195000, 335000)]

        async def fail(*args, **kwargs):
            raise ConnectionError("provider down")

        monkeypatch.setattr(jobs, "get_gateway", lambda: SimpleNamespace(transcribe=fail))
        third = await start(database, learner, clip[1], 320000, 500000)
        with pytest.raises(ConnectionError):
            await jobs.transcribe_passage(JobDeps(database, None, 1), str(third.id), str(learner))
        with psycopg.connect(migrated_url) as conn:
            assert (
                conn.execute(
                    "SELECT count(*) FROM content.passage_transcripts WHERE media_object_id=%s "
                    "AND status='ready'",
                    [clip[0]],
                ).fetchone()[0]
                == 2
            )

        async def recover(*args, **kwargs):
            return result()

        monkeypatch.setattr(jobs, "get_gateway", lambda: SimpleNamespace(transcribe=recover))
        await jobs.transcribe_passage(JobDeps(database, None, 2), str(third.id), str(learner))
        assert boundary[-2:] == [(335000, 505000), (335000, 505000)]
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_reads_enforce_learner_isolation_and_step_gate(
    api_role_url, migrated_url, learner, clip
):
    from listenup.modules.transcript import service

    api, worker = Database(api_role_url), Database(conninfo_to_url(migrated_url))
    try:
        session = await start(api, learner, clip[1])
        for caller, code in [(learner, "step_locked"), (uuid.uuid4(), "session_not_found")]:
            async with api.transaction(caller) as db:
                with pytest.raises(ProblemError) as error:
                    await service.read_passage(db, worker, caller, session.id)
                assert error.value.code == code
    finally:
        await api.dispose()
        await worker.dispose()


@pytest.mark.anyio
async def test_concurrent_requests_reuse_spans(migrated_url, learner, clip, boundary, monkeypatch):
    from listenup.modules.transcript import jobs

    database = Database(conninfo_to_url(migrated_url))
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocking(*args, **kwargs):
        entered.set()
        await release.wait()
        return result()

    monkeypatch.setattr(jobs, "get_gateway", lambda: SimpleNamespace(transcribe=blocking))
    try:
        first = await start(database, learner, clip[1])
        second = await start(database, learner, clip[1], 150000, 330000)
        task = asyncio.create_task(
            jobs.transcribe_passage(JobDeps(database, None, 1), str(first.id), str(learner))
        )
        await asyncio.wait_for(entered.wait(), 3)
        try:
            with pytest.raises(Reschedule):
                await asyncio.wait_for(
                    jobs.transcribe_passage(
                        JobDeps(database, None, 1), str(second.id), str(learner)
                    ),
                    2,
                )
        finally:
            release.set()
            await task
        await jobs.transcribe_passage(JobDeps(database, None, 2), str(second.id), str(learner))
        assert boundary == [(5000, 195000), (195000, 335000)]
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_exhausted_provider_failure_is_reported_and_retry_recovers(
    migrated_url, learner, clip, boundary, monkeypatch
):
    from listenup.modules.transcript import jobs, service
    from listenup.platform.jobs import run_handler

    database = Database(conninfo_to_url(migrated_url))

    async def fail(*args, **kwargs):
        raise ConnectionError("provider unavailable")

    monkeypatch.setattr(jobs, "get_gateway", lambda: SimpleNamespace(transcribe=fail))
    try:
        session = await start(database, learner, clip[1])
        with pytest.raises(ConnectionError):
            await run_handler(
                jobs.TRANSCRIBE,
                JobDeps(database, None, 5),
                session_id=str(session.id),
                user_id=str(learner),
            )
        async with database.transaction(learner) as db:
            await practice.complete_step(
                db, await practice.get_session(db, session.id), practice.Step.BLIND
            )
        async with database.transaction(learner) as db:
            with pytest.raises(ProblemError) as error:
                await service.read_passage(db, database, learner, session.id)
            assert error.value.code == "transcript_failed"

        async def recover(*args, **kwargs):
            return result()

        monkeypatch.setattr(jobs, "get_gateway", lambda: SimpleNamespace(transcribe=recover))
        await jobs.transcribe_passage(JobDeps(database, None, 1), str(session.id), str(learner))
        async with database.transaction(learner) as db:
            await service.read_passage(db, database, learner, session.id)
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_second_learner_reuses_shared_media_only(
    api_role_url, migrated_url, learner, clip, boundary
):
    from listenup.modules.transcript import jobs, service
    from tests.integration.seed import create_learner

    other = create_learner(migrated_url)
    other_content = uuid.uuid4()
    with psycopg.connect(migrated_url) as conn:
        # Shared media is the YouTube data model; uploads remain scoped to their uploader.
        conn.execute(
            "UPDATE content.media_objects SET source='youtube', uploaded_by=NULL, "
            "fingerprint=%s WHERE id=%s",
            [f"youtube:{clip[0]}", clip[0]],
        )
        conn.execute(
            "INSERT INTO content.contents (id,user_id,media_object_id,title) VALUES "
            "(%s,%s,%s,'shared')",
            [other_content, other, clip[0]],
        )
    api, worker = Database(api_role_url), Database(conninfo_to_url(migrated_url))
    try:
        first = await start(api, learner, clip[1])
        second = await start(api, other, other_content, 150000, 330000)
        await jobs.transcribe_passage(JobDeps(worker, None, 1), str(first.id), str(learner))
        await jobs.transcribe_passage(JobDeps(worker, None, 1), str(second.id), str(other))
        assert boundary == [(5000, 195000), (195000, 335000)]
        async with api.transaction(other) as db:
            await practice.complete_step(
                db, await practice.get_session(db, second.id), practice.Step.BLIND
            )
        async with api.transaction(other) as db:
            data = await service.read_passage(db, worker, other, second.id)
        assert data.words == ["Hello.", "Again."]
        assert data.start_ms == [196125, 198000]
        assert data.sentence_starts == [0, 1]
        assert len(data.provenance) == 2
        async with api.transaction(learner) as db:
            with pytest.raises(ProblemError) as error:
                await service.read_passage(db, worker, learner, second.id)
            assert error.value.status == 404
    finally:
        await api.dispose()
        await worker.dispose()
        with psycopg.connect(migrated_url) as conn:
            conn.execute("DELETE FROM identity.users WHERE id=%s", [other])


@pytest.mark.anyio
async def test_ready_event_after_commit_and_rollback_suppresses_notification(
    migrated_url, learner, clip, boundary, monkeypatch
):
    import json

    from listenup.modules.transcript import jobs
    from listenup.platform.events import publish

    database = Database(conninfo_to_url(migrated_url))
    listener = psycopg.connect(migrated_url, autocommit=True)
    listener.execute("LISTEN user_events")
    try:
        session = await start(database, learner, clip[1])

        async def abort(db, user, event, resource):
            # The cached words must already be visible from a separate transaction.
            with psycopg.connect(migrated_url) as conn:
                assert (
                    conn.execute(
                        "SELECT count(*) FROM content.passage_transcripts WHERE "
                        "media_object_id=%s AND status='ready'",
                        [clip[0]],
                    ).fetchone()[0]
                    == 1
                )
            await publish(db, user, event, resource)
            raise RuntimeError("abort notification transaction")

        monkeypatch.setattr(jobs, "publish", abort)
        with pytest.raises(RuntimeError):
            await jobs.transcribe_passage(JobDeps(database, None, 1), str(session.id), str(learner))
        assert list(listener.notifies(timeout=0.05)) == []
        monkeypatch.setattr(jobs, "publish", publish)
        await jobs.transcribe_passage(JobDeps(database, None, 2), str(session.id), str(learner))
        notifications = list(listener.notifies(timeout=1, stop_after=1))
        assert len(notifications) == 1
        assert json.loads(notifications[0].payload) == {
            "u": str(learner),
            "t": "transcript.ready",
            "r": str(session.id),
        }
        assert len(boundary) == 1
    finally:
        listener.close()
        await database.dispose()


@pytest.mark.anyio
async def test_cancelled_worker_releases_lock_and_cleans_scratch(
    migrated_url, learner, clip, boundary, monkeypatch
):
    from listenup.modules.transcript import jobs

    database = Database(conninfo_to_url(migrated_url))
    entered = asyncio.Event()
    paths = []

    async def block(audio, **kwargs):
        paths.append(Path(audio))
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(jobs, "get_gateway", lambda: SimpleNamespace(transcribe=block))
    try:
        session = await start(database, learner, clip[1])
        task = asyncio.create_task(
            jobs.transcribe_passage(JobDeps(database, None, 1), str(session.id), str(learner))
        )
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not paths[0].parent.exists()

        async def recover(*args, **kwargs):
            return result()

        monkeypatch.setattr(jobs, "get_gateway", lambda: SimpleNamespace(transcribe=recover))
        await jobs.transcribe_passage(JobDeps(database, None, 2), str(session.id), str(learner))
        assert len(boundary) == 2
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_deleted_account_during_provider_call_discards_result(
    migrated_url, learner, clip, boundary, monkeypatch
):
    from listenup.modules.transcript import jobs

    database = Database(conninfo_to_url(migrated_url))

    async def deactivate(*args, **kwargs):
        with psycopg.connect(migrated_url) as conn:
            conn.execute(
                "UPDATE identity.users SET status='pending_deletion', "
                "deletion_scheduled_at=now() + interval '7 days' WHERE id=%s",
                [learner],
            )
        return result()

    monkeypatch.setattr(jobs, "get_gateway", lambda: SimpleNamespace(transcribe=deactivate))
    try:
        session = await start(database, learner, clip[1])
        await jobs.transcribe_passage(JobDeps(database, None, 1), str(session.id), str(learner))
        with psycopg.connect(migrated_url) as conn:
            assert (
                conn.execute(
                    "SELECT count(*) FROM content.passage_transcripts WHERE media_object_id=%s",
                    [clip[0]],
                ).fetchone()[0]
                == 0
            )
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_recovered_failure_does_not_mark_unprocessed_gap_failed(
    migrated_url, learner, clip, boundary
):
    from listenup.modules.transcript import jobs, repository, service

    database = Database(conninfo_to_url(migrated_url))
    try:
        async with database.transaction() as db:
            await repository.mark_failed(db, clip[0], [(5000, 195000)])
        first = await start(database, learner, clip[1])
        await jobs.transcribe_passage(JobDeps(database, None, 1), str(first.id), str(learner))
        larger = await start(database, learner, clip[1], 10000, 330000)
        async with database.transaction(learner) as db:
            await practice.complete_step(
                db, await practice.get_session(db, larger.id), practice.Step.BLIND
            )
        async with database.transaction(learner) as db:
            with pytest.raises(ProblemError) as error:
                await service.read_passage(db, database, learner, larger.id)
            assert error.value.code == "transcript_not_ready"
    finally:
        await database.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["missing_audio", "invalid_times", "gateway"])
async def test_provider_failures_never_publish_ready(
    migrated_url, learner, clip, boundary, monkeypatch, failure
):
    from listenup.ai.errors import AIUnavailable
    from listenup.ai.ports import Role
    from listenup.modules.transcript import jobs
    from listenup.platform.jobs import PermanentError, run_handler

    database = Database(conninfo_to_url(migrated_url))
    if failure == "missing_audio":

        async def missing(*args):
            return None

        monkeypatch.setattr(jobs, "get_storage", lambda: SimpleNamespace(download=missing))
    else:

        async def bad_result(*args, **kwargs):
            if failure == "gateway":
                raise AIUnavailable(Role.TRANSCRIPTION, "unavailable")
            bad = result().model_copy(
                update={
                    "segments": (
                        result()
                        .segments[0]
                        .model_copy(
                            update={"words": (result().words[0].model_copy(update={"end": 1000}),)}
                        ),
                    )
                }
            )
            return bad

        monkeypatch.setattr(jobs, "get_gateway", lambda: SimpleNamespace(transcribe=bad_result))
    listener = psycopg.connect(migrated_url, autocommit=True)
    listener.execute("LISTEN user_events")
    try:
        session = await start(database, learner, clip[1])
        with pytest.raises((PermanentError, AIUnavailable)):
            await run_handler(
                jobs.TRANSCRIBE,
                JobDeps(database, None, 5),
                session_id=str(session.id),
                user_id=str(learner),
            )
        notifications = list(listener.notifies(timeout=0.1))
        assert len(notifications) == 1
        assert "transcript.failed" in notifications[0].payload
        with psycopg.connect(migrated_url) as conn:
            assert conn.execute(
                "SELECT status, words FROM content.passage_transcripts WHERE media_object_id=%s",
                [clip[0]],
            ).fetchall() == [("failed", [])]
    finally:
        listener.close()
        await database.dispose()


@pytest.mark.anyio
async def test_deleted_session_and_wrong_job_owner_never_call_provider(
    migrated_url, learner, clip, boundary
):
    from listenup.modules.transcript import jobs
    from listenup.platform.jobs import PermanentError
    from tests.integration.seed import create_learner

    database = Database(conninfo_to_url(migrated_url))
    other = create_learner(migrated_url)
    try:
        session = await start(database, learner, clip[1])
        with pytest.raises(PermanentError):
            await jobs.transcribe_passage(JobDeps(database, None, 1), str(session.id), str(other))
        with psycopg.connect(migrated_url) as conn:
            conn.execute("DELETE FROM practice.sessions WHERE id=%s", [session.id])
        await jobs.transcribe_passage(JobDeps(database, None, 1), str(session.id), str(learner))
        assert boundary == []
    finally:
        await database.dispose()
        with psycopg.connect(migrated_url) as conn:
            conn.execute("DELETE FROM identity.users WHERE id=%s", [other])


@pytest.mark.anyio
async def test_retry_resumes_after_partial_success_within_one_job(
    migrated_url, learner, clip, boundary, monkeypatch
):
    from listenup.modules.transcript import jobs, repository
    from listenup.modules.transcript.packing import pack

    database = Database(conninfo_to_url(migrated_url))
    calls = 0

    async def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ConnectionError("second gap failed")
        return result()

    monkeypatch.setattr(jobs, "get_gateway", lambda: SimpleNamespace(transcribe=fail_second))
    try:
        async with database.transaction() as db:
            await repository.store(db, clip[0], (60000, 120000), pack(result(), (60000, 120000)))
        session = await start(database, learner, clip[1], 0, 180000)
        with pytest.raises(ConnectionError):
            await jobs.transcribe_passage(JobDeps(database, None, 1), str(session.id), str(learner))
        await jobs.transcribe_passage(JobDeps(database, None, 2), str(session.id), str(learner))
        assert boundary == [(0, 60000), (120000, 185000), (120000, 185000)]
        assert calls == 3
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_privileged_caller_still_cannot_read_another_learner(migrated_url, learner, clip):
    from listenup.modules.transcript import service

    database = Database(conninfo_to_url(migrated_url))
    try:
        session = await start(database, learner, clip[1])
        async with database.transaction() as db:
            with pytest.raises(ProblemError) as error:
                await service.read_passage(db, database, uuid.uuid4(), session.id)
            assert error.value.code == "session_not_found"
    finally:
        await database.dispose()
