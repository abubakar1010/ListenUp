"""Submitting Dictation (#54; FR-DI-5, FR-TX-5, NFR-USE-2, ADR 0021, ADR 0041).

The app connects as a role with only the API's rights. Scoring itself runs in a job
(`test_dictation_scoring.py`); here the submission is stored, the attempt is submitted
and the step is complete whatever the state of the transcript.
"""

from collections.abc import Iterator

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.integration.intake_helpers import (
    ClientFactory,
    FakeStorage,
    client_factory,
    learner_id,
)
from tests.integration.test_dictation_api import attempt_of, save
from tests.integration.test_sessions_api import add_clip, start


@pytest.fixture
def make_client(api_role_url: str) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, FakeStorage())


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


@pytest.fixture
def session(client: TestClient, migrated_url: str) -> dict[str, object]:
    return start(client, add_clip(migrated_url, learner_id(client)), entry="dictation")


def submit(
    client: TestClient,
    attempt_id: object,
    session: dict[str, object],
    text: str = "Cities plant street trees to cool the air",
    *,
    version: object = None,
    replays: int = 3,
    key: str | None = "key-1",
) -> httpx.Response:
    return client.post(
        f"/api/v1/dictation/attempts/{attempt_id}/submit",
        json={
            "text": text,
            "version": session["version"] if version is None else version,
            "replay_count": replays,
        },
        headers={"Idempotency-Key": key} if key else {},
    )


def row_of(migrated_url: str, attempt_id: object) -> tuple[object, ...]:
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT d.submitted_text, d.scoring_status, d.diff, d.accuracy, a.status "
            "FROM practice.dictation_attempts d JOIN practice.attempts a ON a.id = d.attempt_id "
            "WHERE d.attempt_id = %s",
            [attempt_id],
        ).fetchone()
    assert row is not None
    return row


def test_submit_stores_the_text_and_completes_the_step_without_waiting_for_scoring(
    client: TestClient, session: dict[str, object], migrated_url: str
) -> None:
    attempt = attempt_of(client, session)

    response = submit(client, attempt["id"], session)

    assert response.status_code == 202, response.text
    assert response.json() == {
        "attempt_id": attempt["id"],
        "status": "submitted",
        "scoring_status": "waiting_transcript",
    }
    assert response.headers["Cache-Control"] == "private, no-store"
    assert row_of(migrated_url, attempt["id"]) == (
        "Cities plant street trees to cool the air",
        "waiting_transcript",
        None,
        None,
        "submitted",
    )
    updated = client.get(f"/api/v1/sessions/{session['id']}").json()
    assert updated["open_step"] == "transcript"
    assert updated["version"] == session["version"] + 1  # type: ignore[operator]


def test_submit_records_the_replay_count(
    client: TestClient, session: dict[str, object], migrated_url: str
) -> None:
    attempt = attempt_of(client, session)

    submit(client, attempt["id"], session, replays=7)

    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT properties FROM ops.analytics_events WHERE event_type = 'dictation_replays' "
            "AND subject_id = %s",
            [attempt["id"]],
        ).fetchone()
    assert row is not None
    assert row[0] == {"replay_count": 7}


def test_the_text_sent_wins_over_an_older_saved_draft(
    client: TestClient, session: dict[str, object], migrated_url: str
) -> None:
    attempt = attempt_of(client, session)
    save(client, attempt["id"], "an older draft", 0)

    submit(client, attempt["id"], session, "the final text")

    assert row_of(migrated_url, attempt["id"])[0] == "the final text"


def test_the_same_key_replays_the_first_answer_and_stores_once(
    client: TestClient, session: dict[str, object], migrated_url: str
) -> None:
    attempt = attempt_of(client, session)
    first = submit(client, attempt["id"], session)

    again = submit(client, attempt["id"], session)

    assert again.status_code == 202
    assert again.json() == first.json()
    assert again.headers["Idempotent-Replayed"] == "true"
    assert row_of(migrated_url, attempt["id"])[0] == "Cities plant street trees to cool the air"


def test_a_resubmit_with_a_new_key_finds_the_step_complete(
    client: TestClient, session: dict[str, object]
) -> None:
    attempt = attempt_of(client, session)
    submit(client, attempt["id"], session)

    again = submit(client, attempt["id"], session, "different", key="key-2")

    assert again.status_code == 409
    body = again.json()
    assert (body["code"], body["open_step"]) == ("step_locked", "transcript")


def test_an_empty_text_is_refused_and_nothing_changes(
    client: TestClient, session: dict[str, object], migrated_url: str
) -> None:
    attempt = attempt_of(client, session)

    response = submit(client, attempt["id"], session, "  \n ")

    assert response.status_code == 422
    assert response.json()["code"] == "empty_submission"
    assert row_of(migrated_url, attempt["id"])[1:] == (None, None, None, "active")


def test_a_text_over_the_limit_is_refused(client: TestClient, session: dict[str, object]) -> None:
    attempt = attempt_of(client, session)

    response = submit(client, attempt["id"], session, "a " * 10_001)

    assert response.status_code == 422
    body = response.json()
    assert (body["code"], body["max_chars"]) == ("submission_too_long", 20_000)


def test_a_stale_session_version_is_refused_and_nothing_changes(
    client: TestClient, session: dict[str, object], migrated_url: str
) -> None:
    attempt = attempt_of(client, session)

    response = submit(client, attempt["id"], session, version=session["version"] + 1)  # type: ignore[operator]

    assert response.status_code == 409
    assert response.json()["code"] == "session_changed"
    assert row_of(migrated_url, attempt["id"])[1:] == (None, None, None, "active")


def test_another_learners_attempt_is_not_found(
    make_client: ClientFactory, client: TestClient, session: dict[str, object]
) -> None:
    attempt = attempt_of(client, session)
    other = make_client()

    response = submit(other, attempt["id"], session)

    assert response.status_code == 404
    assert response.json()["code"] == "attempt_not_found"


def test_a_voided_attempt_is_closed(
    client: TestClient, session: dict[str, object], migrated_url: str
) -> None:
    attempt = attempt_of(client, session)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE practice.attempts SET status = 'voided', finished_at = now() WHERE id = %s",
            [attempt["id"]],
        )

    response = submit(client, attempt["id"], session)

    assert response.status_code == 409
    assert response.json()["code"] == "attempt_closed"
