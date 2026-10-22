"""Adding missed or wrong Dictation words to the mark list (#55; FR-DI-6, FR-TR-2 data).

A mark from the diff is a row in `practice.marks` with `source = 'dictation'`, the word
range and the audio time of its first word; it is `suggested` until the learner confirms
it in Transcript (FR-TR-3, a later story). The browser names each mark, so a resend
inserts nothing, and words that are already marked give back the mark they have
(UNIQUE session_id, word_from, word_to).
"""

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.integration.dictation_helpers import media_of, seed_transcript
from tests.integration.intake_helpers import ClientFactory, FakeStorage, client_factory, learner_id
from tests.integration.test_dictation_api import attempt_of
from tests.integration.test_dictation_result import read, run_scoring
from tests.integration.test_dictation_submit import submit
from tests.integration.test_sessions_api import add_clip, start

# Against "Cities plant street trees to cool the air in summer." (word i starts at
# (i + 1) s), this text misses five words: 1 plant, 3 trees, 5 cool, 7 air, 9 summer.
FIVE_MISSED = "Cities street to the in"
MISSED = [1, 3, 5, 7, 9]


@pytest.fixture
def make_client(api_role_url: str) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, FakeStorage())


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


@pytest.fixture
def clip(client: TestClient, migrated_url: str) -> str:
    return add_clip(migrated_url, learner_id(client))


def scored_attempt(
    client: TestClient, migrated_url: str, clip: str, text: str, words: list[str] | None = None
) -> dict[str, Any]:
    seed_transcript(migrated_url, media_of(migrated_url, clip), words)
    session = start(client, clip, entry="dictation")
    attempt = attempt_of(client, session)
    assert submit(client, attempt["id"], session, text).status_code == 202
    run_scoring(migrated_url, client, attempt["id"])
    return attempt


@pytest.fixture
def attempt(client: TestClient, migrated_url: str, clip: str) -> dict[str, Any]:
    attempt = scored_attempt(client, migrated_url, clip, FIVE_MISSED)
    result: Any = read(client, attempt["id"])["result"]
    assert [i["index"] for i in result["items"] if i["status"] == "missing"] == MISSED
    return attempt


def marks_path(attempt_id: object) -> str:
    return f"/api/v1/dictation/attempts/{attempt_id}/marks"


def mark(word_from: int, word_to: int | None = None, mark_id: str | None = None) -> dict[str, Any]:
    return {
        "id": mark_id or str(uuid.uuid4()),
        "word_from": word_from,
        "word_to": word_from if word_to is None else word_to,
    }


def add(client: TestClient, attempt_id: object, *marks: dict[str, Any]) -> httpx.Response:
    return client.post(marks_path(attempt_id), json={"marks": list(marks)})


def rows(url: str, session_id: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT id::text, word_from, word_to, at_ms, source, status, note "
            "FROM practice.marks WHERE session_id = %s ORDER BY word_from, word_to",
            [session_id],
        ).fetchall()


def mark_events(url: str, session_id: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT subject_id::text FROM ops.analytics_events "
            "WHERE event_type = 'mark_created' AND session_id = %s",
            [session_id],
        ).fetchall()


def test_adding_two_of_five_missed_words_makes_two_dictation_marks(
    client: TestClient, attempt: dict[str, Any], migrated_url: str
) -> None:
    """AC 1: two marks with source `dictation`, word range and audio time."""
    plant, cool = mark(1), mark(5)

    response = add(client, attempt["id"], plant, cool)

    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    assert [
        (m["id"], m["word_from"], m["word_to"], m["at_ms"], m["source"], m["status"])
        for m in response.json()["marks"]
    ] == [
        (plant["id"], 1, 1, 2_000, "dictation", "suggested"),
        (cool["id"], 5, 5, 6_000, "dictation", "suggested"),
    ]
    assert rows(migrated_url, attempt["session_id"]) == [
        (plant["id"], 1, 1, 2_000, "dictation", "suggested", None),
        (cool["id"], 5, 5, 6_000, "dictation", "suggested", None),
    ]
    assert sorted(mark_events(migrated_url, attempt["session_id"])) == sorted(
        [(plant["id"],), (cool["id"],)]
    )


def test_adding_the_same_word_twice_keeps_one_mark(
    client: TestClient, attempt: dict[str, Any], migrated_url: str
) -> None:
    """AC 2: UNIQUE (session_id, word_from, word_to); the second add names the first mark."""
    first = mark(3)
    assert add(client, attempt["id"], first).status_code == 200

    again = add(client, attempt["id"], mark(3))

    assert again.status_code == 200, again.text
    assert [m["id"] for m in again.json()["marks"]] == [first["id"]]
    assert [r[0] for r in rows(migrated_url, attempt["session_id"])] == [first["id"]]
    assert mark_events(migrated_url, attempt["session_id"]) == [(first["id"],)]


def test_a_resent_add_is_the_same_single_mark(
    client: TestClient, attempt: dict[str, Any], migrated_url: str
) -> None:
    """The browser-made id is the idempotency key (ADR 0047): a lost answer is harmless."""
    plant = mark(1)
    first = add(client, attempt["id"], plant)

    resent = add(client, attempt["id"], plant)

    assert resent.status_code == 200, resent.text
    assert resent.json() == first.json()
    assert len(rows(migrated_url, attempt["session_id"])) == 1
    assert mark_events(migrated_url, attempt["session_id"]) == [(plant["id"],)]


def test_the_same_words_twice_in_one_request_make_one_mark(
    client: TestClient, attempt: dict[str, Any], migrated_url: str
) -> None:
    one, two = mark(7), mark(7)

    response = add(client, attempt["id"], one, two)

    assert response.status_code == 200, response.text
    assert [m["id"] for m in response.json()["marks"]] == [one["id"], one["id"]]
    assert len(rows(migrated_url, attempt["session_id"])) == 1


def test_add_all_marks_every_missed_word_and_skips_the_ones_already_added(
    client: TestClient, attempt: dict[str, Any], migrated_url: str
) -> None:
    added = mark(9)
    assert add(client, attempt["id"], added).status_code == 200

    response = add(client, attempt["id"], *(mark(i) for i in MISSED))

    assert response.status_code == 200, response.text
    assert [m["word_from"] for m in response.json()["marks"]] == MISSED
    assert response.json()["marks"][-1]["id"] == added["id"]
    assert [r[1] for r in rows(migrated_url, attempt["session_id"])] == MISSED


def test_a_run_of_missed_words_is_one_mark(
    client: TestClient, migrated_url: str, clip: str
) -> None:
    """A run of words next to each other is marked in one action (FR-TR-2)."""
    attempt = scored_attempt(client, migrated_url, clip, "Cities plant street trees to")

    response = add(client, attempt["id"], mark(5, 7))

    assert response.status_code == 200, response.text
    (only,) = response.json()["marks"]
    assert (only["word_from"], only["word_to"], only["at_ms"]) == (5, 7, 6_000)


def test_a_manual_mark_on_the_same_words_is_the_one_given_back(
    client: TestClient, attempt: dict[str, Any], migrated_url: str
) -> None:
    manual = str(uuid.uuid4())
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO practice.marks (id, session_id, user_id, word_from, word_to, at_ms, "
            "source) VALUES (%s, %s, %s, 5, 5, 6000, 'manual')",
            [manual, attempt["session_id"], learner_id(client)],
        )

    response = add(client, attempt["id"], mark(5))

    assert response.status_code == 200, response.text
    assert [(m["id"], m["source"], m["status"]) for m in response.json()["marks"]] == [
        (manual, "manual", "confirmed")
    ]


def test_the_attempt_lists_the_sessions_marks(client: TestClient, attempt: dict[str, Any]) -> None:
    """The diff shows which words are already added, also after a reload."""
    assert client.get(marks_path(attempt["id"])).json() == {"marks": []}
    cool, plant = mark(5), mark(1)
    add(client, attempt["id"], cool, plant)

    listed = client.get(marks_path(attempt["id"]))

    assert listed.status_code == 200, listed.text
    assert listed.headers["Cache-Control"] == "private, no-store"
    assert [m["id"] for m in listed.json()["marks"]] == [plant["id"], cool["id"]]


@pytest.mark.parametrize(
    ("word_from", "word_to"),
    [(0, 0), (1, 3), (10, 10), (2, 2)],
    ids=["correct word", "run with a correct word", "past the passage", "typed word"],
)
def test_a_word_that_was_not_missed_or_wrong_is_refused(
    client: TestClient,
    attempt: dict[str, Any],
    migrated_url: str,
    word_from: int,
    word_to: int,
) -> None:
    response = add(client, attempt["id"], mark(1), mark(word_from, word_to))

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "not_a_mark_candidate"
    assert rows(migrated_url, attempt["session_id"]) == []  # the whole request is refused


def test_a_run_longer_than_a_mark_is_refused(
    client: TestClient, migrated_url: str, clip: str
) -> None:
    words = [f"word{i}" for i in range(25)]
    attempt = scored_attempt(client, migrated_url, clip, "word0", words)

    response = add(client, attempt["id"], mark(1, 21))

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "mark_too_long"
    assert add(client, attempt["id"], mark(1, 20)).status_code == 200


def test_an_id_already_used_for_other_words_is_refused(
    client: TestClient, attempt: dict[str, Any], migrated_url: str
) -> None:
    plant = mark(1)
    add(client, attempt["id"], plant)

    response = add(client, attempt["id"], mark(3, mark_id=plant["id"]))

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "mark_id_taken"
    assert [r[1] for r in rows(migrated_url, attempt["session_id"])] == [1]


@pytest.mark.parametrize("text", [None, FIVE_MISSED], ids=["active", "waiting for transcript"])
def test_an_attempt_without_a_score_has_nothing_to_mark(
    client: TestClient, clip: str, migrated_url: str, text: str | None
) -> None:
    session = start(client, clip, entry="dictation")
    attempt = attempt_of(client, session)
    if text is not None:
        submit(client, attempt["id"], session, text)

    response = add(client, attempt["id"], mark(1))

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "attempt_not_scored"
    assert rows(migrated_url, session["id"]) == []


def test_a_blind_attempt_is_not_a_dictation_attempt(client: TestClient, clip: str) -> None:
    session = start(client, clip, entry="blind")
    blind = client.post(f"/api/v1/sessions/{session['id']}/blind/attempts")
    assert blind.status_code == 201, blind.text

    blind_id = blind.json()["attempt"]["id"]

    for response in (add(client, blind_id, mark(1)), client.get(marks_path(blind_id))):
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "attempt_not_found"


@pytest.mark.parametrize("count", [0, 2_501])
def test_a_request_holds_one_to_2500_marks(
    client: TestClient, attempt: dict[str, Any], count: int
) -> None:
    response = add(client, attempt["id"], *(mark(1) for _ in range(count)))

    assert response.status_code == 422, response.text
