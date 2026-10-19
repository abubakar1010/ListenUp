"""Reading a Dictation attempt and its score (#54; FR-DI-3, FR-DI-5, FR-TX-5, AT-3).

The reference text is in `result.items` after scoring and in no other response, before
or after (FR-DI-3). The score is made by the job, here run directly after the submit.
"""

import asyncio
import json
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.modules.dictation import jobs
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps
from tests.integration.conftest import conninfo_to_url
from tests.integration.dictation_helpers import media_of, seed_transcript
from tests.integration.intake_helpers import (
    ClientFactory,
    FakeStorage,
    client_factory,
    learner_id,
)
from tests.integration.test_dictation_api import attempt_of, open_attempt, save
from tests.integration.test_dictation_scoring import TYPED
from tests.integration.test_dictation_submit import submit
from tests.integration.test_sessions_api import add_clip, start

# Words only the reference has: a response that holds one of them leaks the transcript.
SECRET_WORDS = ("cities", "street", "trees", "summer")
HEARD = "i heard a man talking about the weather"

EXPECTED_ITEMS = [
    {"index": 0, "status": "correct", "word": "Cities", "typed": "Cities"},
    {"index": 1, "status": "correct", "word": "plant", "typed": "plant"},
    {"index": 2, "status": "spelling_slip", "word": "street", "typed": "streat"},
    {"index": 3, "status": "correct", "word": "trees", "typed": "trees"},
    {"index": 4, "status": "missing", "word": "to", "typed": ""},
    {"index": 5, "status": "correct", "word": "cool", "typed": "cool"},
    {"index": 6, "status": "correct", "word": "the", "typed": "the"},
    {"index": 7, "status": "correct", "word": "air", "typed": "air"},
    {"index": 8, "status": "correct", "word": "in", "typed": "in"},
    {"index": None, "status": "extra", "word": "", "typed": "quickly"},
    {"index": 9, "status": "correct", "word": "summer.", "typed": "summer"},
]


@pytest.fixture
def make_client(api_role_url: str) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, FakeStorage())


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


@pytest.fixture
def clip(client: TestClient, migrated_url: str) -> str:
    # The default title shares words with the reference; a title is not a transcript leak.
    content = add_clip(migrated_url, learner_id(client))
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("UPDATE content.contents SET title = 'A talk' WHERE id = %s", [content])
    return content


@pytest.fixture
def session(client: TestClient, clip: str) -> dict[str, object]:
    return start(client, clip, entry="dictation")


def read(client: TestClient, attempt_id: object) -> dict[str, object]:
    response = client.get(f"/api/v1/dictation/attempts/{attempt_id}")
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def run_scoring(migrated_url: str, client: TestClient, attempt_id: object) -> None:
    async def run() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=1)
        try:
            await jobs.score_attempt(
                JobDeps(database, None, 1), str(attempt_id), learner_id(client)
            )
        finally:
            await database.dispose()

    asyncio.run(run())


def test_an_active_attempt_has_no_score_yet(client: TestClient, session: dict[str, object]) -> None:
    attempt = attempt_of(client, session)

    body = read(client, attempt["id"])

    assert body == {
        "id": attempt["id"],
        "session_id": session["id"],
        "status": "active",
        "scoring_status": None,
        "result": None,
    }


def test_a_submission_without_a_transcript_reads_as_waiting(
    client: TestClient, session: dict[str, object]
) -> None:
    attempt = attempt_of(client, session)
    submit(client, attempt["id"], session, TYPED)

    body = read(client, attempt["id"])

    assert (body["status"], body["scoring_status"], body["result"]) == (
        "submitted",
        "waiting_transcript",
        None,
    )


def test_at3_the_scored_attempt_returns_the_expected_diff_and_accuracy(
    client: TestClient, session: dict[str, object], clip: str, migrated_url: str
) -> None:
    seed_transcript(migrated_url, media_of(migrated_url, clip))
    attempt = attempt_of(client, session)
    submit(client, attempt["id"], session, TYPED)
    run_scoring(migrated_url, client, attempt["id"])

    body = read(client, attempt["id"])

    assert body["scoring_status"] == "scored"
    assert body["result"] == {
        "accuracy": 90.0,
        "counts": {"correct": 8, "spelling_slip": 1, "wrong": 0, "missing": 1, "extra": 1},
        "items": EXPECTED_ITEMS,
    }


def test_no_response_before_scoring_holds_the_reference_text(
    client: TestClient, session: dict[str, object], clip: str, migrated_url: str
) -> None:
    """FR-DI-3, FR-TX-5: even with the transcript cached, nothing shows it before the score."""
    seed_transcript(migrated_url, media_of(migrated_url, clip))
    responses = [open_attempt(client, session["id"])]
    attempt_id = responses[0].json()["id"]
    responses += [
        save(client, attempt_id, HEARD, 0),
        client.post(f"/api/v1/dictation/attempts/{attempt_id}/listen"),
        client.get(f"/api/v1/dictation/attempts/{attempt_id}"),
        open_attempt(client, session["id"]),
        client.get(f"/api/v1/sessions/{session['id']}"),
        client.get("/api/v1/sessions"),
        submit(client, attempt_id, session, HEARD),
        client.get(f"/api/v1/dictation/attempts/{attempt_id}"),
        client.get(f"/api/v1/sessions/{session['id']}"),
    ]

    for response in responses:
        text = response.text.lower()
        assert not [word for word in SECRET_WORDS if word in text], response.request.url


def test_the_reference_text_appears_only_inside_the_scored_diff(
    client: TestClient, session: dict[str, object], clip: str, migrated_url: str
) -> None:
    seed_transcript(migrated_url, media_of(migrated_url, clip))
    attempt = attempt_of(client, session)
    submit(client, attempt["id"], session, HEARD)
    run_scoring(migrated_url, client, attempt["id"])

    body = read(client, attempt["id"])
    outside = json.dumps({k: v for k, v in body.items() if k != "result"}).lower()
    inside = json.dumps(body["result"]).lower()

    assert not [word for word in SECRET_WORDS if word in outside]
    assert all(word in inside for word in SECRET_WORDS)


def test_another_learners_attempt_is_not_found(
    make_client: ClientFactory, client: TestClient, session: dict[str, object]
) -> None:
    attempt = attempt_of(client, session)

    response = make_client().get(f"/api/v1/dictation/attempts/{attempt['id']}")

    assert response.status_code == 404
    assert response.json()["code"] == "attempt_not_found"


def test_an_unknown_attempt_is_not_found(client: TestClient) -> None:
    response = client.get(f"/api/v1/dictation/attempts/{uuid.uuid4()}")

    assert response.status_code == 404


def test_the_latest_attempt_of_a_session_is_found_after_the_step_is_complete(
    client: TestClient, session: dict[str, object], clip: str, migrated_url: str
) -> None:
    seed_transcript(migrated_url, media_of(migrated_url, clip))
    attempt = attempt_of(client, session)
    submit(client, attempt["id"], session, TYPED)
    run_scoring(migrated_url, client, attempt["id"])

    response = client.get(f"/api/v1/sessions/{session['id']}/dictation/attempt")

    assert response.status_code == 200
    assert response.json() == read(client, attempt["id"])


def test_a_newer_unsubmitted_attempt_does_not_hide_the_scored_one(
    client: TestClient, session: dict[str, object], clip: str, migrated_url: str
) -> None:
    seed_transcript(migrated_url, media_of(migrated_url, clip))
    attempt = attempt_of(client, session)
    submit(client, attempt["id"], session, TYPED)
    run_scoring(migrated_url, client, attempt["id"])
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO practice.attempts (id, session_id, user_id, mode, status, started_at) "
            "SELECT gen_random_uuid(), session_id, user_id, mode, 'active', "
            "now() + interval '1 minute' "
            "FROM practice.attempts WHERE id = %s",
            [attempt["id"]],
        )

    response = client.get(f"/api/v1/sessions/{session['id']}/dictation/attempt")

    assert response.status_code == 200
    assert response.json() == read(client, attempt["id"])
    assert response.json()["scoring_status"] == "scored"


def test_a_session_without_a_dictation_attempt_has_none_to_read(
    client: TestClient, session: dict[str, object]
) -> None:
    response = client.get(f"/api/v1/sessions/{session['id']}/dictation/attempt")

    assert response.status_code == 404
    assert response.json()["code"] == "attempt_not_found"


def test_another_learners_session_is_not_found(
    make_client: ClientFactory, session: dict[str, object]
) -> None:
    response = make_client().get(f"/api/v1/sessions/{session['id']}/dictation/attempt")

    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"
