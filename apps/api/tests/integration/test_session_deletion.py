"""AT-20, FR-SH-17, NFR-SEC-5 (#90): deleting a session removes its recordings and data."""

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


def delete(client: TestClient, session: object, confirm: bool = True):
    return client.request("DELETE", f"/api/v1/sessions/{session}", json={"confirm": confirm})


def run_delete(url: str, request: str):
    async def run():
        from listenup.modules.library import jobs  # noqa: F401

        database = Database(conninfo_to_url(url))
        try:
            return await run_handler(
                "library.delete_session", JobDeps(database, None, 1), request_id=request
            )
        finally:
            await database.dispose()

    return asyncio.run(run())


def one(url: str, sql: str, *params: object):
    with psycopg.connect(url) as db:
        return db.execute(sql, params).fetchone()


def test_delete_session_is_confirmed_owned_and_queued(make_client, migrated_url):
    a, b = make_client(), make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    sid = world.sessions["shadow"]
    refused = delete(b, sid)
    assert (refused.status_code, refused.json()["code"]) == (404, "session_not_found")
    assert delete(a, sid, False).status_code == 422
    response = delete(a, sid)
    assert response.status_code == 202, response.text
    request = response.json()["request_id"]
    assert delete(a, sid).json()["request_id"] == request
    gone = a.get(f"/api/v1/sessions/{sid}")
    assert (gone.status_code, gone.json()["code"]) == (404, "session_not_found")
    assert a.get(f"/api/v1/sessions/{sid}/shadow/rounds").status_code == 404
    round_url = f"/api/v1/shadow/rounds/{world.shadow_round_id}/recording"
    for method in ("GET", "DELETE"):
        hidden = a.request(method, round_url, follow_redirects=False)
        assert (hidden.status_code, hidden.json()["code"]) == (404, "round_not_found")
    listed = [item["id"] for item in a.get("/api/v1/sessions").json()["items"]]
    assert str(sid) not in listed
    assert str(world.sessions["card"]) in listed
    # The clip and its other sessions stay.
    assert a.get(f"/api/v1/contents/{world.content_id}").status_code == 200
    assert one(
        migrated_url,
        "SELECT scope,target_id,status FROM ops.deletion_requests WHERE id=%s",
        request,
    ) == ("session", sid, "pending")
    assert one(
        migrated_url,
        "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE task_name="
        "'library.delete_session' AND args->>'request_id'=%s",
        request,
    ) == (1,)


def session_rows(url: str, session: uuid.UUID) -> dict[str, int]:
    """Rows that belong to one session, in every table with a `session_id`."""
    with psycopg.connect(url) as db:
        tables = [
            r[0]
            for r in db.execute(
                "SELECT table_schema||'.'||table_name FROM information_schema.columns "
                "WHERE column_name='session_id' "
                "AND table_schema IN ('practice','grading','content')"
                " AND table_name NOT IN (SELECT table_name FROM information_schema.views)"
            )
        ]
        counts = {
            table: db.execute(
                f"SELECT count(*) FROM {table} WHERE session_id=%s", [session]
            ).fetchone()[0]
            for table in tables
        }
        counts["practice.sessions"] = db.execute(
            "SELECT count(*) FROM practice.sessions WHERE id=%s", [session]
        ).fetchone()[0]
    return counts


def test_deleting_a_session_removes_its_recordings_from_storage_then_rows(
    make_client, migrated_url, storage, monkeypatch
):
    """AT-20: the session's recordings leave storage before any of its rows go, with no
    row lock held during the storage calls; the clip and every other session stay."""
    a, b = make_client(), make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    other = seed_learner_data(migrated_url, uuid.UUID(learner_id(b)))
    sid, user = world.sessions["shadow"], world.user_id
    recording = f"users/{user}/shadow/{sid}/round-1-{world.shadow_round_id}.webm"
    pending = f"users/{user}/shadow/{sid}/round-2-{uuid.uuid4()}.m4a"  # never completed
    keep = [
        f"users/{user}/shadow/{world.sessions['done']}/round-1-{uuid.uuid4()}.webm",
        f"users/{user}/media/{world.media_id}/playback.mp4",
        f"users/{other.user_id}/shadow/{other.sessions['shadow']}/round-1-"
        f"{other.shadow_round_id}.webm",
    ]
    for key in [recording, pending, *keep]:
        storage.arrive(key, 10)
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "INSERT INTO grading.gist_grades(attempt_id,user_id) VALUES (%s,%s)",
            [world.blind_attempt_id, user],
        )
    before = session_rows(migrated_url, sid)
    assert before["practice.shadow_rounds"] > 0 and before["practice.shadow_segments"] > 0
    assert before["practice.session_steps"] > 0
    kept_sessions = {name: session_rows(migrated_url, s) for name, s in world.sessions.items()}
    del kept_sessions["shadow"]
    others = {name: session_rows(migrated_url, s) for name, s in other.sessions.items()}

    original, calls = storage.delete_prefix, []

    async def probe(prefix):
        with psycopg.connect(migrated_url, autocommit=True) as db:
            db.execute("SELECT 1 FROM practice.sessions WHERE id=%s FOR UPDATE NOWAIT", [sid])
            db.execute(
                "SELECT 1 FROM practice.shadow_rounds WHERE session_id=%s FOR UPDATE NOWAIT",
                [sid],
            )
        calls.append((prefix, session_rows(migrated_url, sid)["practice.sessions"]))
        return await original(prefix)

    monkeypatch.setattr(storage, "delete_prefix", probe)
    response = delete(a, sid)
    assert response.status_code == 202, response.text
    request = response.json()["request_id"]
    report = run_delete(migrated_url, request)

    assert f"users/{user}/shadow/{sid}/" in [prefix for prefix, _ in calls]
    assert all(rows == 1 for _, rows in calls)  # storage first, rows second
    assert recording not in storage.objects and pending not in storage.objects
    assert set(keep) <= storage.objects.keys()
    assert report["objects_removed"] == 2
    assert all(count == 0 for count in session_rows(migrated_url, sid).values())
    for name, rows in kept_sessions.items():
        assert session_rows(migrated_url, world.sessions[name]) == rows, name
    for name, rows in others.items():
        assert session_rows(migrated_url, other.sessions[name]) == rows, name
    assert a.get(f"/api/v1/contents/{world.content_id}").status_code == 200
    assert one(migrated_url, "SELECT status FROM ops.deletion_requests WHERE id=%s", request) == (
        "completed",
    )
    run_delete(migrated_url, request)  # repeating is harmless


def queued(url: str, task: str, request: str) -> int:
    return one(
        url,
        "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE task_name=%s "
        "AND args->>'request_id'=%s AND status='todo'",
        task,
        request,
    )[0]


def test_reconciler_requeues_a_completed_session_manifest_for_late_uploads(
    make_client, migrated_url, storage
):
    """A signed PUT issued before the delete can land afterwards: the kept manifest
    sends the job back, and it removes the late object (ADR 0085, 0092)."""
    from listenup.modules.library import jobs

    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    sid = world.sessions["shadow"]
    request = delete(a, sid).json()["request_id"]
    run_delete(migrated_url, request)
    late = f"users/{world.user_id}/shadow/{sid}/round-2-{uuid.uuid4()}.webm"
    storage.arrive(late, 10)
    with psycopg.connect(migrated_url) as db:
        db.execute("UPDATE ops.deletion_requests SET due_at=now() WHERE id=%s", [request])
        db.execute(
            "DELETE FROM procrastinate.procrastinate_jobs WHERE args->>'request_id'=%s", [request]
        )

    async def reconcile():
        database = Database(conninfo_to_url(migrated_url))
        try:
            await jobs.reconcile_content_deletions(JobDeps(database, None, 1))
        finally:
            await database.dispose()

    asyncio.run(reconcile())
    assert queued(migrated_url, "library.delete_session", request) == 1
    assert queued(migrated_url, "library.delete_content", request) == 0
    run_delete(migrated_url, request)
    assert late not in storage.objects


@pytest.mark.parametrize("stage", ["blind", "dictation", "transcript", "card"])
def test_deleting_any_session_removes_its_rows_snippets_and_cached_replies(
    make_client, migrated_url, storage, stage
):
    """Attempts, grades, marks, cards and their snippets go with the session; the
    cached replies that name them are scrubbed; the learner's other data stays."""
    from psycopg.types.json import Jsonb

    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    sid, user = world.sessions[stage], world.user_id
    snippet = f"users/{user}/cards/{world.card_id}/snippet.m4a"
    storage.arrive(snippet, 10)
    attempt = {"blind": world.blind_attempt_id, "dictation": world.dictation_attempt_id}
    with psycopg.connect(migrated_url) as db:
        if stage == "blind":
            db.execute(
                "INSERT INTO grading.gist_grades(attempt_id,user_id) VALUES (%s,%s)",
                [world.blind_attempt_id, user],
            )
        for key, value in [
            ("session", {"session_id": str(sid)}),
            ("attempt", {"attempt_id": str(attempt.get(stage, uuid.uuid4()))}),
            ("card", {"card_id": str(world.card_id), "written_form": "Deleted phrase"}),
            ("other", {"session_id": str(world.sessions["done"])}),
        ]:
            db.execute(
                "INSERT INTO ops.idempotency_keys(user_id,key,request_hash,status_code,response) "
                "VALUES (%s,%s,%s,200,%s)",
                [user, key, b"0" * 32, Jsonb(value)],
            )
    before = session_rows(migrated_url, sid)
    request = delete(a, sid).json()["request_id"]
    run_delete(migrated_url, request)

    assert all(count == 0 for count in session_rows(migrated_url, sid).values()), before
    assert (snippet in storage.objects) is (stage != "card")
    with psycopg.connect(migrated_url) as db:
        kept = {
            row[0]
            for row in db.execute("SELECT key FROM ops.idempotency_keys WHERE user_id=%s", [user])
        }
        grades = db.execute(
            "SELECT count(*) FROM grading.gist_grades WHERE user_id=%s", [user]
        ).fetchone()[0]
        cleanup = db.execute(
            "SELECT count(*) FROM practice.card_snippet_cleanup WHERE user_id=%s", [user]
        ).fetchone()[0]
    expected = {"other"} | ({"attempt"} if stage not in attempt else set())
    expected |= {"card"} if stage != "card" else set()
    assert kept == expected
    assert grades == 0 and cleanup == 0
    assert a.get(f"/api/v1/sessions/{world.sessions['done']}").status_code == 200


def test_a_deleting_session_disappears_from_cards_marks_and_card_audio_writers(
    make_client, migrated_url
):
    """The barrier hides the session's cards and marks before the job runs, and a card
    audio writer no longer finds the card, so it registers no new storage write."""
    from listenup.modules.cards import repository as cards

    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    cards_before = [c["id"] for c in a.get("/api/v1/cards").json()["cards"]]
    marks_before = [m["id"] for m in a.get("/api/v1/marks").json()["marks"]]
    assert str(world.card_id) in cards_before and str(world.mark_id) in marks_before
    for stage in ("card", "transcript"):
        assert delete(a, world.sessions[stage]).status_code == 202
    assert str(world.card_id) not in [c["id"] for c in a.get("/api/v1/cards").json()["cards"]]
    assert str(world.mark_id) not in [m["id"] for m in a.get("/api/v1/marks").json()["marks"]]

    async def writer_sees_card():
        database = Database(conninfo_to_url(migrated_url))
        try:
            async with database.transaction(world.user_id) as db:
                return await cards.audio_row(db, world.card_id, world.user_id, lock=True)
        finally:
            await database.dispose()

    assert asyncio.run(writer_sees_card()) is None


def test_a_session_of_a_clip_being_deleted_or_already_deleted_is_not_found(
    make_client, migrated_url, storage
):
    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    request = delete(a, world.sessions["done"]).json()["request_id"]
    run_delete(migrated_url, request)
    again = delete(a, world.sessions["done"])
    assert (again.status_code, again.json()["code"]) == (404, "session_not_found")
    assert a.request("DELETE", f"/api/v1/contents/{world.content_id}", json={"confirm": True})
    gone = delete(a, world.sessions["blind"])
    assert (gone.status_code, gone.json()["code"]) == (404, "session_not_found")
    assert one(
        migrated_url,
        "SELECT count(*) FROM ops.deletion_requests WHERE scope='session' AND target_id=%s",
        world.sessions["blind"],
    ) == (0,)


def test_retry_after_a_storage_failure_keeps_rows_and_manifest(
    make_client, migrated_url, storage, monkeypatch
):
    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    sid = world.sessions["shadow"]
    key = f"users/{world.user_id}/shadow/{sid}/round-1-{world.shadow_round_id}.webm"
    storage.arrive(key, 10)
    request = delete(a, sid).json()["request_id"]
    original = storage.delete_prefix

    async def unavailable(prefix):
        raise OSError("storage unavailable")

    monkeypatch.setattr(storage, "delete_prefix", unavailable)
    with pytest.raises(OSError):
        run_delete(migrated_url, request)
    assert session_rows(migrated_url, sid)["practice.shadow_rounds"] == 3
    assert key in storage.objects
    status, prefixes = one(
        migrated_url,
        "SELECT status,storage_prefixes FROM ops.deletion_requests WHERE id=%s",
        request,
    )
    assert status == "pending" and f"users/{world.user_id}/shadow/{sid}/" in prefixes
    monkeypatch.setattr(storage, "delete_prefix", original)
    run_delete(migrated_url, request)
    assert key not in storage.objects
    assert session_rows(migrated_url, sid)["practice.sessions"] == 0


def test_a_registered_card_writer_defers_the_session_cleanup(make_client, migrated_url, storage):
    from listenup.platform.jobs import Reschedule

    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    sid, writer = world.sessions["card"], uuid.uuid4()
    snippet = f"users/{world.user_id}/cards/{world.card_id}/snippet.m4a"
    storage.arrive(snippet, 10)
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "INSERT INTO practice.card_snippet_writes(id,card_id,user_id,owner) "
            "VALUES (%s,%s,%s,'test:1')",
            [writer, world.card_id, world.user_id],
        )
    request = delete(a, sid).json()["request_id"]
    with pytest.raises(Reschedule):
        run_delete(migrated_url, request)
    assert snippet in storage.objects
    assert session_rows(migrated_url, sid)["practice.cards"] == 1
    with psycopg.connect(migrated_url) as db:
        db.execute("DELETE FROM practice.card_snippet_writes WHERE id=%s", [writer])
    run_delete(migrated_url, request)
    assert snippet not in storage.objects
    assert session_rows(migrated_url, sid)["practice.cards"] == 0


def test_an_exhausted_session_deletion_is_marked_failed(make_client, migrated_url):
    from listenup.modules.library import jobs

    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    request = delete(a, world.sessions["shadow"]).json()["request_id"]

    async def give_up():
        database = Database(conninfo_to_url(migrated_url))
        try:
            await jobs.give_up_session(JobDeps(database, None, 1), request)
            await jobs.give_up_session(JobDeps(database, None, 1), str(uuid.uuid4()))
        finally:
            await database.dispose()

    asyncio.run(give_up())
    assert one(migrated_url, "SELECT status FROM ops.deletion_requests WHERE id=%s", request) == (
        "failed",
    )
    assert run_delete(migrated_url, str(uuid.uuid4())) is None


def test_a_cleared_barrier_is_restored_and_the_deletion_still_finishes(
    make_client, migrated_url, storage
):
    """After a schema rollback and upgrade the barrier is gone, but the request is
    still open: the job hides the session again and deletes it (ADR 0092)."""
    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    sid = world.sessions["done"]
    request = delete(a, sid).json()["request_id"]
    with psycopg.connect(migrated_url) as db:
        db.execute("UPDATE practice.sessions SET deleting_at=NULL WHERE id=%s", [sid])
    assert a.get(f"/api/v1/sessions/{sid}").status_code == 200
    run_delete(migrated_url, request)
    assert session_rows(migrated_url, sid)["practice.sessions"] == 0


def test_routes_by_attempt_or_card_id_treat_a_deleting_session_as_gone(
    make_client, migrated_url, storage
):
    """Review finding 1 (#263): the barrier also covers routes keyed by an attempt or a
    card id, so nothing of a session being deleted is read, changed or sent to a
    provider; and its unfinished Blind listen no longer blocks whole-clip playback."""
    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    blocked = a.get(f"/api/v1/media/{world.media_id}", follow_redirects=False)
    assert (blocked.status_code, blocked.json()["code"]) == (409, "blind_in_progress")
    for stage in ("blind", "dictation", "card"):
        assert delete(a, world.sessions[stage]).status_code == 202
    attempt, blind, card = world.dictation_attempt_id, world.blind_attempt_id, world.card_id
    for method, path, code in (
        ("GET", f"/api/v1/dictation/attempts/{attempt}", "attempt_not_found"),
        ("GET", f"/api/v1/dictation/attempts/{attempt}/marks", "attempt_not_found"),
        ("POST", f"/api/v1/grades/{blind}/retry", "attempt_not_found"),
        ("DELETE", f"/api/v1/cards/{card}", "card_not_found"),
        ("GET", f"/api/v1/cards/{card}/reviews", "card_not_found"),
    ):
        response = a.request(method, path)
        assert (response.status_code, response.json()["code"]) == (404, code), path
    assert one(
        migrated_url,
        "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE task_name LIKE 'grading.%%' "
        "AND args->>'attempt_id'=%s",
        str(blind),
    ) == (0,)
    assert session_rows(migrated_url, world.sessions["card"])["practice.cards"] == 1
    playback = a.get(f"/api/v1/media/{world.media_id}", follow_redirects=False)
    assert playback.status_code == 307, playback.text
