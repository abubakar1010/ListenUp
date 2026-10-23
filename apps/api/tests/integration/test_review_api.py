"""Transcript review uses the API role and the existing authorized read boundary (#57)."""

import asyncio
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.modules.practice.service import Step
from listenup.modules.review import service as review
from listenup.platform.database import Database
from tests.integration.conftest import conninfo_to_url, with_csrf
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
                    {
                        "index": 0,
                        "text": "Hello",
                        "start_ms": 11000,
                        "end_ms": 11500,
                        "edited": False,
                    },
                    {
                        "index": 1,
                        "text": "world.",
                        "start_ms": 12000,
                        "end_ms": 13000,
                        "edited": False,
                    },
                ],
            },
            {
                "index": 1,
                "start_ms": 30000,
                "end_ms": 31000,
                "words": [
                    {
                        "index": 2,
                        "text": "Again.",
                        "start_ms": 30000,
                        "end_ms": 31000,
                        "edited": False,
                    }
                ],
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


def correction(url, user, media, index=1, value="Greetings"):
    with psycopg.connect(url) as conn:
        transcript_id = conn.execute(
            "SELECT id FROM content.passage_transcripts WHERE media_object_id=%s", [media]
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO content.transcript_corrections "
            "(user_id, passage_transcript_id, word_index, corrected_text) VALUES (%s,%s,%s,%s)",
            [user, transcript_id, index, value],
        )
    return transcript_id


@pytest.mark.parametrize("index,value", [(-1, "x"), (1, "x" * 61)])
def test_correction_storage_rejects_invalid_values(client, clip, migrated_url, index, value):
    media = cache(migrated_url, clip)
    with pytest.raises(psycopg.errors.CheckViolation):
        correction(migrated_url, learner_id(client), media, index, value)


@pytest.mark.parametrize("parent", ["identity.users", "content.passage_transcripts"])
def test_correction_rows_are_private_and_cascade(
    client, clip, make_client, migrated_url, api_role_url, parent
):
    other = make_client()
    user, other_user = learner_id(client), learner_id(other)
    media = cache(migrated_url, clip)
    transcript_id = correction(migrated_url, user, media)
    correction(migrated_url, other_user, media, value="Other learner")
    with psycopg.connect(api_role_url) as conn:
        assert (
            conn.execute("SELECT corrected_text FROM content.transcript_corrections").fetchall()
            == []
        )
        conn.execute("SELECT set_config('app.user_id', %s, true)", [user])
        assert conn.execute(
            "SELECT corrected_text FROM content.transcript_corrections"
        ).fetchall() == [("Greetings",)]
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            f"DELETE FROM {parent} WHERE id=%s",
            [user if parent == "identity.users" else transcript_id],
        )
        assert conn.execute(
            "SELECT count(*) FROM content.transcript_corrections WHERE user_id=%s", [user]
        ).fetchone() == (0,)


def test_transcript_overlays_only_own_corrections_without_changing_word_identity(
    client, clip, make_client, api_role_url, migrated_url
):
    user = learner_id(client)
    media = cache(migrated_url, clip)
    correction(migrated_url, user, media, index=0, value="Outside edit")
    correction(migrated_url, user, media, index=1, value="Greetings")
    correction(migrated_url, user, media, index=2, value="")
    other = make_client(
        transcript_read_database_url=conninfo_to_url(migrated_url)
        + "?options=-c%20role%3Dlistenup_worker"
    )
    correction(migrated_url, learner_id(other), media, index=3, value="Foreign edit")
    other_clip = str(uuid.uuid4())
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "UPDATE content.media_objects SET source='youtube', uploaded_by=NULL WHERE id=%s",
            [media],
        )
        conn.execute(
            "INSERT INTO content.contents (id,user_id,media_object_id,title) "
            "VALUES (%s,%s,%s,'Shared')",
            [other_clip, learner_id(other), media],
        )
    for caller, content_id, expected in [
        (client, clip, [(0, "Greetings", True), (1, "", True), (2, "Again.", False)]),
        (other, other_clip, [(0, "Hello", False), (1, "world.", False), (2, "Foreign edit", True)]),
    ]:
        session = start(
            caller, content_id, "dictation", passage={"start_ms": 10000, "end_ms": 40000}
        )
        path = f"/api/v1/sessions/{session['id']}/transcript"
        assert caller.get(path).json()["code"] == "step_locked"
        finish(api_role_url, caller, session["id"], Step.DICTATION)
        response = caller.get(path)
        assert response.status_code == 200, response.text
        words = [word for line in response.json()["lines"] for word in line["words"]]
        assert [(word["index"], word["text"], word["edited"]) for word in words] == expected
        assert [(word["start_ms"], word["end_ms"]) for word in words] == [
            (11000, 11500),
            (12000, 13000),
            (30000, 31000),
        ]

        # The same service can be called with a privileged DB connection; its
        # explicit learner filter must still prevent another learner's overlay.
        async def privileged_read(reader, session_id):
            database = Database(conninfo_to_url(migrated_url))
            try:
                async with database.transaction() as db:
                    return await review.read_transcript(
                        db, database, uuid.UUID(reader), uuid.UUID(session_id)
                    )
            finally:
                await database.dispose()

        privileged = asyncio.run(privileged_read(learner_id(caller), session["id"]))
        assert [
            (w.index, w.text, w.edited) for line in privileged.lines for w in line.words
        ] == expected
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT words FROM content.passage_transcripts WHERE media_object_id=%s", [media]
        ).fetchone()[0] == ["Outside.", "Hello", "world.", "Again."]


def test_correction_identity_and_sentence_boundaries_survive_cache_composition(
    client, clip, api_role_url, migrated_url
):
    user = learner_id(client)
    ids = [uuid.uuid4(), uuid.uuid4()]
    with psycopg.connect(migrated_url) as conn:
        media = conn.execute(
            "SELECT media_object_id FROM content.contents WHERE id=%s", [clip]
        ).fetchone()[0]
        for row_id, span, word, at in zip(
            ids, ["[0,20000)", "[20000,40000)"], ["First.", "Second."], [11000, 30000], strict=True
        ):
            conn.execute(
                "INSERT INTO content.passage_transcripts "
                "(id,media_object_id,span,origin,status,words,start_ms,end_ms,"
                "confidence,sentence_starts,provider_info) "
                "VALUES (%s,%s,%s,'generated','ready',%s,%s,%s,ARRAY[900]::int2[],ARRAY[0],"
                '\'{"provider":"test","model":"fixture","version":"1"}\')',
                [row_id, media, span, [word], [at], [at + 500]],
            )
        for row_id, value in zip(ids, ["", "New second"], strict=True):
            conn.execute(
                "INSERT INTO content.transcript_corrections "
                "(user_id,passage_transcript_id,word_index,corrected_text) VALUES (%s,%s,0,%s)",
                [user, row_id, value],
            )
    session = start(client, clip, "dictation", passage={"start_ms": 10000, "end_ms": 40000})
    finish(api_role_url, client, session["id"], Step.DICTATION)
    response = client.get(f"/api/v1/sessions/{session['id']}/transcript")
    assert response.status_code == 200, response.text
    assert [
        [(w["index"], w["text"], w["edited"]) for w in line["words"]]
        for line in response.json()["lines"]
    ] == [[(0, "", True)], [(1, "New second", True)]]


def test_finishing_transcript_unlocks_card_and_persists_the_plan(client, clip, api_role_url):
    session = start(client, clip, "dictation")
    finish(api_role_url, client, session["id"], Step.DICTATION)
    path = f"/api/v1/sessions/{session['id']}/transcript/complete"
    response = client.post(path)
    assert response.status_code == 204, response.text
    updated = load(client, session)
    assert updated["open_step"] == "card"
    assert [(s["step"], s["status"]) for s in updated["steps"]] == [
        ("dictation", "done"),
        ("transcript", "done"),
        ("card", "open"),
        ("shadow", "locked"),
    ]
    # A duplicate/lost-answer retry must never finish Card or change the version.
    assert client.post(path).json()["code"] == "step_locked"
    assert load(client, session)["version"] == updated["version"]


def test_finishing_transcript_denies_locked_foreign_missing_and_unsigned_sessions(
    client, clip, make_client
):
    session = start(client, clip, "dictation")
    path = f"/api/v1/sessions/{session['id']}/transcript/complete"
    other = make_client()
    assert client.post(path).json()["code"] == "step_locked"
    assert load(client, session)["open_step"] == "dictation"
    assert other.post(path).json()["code"] == "session_not_found"
    assert (
        client.post(f"/api/v1/sessions/{uuid.uuid4()}/transcript/complete").json()["code"]
        == "session_not_found"
    )
    client.cookies.clear()
    with_csrf(client)
    assert client.post(path).json()["code"] == "not_signed_in"


def test_finishing_transcript_replays_a_key_without_advancing_card(client, clip, api_role_url):
    session = start(client, clip, "dictation")
    finish(api_role_url, client, session["id"], Step.DICTATION)
    path = f"/api/v1/sessions/{session['id']}/transcript/complete"
    headers = {"Idempotency-Key": f"transcript-{session['id']}"}
    first = client.post(path, headers=headers)
    updated = load(client, session)
    replay = client.post(path, headers=headers)
    assert first.status_code == replay.status_code == 204
    assert first.content == replay.content == b""
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert load(client, session) == updated
    assert updated["open_step"] == "card"


def test_a_refused_completion_does_not_consume_its_retry_key(client, clip, api_role_url):
    session = start(client, clip, "dictation")
    path = f"/api/v1/sessions/{session['id']}/transcript/complete"
    headers = {"Idempotency-Key": f"transcript-{session['id']}"}
    assert client.post(path, headers=headers).json()["code"] == "step_locked"
    finish(api_role_url, client, session["id"], Step.DICTATION)
    assert client.post(path, headers=headers).status_code == 204
    assert client.post(path, headers=headers).status_code == 204
    assert load(client, session)["open_step"] == "card"


def test_concurrent_completion_requests_with_one_key_persist_one_transition(
    client, clip, api_role_url
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    session = start(client, clip, "dictation")
    finish(api_role_url, client, session["id"], Step.DICTATION)
    before = load(client, session)
    path = f"/api/v1/sessions/{session['id']}/transcript/complete"
    headers = {"Idempotency-Key": f"transcript-{session['id']}"}
    both = Barrier(2)

    def complete():
        both.wait(timeout=5)
        return client.post(path, headers=headers)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(complete) for _ in range(2)]
        responses = [future.result(timeout=10) for future in futures]
    assert [response.status_code for response in responses] == [204, 204]
    assert sorted(response.headers.get("Idempotent-Replayed", "") for response in responses) == [
        "",
        "true",
    ]
    after = load(client, session)
    assert after["version"] == before["version"] + 1
    assert after["open_step"] == "card"


def test_completion_requires_csrf_even_with_a_valid_retry_key(client, clip, api_role_url):
    session = start(client, clip, "dictation")
    finish(api_role_url, client, session["id"], Step.DICTATION)
    before = load(client, session)
    del client.headers["X-CSRF-Token"]
    response = client.post(
        f"/api/v1/sessions/{session['id']}/transcript/complete",
        headers={"Idempotency-Key": "complete"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"
    assert load(client, session) == before


def test_completion_replay_still_requires_ownership_and_authentication(
    client, clip, api_role_url, make_client
):
    session = start(client, clip, "dictation")
    finish(api_role_url, client, session["id"], Step.DICTATION)
    path = f"/api/v1/sessions/{session['id']}/transcript/complete"
    headers = {"Idempotency-Key": f"transcript-{session['id']}"}
    assert client.post(path, headers=headers).status_code == 204
    updated = load(client, session)
    other = make_client()
    response = other.post(path, headers=headers)
    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"
    assert load(client, session) == updated
    client.cookies.clear()
    with_csrf(client)
    response = client.post(path, headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == "not_signed_in"
