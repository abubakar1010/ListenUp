"""Ready grade integrity, ownership and lifecycle (#68, Database Design 6)."""

import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from listenup.modules.practice import service as practice
from tests.integration.test_key_point_jobs import clip as clip
from tests.integration.test_key_point_jobs import database as database
from tests.integration.test_key_point_jobs import start


@pytest.fixture
async def attempt(database, learner, clip):
    session = await start(database, learner, clip[1])
    async with database.transaction(learner) as db:
        return await practice.start_attempt(db, session.id, practice.Step.BLIND)


def insert(conn, attempt, **changes):
    values = dict(
        attempt_id=attempt.id,
        user_id=attempt.user_id,
        status="ready",
        overall=80,
        level="good",
        feedback="You caught the main idea. You missed shade.",
        rubric_version="v2",
        provider_info=Jsonb(
            {"provider": "fake", "model": "fake-text", "version": "1", "prompt_version": "v2"}
        ),
    )
    values.update(changes)
    from psycopg import sql

    conn.execute(
        sql.SQL("INSERT INTO grading.gist_grades ({}) VALUES ({})").format(
            sql.SQL(",").join(map(sql.Identifier, values)),
            sql.SQL(",").join(sql.Placeholder() for _ in values),
        ),
        list(values.values()),
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "field", ["overall", "level", "feedback", "rubric_version", "provider_info"]
)
async def test_ready_grade_requires_score_level_feedback(migrated_url, attempt, field):
    with psycopg.connect(migrated_url) as conn, pytest.raises(psycopg.errors.CheckViolation):
        insert(conn, attempt, **{field: None})


@pytest.mark.anyio
@pytest.mark.parametrize(
    "changes",
    [
        {"overall": -1},
        {"overall": 101},
        {"level": "amazing"},
        {"feedback": ""},
        {"rubric_version": ""},
        {"provider_info": Jsonb({})},
    ],
)
async def test_database_rejects_invalid_ready_values(migrated_url, attempt, changes):
    with psycopg.connect(migrated_url) as conn, pytest.raises(psycopg.errors.CheckViolation):
        insert(conn, attempt, **changes)


@pytest.mark.anyio
async def test_grade_ownership_and_missing_scope_fail_closed(migrated_url, api_role_url, attempt):
    with psycopg.connect(migrated_url) as conn:
        insert(conn, attempt)
    with psycopg.connect(api_role_url) as conn:
        assert conn.execute("SELECT * FROM grading.gist_grades").fetchall() == []
        conn.execute("SELECT set_config('app.user_id', %s, true)", [str(uuid.uuid4())])
        assert conn.execute("SELECT * FROM grading.gist_grades").fetchall() == []
        conn.execute("SELECT set_config('app.user_id', %s, true)", [str(attempt.user_id)])
        assert conn.execute("SELECT overall FROM grading.gist_grades").fetchall() == [(80,)]


@pytest.mark.anyio
async def test_grade_rejects_mismatched_owner_and_cascades(migrated_url, learner, attempt):
    with psycopg.connect(migrated_url) as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
            insert(conn, attempt, user_id=uuid.uuid4())
        insert(conn, attempt)
        conn.execute("DELETE FROM practice.attempts WHERE id=%s", [attempt.id])
        assert (
            conn.execute(
                "SELECT * FROM grading.gist_grades WHERE attempt_id=%s", [attempt.id]
            ).fetchall()
            == []
        )


@pytest.mark.anyio
async def test_pending_grade_can_be_incomplete(migrated_url, attempt):
    with psycopg.connect(migrated_url) as conn:
        insert(
            conn,
            attempt,
            status="pending",
            overall=None,
            level=None,
            feedback=None,
            rubric_version=None,
            provider_info=None,
        )
        assert conn.execute(
            "SELECT status FROM grading.gist_grades WHERE attempt_id=%s", [attempt.id]
        ).fetchone() == ("pending",)
