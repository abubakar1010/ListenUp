"""Export my data as JSON with my media files (#92, NFR-SEC-5, ADR 0030).

The API runs as a role with only the API's rights, so row-level security is in force;
the build job runs as the migration owner, which bypasses row-level security like the
workers' role, so the job's own filters are what keeps other learners' data out.
Storage is the in-memory fake.
"""

import asyncio
import dataclasses
import io
import json
import uuid
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.modules.export import jobs
from listenup.platform import jobs as platform_jobs
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps, run_handler
from listenup.platform.storage import use_storage
from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import ClientFactory, FakeStorage, client_factory, learner_id
from tests.integration.seed import SeededLearner, seed_learner_data
from tests.integration.test_password_reset import deliver

PLAYBACK = b"uploaded playback bytes"
YOUTUBE = b"youtube playback bytes"


def test_early_expiry_keeps_a_future_job(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str
) -> None:
    client = make_client()
    user = learner_id(client)
    started = request_export(client)
    own_key = f"users/{user}/exports/{started['id']}.zip"
    other = make_client()
    other_user = learner_id(other)
    other_export = request_export(other)
    run_build(migrated_url, other_export["id"], other_user)
    other_key = f"users/{other_user}/exports/{other_export['id']}.zip"
    run_build(migrated_url, started["id"], user)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("UPDATE procrastinate.procrastinate_jobs SET scheduled_at = now()")
    deliver(migrated_url)
    with psycopg.connect(migrated_url) as conn:
        waiting = conn.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE task_name = %s "
            "AND status = 'todo' AND scheduled_at > now() AND args->>'export_id' = %s",
            [jobs.EXPIRE_ARCHIVE, started["id"]],
        ).fetchone()
    assert waiting == (1,)
    assert own_key in storage.objects
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE ops.data_exports SET expires_at = now() - interval '1 second' WHERE id = %s",
            [started["id"]],
        )
        conn.execute("UPDATE procrastinate.procrastinate_jobs SET scheduled_at = now()")
    deliver(migrated_url)
    assert own_key not in storage.objects
    assert latest(client)["status"] == "expired"
    assert other_key in storage.objects


@pytest.mark.parametrize("status", ["pending", "building", "ready", "expired", "failed", "purged"])
def test_cleanup_only_deletes_failed_or_purged_archives(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str, status: str
) -> None:
    client = make_client()
    user = learner_id(client)
    started = request_export(client)
    run_build(migrated_url, started["id"], user)
    key = f"users/{user}/exports/{started['id']}.zip"
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        if status == "purged":
            conn.execute("DELETE FROM identity.users WHERE id = %s", [user])
        else:
            conn.execute(
                "UPDATE ops.data_exports SET status = %s WHERE id = %s", [status, started["id"]]
            )

    async def cleanup() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=1)
        try:
            await jobs.cleanup_archive(
                JobDeps(database, None, 1), export_id=started["id"], user_id=user
            )
        finally:
            await database.dispose()

    asyncio.run(cleanup())
    assert (key in storage.objects) == (status not in ("failed", "purged"))


@pytest.mark.parametrize("restored", [False, True])
def test_cleanup_survives_build_and_cleanup_retry_exhaustion(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str, restored: bool
) -> None:
    client = make_client()
    user = learner_id(client)
    started = request_export(client)
    key = f"users/{user}/exports/{started['id']}.zip"

    class Broken(FakeStorage):
        unavailable = True

        async def delete(self, key: str) -> None:
            if self.unavailable:
                raise RuntimeError("storage unavailable")
            await super().delete(key)

    broken = Broken()
    broken.arrive(key, 1, "application/zip", b"x")
    use_storage(broken)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("DELETE FROM procrastinate.procrastinate_jobs")
        conn.execute(
            "UPDATE identity.users SET status = 'pending_deletion', "
            "deletion_scheduled_at = now() + interval '7 days' WHERE id = %s",
            [user],
        )
    with pytest.raises(RuntimeError, match="storage unavailable"):
        run_build(migrated_url, started["id"], user, attempt=jobs.BUILD_ATTEMPTS)
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs "
            "WHERE task_name = 'export.cleanup_archive' AND status = 'todo'"
        ).fetchone() == (1,)
    # Exhaust the dedicated cleanup's attempts too. A future cycle must survive.
    for _ in range(platform_jobs.LANES[platform_jobs.Lane.BACKGROUND].max_attempts):
        with psycopg.connect(migrated_url, autocommit=True) as conn:
            conn.execute("UPDATE procrastinate.procrastinate_jobs SET scheduled_at = now()")
        deliver(migrated_url)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        assert conn.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs "
            "WHERE task_name = 'export.cleanup_archive' AND status = 'todo' "
            "AND scheduled_at > now()"
        ).fetchone() == (1,)
        if restored:
            conn.execute(
                "UPDATE identity.users SET status = 'active', deletion_scheduled_at = NULL "
                "WHERE id = %s",
                [user],
            )
        conn.execute("UPDATE procrastinate.procrastinate_jobs SET scheduled_at = now()")
    broken.unavailable = False
    deliver(migrated_url)
    assert key not in broken.objects


@pytest.fixture
def storage() -> Iterator[FakeStorage]:
    fake = FakeStorage()
    use_storage(fake)
    yield fake
    use_storage(None)


@pytest.fixture
def make_client(api_role_url: str, storage: FakeStorage) -> Iterator[ClientFactory]:
    def with_exports(make: ClientFactory) -> ClientFactory:
        def build(**settings: object) -> TestClient:
            client = make(**settings)
            client.app.state.exports.storage = storage  # type: ignore[attr-defined]
            return client

        return build

    for make in client_factory(api_role_url, storage):
        yield with_exports(make)


def run_build(migrated_url: str, export_id: str, user_id: str, attempt: int = 1) -> None:
    async def run() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=1)
        try:
            await run_handler(
                jobs.BUILD_ARCHIVE,
                JobDeps(database, None, attempt),
                export_id=export_id,
                user_id=user_id,
            )
        finally:
            await database.dispose()

    asyncio.run(run())


def run_expiry(migrated_url: str, export_id: str, user_id: str) -> None:
    async def run() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=1)
        try:
            await jobs.expire_archive(
                JobDeps(database, None, 1), export_id=export_id, user_id=user_id
            )
        finally:
            await database.dispose()

    asyncio.run(run())


def add_youtube_item(migrated_url: str, learner: uuid.UUID, storage: FakeStorage) -> str:
    """A playable YouTube clip in the learner's library; its file is even stored under
    the learner's prefix, so only the rule that YouTube media is never exported keeps it
    out of the archive. Returns the content id."""
    media_id, content_id = uuid.uuid4(), uuid.uuid4()
    key = f"users/{learner}/media/{media_id}/playback.mp4"
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO content.media_objects (id, fingerprint, source, source_ref, title, "
            "status, duration_ms, playback_key) "
            "VALUES (%s, %s, 'youtube', 'dQw4w9WgXcQ', 'A talk', 'playable', 60000, %s)",
            [media_id, f"youtube:{media_id.hex}", key],
        )
        conn.execute(
            "INSERT INTO content.contents (id, user_id, media_object_id, title) "
            "VALUES (%s, %s, %s, 'A talk from YouTube')",
            [content_id, learner, media_id],
        )
    storage.arrive(key, len(YOUTUBE), "video/mp4", YOUTUBE)
    return str(content_id)


def seeded(migrated_url: str, client: TestClient, storage: FakeStorage) -> SeededLearner:
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(client)))
    key = f"users/{world.user_id}/media/{world.media_id}/playback.mp4"
    storage.arrive(key, len(PLAYBACK), "audio/mp4", PLAYBACK)
    return world


def request_export(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/v1/me/exports")
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def latest(client: TestClient) -> dict[str, Any] | None:
    response = client.get("/api/v1/me/exports/latest")
    assert response.status_code == 200, response.text
    found: dict[str, Any] | None = response.json()["export"]
    return found


def read_archive(storage: FakeStorage, learner: object, export_id: str) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(storage.data[f"users/{learner}/exports/{export_id}.zip"]))


def learner_tables(migrated_url: str) -> set[str]:
    """Every application table with a `user_id` column: each is learner-owned data."""
    with psycopg.connect(migrated_url) as conn:
        rows = conn.execute(
            "SELECT table_schema || '.' || table_name FROM information_schema.columns "
            "WHERE column_name = 'user_id' "
            "AND table_schema IN ('identity', 'content', 'practice', 'grading', 'ai', 'ops')"
        ).fetchall()
    return {str(row[0]) for row in rows}


def test_export_includes_disputed_reference_only_for_its_learner(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str
) -> None:
    from tests.integration.test_dictation_disputes import dispute, share_clip
    from tests.integration.test_dictation_marks import scored_attempt
    from tests.integration.test_sessions_api import add_clip

    client = make_client(
        transcript_read_database_url=conninfo_to_url(migrated_url)
        + "?options=-c%20role%3Dlistenup_worker"
    )
    other = make_client()
    user = learner_id(client)
    clip = add_clip(migrated_url, user)
    attempt = scored_attempt(client, migrated_url, clip, "cap", ["cat"])
    share_clip(client, other, attempt, migrated_url)
    assert dispute(client, attempt["id"]).status_code == 200
    for actor, expected in [(client, ["cap"]), (other, [])]:
        started = request_export(actor)
        run_build(migrated_url, started["id"], learner_id(actor))
        with read_archive(storage, learner_id(actor), started["id"]) as archive:
            exported = json.loads(archive.read("data.json"))
        corrections = exported["tables"]["content.transcript_corrections"]
        assert [row["corrected_text"] for row in corrections] == expected
        assert all(row["user_id"] == user for row in corrections)


def test_export_holds_every_learner_table_and_only_the_learners_data(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str
) -> None:
    client_a, client_b = make_client(), make_client()
    a = seeded(migrated_url, client_a, storage)
    b = seeded(migrated_url, client_b, storage)
    for client, world in [(client_a, a), (client_b, b)]:
        response = client.get(f"/api/v1/sessions/{world.sessions['shadow']}/shadow/segment")
        assert response.status_code == 200, response.text
    # Corrections are private even when both learners reference the same cache row.
    transcript_id = uuid.uuid4()
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "INSERT INTO content.passage_transcripts (id,media_object_id,span,origin) "
            "VALUES (%s,%s,'[0,120000)','generated')",
            [transcript_id, a.media_id],
        )
        for user_id, value in [(a.user_id, "Own correction"), (b.user_id, "Private correction")]:
            conn.execute(
                "INSERT INTO content.transcript_corrections "
                "(user_id,passage_transcript_id,word_index,corrected_text) VALUES (%s,%s,0,%s)",
                [user_id, transcript_id, value],
            )
    youtube_content = add_youtube_item(migrated_url, a.user_id, storage)
    add_youtube_item(migrated_url, b.user_id, storage)

    started = request_export(client_a)
    assert started["status"] == "pending"
    assert started["download_url"] is None
    run_build(migrated_url, started["id"], str(a.user_id))

    shown = latest(client_a)
    assert shown is not None
    assert shown["id"] == started["id"]
    assert shown["status"] == "ready"
    assert shown["file_count"] == 1  # the playback file; the pending upload never arrived
    assert shown["download_url"] == f"/api/v1/me/exports/{started['id']}/download"

    archive = read_archive(storage, a.user_id, started["id"])
    data = json.loads(archive.read("data.json"))
    tables: dict[str, list[dict[str, Any]]] = data["tables"]

    # Every learner-owned table, the account itself and the media the items use.
    assert learner_tables(migrated_url) <= set(tables)
    assert [
        (row["user_id"], row["corrected_text"]) for row in tables["content.transcript_corrections"]
    ] == [(str(a.user_id), "Own correction")]
    segments = tables["practice.shadow_segments"]
    assert len(segments) == 1
    assert segments[0]["session_id"] == str(a.sessions["shadow"])
    assert segments[0]["chosen_by"] == "system"
    assert segments[0]["mark_count"] == 0
    assert segments[0]["locked_at"] is None
    assert segments[0]["span"] == {"lower": 0, "upper": 90_000, "bounds": "[)"}
    assert {"identity.users", "content.media_objects"} <= set(tables)
    assert [row["id"] for row in tables["identity.users"]] == [str(a.user_id)]
    assert {row["id"] for row in tables["practice.sessions"]} == {
        str(s) for s in a.sessions.values()
    }
    assert {row["attempt_id"] for row in tables["practice.dictation_attempts"]} == {
        str(a.dictation_attempt_id)
    }
    assert {row["attempt_id"] for row in tables["practice.blind_attempts"]} == {
        str(a.blind_attempt_id)
    }
    assert {row["id"] for row in tables["content.uploads"]} == {
        str(a.confirmed_upload_id),
        str(a.pending_upload_id),
    }
    # The learner's analytics events go with their data (ADR 0035).
    events = tables["ops.analytics_events"]
    assert {"plan_started", "step_started", "listen_started"} <= {r["event_type"] for r in events}
    session = next(r for r in tables["practice.sessions"] if r["id"] == str(a.sessions["blind"]))
    assert session["passage"]["lower"] == 0
    for name, rows in tables.items():
        for row in rows:
            if "user_id" in row:
                assert row["user_id"] == str(a.user_id), name

    # The YouTube item is exported as data; its media file is not (D10).
    assert youtube_content in {row["id"] for row in tables["content.contents"]}
    youtube_media = [r for r in tables["content.media_objects"] if r["source"] == "youtube"]
    assert [r["source_ref"] for r in youtube_media] == ["dQw4w9WgXcQ"]
    names = archive.namelist()
    assert f"media/{a.media_id}/playback.mp4" in names
    assert archive.read(f"media/{a.media_id}/playback.mp4") == PLAYBACK
    assert not any(archive.read(n) == YOUTUBE for n in names)
    assert f"media/{youtube_media[0]['id']}/playback.mp4" not in names
    assert {f["path"] for f in data["files"]} == {n for n in names if n != "data.json"}
    # The pending upload's original was never put in storage.
    assert data["missing_files"] == [f"uploads/{a.pending_upload_id}.mp3"]

    # No secret and nothing of the other learner's.
    raw = archive.read("data.json").decode()
    for secret in ("password_hash", "token_hash", "media_token_hash", "request_hash"):
        assert f'"{secret}"' not in raw.split('"omitted_columns"')[0]
    assert "archive_key" not in tables["ops.data_exports"][0]
    for other in [*b.ids(), "B's"]:
        assert other not in raw


def test_download_needs_the_owner_and_redirects_to_a_short_lived_link(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str
) -> None:
    owner, other = make_client(), make_client()
    a = seeded(migrated_url, owner, storage)
    started = request_export(owner)
    path = f"/api/v1/me/exports/{started['id']}/download"

    not_ready = owner.get(path, follow_redirects=False)
    assert not_ready.status_code == 409
    assert not_ready.json()["code"] == "export_not_ready"

    run_build(migrated_url, started["id"], str(a.user_id))
    response = owner.get(path, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["cache-control"] == "private, no-store"
    key = f"users/{a.user_id}/exports/{started['id']}.zip"
    assert key in response.headers["location"]
    assert storage.downloads[-1] == (key, 120)

    assert other.get(path, follow_redirects=False).json()["code"] == "export_not_found"
    owner.post("/api/v1/auth/logout")
    signed_out = owner.get(path, follow_redirects=False)
    assert signed_out.status_code == 401


def test_archives_expire(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str
) -> None:
    client = make_client()
    a = seeded(migrated_url, client, storage)
    started = request_export(client)
    run_build(migrated_url, started["id"], str(a.user_id))
    key = f"users/{a.user_id}/exports/{started['id']}.zip"
    with psycopg.connect(migrated_url) as conn:
        expiry = conn.execute(
            "SELECT expires_at - ready_at FROM ops.data_exports WHERE id = %s", [started["id"]]
        ).fetchone()
        job = conn.execute(
            "SELECT scheduled_at FROM procrastinate.procrastinate_jobs "
            "WHERE task_name = 'export.expire_archive' AND args->>'export_id' = %s",
            [started["id"]],
        ).fetchone()
    assert expiry is not None and expiry[0] == timedelta(days=7)
    assert job is not None and job[0] > datetime.now(UTC) + timedelta(days=6)

    # Not due yet: the job leaves the archive alone.
    with pytest.raises(platform_jobs.Reschedule) as postponed:
        run_expiry(migrated_url, started["id"], str(a.user_id))
    assert postponed.value.run_at == job[0]
    assert key in storage.data

    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE ops.data_exports SET expires_at = now() - interval '1 minute' WHERE id = %s",
            [started["id"]],
        )
    gone = client.get(f"/api/v1/me/exports/{started['id']}/download", follow_redirects=False)
    assert gone.status_code == 410
    assert gone.json()["code"] == "export_expired"
    shown = latest(client)
    assert shown is not None and shown["status"] == "expired" and shown["download_url"] is None

    run_expiry(migrated_url, started["id"], str(a.user_id))
    run_expiry(migrated_url, started["id"], str(a.user_id))  # safe to repeat
    assert key not in storage.data
    with psycopg.connect(migrated_url) as conn:
        status = conn.execute(
            "SELECT status FROM ops.data_exports WHERE id = %s", [started["id"]]
        ).fetchone()
    assert status == ("expired",)


def test_one_export_at_a_time_and_a_daily_limit(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str
) -> None:
    client = make_client(export_daily_limit=2)
    user = learner_id(client)
    assert latest(client) is None

    first = request_export(client)
    busy = client.post("/api/v1/me/exports")
    assert busy.status_code == 409
    assert busy.json()["code"] == "export_in_progress"
    assert busy.json()["export_id"] == first["id"]

    run_build(migrated_url, first["id"], user)
    second = request_export(client)
    run_build(migrated_url, second["id"], user)
    refused = client.post("/api/v1/me/exports")
    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limited"
    assert int(refused.headers["retry-after"]) > 0


def test_a_repeated_request_with_its_key_starts_one_export(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str
) -> None:
    client = make_client()
    headers = {"Idempotency-Key": "export-1"}
    first = client.post("/api/v1/me/exports", headers=headers)
    again = client.post("/api/v1/me/exports", headers=headers)
    assert first.status_code == again.status_code == 202
    assert again.json()["id"] == first.json()["id"]
    assert again.headers.get("idempotent-replayed") == "true"


def test_a_failed_build_is_marked_and_announced(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str
) -> None:
    client = make_client()
    user = learner_id(client)
    started = request_export(client)

    class Broken(FakeStorage):
        async def put_file(self, key: str, path: object, content_type: str) -> None:
            raise RuntimeError("storage is down")

    use_storage(Broken())
    with psycopg.connect(migrated_url, autocommit=True) as listener:
        listener.execute("LISTEN user_events")
        with pytest.raises(RuntimeError):
            run_build(migrated_url, started["id"], user, attempt=1)
        assert latest(client)["status"] == "building"  # type: ignore[index]
        with pytest.raises(RuntimeError):
            run_build(migrated_url, started["id"], user, attempt=jobs.BUILD_ATTEMPTS)
        notices = [json.loads(n.payload) for n in listener.notifies(timeout=1, stop_after=1)]
    assert notices == [{"u": user, "t": "export.ready", "r": started["id"]}]
    shown = latest(client)
    assert shown is not None and shown["status"] == "failed"
    assert request_export(client)["status"] == "pending"  # the learner can ask again


def test_a_last_build_that_times_out_frees_the_learner_to_ask_again(
    make_client: ClientFactory,
    storage: FakeStorage,
    migrated_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The timeout cancels the handler, so only the job wrapper can settle it.
    client = make_client()
    user = learner_id(client)
    started = request_export(client)
    entry = platform_jobs._registry[jobs.BUILD_ARCHIVE]
    short = dataclasses.replace(entry.spec, timeout=timedelta(seconds=0.2))
    monkeypatch.setitem(
        platform_jobs._registry, jobs.BUILD_ARCHIVE, dataclasses.replace(entry, spec=short)
    )

    class Stalled(FakeStorage):
        async def put_file(self, key: str, path: object, content_type: str) -> None:
            await asyncio.sleep(60)

    use_storage(Stalled())
    with pytest.raises(TimeoutError):
        run_build(migrated_url, started["id"], user, attempt=jobs.BUILD_ATTEMPTS)
    shown = latest(client)
    assert shown is not None and shown["status"] == "failed"
    assert request_export(client)["status"] == "pending"


def test_an_account_deleted_after_asking_gets_no_archive(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str
) -> None:
    """Deleting the account (ADR 0029) stops an export the learner asked for just before."""
    client = make_client()
    user = learner_id(client)
    seeded(migrated_url, client, storage)
    started = request_export(client)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE identity.users SET status = 'pending_deletion', "
            "deletion_scheduled_at = now() + interval '7 days' WHERE id = %s",
            [user],
        )

    run_build(migrated_url, started["id"], user)

    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT status, error_code, archive_key FROM ops.data_exports WHERE id = %s",
            [started["id"]],
        ).fetchone()
    assert row == ("failed", "account_deleted", None)
    assert not [key for key in storage.objects if "/exports/" in key]


def test_an_account_deleted_while_the_archive_is_built_keeps_no_archive(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str
) -> None:
    """The check at the start passed; the learner deletes the account before it ends."""
    client = make_client()
    user = learner_id(client)
    seeded(migrated_url, client, storage)
    started = request_export(client)

    class DeletesWhileStoring(FakeStorage):
        async def put_file(self, key: str, path: Path, content_type: str) -> None:
            await super().put_file(key, path, content_type)
            with psycopg.connect(migrated_url, autocommit=True) as conn:
                conn.execute(
                    "UPDATE identity.users SET status = 'pending_deletion', "
                    "deletion_scheduled_at = now() + interval '7 days' WHERE id = %s",
                    [user],
                )

    racing = DeletesWhileStoring()
    racing.objects.update(storage.objects)
    racing.data.update(storage.data)
    use_storage(racing)

    run_build(migrated_url, started["id"], user)

    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT status, error_code, archive_key FROM ops.data_exports WHERE id = %s",
            [started["id"]],
        ).fetchone()
        queued = conn.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs "
            "WHERE task_name = %s AND args->>'export_id' = %s",
            [jobs.EXPIRE_ARCHIVE, started["id"]],
        ).fetchone()
    assert row == ("failed", "account_deleted", None)
    assert queued == (0,)
    assert not [key for key in racing.objects if "/exports/" in key]


@pytest.mark.parametrize("restored", [False, True])
def test_rejected_archive_cleanup_is_retried_after_storage_failure(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str, restored: bool
) -> None:
    client = make_client()
    user = learner_id(client)
    started = request_export(client)

    class Interrupted(FakeStorage):
        attempts = 0

        async def put_file(self, key: str, path: Path, content_type: str) -> None:
            await super().put_file(key, path, content_type)
            with psycopg.connect(migrated_url, autocommit=True) as conn:
                conn.execute(
                    "UPDATE identity.users SET status = 'pending_deletion', "
                    "deletion_scheduled_at = now() + interval '7 days' WHERE id = %s",
                    [user],
                )

        async def delete(self, key: str) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("temporary storage failure")
            await super().delete(key)

    interrupted = Interrupted()
    use_storage(interrupted)
    with pytest.raises(RuntimeError, match="temporary storage failure"):
        run_build(migrated_url, started["id"], user)
    assert any("/exports/" in key for key in interrupted.objects)
    if restored:
        with psycopg.connect(migrated_url, autocommit=True) as conn:
            conn.execute(
                "UPDATE identity.users SET status = 'active', deletion_scheduled_at = NULL "
                "WHERE id = %s",
                [user],
            )
    run_build(migrated_url, started["id"], user, attempt=2)
    assert interrupted.attempts == 2
    assert not any("/exports/" in key for key in interrupted.objects)


def test_a_ready_export_is_announced(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str
) -> None:
    client = make_client()
    user = learner_id(client)
    started = request_export(client)
    with psycopg.connect(migrated_url, autocommit=True) as listener:
        listener.execute("LISTEN user_events")
        run_build(migrated_url, started["id"], user)
        run_build(migrated_url, started["id"], user)  # a repeated run builds nothing more
        notices = [json.loads(n.payload) for n in listener.notifies(timeout=1, stop_after=2)]
    assert notices == [{"u": user, "t": "export.ready", "r": started["id"]}]
