"""The practice service against PostgreSQL as the API role (issue #47).

Each action runs in its own transaction, as separate requests would, through the
same `Database` the API uses, connected as a role with only `listenup_api`'s rights.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from listenup.main import create_app
from listenup.modules.practice import service
from listenup.modules.practice.service import Entry, Passage, PracticeSession, Step
from listenup.platform.config import Settings
from listenup.platform.database import Database, DbSession, set_learner
from listenup.platform.errors import ProblemError

PASSAGE = Passage(0, 120_000)


def add_content(url: str, learner: uuid.UUID) -> uuid.UUID:
    media_id, content_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO content.media_objects (id, fingerprint, source, uploaded_by) "
            "VALUES (%s, %s, 'upload', %s)",
            [media_id, f"upload:{learner}:{media_id}", learner],
        )
        conn.execute(
            "INSERT INTO content.contents (id, user_id, media_object_id, title) "
            "VALUES (%s, %s, %s, 'Clip')",
            [content_id, learner, media_id],
        )
    return content_id


@pytest.fixture
def content(migrated_url: str, learner: uuid.UUID) -> uuid.UUID:
    return add_content(migrated_url, learner)


@pytest.fixture
def other_learner(migrated_url: str) -> Iterator[uuid.UUID]:
    user_id = uuid.uuid4()
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO identity.users (id, email) VALUES (%s, %s)",
            [user_id, f"{user_id}@example.com"],
        )
        yield user_id
        conn.execute("DELETE FROM identity.users WHERE id = %s", [user_id])


@pytest.fixture
async def database(api_role_url: str) -> AsyncIterator[Database]:
    database = Database(api_role_url, pool_size=2)
    yield database
    await database.dispose()


async def start(
    database: Database, learner: uuid.UUID, content: uuid.UUID, entry: Entry
) -> PracticeSession:
    async with database.transaction(learner) as db:
        return await service.start_session(db, learner, content, PASSAGE, entry)


async def load(database: Database, learner: uuid.UUID, session_id: uuid.UUID) -> PracticeSession:
    async with database.transaction(learner) as db:
        return await service.get_session(db, session_id)


async def complete(
    database: Database, learner: uuid.UUID, session_id: uuid.UUID, step: Step
) -> PracticeSession:
    async with database.transaction(learner) as db:
        practice = await service.require_step(db, session_id, step)
        return await service.complete_step(db, practice, step)


def stored_steps(url: str, session_id: uuid.UUID) -> list[tuple[object, ...]]:
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT step, position, status, opened_at IS NOT NULL, completed_at IS NOT NULL "
            "FROM practice.session_steps WHERE session_id = %s ORDER BY position",
            [session_id],
        ).fetchall()


def stored_session(url: str, session_id: uuid.UUID) -> tuple[object, ...]:
    with psycopg.connect(url) as conn:
        row = conn.execute(
            "SELECT entry, current_step, status, version, entry_locked_at IS NOT NULL, "
            "completed_at IS NOT NULL FROM practice.sessions WHERE id = %s",
            [session_id],
        ).fetchone()
    assert row is not None
    return row


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("entry", "path"),
    [
        (Entry.BLIND, ["blind", "transcript", "card", "shadow"]),
        (Entry.DICTATION, ["dictation", "transcript", "card", "shadow"]),
        (Entry.BOTH, ["blind", "dictation", "transcript", "card", "shadow"]),
    ],
)
async def test_a_session_walks_its_path_to_completion(
    database: Database,
    migrated_url: str,
    learner: uuid.UUID,
    content: uuid.UUID,
    entry: Entry,
    path: list[str],
) -> None:
    practice = await start(database, learner, content, entry)
    assert [(s[0], s[1], s[2]) for s in stored_steps(migrated_url, practice.id)] == [
        (step, position, "open" if position == 1 else "locked")
        for position, step in enumerate(path, start=1)
    ]
    assert stored_session(migrated_url, practice.id) == (
        entry.value,
        path[0],
        "active",
        0,
        False,
        False,
    )

    for index, step in enumerate(path):
        practice = await complete(database, learner, practice.id, Step(step))
        locked = path.index("transcript") <= index + 1
        done = index == len(path) - 1
        assert stored_session(migrated_url, practice.id) == (
            entry.value,
            "done" if done else path[index + 1],
            "completed" if done else "active",
            index + 1,
            locked,
            done,
        )

    assert stored_steps(migrated_url, practice.id) == [
        (step, position, "done", True, True) for position, step in enumerate(path, start=1)
    ]
    assert practice.current_step == "done"


@pytest.mark.anyio
async def test_skipping_card_and_shadow_completes_the_session(
    database: Database, migrated_url: str, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.DICTATION)
    practice = await complete(database, learner, practice.id, Step.DICTATION)
    practice = await complete(database, learner, practice.id, Step.TRANSCRIPT)

    async with database.transaction(learner) as db:
        with pytest.raises(ProblemError) as refused:
            await service.skip_step(db, practice, Step.CARD, confirmed=False)
    assert (refused.value.status, refused.value.code) == (422, "confirmation_required")

    for step in (Step.CARD, Step.SHADOW):
        async with database.transaction(learner) as db:
            practice = await service.skip_step(
                db, await service.get_session(db, practice.id), step, confirmed=True
            )

    assert stored_session(migrated_url, practice.id)[1:3] == ("done", "completed")
    assert [s[2] for s in stored_steps(migrated_url, practice.id)] == [
        "done",
        "done",
        "skipped",
        "skipped",
    ]


@pytest.mark.anyio
async def test_transcript_cannot_be_skipped(
    database: Database, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.BLIND)
    practice = await complete(database, learner, practice.id, Step.BLIND)

    async with database.transaction(learner) as db:
        with pytest.raises(ProblemError) as refused:
            await service.skip_step(db, practice, Step.TRANSCRIPT, confirmed=True)
    assert (refused.value.status, refused.value.code) == (409, "step_not_skippable")


@pytest.mark.anyio
async def test_a_locked_step_is_refused_naming_the_open_step(
    database: Database, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.BOTH)
    await complete(database, learner, practice.id, Step.BLIND)

    async with database.transaction(learner) as db:
        with pytest.raises(ProblemError) as refused:
            await service.require_step(db, practice.id, Step.TRANSCRIPT)
        reached = await service.require_reached(db, practice.id, Step.BLIND)

    assert (refused.value.status, refused.value.code) == (409, "step_locked")
    assert refused.value.extensions == {"step": "transcript", "open_step": "dictation"}
    assert reached.open_step is Step.DICTATION


@pytest.mark.anyio
async def test_changing_the_entry_rebuilds_the_unfinished_steps(
    database: Database, migrated_url: str, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.DICTATION)

    async with database.transaction(learner) as db:
        practice = await service.change_entry(db, practice, Entry.BOTH)

    assert [(s[0], s[1], s[2]) for s in stored_steps(migrated_url, practice.id)] == [
        ("blind", 1, "open"),
        ("dictation", 2, "locked"),
        ("transcript", 3, "locked"),
        ("card", 4, "locked"),
        ("shadow", 5, "locked"),
    ]
    assert stored_session(migrated_url, practice.id)[:2] == ("both", "blind")

    practice = await complete(database, learner, practice.id, Step.BLIND)
    async with database.transaction(learner) as db:
        practice = await service.change_entry(db, practice, Entry.BLIND)

    assert [(s[0], s[1], s[2]) for s in stored_steps(migrated_url, practice.id)] == [
        ("blind", 1, "done"),
        ("transcript", 2, "open"),
        ("card", 3, "locked"),
        ("shadow", 4, "locked"),
    ]
    assert stored_session(migrated_url, practice.id)[:2] == ("blind", "transcript")
    assert practice.entry_locked_at is not None


@pytest.mark.anyio
async def test_the_entry_is_locked_once_transcript_opens(
    database: Database, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.DICTATION)
    practice = await complete(database, learner, practice.id, Step.DICTATION)

    async with database.transaction(learner) as db:
        with pytest.raises(ProblemError) as refused:
            await service.change_entry(db, practice, Entry.BOTH)
    assert (refused.value.status, refused.value.code) == (409, "entry_locked")


@pytest.mark.anyio
async def test_a_stale_snapshot_is_refused(
    database: Database, learner: uuid.UUID, content: uuid.UUID
) -> None:
    stale = await start(database, learner, content, Entry.BOTH)
    async with database.transaction(learner) as db:
        await service.change_entry(db, stale, Entry.DICTATION)

    async with database.transaction(learner) as db:
        with pytest.raises(ProblemError) as refused:
            await service.change_entry(db, stale, Entry.BLIND)
    assert (refused.value.status, refused.value.code) == (409, "session_changed")
    assert (await load(database, learner, stale.id)).entry is Entry.DICTATION


@pytest.mark.anyio
async def test_concurrent_requests_on_one_session_are_caught_by_the_version(
    database: Database, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.BLIND)
    both_read = asyncio.Barrier(2)
    first_committed = asyncio.Event()

    async def first() -> None:
        async with database.transaction(learner) as db:
            current = await service.require_step(db, practice.id, Step.BLIND)
            await both_read.wait()
            await service.complete_step(db, current, Step.BLIND)
        first_committed.set()

    async def second() -> None:
        async with database.transaction(learner) as db:
            current = await service.require_step(db, practice.id, Step.BLIND)
            await both_read.wait()
            await first_committed.wait()
            await service.change_entry(db, current, Entry.DICTATION)

    results = await asyncio.gather(first(), second(), return_exceptions=True)

    assert results[0] is None
    assert isinstance(results[1], ProblemError)
    assert results[1].code == "session_changed"
    after = await load(database, learner, practice.id)
    assert (after.entry, after.open_step, after.version) == (Entry.BLIND, Step.TRANSCRIPT, 1)


@pytest.mark.anyio
async def test_another_learners_session_is_not_found(
    database: Database, learner: uuid.UUID, other_learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.BLIND)

    async with database.transaction(other_learner) as db:
        with pytest.raises(ProblemError) as refused:
            await service.require_step(db, practice.id, Step.BLIND)
    assert (refused.value.status, refused.value.code) == (404, "session_not_found")


@pytest.mark.anyio
async def test_a_session_needs_the_learners_own_content(
    database: Database, learner: uuid.UUID, other_learner: uuid.UUID, content: uuid.UUID
) -> None:
    async with database.transaction(other_learner) as db:
        with pytest.raises(ProblemError) as refused:
            await service.start_session(db, other_learner, content, PASSAGE, Entry.BLIND)
    assert (refused.value.status, refused.value.code) == (404, "content_not_found")


# Through the API: a mode endpoint gated by require_step (acceptance criterion of #47).


def build_app(database_url: str, learner: uuid.UUID) -> FastAPI:
    app = create_app(Settings(database_url=database_url, log_json=False))
    router = APIRouter()

    @router.get("/test/sessions/{session_id}/transcript")
    async def transcript(session_id: uuid.UUID, db: DbSession) -> dict[str, str]:
        await set_learner(db, learner)
        await service.require_step(db, session_id, Step.TRANSCRIPT)
        return {"text": "visible only from the Transcript step on"}

    @router.get("/test/sessions/{session_id}/force-open/{step}")
    async def force_open(session_id: uuid.UUID, step: str, db: DbSession) -> None:
        # A bug that skips the service: the trigger must still refuse.
        await set_learner(db, learner)
        await db.execute(
            text(
                "UPDATE practice.session_steps SET status = 'open' "
                "WHERE session_id = :id AND step = :step"
            ),
            {"id": session_id, "step": step},
        )

    app.include_router(router)
    return app


@pytest.fixture
def client(api_role_url: str, learner: uuid.UUID) -> Iterator[TestClient]:
    with TestClient(build_app(api_role_url, learner), raise_server_exceptions=False) as c:
        yield c


@pytest.mark.anyio
async def test_the_transcript_endpoint_is_refused_while_dictation_is_open(
    database: Database, client: TestClient, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.BOTH)
    await complete(database, learner, practice.id, Step.BLIND)

    response = client.get(f"/test/sessions/{practice.id}/transcript")

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert (body["code"], body["open_step"], body["step"]) == (
        "step_locked",
        "dictation",
        "transcript",
    )

    await complete(database, learner, practice.id, Step.DICTATION)
    assert client.get(f"/test/sessions/{practice.id}/transcript").status_code == 200


@pytest.mark.anyio
async def test_a_direct_update_that_opens_a_step_early_returns_step_locked(
    database: Database, client: TestClient, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.DICTATION)

    response = client.get(f"/test/sessions/{practice.id}/force-open/card")

    assert response.status_code == 409
    assert response.json()["code"] == "step_locked"
