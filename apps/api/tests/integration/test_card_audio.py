"""Private, durable card audio (FR-CA-2, NFR-SEC-2)."""

import asyncio
import subprocess
import uuid
from itertools import pairwise

import psycopg
import pytest

from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps, run_handler
from listenup.platform.storage import use_storage
from tests.integration import test_cards_api as cards
from tests.integration import test_storage as storage_tests
from tests.integration.conftest import conninfo_to_url

client = cards.client
make_client = cards.make_client
worker_url = cards.worker_url
clip = cards.clip
session_id = cards.session_id
card_session = cards.card_session
s3_storage = storage_tests.storage


def audio(client, card):
    return client.get(f"/api/v1/cards/{card}/audio", follow_redirects=False)


def test_creation_snapshots_span_and_queues_once(client, card_session, migrated_url):
    path = f"/api/v1/sessions/{card_session[0]}/cards"
    body = {"mark_id": card_session[1], "written_form": "hello world", "heard_form": "hullo"}
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    saved = client.post(path, json=body, headers=headers)
    assert saved.status_code == 201, saved.text
    assert saved.json()["audio_status"] == "pending"
    assert client.post(path, json=body, headers=headers).json() == saved.json()
    with psycopg.connect(migrated_url) as db:
        span = db.execute(
            "SELECT snippet_span FROM practice.cards WHERE id=%s", [saved.json()["id"]]
        ).fetchone()[0]
        assert span.lower <= 11000 and span.upper >= 13000
        assert 3000 <= span.upper - span.lower <= 6000
        assert db.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE "
            "task_name='cards.generate_snippet' AND args->>'card_id'=%s",
            [saved.json()["id"]],
        ).fetchone() == (1,)
    assert audio(client, saved.json()["id"]).json()["code"] == "card_audio_not_ready"


def test_audio_ownership_precedes_readiness(client, card_session, make_client):
    card = cards.create(client, card_session).json()["id"]
    other = make_client()
    response = audio(other, card)
    assert response.status_code == 404 and response.json()["code"] == "card_not_found"
    assert "Location" not in response.headers
    assert audio(client, str(uuid.uuid4())).status_code == 404


def test_long_phrase_refused_without_consuming_slot(client, card_session, migrated_url):
    # Extend the marked second word's ending beyond six seconds.
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE content.passage_transcripts SET end_ms=ARRAY[500,11500,18000,31000] "
            "WHERE media_object_id=(SELECT c.media_object_id FROM content.contents c "
            "JOIN practice.sessions s ON s.content_id=c.id WHERE s.id=%s)",
            [card_session[0]],
        )
    response = cards.create(client, card_session)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "card_phrase_too_long"
    assert client.get("/api/v1/cards").json()["cards"] == []


@pytest.fixture
def generated(client, card_session, migrated_url, tmp_path):
    from listenup.modules.cards import jobs

    saved = cards.create(client, card_session).json()
    storage = client.app.state.uploads.storage
    source = tmp_path / "source.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc='sin(2*PI*if(between(t,11,13),880,220)*t)':d=60",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    with psycopg.connect(migrated_url) as db:
        key = db.execute(
            "SELECT m.playback_key FROM content.media_objects m JOIN "
            "content.contents c ON c.media_object_id=m.id WHERE c.id=%s",
            [saved["content_id"]],
        ).fetchone()[0]
    if key is None:
        key = f"users/{client.get('/api/v1/me').json()['id']}/media/test/playback.mp4"
        with psycopg.connect(migrated_url) as db:
            db.execute(
                "UPDATE content.media_objects SET playback_key=%s WHERE "
                "id=(SELECT media_object_id FROM content.contents WHERE id=%s)",
                [key, saved["content_id"]],
            )
    storage.arrive(key, source.stat().st_size, data=source.read_bytes())
    database = Database(conninfo_to_url(migrated_url))
    use_storage(storage)
    user_id = client.get("/api/v1/me").json()["id"]
    with psycopg.connect(migrated_url) as db:
        generation = db.execute(
            "SELECT audio_generation FROM practice.cards WHERE id=%s", [saved["id"]]
        ).fetchone()[0]

    async def run(handler=jobs.generate_snippet):
        try:
            if handler == jobs.generate_snippet:
                await run_handler(
                    jobs.GENERATE,
                    JobDeps(database, None, 1),
                    card_id=saved["id"],
                    user_id=user_id,
                    generation_id=str(generation),
                )
                return
            await handler(
                JobDeps(database, None, 1),
                card_id=saved["id"],
                user_id=user_id,
                generation_id=str(generation),
            )
        finally:
            await database.dispose()

    yield saved, storage, key, run
    use_storage(None)


def test_aac_survives_source_expiry_and_mark_deletion(client, generated, migrated_url, tmp_path):
    saved, storage, source_key, run = generated
    asyncio.run(run())
    response = audio(client, saved["id"])
    assert response.status_code == 307, response.text
    assert response.headers["cache-control"] == "private, no-store"
    snippet_key = storage.downloads[-1][0]
    assert snippet_key.startswith(
        f"users/{client.get('/api/v1/me').json()['id']}/cards/{saved['id']}/"
    )
    assert storage.downloads[-1][1] == 120
    target = tmp_path / "snippet.m4a"
    target.write_bytes(storage.data[snippet_key])
    import json

    probe = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(target)]
        )
    )
    assert probe["streams"][0]["codec_name"] == "aac"
    assert 3 <= float(probe["format"]["duration"]) <= 6.05
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(target), "-f", "null", "-"], check=True)
    # The marked phrase is an 880 Hz tone at absolute seconds 11-13, with
    # 220 Hz context. This detects wrong seek positions, not merely duration.
    import array

    samples = array.array(
        "h",
        subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(target),
                "-f",
                "s16le",
                "-ar",
                "8000",
                "-ac",
                "1",
                "pipe:1",
            ]
        ),
    )

    def frequency(at):
        window = samples[int(at * 8000) : int((at + 0.2) * 8000)]
        return sum(a <= 0 < b for a, b in pairwise(window)) / 0.2

    assert frequency(0.1) == pytest.approx(220, abs=15)
    for at in (0.6, 1.4, 2.2):
        assert frequency(at) == pytest.approx(880, abs=15)
    assert frequency(2.7) == pytest.approx(220, abs=15)
    asyncio.run(storage.delete(source_key))
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE content.media_objects SET source='youtube', "
            "uploaded_by=NULL, status='expired', playback_key=NULL WHERE "
            "id=(SELECT media_object_id FROM practice.cards WHERE id=%s)",
            [saved["id"]],
        )
        db.execute("DELETE FROM practice.marks WHERE id=%s", [saved["mark_id"]])
    assert audio(client, saved["id"]).status_code == 307
    assert storage.data[snippet_key] == target.read_bytes()
    # A successful redelivery does not need source media.
    asyncio.run(run())
    assert client.get("/api/v1/cards").json()["cards"][0]["audio_status"] == "ready"


def test_upload_failure_retries_same_key(client, generated, monkeypatch):
    saved, storage, _, run = generated
    original = storage.put_file

    async def fail(*args, **kwargs):
        raise OSError("storage unavailable")

    monkeypatch.setattr(storage, "put_file", fail)
    with pytest.raises(OSError):
        asyncio.run(run())
    assert audio(client, saved["id"]).status_code == 409
    monkeypatch.setattr(storage, "put_file", original)
    asyncio.run(run())
    assert audio(client, saved["id"]).status_code == 307
    assert len([key for key in storage.data if "/cards/" in key]) == 1


def test_delete_cleanup_retries_and_cannot_resurrect(client, generated, migrated_url, monkeypatch):
    from listenup.modules.cards import jobs

    saved, storage, _, run = generated
    asyncio.run(run())
    audio(client, saved["id"])
    key = storage.downloads[-1][0]
    assert client.delete(f"/api/v1/cards/{saved['id']}").status_code == 204

    async def cleanup():
        database = Database(conninfo_to_url(migrated_url))
        try:
            await jobs.cleanup_snippets(JobDeps(database, None, 1))
        finally:
            await database.dispose()

    original = storage.delete

    async def fail(key):
        raise OSError("storage unavailable")

    monkeypatch.setattr(storage, "delete", fail)
    with pytest.raises(OSError):
        asyncio.run(cleanup())
    assert key in storage.data
    monkeypatch.setattr(storage, "delete", original)
    asyncio.run(cleanup())
    asyncio.run(run())
    assert key not in storage.data
    assert audio(client, saved["id"]).status_code == 404


def test_expired_source_is_permanent_and_retry_is_owned(
    client, generated, migrated_url, make_client
):
    from listenup.platform.jobs import PermanentError

    saved, storage, _source_key, run = generated
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE content.media_objects SET status='expired', "
            "playback_key=NULL WHERE id=(SELECT media_object_id FROM "
            "practice.cards WHERE id=%s)",
            [saved["id"]],
        )
    with pytest.raises(PermanentError):
        asyncio.run(run())
    assert client.get("/api/v1/cards").json()["cards"][0]["audio_status"] == "failed"
    path = f"/api/v1/cards/{saved['id']}/audio/retry"
    assert make_client().post(path).status_code == 404
    assert client.post(path).status_code == 202
    assert client.post(path).status_code == 409
    assert client.get("/api/v1/cards").json()["cards"][0]["audio_status"] == "pending"
    assert not any("/cards/" in key for key in storage.data)


def test_deletion_during_encoding_never_writes_object(client, generated, monkeypatch):
    from listenup.modules.cards import jobs

    saved, storage, _, run = generated
    original = jobs.audio.cut

    async def cut_then_delete(*args):
        await original(*args)
        response = await asyncio.to_thread(client.delete, f"/api/v1/cards/{saved['id']}")
        assert response.status_code == 204

    monkeypatch.setattr(jobs.audio, "cut", cut_then_delete)
    asyncio.run(run())
    assert not any("/cards/" in key for key in storage.data)


def test_storage_write_then_crash_retries_one_object(client, generated, monkeypatch):
    saved, storage, _, run = generated
    original = storage.put_file

    async def put_then_fail(*args):
        await original(*args)
        raise OSError("connection lost after upload")

    monkeypatch.setattr(storage, "put_file", put_then_fail)
    with pytest.raises(OSError):
        asyncio.run(run())
    assert client.get("/api/v1/cards").json()["cards"][0]["audio_status"] == "pending"
    assert len([key for key in storage.data if "/cards/" in key]) == 1
    monkeypatch.setattr(storage, "put_file", original)
    asyncio.run(run())
    assert audio(client, saved["id"]).status_code == 307
    assert len([key for key in storage.data if "/cards/" in key]) == 1


def test_retry_while_old_job_is_settling_queues_new_work(client, generated, migrated_url):
    from listenup.modules.cards import jobs

    saved, _storage, _key, run = generated
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE procrastinate.procrastinate_jobs SET status='doing' "
            "WHERE task_name='cards.generate_snippet' AND args->>'card_id'=%s",
            [saved["id"]],
        )
    asyncio.run(run(jobs.give_up))
    assert client.post(f"/api/v1/cards/{saved['id']}/audio/retry").status_code == 202
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE "
            "task_name='cards.generate_snippet' AND args->>'card_id'=%s AND status='todo'",
            [saved["id"]],
        ).fetchone() == (1,)
        db.execute(
            "UPDATE procrastinate.procrastinate_jobs SET status='failed' "
            "WHERE task_name='cards.generate_snippet' AND args->>'card_id'=%s AND status='doing'",
            [saved["id"]],
        )
    drain_intake(migrated_url)
    assert audio(client, saved["id"]).status_code == 307


def test_old_failure_callback_cannot_fail_a_new_retry(client, generated):
    from listenup.modules.cards import jobs

    saved, _storage, _key, run = generated
    asyncio.run(run(jobs.give_up))
    assert client.post(f"/api/v1/cards/{saved['id']}/audio/retry").status_code == 202
    asyncio.run(run(jobs.give_up))
    assert client.get("/api/v1/cards").json()["cards"][0]["audio_status"] == "pending"


def test_cascade_keeps_cleanup_record(client, generated, migrated_url):
    saved, _storage, _, run = generated
    asyncio.run(run())
    with psycopg.connect(migrated_url) as db:
        db.execute("DELETE FROM practice.sessions WHERE id=%s", [saved["session_id"]])
        assert db.execute(
            "SELECT user_id FROM practice.card_snippet_cleanup WHERE card_id=%s", [saved["id"]]
        ).fetchone()
    assert audio(client, saved["id"]).status_code == 404


def test_real_s3_snippet_delivery_and_cleanup(
    client, generated, migrated_url, s3_storage, monkeypatch
):
    import httpx

    from listenup.modules.cards import jobs

    saved, fake, source_key, run = generated
    asyncio.run(s3_storage.put(source_key, fake.data[source_key], "audio/mp4"))
    use_storage(s3_storage)
    monkeypatch.setattr(client.app.state.uploads, "storage", s3_storage)
    asyncio.run(run())
    location = audio(client, saved["id"]).headers["location"]
    assert httpx.get(location).status_code == 200
    assert httpx.get(location.split("?", 1)[0]).status_code == 403
    asyncio.run(s3_storage.delete(source_key))
    assert httpx.get(audio(client, saved["id"]).headers["location"]).status_code == 200
    assert client.delete(f"/api/v1/cards/{saved['id']}").status_code == 204

    async def cleanup():
        db = Database(conninfo_to_url(migrated_url))
        try:
            await jobs.cleanup_snippets(JobDeps(db, None, 1))
        finally:
            await db.dispose()

    asyncio.run(cleanup())
    assert httpx.get(location).status_code == 404


def test_export_omits_storage_keys_and_includes_uploaded_snippet(client, generated, migrated_url):
    from listenup.modules.cards import service

    saved, _storage, _, run = generated
    asyncio.run(run())

    async def export():
        database = Database(conninfo_to_url(migrated_url))
        try:
            async with database.transaction() as db:
                return await service.export_data(
                    db, uuid.UUID(client.get("/api/v1/me").json()["id"])
                )
        finally:
            await database.dispose()

    part = asyncio.run(export())
    assert len(part.files) == 1
    assert part.files[0].path == f"cards/{saved['id']}/snippet.m4a"
    assert all("snippet_key" not in row for table in part.tables for row in table.rows)
    assert "practice.card_snippet_cleanup" in {table.name for table in part.tables}
    # YouTube-derived files stay outside data exports, even when the snippet is ready.
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE content.media_objects SET source='youtube', uploaded_by=NULL "
            "WHERE id=(SELECT media_object_id FROM practice.cards WHERE id=%s)",
            [saved["id"]],
        )
    assert asyncio.run(export()).files == ()


def test_intake_worker_makes_new_card_playable(client, generated, migrated_url):
    import time

    saved, _storage, _, _run = generated
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "DELETE FROM procrastinate.procrastinate_jobs "
            "WHERE args->>'card_id' IS DISTINCT FROM %s",
            [saved["id"]],
        )

    started = time.monotonic()
    drain_intake(migrated_url)
    elapsed = time.monotonic() - started
    assert audio(client, saved["id"]).status_code == 307
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status::text FROM procrastinate.procrastinate_jobs "
            "WHERE task_name='cards.generate_snippet'"
        ).fetchone() == ("succeeded",)
    print(f"Local intake queue + AAC generation: {elapsed:.3f}s (not staging evidence)")


def drain_intake(migrated_url, *, isolated=False):
    import procrastinate

    from listenup.platform.jobs import app, configure_runtime

    async def drain():
        database = Database(conninfo_to_url(migrated_url))
        configure_runtime(database, isolate_media=isolated)
        try:
            with app.replace_connector(procrastinate.PsycopgConnector(conninfo=migrated_url)):
                async with app.open_async():
                    await app.run_worker_async(
                        queues=["intake"], wait=False, install_signal_handlers=False
                    )
        finally:
            configure_runtime(database)
            await database.dispose()

    asyncio.run(drain())


@pytest.mark.parametrize("when", ["before", "during_encoding"])
def test_disabled_account_finishes_failed_without_upload(
    client, generated, migrated_url, monkeypatch, when
):
    from listenup.modules.cards import jobs
    from listenup.platform.jobs import PermanentError

    _saved, storage, _, run = generated
    user = client.get("/api/v1/me").json()["id"]

    def status(value):
        with psycopg.connect(migrated_url) as db:
            db.execute(
                "UPDATE identity.users SET status=%s, deletion_scheduled_at="
                "CASE WHEN %s='pending_deletion' THEN now()+interval '7 days' "
                "ELSE NULL END WHERE id=%s",
                [value, value, user],
            )

    if when == "before":
        status("pending_deletion")
    else:
        original = jobs.audio.cut

        async def disable_after_cut(*args):
            await original(*args)
            await asyncio.to_thread(status, "pending_deletion")

        monkeypatch.setattr(jobs.audio, "cut", disable_after_cut)
    try:
        with pytest.raises(PermanentError):
            asyncio.run(run())
    finally:
        status("active")
    assert client.get("/api/v1/cards").json()["cards"][0]["audio_status"] == "failed"
    assert not any("/cards/" in key for key in storage.data)


@pytest.mark.parametrize("bad_source", ["missing", "invalid"])
def test_unusable_bytes_fail_and_remove_scratch(
    client, generated, monkeypatch, tmp_path, bad_source
):
    from listenup.modules.cards import jobs
    from listenup.platform.config import Settings
    from listenup.platform.jobs import PermanentError

    _saved, storage, source_key, run = generated
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(jobs, "get_settings", lambda: Settings(media_scratch_dir=str(scratch)))
    if bad_source == "missing":
        asyncio.run(storage.delete(source_key))
    else:
        storage.data[source_key] = b"not audio"
    with pytest.raises(PermanentError):
        asyncio.run(run())
    assert client.get("/api/v1/cards").json()["cards"][0]["audio_status"] == "failed"
    assert list(scratch.iterdir()) == []
    assert not any("/cards/" in key for key in storage.data)


def test_database_loss_during_upload_retains_cleanup_until_writer_finishes(
    client, generated, migrated_url, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    from listenup.modules.cards import jobs

    saved, storage, _, run = generated
    original = storage.put_file
    observed = {}

    async def cleanup():
        database = Database(conninfo_to_url(migrated_url))
        try:
            await jobs.cleanup_snippets(JobDeps(database, None, 1))
        finally:
            await database.dispose()

    async def upload_after_connection_loss(key, path, content_type):
        with psycopg.connect(migrated_url) as db:
            assert db.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=current_database() AND usename=current_user "
                "AND state='idle in transaction' AND pid<>pg_backend_pid()"
            ).fetchall()
        response = await asyncio.to_thread(client.delete, f"/api/v1/cards/{saved['id']}")
        assert response.status_code == 204
        await cleanup()
        with psycopg.connect(migrated_url) as db:
            observed["tombstones"] = db.execute(
                "SELECT count(*) FROM practice.card_snippet_cleanup WHERE card_id=%s",
                [saved["id"]],
            ).fetchone()[0]
        await original(key, path, content_type)

    monkeypatch.setattr(storage, "put_file", upload_after_connection_loss)
    with pytest.raises(OperationalError):
        asyncio.run(run())
    assert observed["tombstones"] == 1
    assert any("/cards/" in key for key in storage.data)
    asyncio.run(cleanup())
    asyncio.run(run())
    assert not any("/cards/" in key for key in storage.data)
    with psycopg.connect(migrated_url) as db:
        assert db.execute("SELECT count(*) FROM practice.card_snippet_writes").fetchone() == (0,)


def test_account_purge_waits_for_snippet_writer(client, generated, migrated_url, monkeypatch):
    from listenup.modules.identity import jobs as identity_jobs
    from listenup.platform.jobs import Reschedule
    from tests.integration.test_account_deletion import PASSWORD, deletion_request, make_due

    _saved, storage, _, run = generated
    original = storage.put_file
    user = client.get("/api/v1/me").json()["id"]
    observed = {}

    async def purge(request_id):
        database = Database(conninfo_to_url(migrated_url))
        try:
            await identity_jobs.purge_account(JobDeps(database, None, 1), request_id=request_id)
        finally:
            await database.dispose()

    async def upload_during_purge(key, path, content_type):
        # Lose the account/card locks as with an idle timeout, then start deletion.
        with psycopg.connect(migrated_url) as db:
            db.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=current_database() AND usename=current_user "
                "AND state='idle in transaction' AND pid<>pg_backend_pid()"
            )
        response = await asyncio.to_thread(
            client.request, "DELETE", "/api/v1/me", json={"password": PASSWORD, "confirm": True}
        )
        assert response.status_code == 202
        request = deletion_request(migrated_url, uuid.UUID(user))
        make_due(migrated_url, uuid.UUID(user))
        try:
            await purge(str(request["id"]))
        except Reschedule:
            observed["waited"] = True
        else:
            observed["waited"] = False
        with psycopg.connect(migrated_url) as db:
            observed["users"] = db.execute(
                "SELECT count(*) FROM identity.users WHERE id=%s", [user]
            ).fetchone()[0]
        await original(key, path, content_type)

    monkeypatch.setattr(storage, "put_file", upload_during_purge)
    from sqlalchemy.exc import OperationalError

    with pytest.raises(OperationalError):
        asyncio.run(run())
    assert observed == {"waited": True, "users": 1}
    request = deletion_request(migrated_url, uuid.UUID(user))
    asyncio.run(purge(str(request["id"])))
    assert not any(key.startswith(f"users/{user}/") for key in storage.data)
    assert deletion_request(migrated_url, uuid.UUID(user))["status"] == "completed"


def test_uncertain_writer_survives_expiry_and_blocks_cleanup_purge_and_downgrade(
    client, generated, migrated_url, monkeypatch, api_role_url, make_client
):
    from alembic import command
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from listenup.modules.cards import jobs, service
    from listenup.platform.storage import StorageWriteUncertain
    from tests.integration.conftest import alembic_config

    saved, storage, _, run = generated
    user = uuid.UUID(client.get("/api/v1/me").json()["id"])
    other = uuid.UUID(make_client().get("/api/v1/me").json()["id"])
    original = storage.put_file

    async def uncertain(*args):
        await original(*args)
        raise StorageWriteUncertain("lost confirmation")

    async def inspect():
        database = Database(api_role_url)
        try:
            async with database.transaction(user) as db:
                part = await service.export_data(db, user)
                table = next(t for t in part.tables if t.name == "practice.card_snippet_writes")
                assert len(table.rows) == 1
                assert "owner" not in table.rows[0] and "id" not in table.rows[0]
                cards_table = next(t for t in part.tables if t.name == "practice.cards")
                assert "audio_generation" not in cards_table.rows[0]
            async with database.transaction(other) as db:
                assert (
                    await db.scalar(text("SELECT count(*) FROM practice.card_snippet_writes")) == 0
                )
        finally:
            await database.dispose()

    async def cleanup():
        database = Database(conninfo_to_url(migrated_url))
        try:
            await jobs.cleanup_snippets(JobDeps(database, None, 1))
        finally:
            await database.dispose()

    monkeypatch.setattr(storage, "put_file", uncertain)
    try:
        with pytest.raises(StorageWriteUncertain):
            asyncio.run(run())
        asyncio.run(inspect())
        with psycopg.connect(migrated_url) as db:
            db.execute(
                "UPDATE practice.card_snippet_writes SET created_at=now()-interval '100 days' "
                "WHERE user_id=%s",
                [user],
            )
        assert client.delete(f"/api/v1/cards/{saved['id']}").status_code == 204
        asyncio.run(cleanup())
        assert any("/cards/" in key for key in storage.data)
        with (
            pytest.raises(psycopg.errors.ForeignKeyViolation),
            psycopg.connect(migrated_url) as db,
        ):
            db.execute("DELETE FROM identity.users WHERE id=%s", [user])
        with pytest.raises(DBAPIError, match="Reconcile snippet writers"):
            command.downgrade(alembic_config(migrated_url), "73_card_audio")
    finally:
        # Simulated operator reconciliation: this controlled writer has stopped,
        # and its storage operation is known complete. Never expire real writers.
        with psycopg.connect(migrated_url) as db:
            db.execute("DELETE FROM practice.card_snippet_writes WHERE user_id=%s", [user])
        # Later migrations may have been downgraded before the writer barrier
        # refused removal of 73_audio_lifecycle. Restore the shared test schema.
        command.upgrade(alembic_config(migrated_url), "head")
    asyncio.run(cleanup())
    assert not any("/cards/" in key for key in storage.data)


def test_retry_enqueue_failure_rolls_back_state(client, generated, monkeypatch):
    from listenup.modules.cards import jobs, service

    saved, _storage, _, run = generated
    asyncio.run(run(jobs.give_up))

    async def fail(*args, **kwargs):
        raise OSError("queue unavailable")

    original = service.enqueue
    monkeypatch.setattr(service, "enqueue", fail)
    assert client.post(f"/api/v1/cards/{saved['id']}/audio/retry").status_code == 500
    assert client.get("/api/v1/cards").json()["cards"][0]["audio_status"] == "failed"
    monkeypatch.setattr(service, "enqueue", original)
    assert client.post(f"/api/v1/cards/{saved['id']}/audio/retry").status_code == 202


def test_sandboxed_worker_persists_terminal_failure_and_event(
    client, generated, migrated_url, monkeypatch
):
    import json

    saved, _storage, _, _run = generated
    monkeypatch.setenv("LISTENUP_DATABASE_URL", conninfo_to_url(migrated_url))
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "DELETE FROM procrastinate.procrastinate_jobs "
            "WHERE args->>'card_id' IS DISTINCT FROM %s",
            [saved["id"]],
        )
        db.execute(
            "UPDATE content.media_objects SET status='expired', playback_key=NULL "
            "WHERE id=(SELECT media_object_id FROM practice.cards WHERE id=%s)",
            [saved["id"]],
        )
    with psycopg.connect(migrated_url, autocommit=True) as listener:
        listener.execute("LISTEN user_events")
        drain_intake(migrated_url, isolated=True)
        events = [json.loads(n.payload) for n in listener.notifies(timeout=1, stop_after=1)]
    assert client.get("/api/v1/cards").json()["cards"][0]["audio_status"] == "failed"
    assert len(events) == 1
    assert events[0]["t"] == "card.audio_updated" and events[0]["r"] == saved["session_id"]
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status::text FROM procrastinate.procrastinate_jobs "
            "WHERE task_name='cards.generate_snippet'"
        ).fetchone() == ("failed",)


def test_account_disabled_between_registration_and_upload_never_writes(
    client, generated, migrated_url, monkeypatch
):
    from listenup.modules.identity import service as identity
    from listenup.platform.jobs import PermanentError

    _saved, storage, _, run = generated
    user = client.get("/api/v1/me").json()["id"]
    original = identity.hold_active_account
    calls = 0

    def status(value):
        with psycopg.connect(migrated_url) as db:
            db.execute(
                "UPDATE identity.users SET status=%s, deletion_scheduled_at="
                "CASE WHEN %s='pending_deletion' THEN now()+interval '7 days' "
                "ELSE NULL END WHERE id=%s",
                [value, value, user],
            )

    async def hold(db, learner):
        nonlocal calls
        calls += 1
        if calls == 2:
            status("pending_deletion")
        return await original(db, learner)

    monkeypatch.setattr(identity, "hold_active_account", hold)
    try:
        with pytest.raises(PermanentError):
            asyncio.run(run())
    finally:
        status("active")
    assert calls == 2
    assert client.get("/api/v1/cards").json()["cards"][0]["audio_status"] == "failed"
    assert not any("/cards/" in key for key in storage.data)
    with psycopg.connect(migrated_url) as db:
        assert db.execute("SELECT count(*) FROM practice.card_snippet_writes").fetchone() == (0,)
