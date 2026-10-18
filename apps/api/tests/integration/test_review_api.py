"""Transcript review uses the API role and the existing authorized read boundary (#57)."""

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.modules.practice.service import Step
from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import (
    ClientFactory,
    FakeStorage,
    client_factory,
    learner_id,
)
from tests.integration.test_sessions_api import add_clip, finish, load, start


@pytest.fixture
def make_client(api_role_url: str) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, FakeStorage())


@pytest.fixture
def client(make_client: ClientFactory, migrated_url: str) -> TestClient:
    return make_client(
        transcript_read_database_url=conninfo_to_url(migrated_url)
        + "?options=-c%20role%3Dlistenup_worker"
    )


@pytest.fixture
def clip(client: TestClient, migrated_url: str) -> str:
    return add_clip(migrated_url, learner_id(client))


@pytest.mark.parametrize("entry", ["blind", "dictation"])
def test_transcript_before_unlock_returns_step_locked(client, clip, entry):
    session = start(client, clip, entry)
    response = client.get(f"/api/v1/sessions/{session['id']}/transcript")
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "step_locked"
    assert response.json()["open_step"] == entry
    assert response.json()["step"] == "transcript"


def test_opening_transcript_persists_entry_lock(client, clip, api_role_url, migrated_url):
    session = start(client, clip, "dictation")
    assert session["entry_locked_at"] is None
    finish(api_role_url, client, session["id"], Step.DICTATION)
    opened = load(client, session)
    assert opened["entry_locked"] is True
    assert opened["entry_locked_at"] is not None
    with psycopg.connect(migrated_url) as conn:
        stamp = conn.execute(
            "SELECT entry_locked_at FROM practice.sessions WHERE id=%s", [session["id"]]
        ).fetchone()[0]
    assert stamp.isoformat() == opened["entry_locked_at"].replace("Z", "+00:00")
    refused = client.patch(
        f"/api/v1/sessions/{session['id']}/entry",
        json={"entry": "both", "version": opened["version"]},
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "entry_locked"
    assert load(client, session)["entry_locked_at"] == opened["entry_locked_at"]


def cache(url, content_id, *, status="ready", silent=False):
    with psycopg.connect(url) as conn:
        media = conn.execute(
            "SELECT media_object_id FROM content.contents WHERE id=%s", [content_id]
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO content.passage_transcripts "
            "(id, media_object_id, span, origin, status, words, start_ms, end_ms, "
            "confidence, sentence_starts, provider_info) "
            "VALUES (%s,%s,int4range(0,120000),'generated',%s,%s,%s,%s,%s,%s,"
            '\'{"provider":"test","model":"fixture","version":"1"}\')',
            [
                uuid.uuid4(),
                media,
                status,
                [] if silent else ["Outside.", "Hello", "world.", "Again."],
                [] if silent else [0, 11000, 12000, 30000],
                [] if silent else [500, 11500, 13000, 31000],
                [] if silent else [900, 900, 900, 900],
                [] if silent else [0, 1, 3],
            ],
        )
    return media


def test_transcript_returns_sentence_lines_with_absolute_word_timings(
    client, clip, api_role_url, migrated_url
):
    session = start(client, clip, "dictation", passage={"start_ms": 10000, "end_ms": 40000})
    media = cache(migrated_url, clip)
    finish(api_role_url, client, session["id"], Step.DICTATION)
    response = client.get(f"/api/v1/sessions/{session['id']}/transcript")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "session_id": session["id"],
        "passage": {"start_ms": 10000, "end_ms": 40000},
        "media_url": f"/api/v1/media/{media}",
        "lines": [
            {
                "index": 0,
                "start_ms": 11000,
                "end_ms": 13000,
                "words": [
                    {"index": 0, "text": "Hello", "start_ms": 11000, "end_ms": 11500},
                    {"index": 1, "text": "world.", "start_ms": 12000, "end_ms": 13000},
                ],
            },
            {
                "index": 1,
                "start_ms": 30000,
                "end_ms": 31000,
                "words": [{"index": 2, "text": "Again.", "start_ms": 30000, "end_ms": 31000}],
            },
        ],
    }
    stamp = load(client, session)["entry_locked_at"]
    finish(api_role_url, client, session["id"], Step.TRANSCRIPT, Step.CARD, Step.SHADOW)
    assert client.get(f"/api/v1/sessions/{session['id']}/transcript").json() == response.json()
    assert load(client, session)["entry_locked_at"] == stamp


@pytest.mark.parametrize(
    "status,code", [(None, "transcript_not_ready"), ("failed", "transcript_failed")]
)
def test_transcript_reports_readiness_refusals(
    client, clip, api_role_url, migrated_url, status, code
):
    session = start(client, clip, "dictation")
    finish(api_role_url, client, session["id"], Step.DICTATION)
    if status:
        cache(migrated_url, clip, status=status)
    response = client.get(f"/api/v1/sessions/{session['id']}/transcript")
    assert response.status_code == 409
    assert response.json()["code"] == code
    assert "words" not in response.text


def test_silent_transcript_has_no_lines(client, clip, api_role_url, migrated_url):
    session = start(client, clip, "dictation")
    cache(migrated_url, clip, silent=True)
    finish(api_role_url, client, session["id"], Step.DICTATION)
    response = client.get(f"/api/v1/sessions/{session['id']}/transcript")
    assert response.status_code == 200
    assert response.json()["lines"] == []


def test_transcript_denials_do_not_open_worker_transaction(client, clip, make_client, monkeypatch):
    session = start(client, clip, "dictation")
    other = make_client()
    path = f"/api/v1/sessions/{session['id']}/transcript"
    worker = client.app.state.transcript_database

    def forbidden(*args, **kwargs):
        pytest.fail("denial opened a privileged transaction")

    monkeypatch.setattr(worker, "transaction", forbidden)
    monkeypatch.setattr(other.app.state.transcript_database, "transaction", forbidden)
    assert client.get(path).json()["code"] == "step_locked"
    assert other.get(path).json()["code"] == "session_not_found"
    assert (
        client.get(f"/api/v1/sessions/{uuid.uuid4()}/transcript").json()["code"]
        == "session_not_found"
    )
    assert client.get("/api/v1/sessions/invalid/transcript").json()["code"] == "validation_failed"
    client.cookies.clear()
    assert client.get(path).json()["code"] == "not_signed_in"
