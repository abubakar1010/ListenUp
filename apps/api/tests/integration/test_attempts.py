"""Attempts at Blind and Dictation steps (migration 0008; FR-PL-4).

Runs the practice service as the API role, one transaction per action, with the
helpers of test_practice_sessions.py.
"""

import asyncio
import uuid

import psycopg
import pytest

from listenup.modules.practice import service
from listenup.modules.practice.service import Attempt, AttemptStatus, Entry, Step
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError
from tests.integration.conftest import conninfo_to_url
from tests.integration.test_practice_sessions import complete, start

# Fixtures shared with the session tests (pytest finds them by name in this module).
from tests.integration.test_practice_sessions import content as content
from tests.integration.test_practice_sessions import database as database
from tests.integration.test_practice_sessions import other_learner as other_learner


async def attempt_at(
    database: Database, learner: uuid.UUID, session_id: uuid.UUID, mode: Step
) -> Attempt:
    async with database.transaction(learner) as db:
        return await service.start_attempt(db, session_id, mode)


@pytest.mark.anyio
async def test_an_attempt_starts_on_the_open_step(
    database: Database, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.BOTH)

    attempt = await attempt_at(database, learner, practice.id, Step.BLIND)

    assert (attempt.mode, attempt.status, attempt.finished_at) == (
        Step.BLIND,
        AttemptStatus.ACTIVE,
        None,
    )
    async with database.transaction(learner) as db:
        assert await service.active_attempt(db, practice.id, Step.BLIND) == attempt


@pytest.mark.anyio
async def test_a_locked_step_has_no_attempts(
    database: Database, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.BOTH)

    with pytest.raises(ProblemError) as refused:
        await attempt_at(database, learner, practice.id, Step.DICTATION)

    assert refused.value.code == "step_locked"


@pytest.mark.anyio
async def test_only_one_attempt_is_live_at_a_time(
    database: Database, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.BLIND)
    first = await attempt_at(database, learner, practice.id, Step.BLIND)

    with pytest.raises(ProblemError) as refused:
        await attempt_at(database, learner, practice.id, Step.BLIND)

    assert refused.value.code == "attempt_active"
    assert refused.value.extensions["attempt_id"] == str(first.id)


@pytest.mark.anyio
async def test_a_voided_attempt_makes_room_for_a_new_one(
    database: Database, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.BLIND)
    first = await attempt_at(database, learner, practice.id, Step.BLIND)
    async with database.transaction(learner) as db:
        voided = await service.finish_attempt(db, first.id, AttemptStatus.VOIDED)

    second = await attempt_at(database, learner, practice.id, Step.BLIND)

    assert voided.status is AttemptStatus.VOIDED
    assert voided.finished_at is not None
    assert second.id != first.id


@pytest.mark.anyio
async def test_a_finished_attempt_cannot_end_again(
    database: Database, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.DICTATION)
    attempt = await attempt_at(database, learner, practice.id, Step.DICTATION)
    async with database.transaction(learner) as db:
        await service.finish_attempt(db, attempt.id, AttemptStatus.SUBMITTED)

    with pytest.raises(ProblemError) as refused:
        async with database.transaction(learner) as db:
            await service.finish_attempt(db, attempt.id, AttemptStatus.VOIDED)

    assert refused.value.code == "attempt_closed"


@pytest.mark.anyio
async def test_another_learners_attempt_is_not_found(
    database: Database, learner: uuid.UUID, other_learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.BLIND)
    attempt = await attempt_at(database, learner, practice.id, Step.BLIND)

    for action in ("get", "finish"):
        with pytest.raises(ProblemError) as refused:
            async with database.transaction(other_learner) as db:
                if action == "get":
                    await service.get_attempt(db, attempt.id)
                else:
                    await service.finish_attempt(db, attempt.id, AttemptStatus.VOIDED)
        assert refused.value.code == "attempt_not_found"


@pytest.mark.anyio
async def test_attempts_exist_only_for_blind_and_dictation(
    database: Database, learner: uuid.UUID, content: uuid.UUID
) -> None:
    practice = await start(database, learner, content, Entry.BLIND)
    await complete(database, learner, practice.id, Step.BLIND)

    with pytest.raises(ValueError):
        await attempt_at(database, learner, practice.id, Step.TRANSCRIPT)


def test_the_database_allows_one_live_attempt_and_keeps_it_with_its_learner(
    migrated_url: str, learner: uuid.UUID, content: uuid.UUID, other_learner: uuid.UUID
) -> None:
    async def make() -> uuid.UUID:
        db = Database(conninfo_to_url(migrated_url))
        try:
            return (await start(db, learner, content, Entry.BLIND)).id
        finally:
            await db.dispose()

    session_id = asyncio.run(make())
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        insert = (
            "INSERT INTO practice.attempts (id, session_id, user_id, mode) VALUES (%s, %s, %s, %s)"
        )
        conn.execute(insert, [uuid.uuid4(), session_id, learner, "blind"])
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(insert, [uuid.uuid4(), session_id, learner, "blind"])
        # Not a step this session has.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(insert, [uuid.uuid4(), session_id, learner, "dictation"])
        # Not the session's learner.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(
                "INSERT INTO practice.attempts (id, session_id, user_id, mode, status, "
                "finished_at) VALUES (%s, %s, %s, 'blind', 'voided', now())",
                [uuid.uuid4(), session_id, other_learner],
            )
        # A finished attempt records when it finished; a live one does not.
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO practice.attempts (id, session_id, user_id, mode, status) "
                "VALUES (%s, %s, %s, 'blind', 'voided')",
                [uuid.uuid4(), session_id, learner],
            )
