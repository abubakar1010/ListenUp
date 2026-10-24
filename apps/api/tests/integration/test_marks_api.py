"""Marking a word or phrase in Transcript (#58; FR-TR-2, AT-4, NFR-PERF-3, NFR-REL-1).

The browser names each new mark with its own id, so a create resent after a lost
connection is the same single INSERT and answers with the same mark (ADR 0047).
"""

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from listenup.modules.practice.service import Step
from listenup.modules.review.domain import MAX_MARK_WORDS
from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import ClientFactory, FakeStorage, client_factory, learner_id
from tests.integration.test_review_api import cache, correction
from tests.integration.test_sessions_api import add_clip, finish, start

# The cached words (test_review_api.cache) inside the passage 10 s to 40 s:
# 0 "Hello" at 11 000 ms, 1 "world." at 12 000 ms, 2 "Again." at 30 000 ms.
PASSAGE = {"start_ms": 10_000, "end_ms": 40_000}


@pytest.fixture
def make_client(api_role_url: str) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, FakeStorage())


@pytest.fixture
def worker_url(migrated_url: str) -> str:
    return conninfo_to_url(migrated_url) + "?options=-c%20role%3Dlistenup_worker"


@pytest.fixture
def client(make_client: ClientFactory, worker_url: str) -> TestClient:
    return make_client(transcript_read_database_url=worker_url)


@pytest.fixture
def clip(client: TestClient, migrated_url: str) -> str:
    content_id = add_clip(migrated_url, learner_id(client))
    cache(migrated_url, content_id)
    return content_id


@pytest.fixture
def session_id(client: TestClient, clip: str, api_role_url: str) -> str:
    session = start(client, clip, "dictation", passage=PASSAGE)
    finish(api_role_url, client, session["id"], Step.DICTATION)
    return str(session["id"])


def marks_path(session_id: str) -> str:
    return f"/api/v1/sessions/{session_id}/marks"


def new_mark(**values: Any) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "word_from": 0, "word_to": 1, **values}


def stored(url: str, mark_id: str) -> tuple[Any, ...] | None:
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT word_from, word_to, at_ms, note, source, status FROM practice.marks "
            "WHERE id = %s",
            [mark_id],
        ).fetchone()


def mark_events(url: str, mark_id: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT session_id, properties FROM ops.analytics_events "
            "WHERE event_type = 'mark_created' AND subject_id = %s",
            [mark_id],
        ).fetchall()


class Statements:
    """The SQL the app's request connection sends while the block runs."""

    def __init__(self, client: TestClient) -> None:
        self.engine = client.app.state.database.engine.sync_engine  # type: ignore[attr-defined]
        self.sent: list[str] = []

    def _record(self, conn: object, cursor: object, statement: str, *args: object) -> None:
        self.sent.append(" ".join(statement.split()))

    def __enter__(self) -> "Statements":
        event.listen(self.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(self.engine, "before_cursor_execute", self._record)

    def inserts_into(self, table: str) -> int:
        return sum(s.startswith(f"INSERT INTO {table} ") for s in self.sent)


# -- creating (FR-TR-2, AT-4) ------------------------------------------------------------


def test_a_mark_stores_its_word_range_audio_time_and_note(client, session_id, migrated_url):
    body = new_mark(word_from=1, word_to=2, note="  sounds like 'worl'  ")
    response = client.post(marks_path(session_id), json=body)
    assert response.status_code == 201, response.text
    mark = response.json()
    assert mark == {
        "id": body["id"],
        "session_id": session_id,
        "word_from": 1,
        "word_to": 2,
        "at_ms": 12_000,
        "note": "sounds like 'worl'",
        "source": "manual",
        "status": "confirmed",
        "created_at": mark["created_at"],
    }
    assert response.headers["cache-control"] == "private, no-store"
    assert stored(migrated_url, body["id"]) == (
        1,
        2,
        12_000,
        "sounds like 'worl'",
        "manual",
        "confirmed",
    )


def test_a_mark_without_a_note_stores_none(client, session_id, migrated_url):
    for word, note in enumerate(({}, {"note": None}, {"note": "   "})):
        body = new_mark(word_from=word, word_to=word, **note)
        assert client.post(marks_path(session_id), json=body).json()["note"] is None
        assert stored(migrated_url, body["id"])[3] is None


def test_saving_a_mark_is_one_insert(client, session_id):
    with Statements(client) as sql:
        response = client.post(marks_path(session_id), json=new_mark())
    assert response.status_code == 201, response.text
    assert sql.inserts_into("practice.marks") == 1


def test_a_resent_create_answers_with_the_same_mark_and_stores_one(
    client, session_id, migrated_url
):
    body = new_mark(note="first")
    first = client.post(marks_path(session_id), json=body)
    again = client.post(marks_path(session_id), json=body)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT count(*) FROM practice.marks WHERE session_id = %s", [session_id]
        ).fetchone() == (1,)
    assert len(mark_events(migrated_url, body["id"])) == 1


def test_a_new_mark_records_its_pattern_but_never_its_words(client, session_id, migrated_url):
    body = new_mark()
    client.post(marks_path(session_id), json=body)
    [(event_session, properties)] = mark_events(migrated_url, body["id"])
    assert str(event_session) == session_id
    assert set(properties) == {"pattern"}
    assert "Hello" not in str(properties) and "world" not in str(properties)


def test_the_same_words_cannot_be_marked_twice(client, session_id):
    first = client.post(marks_path(session_id), json=new_mark()).json()
    response = client.post(marks_path(session_id), json=new_mark())
    assert response.status_code == 409
    assert response.json()["code"] == "mark_exists"
    assert response.json()["mark_id"] == first["id"]


def test_a_mark_id_in_use_for_other_words_is_refused(client, session_id):
    body = new_mark()
    client.post(marks_path(session_id), json=body)
    response = client.post(marks_path(session_id), json={**body, "word_from": 2, "word_to": 2})
    assert response.status_code == 409
    assert response.json()["code"] == "mark_id_taken"


@pytest.mark.parametrize(
    ("values", "status", "code"),
    [
        ({"word_from": 2, "word_to": 3}, 422, "mark_out_of_range"),
        ({"word_from": 1, "word_to": 0}, 422, "mark_out_of_range"),
        ({"word_from": -1, "word_to": 0}, 422, "validation_failed"),
        ({"note": "x" * 501}, 422, "note_too_long"),
        ({"id": "not-a-uuid"}, 422, "validation_failed"),
    ],
)
def test_invalid_marks_are_refused_and_nothing_is_stored(
    client, session_id, migrated_url, values, status, code
):
    body = new_mark(**values)
    response = client.post(marks_path(session_id), json=body)
    assert response.status_code == status, response.text
    assert response.json()["code"] == code
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT count(*) FROM practice.marks WHERE session_id = %s", [session_id]
        ).fetchone() == (0,)


def test_a_mark_longer_than_a_phrase_is_refused(client, migrated_url, api_role_url):
    content_id = add_clip(migrated_url, learner_id(client))
    words = MAX_MARK_WORDS + 1
    with psycopg.connect(migrated_url) as conn:
        media = conn.execute(
            "SELECT media_object_id FROM content.contents WHERE id=%s", [content_id]
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO content.passage_transcripts "
            "(id, media_object_id, span, origin, status, words, start_ms, end_ms, "
            "confidence, sentence_starts, provider_info) "
            "VALUES (%s,%s,int4range(0,120000),'generated','ready',%s,%s,%s,%s,ARRAY[0],"
            '\'{"provider":"test","model":"fixture","version":"1"}\')',
            [
                uuid.uuid4(),
                media,
                ["word"] * words,
                [10_000 + 100 * i for i in range(words)],
                [10_050 + 100 * i for i in range(words)],
                [900] * words,
            ],
        )
    session = start(client, content_id, "dictation", passage=PASSAGE)
    finish(api_role_url, client, session["id"], Step.DICTATION)
    path = marks_path(str(session["id"]))
    longest = client.post(path, json=new_mark(word_from=0, word_to=MAX_MARK_WORDS - 1))
    assert longest.status_code == 201, longest.text
    response = client.post(path, json=new_mark(word_from=0, word_to=MAX_MARK_WORDS))
    assert response.status_code == 422
    assert response.json()["code"] == "mark_too_long"


# -- the Transcript gate (FR-TX-5) -------------------------------------------------------


def test_marks_wait_for_the_transcript_step(client, clip):
    session = start(client, clip, "dictation", passage=PASSAGE)
    path = marks_path(str(session["id"]))
    mark_id = uuid.uuid4()
    for response in (
        client.get(path),
        client.post(path, json=new_mark()),
        client.patch(f"{path}/{mark_id}", json={"note": "x"}),
        client.delete(f"{path}/{mark_id}"),
        client.put(f"{path}/{mark_id}/status", json={"status": "confirmed"}),
    ):
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "step_locked"
        assert response.json()["step"] == "transcript"


def test_marks_stay_open_after_transcript_is_finished(client, session_id, api_role_url):
    finish(api_role_url, client, session_id, Step.TRANSCRIPT)
    assert client.post(marks_path(session_id), json=new_mark()).status_code == 201


def test_a_mark_needs_the_transcript_words(client, api_role_url, migrated_url):
    content_id = add_clip(migrated_url, learner_id(client))
    session = start(client, content_id, "dictation", passage=PASSAGE)
    finish(api_role_url, client, session["id"], Step.DICTATION)
    response = client.post(marks_path(str(session["id"])), json=new_mark())
    assert response.status_code == 409
    assert response.json()["code"] == "transcript_not_ready"


def test_an_unknown_session_has_no_marks(client):
    response = client.get(marks_path(str(uuid.uuid4())))
    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"


# -- reading back (NFR-REL-1: a reload shows the marks) ----------------------------------


def test_marks_come_back_in_audio_order(client, session_id):
    later = client.post(marks_path(session_id), json=new_mark(word_from=2, word_to=2)).json()
    earlier = client.post(marks_path(session_id), json=new_mark(word_from=0, word_to=0)).json()
    response = client.get(marks_path(session_id))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {"marks": [earlier, later]}


def test_a_session_without_marks_lists_none(client, session_id):
    assert client.get(marks_path(session_id)).json() == {"marks": []}


# -- changing the note and removing ------------------------------------------------------


def test_the_note_can_be_changed_and_cleared(client, session_id, migrated_url):
    mark = client.post(marks_path(session_id), json=new_mark()).json()
    path = f"{marks_path(session_id)}/{mark['id']}"
    changed = client.patch(path, json={"note": " linking "})
    assert changed.status_code == 200, changed.text
    assert changed.json() == {**mark, "note": "linking"}
    assert stored(migrated_url, mark["id"])[3] == "linking"
    cleared = client.patch(path, json={"note": ""})
    assert cleared.json()["note"] is None
    assert stored(migrated_url, mark["id"])[3] is None
    too_long = client.patch(path, json={"note": "x" * 501})
    assert too_long.status_code == 422
    assert too_long.json()["code"] == "note_too_long"


def test_a_mark_can_be_removed_once(client, session_id, migrated_url):
    mark = client.post(marks_path(session_id), json=new_mark()).json()
    path = f"{marks_path(session_id)}/{mark['id']}"
    assert client.delete(path).status_code == 204
    assert stored(migrated_url, mark["id"]) is None
    again = client.delete(path)
    assert again.status_code == 404
    assert again.json()["code"] == "mark_not_found"
    assert client.patch(path, json={"note": "x"}).json()["code"] == "mark_not_found"


def test_a_mark_is_reached_only_through_its_own_session(client, clip, session_id, api_role_url):
    mark = client.post(marks_path(session_id), json=new_mark()).json()
    other = start(client, clip, "dictation", passage=PASSAGE)
    finish(api_role_url, client, other["id"], Step.DICTATION)
    path = f"{marks_path(str(other['id']))}/{mark['id']}"
    assert client.patch(path, json={"note": "x"}).json()["code"] == "mark_not_found"
    assert client.delete(path).json()["code"] == "mark_not_found"
    assert client.get(marks_path(session_id)).json() == {"marks": [mark]}


def test_another_learner_cannot_reach_the_marks(make_client, worker_url, client, session_id):
    mark = client.post(marks_path(session_id), json=new_mark()).json()
    other = make_client(transcript_read_database_url=worker_url)
    path = f"{marks_path(session_id)}/{mark['id']}"
    for response in (
        other.get(marks_path(session_id)),
        other.post(marks_path(session_id), json=new_mark(word_from=2, word_to=2)),
        other.patch(path, json={"note": "x"}),
        other.delete(path),
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "session_not_found"
    assert client.get(marks_path(session_id)).json() == {"marks": [mark]}


def test_a_mark_id_owned_by_another_learner_is_refused_and_nothing_leaks(
    make_client, worker_url, client, session_id, migrated_url, api_role_url
):
    mark = client.post(marks_path(session_id), json=new_mark(note="mine")).json()
    other = make_client(transcript_read_database_url=worker_url)
    other_clip = add_clip(migrated_url, learner_id(other))
    cache(migrated_url, other_clip)
    theirs = start(other, other_clip, "dictation", passage=PASSAGE)
    finish(api_role_url, other, theirs["id"], Step.DICTATION)
    response = other.post(
        marks_path(str(theirs["id"])), json=new_mark(id=mark["id"], word_from=2, word_to=2)
    )
    assert response.status_code == 409
    assert response.json()["code"] == "mark_id_taken"
    assert "mine" not in response.text and session_id not in response.text
    assert stored(migrated_url, mark["id"]) == (0, 1, 11_000, "mine", "manual", "confirmed")
    assert other.get(marks_path(str(theirs["id"]))).json() == {"marks": []}
    assert mark_events(migrated_url, mark["id"]) != []
    assert len(mark_events(migrated_url, mark["id"])) == 1


def test_a_word_a_correction_removed_cannot_be_marked(client, clip, session_id, migrated_url):
    with psycopg.connect(migrated_url) as conn:
        (media,) = conn.execute(
            "SELECT media_object_id FROM content.contents WHERE id = %s", [clip]
        ).fetchone()
    # Cached word 2 is the passage's word 1 ("world."): word 0 of the cache lies before it.
    correction(migrated_url, learner_id(client), media, index=2, value="")
    refused = client.post(marks_path(session_id), json=new_mark(word_from=1, word_to=1))
    assert (refused.status_code, refused.json()["code"]) == (422, "mark_no_words")
    # Removed words inside a longer phrase are fine: the phrase still has words.
    ok = client.post(marks_path(session_id), json=new_mark(word_from=0, word_to=1))
    assert ok.status_code == 201
