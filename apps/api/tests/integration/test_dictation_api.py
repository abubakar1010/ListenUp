"""The Dictation attempt and its draft (#51, #52, #50; FR-DI-1 to FR-DI-4, ADR 0025).

The app connects as a role with only the API's rights, so row-level security is in
force as in production. Clips are inserted directly, so nothing here needs S3. Steps
before Dictation are finished through the practice service, as their mode endpoints
will.
"""

import asyncio
import uuid
from collections.abc import Iterator

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.modules.practice import service as practice
from listenup.modules.practice.service import AttemptStatus, Step
from listenup.platform.database import Database
from tests.integration.intake_helpers import (
    ClientFactory,
    FakeStorage,
    client_factory,
    learner_id,
)
from tests.integration.test_sessions_api import add_clip, finish, start

ATTEMPT_FIELDS = {
    "id",
    "session_id",
    "status",
    "started_at",
    "resumed",
    "draft_text",
    "draft_version",
    "draft_updated_at",
    "passage",
    "media_url",
}


@pytest.fixture
def make_client(api_role_url: str) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, FakeStorage())


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


@pytest.fixture
def session(client: TestClient, migrated_url: str) -> dict[str, object]:
    """A plan of Dictation only, so Dictation is the open step."""
    return start(client, add_clip(migrated_url, learner_id(client)), entry="dictation")


def open_attempt(client: TestClient, session_id: object) -> httpx.Response:
    return client.post(f"/api/v1/sessions/{session_id}/dictation/attempts")


def save(client: TestClient, attempt_id: object, text: str, version: int) -> httpx.Response:
    return client.put(
        f"/api/v1/dictation/attempts/{attempt_id}/draft",
        json={"draft_text": text, "draft_version": version},
    )


def attempt_of(client: TestClient, session: dict[str, object]) -> dict[str, object]:
    response = open_attempt(client, session["id"])
    assert response.status_code in (200, 201), response.text
    body: dict[str, object] = response.json()
    return body


def end_attempt(api_role_url: str, client: TestClient, attempt_id: object) -> None:
    async def run() -> None:
        database = Database(api_role_url, pool_size=1)
        try:
            async with database.transaction(uuid.UUID(learner_id(client))) as db:
                await practice.finish_attempt(
                    db, uuid.UUID(str(attempt_id)), AttemptStatus.SUBMITTED
                )
        finally:
            await database.dispose()

    asyncio.run(run())


# Starting and resuming (#51, #50)


def test_the_first_call_starts_an_attempt_with_an_empty_draft(
    client: TestClient, session: dict[str, object], migrated_url: str
) -> None:
    response = open_attempt(client, session["id"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == ATTEMPT_FIELDS
    assert body["session_id"] == session["id"]
    assert (body["status"], body["resumed"]) == ("active", False)
    assert (body["draft_text"], body["draft_version"]) == ("", 0)
    assert body["passage"] == session["passage"]
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT media_object_id FROM content.contents WHERE id = %s", [session["content_id"]]
        ).fetchone()
    assert row is not None
    assert body["media_url"] == f"/api/v1/media/{row[0]}"
    assert response.headers["Cache-Control"] == "private, no-store"


def test_coming_back_resumes_the_same_attempt_with_its_draft(
    client: TestClient, session: dict[str, object]
) -> None:
    first = attempt_of(client, session)
    saved = save(client, first["id"], "So the first thing you notice", 0)
    assert saved.status_code == 200, saved.text

    again = open_attempt(client, session["id"])

    assert again.status_code == 200
    body = again.json()
    assert body["id"] == first["id"]
    assert body["resumed"] is True
    assert (body["draft_text"], body["draft_version"]) == ("So the first thing you notice", 1)


def test_dictation_cannot_start_before_its_step_opens(
    client: TestClient, migrated_url: str
) -> None:
    both = start(client, add_clip(migrated_url, learner_id(client)), entry="both")

    response = open_attempt(client, both["id"])

    assert response.status_code == 409
    assert (response.json()["code"], response.json()["open_step"]) == ("step_locked", "blind")


def test_a_plan_without_dictation_has_no_dictation_attempt(
    client: TestClient, migrated_url: str
) -> None:
    blind = start(client, add_clip(migrated_url, learner_id(client)), entry="blind")

    response = open_attempt(client, blind["id"])

    assert response.status_code == 409
    assert response.json()["code"] == "step_not_in_plan"


def test_dictation_opens_after_blind_in_a_plan_of_both(
    client: TestClient, migrated_url: str, api_role_url: str
) -> None:
    both = start(client, add_clip(migrated_url, learner_id(client)), entry="both")
    finish(api_role_url, client, both["id"], Step.BLIND)

    assert open_attempt(client, both["id"]).status_code == 201


# Saving the draft (#52, #50)


def test_each_save_moves_the_draft_to_a_new_version(
    client: TestClient, session: dict[str, object]
) -> None:
    attempt = attempt_of(client, session)

    first = save(client, attempt["id"], "So the first", 0)
    second = save(client, attempt["id"], "So the first thing", first.json()["draft_version"])

    assert (first.status_code, second.status_code) == (200, 200)
    assert set(first.json()) == {"draft_version", "updated_at"}
    assert [first.json()["draft_version"], second.json()["draft_version"]] == [1, 2]
    assert attempt_of(client, session)["draft_text"] == "So the first thing"


def test_a_second_tab_cannot_overwrite_a_newer_draft(
    client: TestClient, session: dict[str, object]
) -> None:
    attempt = attempt_of(client, session)
    assert save(client, attempt["id"], "Typed in tab one", 0).status_code == 200

    stale = save(client, attempt["id"], "Typed in tab two", 0)

    assert stale.status_code == 409
    problem = stale.json()
    assert problem["code"] == "draft_conflict"
    assert (problem["draft_text"], problem["draft_version"]) == ("Typed in tab one", 1)
    assert "updated_at" in problem
    assert attempt_of(client, session)["draft_text"] == "Typed in tab one"


def test_the_conflict_is_resolved_by_saving_on_the_current_version(
    client: TestClient, session: dict[str, object]
) -> None:
    attempt = attempt_of(client, session)
    save(client, attempt["id"], "Typed in tab one", 0)
    current = save(client, attempt["id"], "Typed in tab two", 0).json()["draft_version"]

    kept = save(client, attempt["id"], "Typed in tab two", current)

    assert kept.status_code == 200
    assert kept.json()["draft_version"] == 2


def test_resending_a_save_that_already_landed_is_not_a_conflict(
    client: TestClient, session: dict[str, object]
) -> None:
    attempt = attempt_of(client, session)
    first = save(client, attempt["id"], "The answer was lost on the way back", 0)

    resent = save(client, attempt["id"], "The answer was lost on the way back", 0)

    assert resent.status_code == 200
    assert resent.json()["draft_version"] == first.json()["draft_version"] == 1


def test_a_draft_may_be_20000_characters_and_no_more(
    client: TestClient, session: dict[str, object]
) -> None:
    attempt = attempt_of(client, session)

    longest = save(client, attempt["id"], "é" * 20_000, 0)
    too_long = save(client, attempt["id"], "a" * 20_001, 1)

    assert longest.status_code == 200
    assert too_long.status_code == 422
    assert (too_long.json()["code"], too_long.json()["max_chars"]) == ("draft_too_long", 20_000)
    assert attempt_of(client, session)["draft_text"] == "é" * 20_000


def test_the_database_refuses_a_draft_over_the_limit(
    client: TestClient, session: dict[str, object], migrated_url: str
) -> None:
    attempt = attempt_of(client, session)

    with (
        psycopg.connect(migrated_url) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        conn.execute(
            "UPDATE practice.dictation_attempts SET draft_text = %s WHERE attempt_id = %s",
            ["a" * 20_001, attempt["id"]],
        )


def test_a_finished_attempt_takes_no_more_saves(
    client: TestClient, session: dict[str, object], api_role_url: str
) -> None:
    attempt = attempt_of(client, session)
    end_attempt(api_role_url, client, attempt["id"])

    response = save(client, attempt["id"], "Too late", 0)

    assert response.status_code == 409
    assert response.json()["code"] == "attempt_closed"


def test_no_saves_once_the_dictation_step_is_done(
    client: TestClient, session: dict[str, object], api_role_url: str
) -> None:
    attempt = attempt_of(client, session)
    finish(api_role_url, client, session["id"], Step.DICTATION)

    response = save(client, attempt["id"], "Too late", 0)

    assert response.status_code == 409
    assert (response.json()["code"], response.json()["open_step"]) == ("step_locked", "transcript")


def test_a_blind_attempt_is_not_a_dictation_attempt(
    client: TestClient, migrated_url: str, api_role_url: str
) -> None:
    blind = start(client, add_clip(migrated_url, learner_id(client)), entry="blind")

    async def blind_attempt() -> uuid.UUID:
        database = Database(api_role_url, pool_size=1)
        try:
            async with database.transaction(uuid.UUID(learner_id(client))) as db:
                return (await practice.start_attempt(db, uuid.UUID(blind["id"]), Step.BLIND)).id
        finally:
            await database.dispose()

    attempt_id = asyncio.run(blind_attempt())

    response = save(client, attempt_id, "Not here", 0)

    assert response.status_code == 404
    assert response.json()["code"] == "attempt_not_found"


# Other learners (NFR-SEC-2) and the hidden transcript (FR-DI-3, FR-TX-5)


def test_another_learner_can_neither_open_nor_write_my_dictation(
    make_client: ClientFactory, migrated_url: str
) -> None:
    mine, theirs = make_client(), make_client()
    session = start(mine, add_clip(migrated_url, learner_id(mine)), entry="dictation")
    attempt = attempt_of(mine, session)
    save(mine, attempt["id"], "Mine", 0)

    opened = open_attempt(theirs, session["id"])
    written = save(theirs, attempt["id"], "Theirs", 1)

    assert (opened.status_code, opened.json()["code"]) == (404, "session_not_found")
    assert (written.status_code, written.json()["code"]) == (404, "attempt_not_found")
    assert attempt_of(mine, session)["draft_text"] == "Mine"
    assert "Mine" not in written.text


def test_the_database_keeps_a_draft_with_its_attempts_learner(
    client: TestClient, session: dict[str, object], migrated_url: str, learner: uuid.UUID
) -> None:
    attempt = attempt_of(client, session)

    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM practice.dictation_attempts WHERE attempt_id = %s", [attempt["id"]]
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(
                "INSERT INTO practice.dictation_attempts (attempt_id, user_id) VALUES (%s, %s)",
                [attempt["id"], learner],
            )


def test_no_dictation_answer_carries_reference_text(
    client: TestClient, session: dict[str, object]
) -> None:
    attempt = attempt_of(client, session)
    saved = save(client, attempt["id"], "typed", 0).json()
    conflict = save(client, attempt["id"], "other", 0).json()

    assert set(attempt) == ATTEMPT_FIELDS
    assert set(saved) == {"draft_version", "updated_at"}
    assert set(conflict) - {"type", "title", "status", "detail", "request_id"} == {
        "code",
        "draft_text",
        "draft_version",
        "updated_at",
    }
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ("DictationAttempt", "SaveDraft", "SavedDraft"):
        fields = " ".join(schemas[name]["properties"])
        assert "transcript" not in fields and "reference" not in fields, name
