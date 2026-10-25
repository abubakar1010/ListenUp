"""The B5 load-test seed (#94): N signed-in learners with data the load script can use.

Checked through the API as the restricted role, so what k6 sends works as it would
against the running stack.
"""

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.main import create_app
from listenup.platform.config import Settings
from tests.integration.conftest import conninfo_to_url
from tests.integration.load_seed import seed_load


@pytest.fixture(scope="module")
def manifest(migrated_url: str) -> Iterator[dict]:
    world = seed_load(migrated_url, learners=2, history=1, blind_learners=1, blind_sessions=2)
    yield world
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        for learner in world["learners"]:
            conn.execute("DELETE FROM identity.users WHERE id = %s", [learner["user_id"]])


@pytest.fixture
def make_client(api_role_url: str, migrated_url: str, manifest: dict) -> Iterator[object]:
    worker_url = conninfo_to_url(migrated_url) + "?options=-c%20role%3Dlistenup_worker"
    settings = Settings(
        database_url=api_role_url, transcript_read_database_url=worker_url, log_json=False
    )
    opened: list[TestClient] = []

    def make(learner: dict) -> TestClient:
        # What the k6 script sends: the seeded session cookie, and the same CSRF value
        # as cookie and header.
        client = TestClient(create_app(settings), raise_server_exceptions=False)
        client.__enter__()
        cookies = manifest["cookies"]
        client.cookies.set(cookies["session"], learner["token"])
        client.cookies.set(cookies["csrf"], "b5-load-test")
        client.headers["X-CSRF-Token"] = "b5-load-test"
        opened.append(client)
        return client

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def test_every_learner_is_signed_in_with_the_seeded_cookie(manifest, make_client) -> None:
    assert len(manifest["learners"]) == 2
    for learner in manifest["learners"]:
        me = make_client(learner).get("/api/v1/me")
        assert me.status_code == 200
        assert me.json()["id"] == learner["user_id"]


def test_a_learner_has_a_session_at_each_step_and_extra_clips(manifest, make_client) -> None:
    learner = manifest["learners"][1]
    client = make_client(learner)
    assert set(learner["sessions"]) == {
        "blind",
        "dictation",
        "transcript",
        "card",
        "shadow",
        "done",
    }
    opened = client.get(f"/api/v1/sessions/{learner['sessions']['card']}").json()
    assert opened["open_step"] == "card"
    # One seeded clip plus `history` more, each with its own sessions.
    contents = client.get("/api/v1/contents").json()
    assert len(contents["items"]) == 2
    assert len(client.get("/api/v1/sessions?limit=50").json()["items"]) == 12


def test_the_transcript_session_has_words_to_read_and_mark(manifest, make_client) -> None:
    learner = manifest["learners"][0]
    client = make_client(learner)
    session = learner["sessions"]["transcript"]
    transcript = client.get(f"/api/v1/sessions/{session}/transcript")
    assert transcript.status_code == 200
    assert transcript.json()["lines"]
    mark_id = str(uuid.uuid4())
    made = client.post(
        f"/api/v1/sessions/{session}/marks", json={"id": mark_id, "word_from": 5, "word_to": 6}
    )
    assert made.status_code == 201
    assert client.delete(f"/api/v1/sessions/{session}/marks/{mark_id}").status_code == 204
    note = client.patch(
        f"/api/v1/sessions/{session}/marks/{learner['mark_id']}", json={"note": "load"}
    )
    assert note.status_code == 200


def test_the_dictation_draft_resumes_and_saves_at_its_version(manifest, make_client) -> None:
    learner = manifest["learners"][0]
    client = make_client(learner)
    resumed = client.post(f"/api/v1/sessions/{learner['sessions']['dictation']}/dictation/attempts")
    assert resumed.status_code == 200
    work = resumed.json()
    assert work["id"] == learner["dictation_attempt_id"]
    saved = client.put(
        f"/api/v1/dictation/attempts/{work['id']}/draft",
        json={"draft_text": "So the first thing we", "draft_version": work["draft_version"]},
    )
    assert saved.status_code == 200


def test_blind_learners_get_fresh_sessions_open_at_blind(manifest, make_client) -> None:
    blind, other = manifest["learners"]
    assert len(blind["blind_sessions"]) == 2
    assert other["blind_sessions"] == []
    client = make_client(blind)
    for session in blind["blind_sessions"]:
        started = client.post(f"/api/v1/sessions/{session}/blind/attempts")
        assert started.status_code == 201
        beat = client.post(
            f"/api/v1/blind/attempts/{started.json()['attempt']['id']}/heartbeat",
            json={"position_ms": 0, "state": "playing"},
        )
        assert beat.status_code == 200
        assert beat.json()["action"] == "continue"


def test_the_seeded_blind_attempt_is_active(manifest, migrated_url) -> None:
    with psycopg.connect(migrated_url) as conn:
        statuses = [
            conn.execute(
                "SELECT status FROM practice.attempts WHERE session_id = %s AND mode = 'blind'",
                [learner["sessions"]["blind"]],
            ).fetchall()
            for learner in manifest["learners"]
        ]
    assert statuses == [[("active",)], [("active",)]]


def test_the_manifest_never_holds_a_password(manifest) -> None:
    assert "password" not in str(manifest).lower()
