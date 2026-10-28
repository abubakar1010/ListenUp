"""DR-2 deletes only the selected learner's content and tracks every private object."""

import asyncio
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps, run_handler
from listenup.platform.storage import use_storage
from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import ClientFactory, FakeStorage, client_factory, learner_id
from tests.integration.seed import seed_learner_data


@pytest.fixture
def storage() -> Iterator[FakeStorage]:
    fake = FakeStorage()
    use_storage(fake)
    yield fake
    use_storage(None)


@pytest.fixture
def make_client(api_role_url: str, storage: FakeStorage) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, storage)


def delete(client: TestClient, content: object, confirm: bool = True):
    return client.request("DELETE", f"/api/v1/contents/{content}", json={"confirm": confirm})


def run_delete(url: str, request: str):
    async def run():
        # Like the worker, register the library job module.
        from listenup.modules.library import jobs  # noqa: F401

        database = Database(conninfo_to_url(url))
        try:
            return await run_handler(
                "library.delete_content", JobDeps(database, None, 1), request_id=request
            )
        finally:
            await database.dispose()

    return asyncio.run(run())


def add_caches(url, media, learner, session=None):
    from psycopg.types.json import Jsonb

    transcript, points = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(url) as db:
        db.execute(
            "INSERT INTO content.passage_transcripts(id,media_object_id,span,origin) "
            "VALUES (%s,%s,'[0,120000)','generated')",
            [transcript, media],
        )
        db.execute(
            "INSERT INTO "
            "content.transcript_corrections(user_id,passage_transcript_id,"
            "word_index,corrected_text) "
            "VALUES (%s,%s,0,'private correction')",
            [learner, transcript],
        )
        db.execute(
            "INSERT INTO content.reference_profiles(passage_transcript_id,fingerprint) "
            "VALUES (%s,%s)",
            [transcript, "a" * 64],
        )
        db.execute(
            "INSERT INTO "
            "grading.key_points(id,media_object_id,span,prompt_version,points,provider_info) "
            "VALUES (%s,%s,'[0,120000)','v1',%s,%s)",
            [
                points,
                media,
                Jsonb(
                    [
                        {"id": "kp1", "text": "The main point.", "kind": "main"},
                        {"id": "kp2", "text": "Supporting detail.", "kind": "supporting"},
                        {"id": "kp3", "text": "Another detail.", "kind": "supporting"},
                    ]
                ),
                Jsonb({"provider": "fake", "model": "fake", "version": "v1"}),
            ],
        )
        db.execute(
            "INSERT INTO grading.key_point_delays(media_object_id,span,prompt_version) "
            "VALUES (%s,'[0,120000)','v1')",
            [media],
        )
        if session:
            db.execute(
                "INSERT INTO "
                "content.profile_subscriptions(session_id,user_id,"
                "media_object_id,span,fingerprint) "
                "VALUES (%s,%s,%s,'[0,120000)',%s)",
                [session, learner, media, "a" * 64],
            )
    return transcript, points


def test_delete_content_is_confirmed_owned_and_transactionally_queued(make_client, migrated_url):
    a, b = make_client(), make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    assert delete(b, world.content_id).status_code == 404
    assert delete(a, world.content_id, False).status_code == 422
    response = delete(a, world.content_id)
    assert response.status_code == 202, response.text
    request = response.json()["request_id"]
    assert delete(a, world.content_id).json()["request_id"] == request
    assert a.get(f"/api/v1/contents/{world.content_id}").status_code == 404
    assert a.get(f"/api/v1/sessions/{world.sessions['shadow']}").status_code == 404
    assert a.get("/api/v1/library/contents").json()["items"] == []
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT scope,target_id,status FROM ops.deletion_requests WHERE id=%s", [request]
        ).fetchone() == ("content", world.content_id, "pending")
        assert db.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE task_name="
            "'library.delete_content' AND args->>'request_id'=%s",
            [request],
        ).fetchone() == (1,)


def test_delete_upload_removes_all_derived_rows_and_objects(make_client, migrated_url, storage):
    a, b = make_client(), make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    other = seed_learner_data(migrated_url, uuid.UUID(learner_id(b)))
    transcript, points = add_caches(
        migrated_url, world.media_id, world.user_id, world.sessions["shadow"]
    )
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "INSERT INTO grading.gist_grades(attempt_id,user_id) VALUES (%s,%s)",
            [world.blind_attempt_id, world.user_id],
        )
        db.execute(
            "UPDATE practice.cards SET "
            "audio_status='ready',snippet_key=%s,snippet_span='[0,3000)' WHERE id=%s",
            [f"users/{world.user_id}/cards/{world.card_id}/snippet.m4a", world.card_id],
        )
        db.execute(
            "INSERT INTO practice.card_reviews(id,card_id,user_id,result) VALUES "
            "(%s,%s,%s,'heard')",
            [uuid.uuid4(), world.card_id, world.user_id],
        )

    keys = [
        f"users/{world.user_id}/media/{world.media_id}/playback.mp4",
        f"users/{world.user_id}/media/{world.media_id}/peaks.json",
        f"users/{world.user_id}/uploads/{world.confirmed_upload_id}.mp3",
        f"users/{world.user_id}/cards/{world.card_id}/snippet.m4a",
        f"users/{world.user_id}/shadow/{world.sessions['shadow']}/round-1-{world.shadow_round_id}.webm",
    ]
    keep = [
        world.pending_upload_key,
        other.pending_upload_key,
        f"users/{other.user_id}/media/{other.media_id}/playback.mp4",
    ]
    for key in keys + keep:
        storage.arrive(key, 10)
    with psycopg.connect(migrated_url) as db:
        tables = [
            r[0]
            for r in db.execute(
                "SELECT table_schema||'.'||table_name FROM "
                "information_schema.columns WHERE column_name='user_id' AND table_schema IN "
                "('practice','grading','content')"
            )
        ]
        before = {
            table: db.execute(
                f"SELECT count(*) FROM {table} WHERE user_id=%s", [world.user_id]
            ).fetchone()[0]
            for table in tables
        }
        other_before = {
            table: db.execute(
                f"SELECT count(*) FROM {table} WHERE user_id=%s", [other.user_id]
            ).fetchone()[0]
            for table in tables
        }
        assert all(
            before[t] > 0
            for t in (
                "practice.sessions",
                "practice.session_steps",
                "practice.attempts",
                "practice.blind_attempts",
                "practice.dictation_attempts",
                "practice.marks",
                "practice.cards",
                "practice.card_reviews",
                "practice.shadow_segments",
                "practice.shadow_rounds",
                "content.transcript_corrections",
                "content.profile_subscriptions",
                "grading.gist_grades",
            )
        )
        analytics = db.execute(
            "SELECT count(*) FROM ops.analytics_events WHERE user_id=%s", [world.user_id]
        ).fetchone()[0]
    response = delete(a, world.content_id)
    assert response.status_code == 202, response.text
    request = response.json()["request_id"]
    run_delete(migrated_url, request)
    assert not set(keys) & storage.objects.keys()
    assert set(keep) <= storage.objects.keys()
    with psycopg.connect(migrated_url) as db:
        for table in tables:
            remaining = db.execute(
                f"SELECT count(*) FROM {table} WHERE user_id=%s", [world.user_id]
            ).fetchone()[0]
            if table == "content.uploads":
                assert remaining == 1  # unrelated, unconfirmed upload
            else:
                assert remaining == 0, (table, before[table], remaining)
        assert db.execute(
            "SELECT count(*) FROM ops.analytics_events WHERE user_id=%s", [world.user_id]
        ).fetchone() == (analytics,)
        assert (
            db.execute(
                "SELECT id FROM content.media_objects WHERE id=%s", [world.media_id]
            ).fetchone()
            is None
        )
        assert db.execute(
            "SELECT id FROM content.contents WHERE id=%s", [other.content_id]
        ).fetchone() == (other.content_id,)
        assert db.execute(
            "SELECT status FROM ops.deletion_requests WHERE id=%s", [request]
        ).fetchone() == ("completed",)
        for table in tables:
            assert db.execute(
                f"SELECT count(*) FROM {table} WHERE user_id=%s", [other.user_id]
            ).fetchone() == (other_before[table],), table
        for table in ("content.passage_transcripts", "content.reference_profiles"):
            column = "id" if table.endswith("passage_transcripts") else "passage_transcript_id"
            assert db.execute(
                f"SELECT count(*) FROM {table} WHERE {column}=%s", [transcript]
            ).fetchone() == (0,)
        assert db.execute(
            "SELECT count(*) FROM grading.key_points WHERE id=%s", [points]
        ).fetchone() == (0,)
        assert db.execute(
            "SELECT count(*) FROM grading.key_point_delays WHERE media_object_id=%s",
            [world.media_id],
        ).fetchone() == (0,)
    run_delete(migrated_url, request)  # repeat is harmless


def test_retry_after_partial_storage_failure_keeps_rows_and_manifest(
    make_client, migrated_url, storage, monkeypatch
):
    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    key = f"users/{world.user_id}/media/{world.media_id}/playback.mp4"
    storage.arrive(key, 10)
    response = delete(a, world.content_id)
    assert response.status_code == 202, response.text
    request = response.json()["request_id"]
    original = storage.delete_prefix

    async def partial(prefix):
        await original(prefix)
        raise OSError("storage unavailable after deletion")

    monkeypatch.setattr(storage, "delete_prefix", partial)
    with pytest.raises(OSError):
        run_delete(migrated_url, request)
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT id FROM content.contents WHERE id=%s", [world.content_id]
        ).fetchone() == (world.content_id,)
        assert db.execute(
            "SELECT storage_prefixes FROM ops.deletion_requests WHERE id=%s", [request]
        ).fetchone()[0]
    monkeypatch.setattr(storage, "delete_prefix", original)
    run_delete(migrated_url, request)
    assert key not in storage.objects


@pytest.mark.parametrize("last", [False, True])
def test_shared_transcript_and_orphan_eligibility(make_client, migrated_url, last, storage):
    from tests.integration.test_account_deletion import add_shared_youtube

    a, b = make_client(), make_client()
    ua, ub = uuid.UUID(learner_id(a)), uuid.UUID(learner_id(b))
    media = add_shared_youtube(migrated_url, ua, ub)
    transcript, _points = add_caches(migrated_url, media, ua)
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE content.passage_transcripts SET words=ARRAY['shared','original','words'], "
            "start_ms=ARRAY[0,1000,2000],end_ms=ARRAY[1000,2000,3000], "
            "confidence=ARRAY[900,900,900],sentence_starts=ARRAY[0] WHERE id=%s",
            [transcript],
        )

    with psycopg.connect(migrated_url) as db:
        content = db.execute(
            "SELECT id FROM content.contents WHERE user_id=%s AND media_object_id=%s", [ua, media]
        ).fetchone()[0]
        b_content = db.execute(
            "SELECT id FROM content.contents WHERE user_id=%s AND media_object_id=%s", [ub, media]
        ).fetchone()[0]
        db.execute(
            "INSERT INTO "
            "content.transcript_corrections(user_id,passage_transcript_id,"
            "word_index,corrected_text) "
            "VALUES (%s,%s,0,'B correction')",
            [ub, transcript],
        )
    from tests.integration.seed import add_sessions

    sessions_a = asyncio.run(add_sessions(migrated_url, ua, content))
    sessions_b = asyncio.run(add_sessions(migrated_url, ub, b_content))
    from tests.integration.seed import add_mark, add_shadow_recording

    mark_b = add_mark(migrated_url, ub, sessions_b["transcript"])
    round_a = add_shadow_recording(migrated_url, ua, sessions_a["shadow"])
    own_recording = f"users/{ua}/shadow/{sessions_a['shadow']}/round-1-{round_a}.webm"
    shared_key = f"users/{ub}/media/{media}/playback.mp4"
    storage.arrive(own_recording, 10)
    storage.arrive(shared_key, 10)
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE content.media_objects SET playback_key=%s WHERE id=%s", [shared_key, media]
        )
    response = delete(a, content)
    assert response.status_code == 202, response.text
    run_delete(migrated_url, response.json()["request_id"])
    assert own_recording not in storage.objects
    assert shared_key in storage.objects
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT count(*) FROM practice.sessions WHERE content_id=%s", [content]
        ).fetchone() == (0,)
        assert db.execute("SELECT id FROM practice.marks WHERE id=%s", [mark_b]).fetchone() == (
            mark_b,
        )
        assert db.execute(
            "SELECT id FROM grading.key_points WHERE id=%s", [_points]
        ).fetchone() == (_points,)
        assert db.execute(
            "SELECT count(*) FROM content.reference_profiles WHERE passage_transcript_id=%s",
            [transcript],
        ).fetchone() == (1,)
        assert db.execute(
            "SELECT user_id,corrected_text FROM content.transcript_corrections WHERE "
            "passage_transcript_id=%s",
            [transcript],
        ).fetchall() == [(ub, "B correction")]
        assert {
            row[0]
            for row in db.execute(
                "SELECT id FROM practice.sessions WHERE content_id=%s", [b_content]
            )
        } == set(sessions_b.values())
    if last:
        with psycopg.connect(migrated_url) as db:
            other = db.execute(
                "SELECT id FROM content.contents WHERE user_id=%s AND media_object_id=%s",
                [ub, media],
            ).fetchone()[0]
        response = delete(b, other)
        assert response.status_code == 202, response.text
        run_delete(migrated_url, response.json()["request_id"])
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT words FROM content.passage_transcripts WHERE id=%s", [transcript]
        ).fetchone() == (["shared", "original", "words"],)
        assert shared_key in storage.objects
        assert db.execute(
            "SELECT ref_count FROM content.media_objects WHERE id=%s", [media]
        ).fetchone() == (0 if last else 1,)
        assert db.execute(
            "SELECT id FROM content.passage_transcripts WHERE id=%s", [transcript]
        ).fetchone() == (transcript,)


@pytest.mark.anyio
async def test_conversion_writer_blocks_cleanup_and_retains_uncertain_upload(
    make_client, migrated_url, storage
):
    from listenup.modules.content import service as content
    from listenup.modules.content import writes
    from listenup.platform.jobs import Reschedule
    from listenup.platform.storage import StorageWriteUncertain

    a = make_client()
    world = await asyncio.to_thread(seed_learner_data, migrated_url, uuid.UUID(learner_id(a)))
    database = Database(conninfo_to_url(migrated_url))
    try:
        with pytest.raises(StorageWriteUncertain):
            async with writes.registered_write(
                database, world.user_id, world.media_id, world.content_id
            ):
                async with database.transaction() as db:
                    with pytest.raises(Reschedule):
                        await content.require_no_media_writes(db, world.user_id, world.media_id)
                raise StorageWriteUncertain("unknown remote write")
        async with database.transaction() as db:
            with pytest.raises(Reschedule):
                await content.require_no_media_writes(db, world.user_id, world.media_id)
    finally:
        # Operator reconciliation is explicit; never age out a writer registration.
        with psycopg.connect(migrated_url) as db:
            db.execute(
                "DELETE FROM content.media_writes WHERE media_object_id=%s", [world.media_id]
            )
        await database.dispose()


@pytest.mark.anyio
async def test_conversion_cannot_register_after_content_deletion(make_client, migrated_url):
    from listenup.modules.content import writes
    from listenup.platform.jobs import PermanentError

    a = make_client()
    world = await asyncio.to_thread(seed_learner_data, migrated_url, uuid.UUID(learner_id(a)))
    response = delete(a, world.content_id)
    assert response.status_code == 202, response.text
    database = Database(conninfo_to_url(migrated_url))
    try:
        with pytest.raises(PermanentError):
            async with writes.registered_write(
                database, world.user_id, world.media_id, world.content_id
            ):
                pytest.fail("A deleted clip must not write storage")
    finally:
        await database.dispose()


def test_completed_manifest_recovers_late_browser_upload(make_client, migrated_url, storage):
    from listenup.modules.library import jobs

    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    response = delete(a, world.content_id)
    assert response.status_code == 202, response.text
    request = response.json()["request_id"]
    run_delete(migrated_url, request)
    late = f"users/{world.user_id}/shadow/{world.sessions['shadow']}/late.webm"
    storage.arrive(late, 10)
    run_delete(migrated_url, request)
    assert late not in storage.objects
    # The scheduler remains registered even when all original rows disappeared.
    assert jobs.reconcile_content_deletions is not None


def test_request_manifest_survives_rows_removed_before_worker(make_client, migrated_url, storage):
    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    original = f"users/{world.user_id}/uploads/{world.confirmed_upload_id}.mp3"
    storage.arrive(original, 10)
    response = delete(a, world.content_id)
    assert response.status_code == 202, response.text
    # A conversion's duplicate-merge may have already read the upload. Model its
    # row deletion followed by a crash before its original-object deletion.
    with psycopg.connect(migrated_url) as db:
        db.execute("DELETE FROM content.contents WHERE id=%s", [world.content_id])
        db.execute("DELETE FROM content.media_objects WHERE id=%s", [world.media_id])
    run_delete(migrated_url, response.json()["request_id"])
    assert original not in storage.objects


def test_delete_request_does_not_invert_session_content_lock_order(make_client, migrated_url):
    from concurrent.futures import ThreadPoolExecutor

    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    with ThreadPoolExecutor(max_workers=1) as pool, psycopg.connect(migrated_url) as db:
        db.execute(
            "SELECT id FROM practice.sessions WHERE id=%s FOR UPDATE",
            [world.sessions["shadow"]],
        )
        future = pool.submit(delete, a, world.content_id)
        try:
            response = future.result(timeout=3)
            assert response.status_code == 202, response.text
        finally:
            db.rollback()


def test_missing_deletion_request_is_harmless(migrated_url):
    assert run_delete(migrated_url, str(uuid.uuid4())) is None


def test_exhausted_deletion_is_reported_and_recovered(
    make_client, migrated_url, storage, monkeypatch
):
    from listenup.modules.library import jobs
    from listenup.platform.jobs import LANES, Lane

    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    response = delete(a, world.content_id)
    assert response.status_code == 202, response.text
    request = response.json()["request_id"]
    original = storage.delete_prefix

    async def broken(prefix):
        raise OSError("storage offline")

    monkeypatch.setattr(storage, "delete_prefix", broken)

    async def exhaust():
        database = Database(conninfo_to_url(migrated_url))
        try:
            with pytest.raises(OSError):
                await run_handler(
                    jobs.DELETE_CONTENT,
                    JobDeps(database, None, LANES[Lane.BACKGROUND].max_attempts),
                    request_id=request,
                )
        finally:
            await database.dispose()

    asyncio.run(exhaust())
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status FROM ops.deletion_requests WHERE id=%s", [request]
        ).fetchone() == ("failed",)
    monkeypatch.setattr(storage, "delete_prefix", original)
    run_delete(migrated_url, request)
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status FROM ops.deletion_requests WHERE id=%s", [request]
        ).fetchone() == ("completed",)


@pytest.mark.anyio
async def test_disabled_account_cannot_start_conversion_write(make_client, migrated_url):
    from listenup.modules.content import writes
    from listenup.platform.jobs import PermanentError

    a = make_client()
    world = await asyncio.to_thread(seed_learner_data, migrated_url, uuid.UUID(learner_id(a)))
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE identity.users SET "
            "status='pending_deletion',deletion_scheduled_at=now()+interval '7 days' WHERE id=%s",
            [world.user_id],
        )
    database = Database(conninfo_to_url(migrated_url))
    try:
        with pytest.raises(PermanentError):
            async with writes.registered_write(
                database, world.user_id, world.media_id, world.content_id
            ):
                pytest.fail("A disabled account cannot create storage objects")
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_peaks_upload_failure_retains_its_writer(make_client, migrated_url):
    from listenup.modules.content import service as content
    from listenup.modules.content import writes
    from listenup.platform.jobs import Reschedule
    from listenup.platform.storage import StorageWriteUncertain

    a = make_client()
    world = await asyncio.to_thread(seed_learner_data, migrated_url, uuid.UUID(learner_id(a)))
    database = Database(conninfo_to_url(migrated_url))

    async def failed_put():
        raise OSError("connection lost after request body")

    try:
        with pytest.raises(StorageWriteUncertain):
            async with writes.registered_write(
                database, world.user_id, world.media_id, world.content_id
            ):
                await writes.store(failed_put())
        async with database.transaction() as db:
            with pytest.raises(Reschedule):
                await content.require_no_media_writes(db, world.user_id, world.media_id)
    finally:
        with psycopg.connect(migrated_url) as db:
            db.execute(
                "DELETE FROM content.media_writes WHERE media_object_id=%s", [world.media_id]
            )
        await database.dispose()


def test_scheduler_recovers_failed_cleanup_without_duplicate_jobs(make_client, migrated_url):
    from listenup.modules.library import jobs

    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    response = delete(a, world.content_id)
    assert response.status_code == 202, response.text
    request = response.json()["request_id"]
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE procrastinate.procrastinate_jobs SET status='failed' "
            "WHERE task_name=%s AND args->>'request_id'=%s",
            [jobs.DELETE_CONTENT, request],
        )
        db.execute(
            "UPDATE ops.deletion_requests SET status='failed',failed_at=now(),due_at=now() "
            "WHERE id=%s",
            [request],
        )

    async def sweep():
        database = Database(conninfo_to_url(migrated_url))
        try:
            await jobs.reconcile_content_deletions(JobDeps(database, None, 1))
            await jobs.reconcile_content_deletions(JobDeps(database, None, 1))
        finally:
            await database.dispose()

    asyncio.run(sweep())
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs "
            "WHERE task_name=%s AND args->>'request_id'=%s AND status='todo'",
            [jobs.DELETE_CONTENT, request],
        ).fetchone() == (1,)
    run_delete(migrated_url, request)


@pytest.mark.parametrize("remove_card", [False, True])
def test_card_writer_defers_content_cleanup_before_any_storage_delete(
    make_client, migrated_url, storage, remove_card
):
    from listenup.platform.jobs import Reschedule

    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    writer = uuid.uuid4()
    key = f"users/{world.user_id}/media/{world.media_id}/playback.mp4"
    snippet = f"users/{world.user_id}/cards/{world.card_id}/snippet.m4a"
    storage.arrive(key, 10)
    storage.arrive(snippet, 10)
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "INSERT INTO practice.card_snippet_writes(id,card_id,user_id,owner) "
            "VALUES (%s,%s,%s,%s)",
            [writer, world.card_id, world.user_id, "test:1"],
        )
    response = delete(a, world.content_id)
    assert response.status_code == 202, response.text
    if remove_card:
        with psycopg.connect(migrated_url) as db:
            db.execute("DELETE FROM practice.cards WHERE id=%s", [world.card_id])
    try:
        with pytest.raises(Reschedule):
            run_delete(migrated_url, response.json()["request_id"])
        assert key in storage.objects
        assert snippet in storage.objects
        with psycopg.connect(migrated_url) as db:
            assert db.execute(
                "SELECT id FROM content.contents WHERE id=%s", [world.content_id]
            ).fetchone() == (world.content_id,)
            assert db.execute(
                "SELECT status FROM ops.deletion_requests WHERE id=%s",
                [response.json()["request_id"]],
            ).fetchone() == ("pending",)
            if remove_card:
                assert db.execute(
                    "SELECT card_id FROM practice.card_snippet_cleanup WHERE card_id=%s",
                    [world.card_id],
                ).fetchone() == (world.card_id,)
    finally:
        with psycopg.connect(migrated_url) as db:
            db.execute("DELETE FROM practice.card_snippet_writes WHERE id=%s", [writer])
    run_delete(migrated_url, response.json()["request_id"])
    assert key not in storage.objects
    assert snippet not in storage.objects
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status FROM ops.deletion_requests WHERE id=%s",
            [response.json()["request_id"]],
        ).fetchone() == ("completed",)
        assert (
            db.execute(
                "SELECT card_id FROM practice.card_snippet_cleanup WHERE card_id=%s",
                [world.card_id],
            ).fetchone()
            is None
        )


@pytest.mark.anyio
async def test_cancellation_drains_put_before_releasing_conversion_writer(
    make_client, migrated_url
):
    from listenup.modules.content import service as content
    from listenup.modules.content import writes
    from listenup.platform.jobs import Reschedule

    a = make_client()
    world = await asyncio.to_thread(seed_learner_data, migrated_url, uuid.UUID(learner_id(a)))
    database = Database(conninfo_to_url(migrated_url))
    started, finish = asyncio.Event(), asyncio.Event()

    async def put():
        started.set()
        await finish.wait()

    async def upload():
        async with writes.registered_write(
            database, world.user_id, world.media_id, world.content_id
        ):
            await writes.store(put())

    task = asyncio.create_task(upload())
    try:
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        async with database.transaction() as db:
            with pytest.raises(Reschedule):
                await content.require_no_media_writes(db, world.user_id, world.media_id)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        async with database.transaction() as db:
            await content.require_no_media_writes(db, world.user_id, world.media_id)
    finally:
        finish.set()
        if not task.done():
            await asyncio.gather(task, return_exceptions=True)
        await database.dispose()


@pytest.mark.anyio
async def test_direct_put_task_cancellation_preserves_uncertain_writer(make_client, migrated_url):
    from listenup.modules.content import service as content
    from listenup.modules.content import writes
    from listenup.platform.jobs import Reschedule

    a = make_client()
    world = await asyncio.to_thread(seed_learner_data, migrated_url, uuid.UUID(learner_id(a)))
    database = Database(conninfo_to_url(migrated_url))
    started = asyncio.Event()
    inner = []

    async def put():
        inner.append(asyncio.current_task())
        started.set()
        await asyncio.Event().wait()

    async def upload():
        async with writes.registered_write(
            database, world.user_id, world.media_id, world.content_id
        ):
            await writes.store(put())

    task = asyncio.create_task(upload())
    try:
        await asyncio.wait_for(started.wait(), 5)
        # Event-loop shutdown can cancel the child directly, bypassing shield().
        # A thread/remote PUT may still be running even though this task ended.
        inner[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        async with database.transaction() as db:
            with pytest.raises(Reschedule):
                await content.require_no_media_writes(db, world.user_id, world.media_id)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        with psycopg.connect(migrated_url) as db:
            db.execute(
                "DELETE FROM content.media_writes WHERE media_object_id=%s", [world.media_id]
            )
        await database.dispose()


@pytest.mark.anyio
async def test_account_disabled_after_registration_cannot_reach_conversion_put(
    make_client, migrated_url, monkeypatch
):
    from listenup.modules.content import writes
    from listenup.modules.identity import service as identity
    from listenup.platform.jobs import PermanentError

    a = make_client()
    world = await asyncio.to_thread(seed_learner_data, migrated_url, uuid.UUID(learner_id(a)))
    database = Database(conninfo_to_url(migrated_url))
    original = identity.hold_active_account
    calls = 0

    async def disable_before_second_check(db, learner):
        nonlocal calls
        calls += 1
        if calls == 2:
            with psycopg.connect(migrated_url) as owner:
                owner.execute(
                    "UPDATE identity.users SET status='pending_deletion', "
                    "deletion_scheduled_at=now()+interval '7 days' WHERE id=%s",
                    [learner],
                )
        return await original(db, learner)

    monkeypatch.setattr(identity, "hold_active_account", disable_before_second_check)
    try:
        with pytest.raises(PermanentError):
            async with writes.registered_write(
                database, world.user_id, world.media_id, world.content_id
            ):
                pytest.fail("The remote PUT must not start after account deletion")
        with psycopg.connect(migrated_url) as db:
            assert db.execute(
                "SELECT count(*) FROM content.media_writes WHERE user_id=%s", [world.user_id]
            ).fetchone() == (0,)
    finally:
        await database.dispose()


def test_deletion_scrubs_related_replay_text_without_changing_other_requests(
    make_client, migrated_url
):
    from psycopg.types.json import Jsonb

    a, b = make_client(), make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    other = uuid.UUID(learner_id(b))
    related = {
        "items": [
            {
                "attempt_id": str(world.dictation_attempt_id),
                "submitted_text": "private learner text",
            }
        ]
    }
    unrelated = {
        "id": str(uuid.uuid4()),
        "title": "Keep this other clip",
        "submitted_text": str(world.dictation_attempt_id),
        "values": [1, False, None],
    }
    with psycopg.connect(migrated_url) as db:
        for user, key, value in [
            (world.user_id, "related", related),
            (world.user_id, "content", {"id": str(world.content_id), "title": "Deleted title"}),
            (world.user_id, "session", {"session_id": str(world.sessions["dictation"])}),
            (
                world.user_id,
                "card",
                {"card_id": str(world.card_id), "written_form": "Deleted phrase"},
            ),
            (world.user_id, "unrelated", unrelated),
            (other, "related", related),
        ]:
            db.execute(
                "INSERT INTO ops.idempotency_keys(user_id,key,request_hash,status_code,response) "
                "VALUES (%s,%s,%s,200,%s)",
                [user, key, b"0" * 32, Jsonb(value)],
            )
    response = delete(a, world.content_id)
    assert response.status_code == 202, response.text
    run_delete(migrated_url, response.json()["request_id"])
    with psycopg.connect(migrated_url) as db:
        assert (
            db.execute(
                "SELECT status_code,response FROM ops.idempotency_keys WHERE user_id=%s AND key=%s",
                [world.user_id, "related"],
            ).fetchone()
            is None
        )
        assert (
            db.execute(
                "SELECT key FROM ops.idempotency_keys WHERE user_id=%s AND key=ANY(%s)",
                [world.user_id, ["content", "session", "card"]],
            ).fetchall()
            == []
        )
        assert db.execute(
            "SELECT response FROM ops.idempotency_keys WHERE user_id=%s AND key=%s",
            [world.user_id, "unrelated"],
        ).fetchone() == (unrelated,)
        assert db.execute(
            "SELECT response FROM ops.idempotency_keys WHERE user_id=%s AND key=%s",
            [other, "related"],
        ).fetchone() == (related,)


@pytest.mark.anyio
async def test_content_deleted_after_registration_cannot_reach_conversion_put(
    make_client, migrated_url, monkeypatch
):
    from listenup.modules.content import writes
    from listenup.modules.identity import service as identity
    from listenup.platform.jobs import PermanentError

    a = make_client()
    world = await asyncio.to_thread(seed_learner_data, migrated_url, uuid.UUID(learner_id(a)))
    database = Database(conninfo_to_url(migrated_url))
    original = identity.hold_active_account
    calls = 0

    async def mark_before_second_check(db, learner):
        nonlocal calls
        calls += 1
        if calls == 2:
            with psycopg.connect(migrated_url) as owner:
                owner.execute(
                    "UPDATE content.contents SET deleting_at=now() WHERE id=%s", [world.content_id]
                )
        return await original(db, learner)

    monkeypatch.setattr(identity, "hold_active_account", mark_before_second_check)
    try:
        with pytest.raises(PermanentError):
            async with writes.registered_write(
                database, world.user_id, world.media_id, world.content_id
            ):
                pytest.fail("A parent deleted between phases must never reach storage")
        with psycopg.connect(migrated_url) as db:
            assert db.execute(
                "SELECT count(*) FROM content.media_writes WHERE user_id=%s", [world.user_id]
            ).fetchone() == (0,)
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_deletion_export_redacts_manifest_but_keeps_counts(make_client, migrated_url):
    from listenup.modules.identity import service as identity

    a = make_client()
    world = await asyncio.to_thread(seed_learner_data, migrated_url, uuid.UUID(learner_id(a)))
    response = delete(a, world.content_id)
    assert response.status_code == 202, response.text
    request = response.json()["request_id"]
    await asyncio.to_thread(run_delete, migrated_url, request)
    prior = uuid.uuid4()
    with psycopg.connect(migrated_url) as owner:
        owner.execute(
            "INSERT INTO ops.deletion_requests(id,subject_user_id,scope,status,cancelled_at) "
            "VALUES (%s,%s,'account','cancelled',now())",
            [prior, world.user_id],
        )
    database = Database(conninfo_to_url(migrated_url))
    try:
        async with database.transaction() as db:
            part = await identity.export_data(db, world.user_id)
        audit = next(t for t in part.tables if t.name == "ops.deletion_requests")
        row = next(row for row in audit.rows if str(row["id"]) == request)
        assert next(row for row in audit.rows if row["id"] == prior)["report"] is None
        assert "storage_prefixes" not in row
        report = row["report"]
        assert "keys" not in report
        assert "card_prefixes" not in report
        assert "resource_ids" not in report
        assert report["sessions_removed"] == len(world.sessions)
        assert report["objects_removed"] == 0  # fake storage is empty
    finally:
        await database.dispose()
