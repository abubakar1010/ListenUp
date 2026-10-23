"""Dictation marks pre-filled in Transcript, confirmed or removed (#59; FR-TR-3, AT-4).

A mark added from the Dictation diff is `suggested` (#55, ADR 0055). In Transcript the
learner confirms it (`PUT .../status`, one UPDATE) or removes it; a removed Dictation
mark is deleted like any other mark (ADR 0057).
"""

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.modules.practice.service import Step
from tests.integration.intake_helpers import ClientFactory, FakeStorage, client_factory, learner_id
from tests.integration.test_dictation_marks import FIVE_MISSED, add, mark, rows, scored_attempt
from tests.integration.test_marks_api import Statements
from tests.integration.test_sessions_api import add_clip, finish, start


@pytest.fixture
def make_client(api_role_url: str) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, FakeStorage())


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


@pytest.fixture
def attempt(client: TestClient, migrated_url: str) -> dict[str, Any]:
    clip = add_clip(migrated_url, learner_id(client))
    return scored_attempt(client, migrated_url, clip, FIVE_MISSED)


def transcript_marks(session_id: object) -> str:
    return f"/api/v1/sessions/{session_id}/marks"


def status_path(session_id: object, mark_id: object) -> str:
    return f"{transcript_marks(session_id)}/{mark_id}/status"


@pytest.fixture
def added(client: TestClient, attempt: dict[str, Any]) -> list[dict[str, Any]]:
    response = add(client, attempt["id"], mark(1), mark(5))
    assert response.status_code == 200, response.text
    marks: list[dict[str, Any]] = response.json()["marks"]
    return marks


def test_after_dictation_its_marks_are_pre_filled_in_transcript(
    client: TestClient, attempt: dict[str, Any], added: list[dict[str, Any]]
) -> None:
    """AT-4 (part): the Transcript list shows the Dictation marks, still to confirm."""
    listed = client.get(transcript_marks(attempt["session_id"]))

    assert listed.status_code == 200, listed.text
    assert [(m["id"], m["source"], m["status"]) for m in listed.json()["marks"]] == [
        (added[0]["id"], "dictation", "suggested"),
        (added[1]["id"], "dictation", "suggested"),
    ]


def test_confirming_a_dictation_mark_is_stored_and_survives_a_reload(
    client: TestClient, attempt: dict[str, Any], added: list[dict[str, Any]], migrated_url: str
) -> None:
    plant = client.get(transcript_marks(attempt["session_id"])).json()["marks"][0]
    assert plant["id"] == added[0]["id"]

    with Statements(client) as sent:
        response = client.put(
            status_path(attempt["session_id"], plant["id"]), json={"status": "confirmed"}
        )

    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.json() == {**plant, "status": "confirmed"}
    assert sum(s.startswith("UPDATE practice.marks ") for s in sent.sent) == 1
    assert [(r[0], r[4], r[5]) for r in rows(migrated_url, attempt["session_id"])] == [
        (plant["id"], "dictation", "confirmed"),
        (added[1]["id"], "dictation", "suggested"),
    ]
    reloaded = client.get(transcript_marks(attempt["session_id"])).json()["marks"]
    assert [m["status"] for m in reloaded] == ["confirmed", "suggested"]


def test_confirming_twice_answers_with_the_same_confirmed_mark(
    client: TestClient, attempt: dict[str, Any], added: list[dict[str, Any]]
) -> None:
    path = status_path(attempt["session_id"], added[0]["id"])
    first = client.put(path, json={"status": "confirmed"})

    again = client.put(path, json={"status": "confirmed"})

    assert again.status_code == 200, again.text
    assert again.json() == first.json()


def test_a_mark_cannot_be_put_back_to_suggested(
    client: TestClient, attempt: dict[str, Any], added: list[dict[str, Any]], migrated_url: str
) -> None:
    path = status_path(attempt["session_id"], added[0]["id"])
    assert client.put(path, json={"status": "confirmed"}).status_code == 200

    response = client.put(path, json={"status": "suggested"})

    assert response.status_code == 422
    assert rows(migrated_url, attempt["session_id"])[0][5] == "confirmed"


def test_removing_a_dictation_mark_deletes_it_and_keeps_its_analytics_event(
    client: TestClient, attempt: dict[str, Any], added: list[dict[str, Any]], migrated_url: str
) -> None:
    """ADR 0057: a removed suggestion is not kept with a status."""
    session_id = attempt["session_id"]

    removed = client.delete(f"{transcript_marks(session_id)}/{added[0]['id']}")

    assert removed.status_code == 204
    assert [r[0] for r in rows(migrated_url, session_id)] == [added[1]["id"]]
    assert [m["id"] for m in client.get(transcript_marks(session_id)).json()["marks"]] == [
        added[1]["id"]
    ]
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT count(*) FROM ops.analytics_events "
            "WHERE event_type = 'mark_created' AND subject_id = %s",
            [added[0]["id"]],
        ).fetchone() == (1,)


def test_a_removed_dictation_word_can_be_marked_again_by_hand(
    client: TestClient, attempt: dict[str, Any], added: list[dict[str, Any]]
) -> None:
    session_id = attempt["session_id"]
    client.delete(f"{transcript_marks(session_id)}/{added[0]['id']}")

    again = add(client, attempt["id"], mark(1))

    assert again.status_code == 200, again.text
    assert again.json()["marks"][0]["id"] != added[0]["id"]


def test_confirming_an_unknown_mark_is_refused(
    client: TestClient, attempt: dict[str, Any], added: list[dict[str, Any]]
) -> None:
    session_id = attempt["session_id"]
    client.delete(f"{transcript_marks(session_id)}/{added[0]['id']}")

    response = client.put(status_path(session_id, added[0]["id"]), json={"status": "confirmed"})

    assert response.status_code == 404
    assert response.json()["code"] == "mark_not_found"


def test_a_mark_is_confirmed_only_through_its_own_session(
    client: TestClient,
    attempt: dict[str, Any],
    added: list[dict[str, Any]],
    migrated_url: str,
    api_role_url: str,
) -> None:
    other = start(client, add_clip(migrated_url, learner_id(client)), "dictation")
    finish(api_role_url, client, other["id"], Step.DICTATION)

    response = client.put(status_path(other["id"], added[0]["id"]), json={"status": "confirmed"})

    assert response.json()["code"] == "mark_not_found"
    assert rows(migrated_url, attempt["session_id"])[0][5] == "suggested"


def test_another_learner_cannot_confirm_the_mark(
    make_client: ClientFactory,
    attempt: dict[str, Any],
    added: list[dict[str, Any]],
    migrated_url: str,
) -> None:
    other = make_client()

    response = other.put(
        status_path(attempt["session_id"], added[0]["id"]), json={"status": "confirmed"}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"
    assert rows(migrated_url, attempt["session_id"])[0][5] == "suggested"
