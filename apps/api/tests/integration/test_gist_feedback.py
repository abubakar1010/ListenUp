"""D4 responses through the restricted API role."""

import asyncio
import uuid
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.types.json import Jsonb

from listenup.platform.database import Database
from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import learner_id
from tests.integration.test_blind import (
    END,
    SENTENCES_3,
    START,
    attempt_id,
    media_for_session,
    play,
    start_attempt,
    start_session,
)
from tests.integration.test_blind import client as client
from tests.integration.test_blind import clock as clock
from tests.integration.test_blind import make_client as make_client
from tests.integration.test_blind import storage as storage
from tests.integration.test_gist_grades import insert as insert_grade
from tests.integration.test_key_points import insert as insert_points


def submitted(client, clock, migrated_url, entry):
    session = start_session(client, migrated_url, entry)
    attempt = attempt_id(start_attempt(client, session))
    play(client, clock, attempt, START, END)
    response = client.post(f"/api/v1/blind/attempts/{attempt}/gist", json={"text": SENTENCES_3})
    assert response.status_code == 201, response.text
    return session, attempt


@pytest.mark.parametrize("entry", ["blind", "both"])
def test_d4_grade_details_follow_transcript_gate(client, clock, migrated_url, entry):
    original = client.app.state.transcript_database
    privileged = Database(conninfo_to_url(migrated_url), 1)
    client.app.state.transcript_database = privileged
    try:
        session, attempt = submitted(client, clock, migrated_url, entry)
        media = media_for_session(migrated_url, session)
        with psycopg.connect(migrated_url) as conn:
            insert_points(conn, media, span="[10000,40000)")
            points = conn.execute(
                "SELECT id FROM grading.key_points WHERE media_object_id=%s", [media]
            ).fetchone()[0]
            conn.execute("DELETE FROM grading.gist_grades WHERE attempt_id=%s", [attempt])
            insert_grade(
                conn,
                SimpleNamespace(id=attempt, user_id=learner_id(client)),
                key_points_id=points,
                dimension_scores=Jsonb({"main_idea": 90, "key_details": 70, "accuracy": 80}),
                covered_points=["kp1", "kp3"],
            )
        response = client.get(f"/api/v1/gists/{attempt}/grade")
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        body = response.json()
        assert body["overall"] == 80 and body["level"] == "good"
        assert body["dimension_scores"] == {"main_idea": 90, "key_details": 70, "accuracy": 80}
        assert (body["captured_count"], body["total_count"]) == (2, 3)
        if entry == "both":
            assert set(body) == {
                "status",
                "overall",
                "level",
                "dimension_scores",
                "captured_count",
                "total_count",
            }
            assert "shade" not in response.text and "kp1" not in response.text

            async def advance():
                from listenup.modules.practice import service as practice

                database = Database(conninfo_to_url(migrated_url), 1)
                async with database.transaction(uuid.UUID(learner_id(client))) as db:
                    state = await practice.get_session(db, uuid.UUID(session))
                    await practice.complete_step(db, state, practice.Step.DICTATION)
                await database.dispose()

            asyncio.run(advance())
            body = client.get(f"/api/v1/gists/{attempt}/grade").json()
        assert body["feedback"] == "You caught the main idea. You missed shade."
        assert [p["captured"] for p in body["key_points"]] == [True, False, True]
        assert body["key_points"][1]["text"] == "Trees shade the pavement."
        assert body["gist"] == SENTENCES_3
    finally:
        client.app.state.transcript_database = original
        client.portal.call(privileged.dispose)


def test_pending_grade_and_unknown_attempt(client, clock, migrated_url):
    _, attempt = submitted(client, clock, migrated_url, "both")
    response = client.get(f"/api/v1/gists/{attempt}/grade")
    assert response.status_code == 200
    assert response.json() == {"status": "pending"}
    assert client.get(f"/api/v1/gists/{uuid.uuid4()}/grade").status_code == 404


def test_unsubmitted_and_unavailable_are_neutral(client, clock, migrated_url):
    session = start_session(client, migrated_url, "both")
    attempt = attempt_id(start_attempt(client, session))
    assert client.get(f"/api/v1/gists/{attempt}/grade").json() == {"status": "pending"}
    play(client, clock, attempt, START, END)
    client.post(f"/api/v1/blind/attempts/{attempt}/gist", json={"text": SENTENCES_3})
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "UPDATE grading.gist_grades SET status='unavailable' WHERE attempt_id=%s", [attempt]
        )
    assert client.get(f"/api/v1/gists/{attempt}/grade").json() == {"status": "pending"}


def test_other_learner_cannot_read_gist_grade(client, clock, migrated_url, make_client):
    _, attempt = submitted(client, clock, migrated_url, "blind")
    other = make_client()
    response = other.get(f"/api/v1/gists/{attempt}/grade")
    assert response.status_code == 404
    assert response.json()["code"] == "attempt_not_found"
