"""Limited shared reference profiles (#76); AI boundaries are faked explicitly."""

import asyncio
import json
import uuid
from types import SimpleNamespace

import psycopg
import pytest
from sqlalchemy import select

from listenup.ai.ports import AlignedWord, Alignment, Provenance
from listenup.modules.practice import service as practice
from listenup.modules.transcript import repository
from listenup.modules.transcript.models import PassageTranscript
from listenup.modules.transcript.packing import pack
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps, Reschedule, run_handler
from tests.integration.conftest import conninfo_to_url
from tests.integration.seed import add_clip, create_learner
from tests.unit.test_transcript_packing import result


def test_profile_schema_is_worker_only(migrated_url, api_role_url):
    with psycopg.connect(migrated_url) as db:
        assert db.execute("SELECT to_regclass('content.reference_profiles')").fetchone()[0]
        assert db.execute("SELECT to_regclass('content.profile_subscriptions')").fetchone()[0]
    with psycopg.connect(api_role_url) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("SELECT * FROM content.reference_profiles")


@pytest.fixture
async def reference(migrated_url, learner):
    media, content, _ = add_clip(migrated_url, learner)
    with psycopg.connect(migrated_url) as db:
        db.execute("UPDATE content.media_objects SET duration_ms=600000 WHERE id=%s", [media])
    database = Database(conninfo_to_url(migrated_url))
    async with database.transaction(learner) as db:
        session = await practice.start_plan(db, learner, content, 0, 180000, practice.Entry.BLIND)
        await repository.store(db, media, (0, 185000), pack(result(), (0, 185000)))
        row = await db.scalar(
            select(PassageTranscript).where(PassageTranscript.media_object_id == media)
        )
        transcript = row.id
    yield SimpleNamespace(
        database=database, media=media, content=content, session=session.id, transcript=transcript
    )
    await database.dispose()


@pytest.fixture
def processing(monkeypatch):
    from listenup.ai.providers.parselmouth_acoustics import SETTINGS, VERSION, AcousticTrack
    from listenup.modules.transcript import profile_jobs

    calls = []

    async def align(audio, text):
        calls.append(text)
        return Alignment(
            provenance=Provenance(provider="fake", model="fake-alignment", version="1"),
            unit_kind="character",
            words=tuple(
                AlignedWord(index=i, text=t, start=i + 0.1, end=i + 0.5, confidence=0.9, units=())
                for i, t in enumerate(text.split())
            ),
        )

    class Storage:
        async def download(self, key, target):
            target.write_bytes(b"audio")
            return object()

    async def extract(source, target, span):
        target.write_bytes(b"PCM")

    def acoustics(audio, duration):
        return AcousticTrack(
            [100] * ((duration + 19) // 20),
            [7000] * ((duration + 19) // 20),
            {
                "provider": "parselmouth",
                "model": "praat-pitch-intensity",
                "version": VERSION,
                "praat_version": "test",
                "settings": dict(SETTINGS),
            },
        )

    monkeypatch.setattr(profile_jobs, "get_gateway", lambda: SimpleNamespace(align=align))
    monkeypatch.setattr(profile_jobs, "get_storage", lambda: Storage())
    monkeypatch.setattr(profile_jobs, "extract", extract)
    monkeypatch.setattr(profile_jobs, "extract_acoustics", acoustics)
    return calls


async def subscribe(reference, learner, session=None):
    from listenup.modules.transcript import profile_service

    async with reference.database.transaction(learner) as db:
        await profile_service.queue_profile(db, learner, session or reference.session)
    async with reference.database.transaction() as db:
        from listenup.modules.transcript.models import ProfileSubscription

        return await db.scalar(
            select(ProfileSubscription.fingerprint).where(
                ProfileSubscription.session_id == (session or reference.session)
            )
        )


async def process(reference, fingerprint):
    from listenup.modules.transcript.profile_jobs import profile_span

    await profile_span(JobDeps(reference.database, None, 1), str(reference.transcript), fingerprint)


@pytest.mark.anyio
async def test_shared_passage_reuses_profile_without_job(
    reference, learner, migrated_url, processing
):
    fingerprint = await subscribe(reference, learner)
    await process(reference, fingerprint)
    other = create_learner(migrated_url)
    try:
        shared_content = uuid.uuid4()
        with psycopg.connect(migrated_url) as db:
            db.execute(
                "UPDATE content.media_objects SET "
                "source='youtube',uploaded_by=NULL,fingerprint=%s WHERE id=%s",
                [f"youtube:{reference.media}", reference.media],
            )
            db.execute(
                "INSERT INTO content.contents(id,user_id,media_object_id,title) VALUES "
                "(%s,%s,%s,'shared')",
                [shared_content, other, reference.media],
            )
        async with reference.database.transaction(other) as db:
            session = await practice.start_plan(
                db, other, shared_content, 0, 180000, practice.Entry.BLIND
            )
        await subscribe(reference, other, session.id)
        with psycopg.connect(migrated_url) as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE "
                    "task_name='transcript.profile_span' AND args->>'transcript_id'=%s",
                    [str(reference.transcript)],
                ).fetchone()[0]
                == 1
            )
            assert db.execute(
                "SELECT status FROM content.profile_subscriptions WHERE session_id=%s", [session.id]
            ).fetchone() == ("ready",)
        assert processing == ["Hello. Again."]
    finally:
        with psycopg.connect(migrated_url) as db:
            db.execute("DELETE FROM identity.users WHERE id=%s", [other])


@pytest.mark.anyio
async def test_profile_provenance_round_trip_and_atomic_readiness(
    reference, learner, migrated_url, processing
):
    fingerprint = await subscribe(reference, learner)
    listener = psycopg.connect(migrated_url, autocommit=True)
    listener.execute("LISTEN user_events")
    try:
        await process(reference, fingerprint)
        notifications = list(listener.notifies(timeout=0.1))
        assert [json.loads(n.payload) for n in notifications] == [
            {"u": str(learner), "t": "profile.ready", "r": str(reference.session)}
        ]
        with psycopg.connect(migrated_url) as db:
            row = db.execute(
                "SELECT "
                "status,word_indices,word_start_ms,provenance,cardinality(pitch_cents) "
                "FROM content.reference_profiles WHERE passage_transcript_id=%s",
                [reference.transcript],
            ).fetchone()
            assert row[:3] == ("ready", [0, 1], [100, 1100])
            assert row[3]["alignment"] == {
                "provider": "fake",
                "model": "fake-alignment",
                "version": "1",
            }
            assert row[3]["acoustics"]["version"] == "0.4.7"
            assert row[4] == 9250
        await process(reference, fingerprint)
        assert list(listener.notifies(timeout=0.05)) == []
        assert len(processing) == 1
    finally:
        listener.close()


@pytest.mark.anyio
async def test_concurrent_profile_requests_compute_once(
    reference, learner, processing, monkeypatch
):
    from listenup.modules.transcript import profile_jobs

    fingerprint = await subscribe(reference, learner)
    original = profile_jobs.get_gateway().align
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(profile_jobs, "get_gateway", lambda: SimpleNamespace(align=blocked))
    task = asyncio.create_task(process(reference, fingerprint))
    await asyncio.wait_for(entered.wait(), 3)
    try:
        with pytest.raises(Reschedule):
            await asyncio.wait_for(process(reference, fingerprint), 2)
    finally:
        release.set()
        await task
    await process(reference, fingerprint)
    assert len(processing) == 1


@pytest.mark.anyio
async def test_failed_profile_never_announces_ready_and_retry_recovers(
    reference, learner, migrated_url, processing, monkeypatch
):
    from listenup.modules.transcript import profile_jobs

    fingerprint = await subscribe(reference, learner)
    original = profile_jobs.get_gateway

    async def unavailable(*args):
        raise ConnectionError("unavailable")

    monkeypatch.setattr(profile_jobs, "get_gateway", lambda: SimpleNamespace(align=unavailable))
    with pytest.raises(ConnectionError):
        await run_handler(
            "transcript.profile_span",
            JobDeps(reference.database, None, 5),
            transcript_id=str(reference.transcript),
            fingerprint=fingerprint,
        )
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status,word_indices FROM content.reference_profiles WHERE "
            "passage_transcript_id=%s",
            [reference.transcript],
        ).fetchone() == ("failed", [])
        assert db.execute(
            "SELECT status FROM content.profile_subscriptions WHERE session_id=%s",
            [reference.session],
        ).fetchone() == ("failed",)
    monkeypatch.setattr(profile_jobs, "get_gateway", original)
    await process(reference, fingerprint)
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status FROM content.profile_subscriptions WHERE session_id=%s",
            [reference.session],
        ).fetchone() == ("ready",)


@pytest.mark.anyio
async def test_profile_access_boundaries_and_playback_independence(
    reference, learner, api_role_url, processing
):
    from listenup.modules.content import service as content_service
    from listenup.modules.transcript import service
    from listenup.platform.errors import ProblemError

    fingerprint = await subscribe(reference, learner)
    api = Database(api_role_url)
    try:
        async with api.transaction(learner) as db:
            # Profiling neither changes playable content nor the active practice step.
            item = await content_service.get_content(db, learner, reference.content)
            assert item.status == "playable"
            await practice.require_step(db, reference.session, practice.Step.BLIND)
            with pytest.raises(ProblemError) as error:
                await service.reference_profile(db, reference.database, learner, reference.session)
            assert error.value.code == "step_locked"
        async with reference.database.transaction() as db:
            with pytest.raises(ProblemError) as error:
                await service.reference_profile(
                    db, reference.database, uuid.uuid4(), reference.session
                )
            assert error.value.code == "session_not_found"
        async with reference.database.transaction(learner) as db:
            for step in [practice.Step.BLIND, practice.Step.TRANSCRIPT, practice.Step.CARD]:
                await practice.complete_step(
                    db, await practice.get_session(db, reference.session), step
                )
        async with api.transaction(learner) as db:
            state = await service.reference_profile(
                db, reference.database, learner, reference.session
            )
            assert (
                state.status == "pending" and state.stage == "transcribed" and state.profiles == ()
            )
            # Playback/round owners can continue to use their existing step boundary.
            await practice.require_step(db, reference.session, practice.Step.SHADOW)
        await process(reference, fingerprint)
        async with api.transaction(learner) as db:
            state = await service.reference_profile(
                db, reference.database, learner, reference.session
            )
            assert state.status == "ready" and state.stage == "profiled"
            assert state.profiles[0].word_indices == [0, 1]
            assert state.profiles[0].passage_transcript_id == reference.transcript
    finally:
        await api.dispose()


@pytest.mark.anyio
async def test_profile_ready_requires_complete_coverage_and_retry_keeps_completed_spans(
    reference, learner, migrated_url, processing, monkeypatch
):
    from listenup.modules.transcript import profile_jobs

    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE content.passage_transcripts SET span='[0,90000)' WHERE id=%s",
            [reference.transcript],
        )
    async with reference.database.transaction() as db:
        await repository.store(
            db, reference.media, (90000, 185000), pack(result(), (90000, 185000))
        )
        second = await db.scalar(
            select(PassageTranscript.id).where(
                PassageTranscript.media_object_id == reference.media,
                PassageTranscript.id != reference.transcript,
            )
        )
    fingerprint = await subscribe(reference, learner)
    await process(reference, fingerprint)
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status FROM content.profile_subscriptions WHERE session_id=%s",
            [reference.session],
        ).fetchone() == ("pending",)
    original = profile_jobs.get_gateway

    async def fail(*args):
        raise ConnectionError("retry")

    monkeypatch.setattr(profile_jobs, "get_gateway", lambda: SimpleNamespace(align=fail))
    with pytest.raises(ConnectionError):
        await profile_jobs.profile_span(
            JobDeps(reference.database, None, 1), str(second), fingerprint
        )
    await process(reference, fingerprint)
    assert len(processing) == 1
    monkeypatch.setattr(profile_jobs, "get_gateway", original)
    await profile_jobs.profile_span(JobDeps(reference.database, None, 2), str(second), fingerprint)
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status FROM content.profile_subscriptions WHERE session_id=%s",
            [reference.session],
        ).fetchone() == ("ready",)
    assert len(processing) == 2


@pytest.mark.anyio
async def test_profile_cancellation_cleans_scratch_and_releases_lock(
    reference, learner, processing, monkeypatch
):
    from listenup.modules.transcript import profile_jobs

    fingerprint = await subscribe(reference, learner)
    entered = asyncio.Event()
    paths = []
    original = profile_jobs.get_gateway

    async def block(audio, text):
        paths.append(audio)
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(profile_jobs, "get_gateway", lambda: SimpleNamespace(align=block))
    task = asyncio.create_task(process(reference, fingerprint))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not paths[0].parent.exists()
    monkeypatch.setattr(profile_jobs, "get_gateway", original)
    await process(reference, fingerprint)
    assert len(processing) == 1


@pytest.mark.anyio
async def test_profile_subscriptions_are_learner_scoped(
    reference, learner, api_role_url, processing
):
    await subscribe(reference, learner)
    for caller, expected in [(learner, 1), (uuid.uuid4(), 0)]:
        api = Database(api_role_url)
        try:
            async with api.transaction(caller) as db:
                from sqlalchemy import text

                assert (
                    len(
                        (
                            await db.execute(text("SELECT * FROM content.profile_subscriptions"))
                        ).all()
                    )
                    == expected
                )
        finally:
            await api.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path,value",
    [
        ("alignment,provider", 123),
        ("alignment,model", None),
        ("alignment,version", ""),
        ("acoustics,version", 123),
        ("acoustics,praat_version", None),
        ("acoustics,settings", None),
    ],
)
async def test_ready_profile_rejects_invalid_provenance(
    reference, learner, migrated_url, processing, path, value
):
    from psycopg.types.json import Jsonb

    fingerprint = await subscribe(reference, learner)
    await process(reference, fingerprint)
    with psycopg.connect(migrated_url) as db, pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "UPDATE content.reference_profiles SET "
            "provenance=jsonb_set(provenance,%s,%s) WHERE passage_transcript_id=%s",
            ["{" + path + "}", Jsonb(value), reference.transcript],
        )


@pytest.mark.anyio
async def test_ready_event_rolls_back_with_profile(
    reference, learner, migrated_url, processing, monkeypatch
):
    from listenup.modules.transcript import profile_repository

    fingerprint = await subscribe(reference, learner)
    original = profile_repository.publish

    async def abort(*args):
        await original(*args)
        raise RuntimeError("rollback")

    monkeypatch.setattr(profile_repository, "publish", abort)
    listener = psycopg.connect(migrated_url, autocommit=True)
    listener.execute("LISTEN user_events")
    try:
        with pytest.raises(RuntimeError):
            await process(reference, fingerprint)
        assert list(listener.notifies(timeout=0.05)) == []
        with psycopg.connect(migrated_url) as db:
            assert db.execute(
                "SELECT status,word_indices FROM content.reference_profiles WHERE "
                "passage_transcript_id=%s",
                [reference.transcript],
            ).fetchone() == ("pending", [])
        monkeypatch.setattr(profile_repository, "publish", original)
        await process(reference, fingerprint)
        assert len(list(listener.notifies(timeout=0.1))) == 1
    finally:
        listener.close()


@pytest.mark.anyio
async def test_changed_recipe_creates_new_cache_identity(
    reference, learner, migrated_url, processing, monkeypatch
):
    from listenup.modules.transcript import profile_service

    first = await subscribe(reference, learner)
    await process(reference, first)
    original = profile_service.recipe()
    monkeypatch.setattr(profile_service, "recipe", lambda: {**original, "format_version": 2})
    second = await subscribe(reference, learner)
    assert first != second
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status FROM content.reference_profiles WHERE "
            "passage_transcript_id=%s ORDER BY status",
            [reference.transcript],
        ).fetchall() == [("pending",), ("ready",)]
        assert db.execute(
            "SELECT status FROM content.profile_subscriptions WHERE session_id=%s",
            [reference.session],
        ).fetchone() == ("pending",)


@pytest.mark.anyio
async def test_concurrent_subscribers_share_one_queued_job(
    reference, learner, migrated_url, processing
):
    async with reference.database.transaction(learner) as db:
        second = await practice.start_plan(
            db, learner, reference.content, 0, 180000, practice.Entry.BLIND
        )
    first_key, second_key = await asyncio.gather(
        subscribe(reference, learner), subscribe(reference, learner, second.id)
    )
    assert first_key == second_key
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE "
            "task_name='transcript.profile_span' AND args->>'transcript_id'=%s",
            [str(reference.transcript)],
        ).fetchone() == (1,)
    await process(reference, first_key)
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status FROM content.profile_subscriptions WHERE media_object_id=%s",
            [reference.media],
        ).fetchall() == [("ready",), ("ready",)]


@pytest.mark.anyio
async def test_deleted_media_during_processing_never_resurrects(
    reference, learner, migrated_url, processing, monkeypatch
):
    from listenup.modules.transcript import profile_jobs

    fingerprint = await subscribe(reference, learner)
    original = profile_jobs.get_gateway().align

    async def deleted(*args):
        with psycopg.connect(migrated_url) as db:
            db.execute("DELETE FROM content.contents WHERE media_object_id=%s", [reference.media])
            db.execute("DELETE FROM content.media_objects WHERE id=%s", [reference.media])
        return await original(*args)

    monkeypatch.setattr(profile_jobs, "get_gateway", lambda: SimpleNamespace(align=deleted))
    await process(reference, fingerprint)
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT count(*) FROM content.reference_profiles WHERE passage_transcript_id=%s",
            [reference.transcript],
        ).fetchone() == (0,)
        assert db.execute(
            "SELECT count(*) FROM content.profile_subscriptions WHERE session_id=%s",
            [reference.session],
        ).fetchone() == (0,)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure",
    [
        "missing_audio",
        "alignment_bounds",
        "alignment_provenance",
        "acoustic_provenance",
        "frame_count",
        "stale_recipe",
    ],
)
async def test_permanent_processing_failures_publish_only_failed(
    reference, learner, migrated_url, processing, monkeypatch, failure
):
    from listenup.modules.transcript import profile_jobs, profile_service
    from listenup.platform.jobs import PermanentError

    fingerprint = await subscribe(reference, learner)
    if failure == "missing_audio":

        async def missing(*args):
            return None

        monkeypatch.setattr(profile_jobs, "get_storage", lambda: SimpleNamespace(download=missing))
    elif failure.startswith("alignment"):
        original = profile_jobs.get_gateway().align

        async def invalid(*args):
            value = await original(*args)
            if failure == "alignment_bounds":
                return value.model_copy(
                    update={"words": (value.words[0].model_copy(update={"end": 999}),)}
                )
            return value.model_copy(
                update={"provenance": Provenance(provider="wrong", model="wrong", version="wrong")}
            )

        monkeypatch.setattr(profile_jobs, "get_gateway", lambda: SimpleNamespace(align=invalid))
    elif failure.startswith("acoustic") or failure == "frame_count":
        from dataclasses import replace

        original = profile_jobs.extract_acoustics

        def invalid(*args):
            value = original(*args)
            if failure == "frame_count":
                return replace(value, pitch_cents=[])
            return replace(value, provenance={**value.provenance, "version": "wrong"})

        monkeypatch.setattr(profile_jobs, "extract_acoustics", invalid)
    else:
        original = profile_service.recipe()
        monkeypatch.setattr(profile_service, "recipe", lambda: {**original, "format_version": 2})
    listener = psycopg.connect(migrated_url, autocommit=True)
    listener.execute("LISTEN user_events")
    try:
        with pytest.raises(PermanentError):
            await process(reference, fingerprint)
        events = [json.loads(event.payload) for event in listener.notifies(timeout=0.05)]
        assert events == [{"u": str(learner), "t": "profile.failed", "r": str(reference.session)}]
        with psycopg.connect(migrated_url) as db:
            assert db.execute(
                "SELECT status,word_indices FROM content.reference_profiles "
                "WHERE passage_transcript_id=%s",
                [reference.transcript],
            ).fetchone() == ("failed", [])
    finally:
        listener.close()


@pytest.mark.anyio
async def test_profile_queue_rejects_foreign_session_and_incomplete_transcript(
    reference, learner, processing, migrated_url
):
    from listenup.modules.transcript import profile_service
    from listenup.platform.errors import ProblemError

    async with reference.database.transaction() as db:
        with pytest.raises(ProblemError) as error:
            await profile_service.queue_profile(db, uuid.uuid4(), reference.session)
        assert error.value.code == "session_not_found"
    with psycopg.connect(migrated_url) as db:
        db.execute("DELETE FROM content.passage_transcripts WHERE id=%s", [reference.transcript])
    async with reference.database.transaction(learner) as db:
        with pytest.raises(ProblemError) as error:
            await profile_service.queue_profile(db, learner, reference.session)
        assert error.value.code == "transcript_not_ready"


@pytest.mark.anyio
async def test_deleted_queued_profile_is_a_noop(reference, learner, processing, migrated_url):
    fingerprint = await subscribe(reference, learner)
    with psycopg.connect(migrated_url) as db:
        db.execute("DELETE FROM content.passage_transcripts WHERE id=%s", [reference.transcript])
    await process(reference, fingerprint)
    from listenup.modules.transcript import profile_jobs

    await profile_jobs._give_up(
        JobDeps(reference.database, None, 5), str(reference.transcript), fingerprint
    )
    assert processing == []


@pytest.mark.anyio
async def test_failed_profile_still_allows_shadow_step_and_reports_failed(
    reference, learner, processing
):
    from listenup.modules.transcript import profile_jobs, service

    await subscribe(reference, learner)
    async with reference.database.transaction(learner) as db:
        for step in [practice.Step.BLIND, practice.Step.TRANSCRIPT, practice.Step.CARD]:
            await practice.complete_step(
                db, await practice.get_session(db, reference.session), step
            )
    async with reference.database.transaction(learner) as db:
        state = await service.reference_profile(db, reference.database, learner, reference.session)
        assert state.status == "pending"
    fingerprint = await subscribe(reference, learner)
    await profile_jobs._give_up(
        JobDeps(reference.database, None, 5), str(reference.transcript), fingerprint
    )
    async with reference.database.transaction(learner) as db:
        state = await service.reference_profile(db, reference.database, learner, reference.session)
        assert state.status == "failed" and state.stage == "transcribed" and state.profiles == ()
        await practice.require_step(db, reference.session, practice.Step.SHADOW)


@pytest.mark.anyio
async def test_profile_subscription_is_in_learner_export(reference, learner, processing):
    from listenup.modules.transcript import service

    await subscribe(reference, learner)
    async with reference.database.transaction(learner) as db:
        data = await service.export_data(db, learner)
    subscriptions = next(
        table for table in data.tables if table.name == "content.profile_subscriptions"
    )
    assert len(subscriptions.rows) == 1
    assert subscriptions.rows[0]["session_id"] == reference.session
    assert subscriptions.rows[0]["user_id"] == learner
