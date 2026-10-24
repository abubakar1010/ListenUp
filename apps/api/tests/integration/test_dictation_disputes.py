"""Learner-only reference disputes (#56, FR-TX-3/4)."""

import concurrent.futures
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.platform.storage import S3Storage, use_storage

from tests.integration.conftest import conninfo_to_url
from tests.integration.dictation_helpers import media_of, seed_transcript
from tests.integration.intake_helpers import ClientFactory, FakeStorage, client_factory, learner_id
from tests.integration.test_account_deletion import delete_me, make_due, sweep_queues_purge
from tests.integration.test_dictation_api import attempt_of
from tests.integration.test_dictation_marks import add, mark, rows, scored_attempt
from tests.integration.test_dictation_result import read, run_scoring
from tests.integration.test_dictation_submit import submit
from tests.integration.test_password_reset import deliver
from tests.integration.test_sessions_api import add_clip, start


@pytest.fixture
def storage() -> Iterator[FakeStorage]:
    fake = FakeStorage()
    use_storage(fake)
    yield fake
    use_storage(None)


@pytest.fixture
def make_client(api_role_url: str, storage: FakeStorage) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, storage)


@pytest.fixture
def client(make_client: ClientFactory, migrated_url: str) -> TestClient:
    return make_client(
        transcript_read_database_url=conninfo_to_url(migrated_url)
        + "?options=-c%20role%3Dlistenup_worker"
    )


@pytest.fixture
def attempt(client, migrated_url):
    clip = add_clip(migrated_url, learner_id(client))
    return scored_attempt(client, migrated_url, clip, "cap", ["cat"])


def dispute(client, attempt_id, word_index=0, corrected_text="cap", **kwargs):
    return client.post(
        f"/api/v1/dictation/attempts/{attempt_id}/disputes",
        json={"word_index": word_index, "corrected_text": corrected_text},
        **kwargs,
    )


def test_dispute_cat_to_cap_recalculates_accuracy_and_marks_edited(client, attempt, migrated_url):
    assert read(client, attempt["id"])["result"]["accuracy"] == 0

    response = dispute(client, attempt["id"])

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    result = response.json()["result"]
    assert result["accuracy"] == 100
    assert result["items"] == [{"index": 0, "status": "correct", "word": "cap", "typed": "cap"}]
    assert read(client, attempt["id"]) == response.json()
    transcript = client.get(f"/api/v1/sessions/{attempt['session_id']}/transcript")
    assert transcript.status_code == 200, transcript.text
    assert transcript.json()["lines"][0]["words"][0] == {
        "index": 0,
        "text": "cap",
        "start_ms": 1000,
        "end_ms": 1800,
        "edited": True,
    }
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT words FROM content.passage_transcripts WHERE id IN "
            "(SELECT passage_transcript_id FROM content.transcript_corrections WHERE user_id=%s)",
            [learner_id(client)],
        ).fetchall() == [(["cat"],)]


def share_clip(client, other, attempt, url):
    with psycopg.connect(url) as conn:
        media = conn.execute(
            "SELECT c.media_object_id FROM content.contents c JOIN practice.sessions s "
            "ON s.content_id=c.id WHERE s.id=%s",
            [attempt["session_id"]],
        ).fetchone()[0]
        conn.execute(
            "UPDATE content.media_objects SET source='youtube',uploaded_by=NULL WHERE id=%s",
            [media],
        )
        content_id = uuid.uuid4()
        conn.execute(
            "INSERT INTO content.contents (id,user_id,media_object_id,title) "
            "VALUES (%s,%s,%s,'Shared')",
            [content_id, learner_id(other), media],
        )
    return str(content_id), media


def test_dispute_keeps_shared_passage_original_for_learner_b(
    client, make_client, attempt, migrated_url
):
    other = make_client(
        transcript_read_database_url=conninfo_to_url(migrated_url)
        + "?options=-c%20role%3Dlistenup_worker"
    )
    clip, _ = share_clip(client, other, attempt, migrated_url)
    session = start(other, clip, entry="dictation")
    other_attempt = attempt_of(other, session)
    submit(other, other_attempt["id"], session, "cap")
    assert dispute(client, attempt["id"]).status_code == 200
    run_scoring(migrated_url, other, other_attempt["id"])
    assert read(other, other_attempt["id"])["result"]["accuracy"] == 0
    word = other.get(f"/api/v1/sessions/{session['id']}/transcript").json()["lines"][0]["words"][0]
    assert (word["text"], word["edited"]) == ("cat", False)
    assert dispute(other, attempt["id"]).json()["code"] == "attempt_not_found"


def test_corrections_deleted_with_content_while_shared_cache_and_other_learner_remain(
    client, make_client, attempt, migrated_url
):
    other = make_client(
        transcript_read_database_url=conninfo_to_url(migrated_url)
        + "?options=-c%20role%3Dlistenup_worker"
    )
    clip, media = share_clip(client, other, attempt, migrated_url)
    session = start(other, clip, entry="dictation")
    other_attempt = attempt_of(other, session)
    submit(other, other_attempt["id"], session, "cap")
    run_scoring(migrated_url, other, other_attempt["id"])
    assert dispute(client, attempt["id"]).status_code == 200
    assert dispute(other, other_attempt["id"], corrected_text="can").status_code == 200
    user, other_user = learner_id(client), learner_id(other)
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "DELETE FROM content.contents WHERE user_id=%s AND media_object_id=%s", [user, media]
        )
        assert conn.execute(
            "SELECT user_id::text,corrected_text FROM content.transcript_corrections "
            "WHERE user_id IN (%s,%s)",
            [user, other_user],
        ).fetchall() == [(other_user, "can")]
        assert conn.execute(
            "SELECT words FROM content.passage_transcripts WHERE media_object_id=%s", [media]
        ).fetchall() == [(["cat"],)]


def test_dispute_preserves_existing_marks_and_notes_but_replaces_candidates(
    client, attempt, migrated_url
):
    made = mark(0)
    assert add(client, attempt["id"], made).status_code == 200
    with psycopg.connect(migrated_url) as conn:
        conn.execute("UPDATE practice.marks SET note='Keep practising' WHERE id=%s", [made["id"]])
    before = rows(migrated_url, attempt["session_id"])
    assert dispute(client, attempt["id"]).status_code == 200
    assert rows(migrated_url, attempt["session_id"]) == before
    refused = add(client, attempt["id"], mark(0))
    assert refused.status_code == 422
    assert refused.json()["code"] == "not_a_mark_candidate"


@pytest.mark.parametrize("value", ["", "cap hat", "x" * 60])
def test_replacements_preserve_word_indices_and_audio_times(client, attempt, value):
    response = dispute(client, attempt["id"], corrected_text=value)
    assert response.status_code == 200, response.text
    word = client.get(f"/api/v1/sessions/{attempt['session_id']}/transcript").json()["lines"][0][
        "words"
    ][0]
    assert word == {"index": 0, "text": value, "start_ms": 1000, "end_ms": 1800, "edited": True}


@pytest.mark.parametrize("index,value", [(-1, "cap"), (1, "cap"), (2**31, "cap"), (0, "x" * 61)])
def test_invalid_dispute_has_no_side_effects(client, attempt, migrated_url, index, value):
    before = read(client, attempt["id"])
    response = dispute(client, attempt["id"], index, value)
    assert response.status_code == 422, response.text
    assert read(client, attempt["id"]) == before
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT count(*) FROM content.transcript_corrections WHERE user_id=%s",
            [learner_id(client)],
        ).fetchone() == (0,)


@pytest.mark.parametrize("submitted", [False, True])
def test_unscored_attempt_cannot_be_disputed(client, migrated_url, submitted):
    clip = add_clip(migrated_url, learner_id(client))
    session = start(client, clip, entry="dictation")
    attempt = attempt_of(client, session)
    if submitted:
        submit(client, attempt["id"], session, "cap")
    response = dispute(client, attempt["id"])
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "attempt_not_scored"


def test_retry_does_not_undo_a_later_correction(client, attempt, migrated_url):
    key = {"Idempotency-Key": "first-correction"}
    first = dispute(client, attempt["id"], headers=key)
    assert first.status_code == 200, first.text
    assert dispute(client, attempt["id"], corrected_text="can").status_code == 200
    again = dispute(client, attempt["id"], headers=key)
    assert again.json() == first.json()
    assert read(client, attempt["id"])["result"]["items"][0]["word"] == "can"
    refused = dispute(client, attempt["id"], corrected_text="car", headers=key)
    assert refused.status_code == 422
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT corrected_text FROM content.transcript_corrections WHERE user_id=%s",
            [learner_id(client)],
        ).fetchall() == [("can",)]


def test_future_attempt_is_scored_with_own_corrections(client, attempt, migrated_url):
    assert dispute(client, attempt["id"]).status_code == 200
    with psycopg.connect(migrated_url) as conn:
        clip = str(
            conn.execute(
                "SELECT content_id FROM practice.sessions WHERE id=%s", [attempt["session_id"]]
            ).fetchone()[0]
        )
    session = start(client, clip, entry="dictation")
    next_attempt = attempt_of(client, session)
    assert next_attempt.get("result") is None
    assert submit(client, next_attempt["id"], session, "cap", key="next-attempt").status_code == 202
    run_scoring(migrated_url, client, next_attempt["id"])
    assert read(client, next_attempt["id"])["result"]["accuracy"] == 100


def test_dispute_rollback_keeps_correction_score_and_events_atomic(
    client, attempt, migrated_url, monkeypatch
):
    from listenup.modules.dictation import repository

    before = read(client, attempt["id"])

    async def unavailable(*args, **kwargs):
        raise RuntimeError("write failed")

    monkeypatch.setattr(repository, "rescore", unavailable)
    response = dispute(client, attempt["id"])
    assert response.status_code == 500
    assert read(client, attempt["id"]) == before
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT count(*) FROM content.transcript_corrections WHERE user_id=%s",
            [learner_id(client)],
        ).fetchone() == (0,)


def test_concurrent_disputes_on_different_words_keep_both_corrections_and_score(
    client, migrated_url
):
    clip = add_clip(migrated_url, learner_id(client))
    attempt = scored_attempt(client, migrated_url, clip, "cap dog", ["cat", "dig"])
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(dispute, client, attempt["id"], i, text)
            for i, text in enumerate(["cap", "dog"])
        ]
        for future in futures:
            response = future.result(timeout=10)
            assert response.status_code == 200, response.text
    assert read(client, attempt["id"])["result"]["accuracy"] == 100
    words = client.get(f"/api/v1/sessions/{attempt['session_id']}/transcript").json()["lines"][0][
        "words"
    ]
    assert [(w["text"], w["edited"]) for w in words] == [("cap", True), ("dog", True)]


def test_dispute_maps_partial_passage_index_to_second_cache_span(client, migrated_url):
    clip = add_clip(migrated_url, learner_id(client))
    media = media_of(migrated_url, clip)
    seed_transcript(migrated_url, media, ["Outside", "Hello"])
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "UPDATE content.passage_transcripts SET span='[0,30000)' WHERE media_object_id=%s",
            [media],
        )
        conn.execute(
            "INSERT INTO content.passage_transcripts "
            "(id,media_object_id,span,origin,status,words,start_ms,end_ms,confidence,"
            "sentence_starts,provider_info) "
            "VALUES (%s,%s,'[30000,125000)','generated','ready',ARRAY['cat'],ARRAY[31000],"
            "ARRAY[31800],ARRAY[900]::int2[],ARRAY[0],"
            '\'{"provider":"test","model":"speech","version":"1"}\')',
            [uuid.uuid4(), media],
        )
    session = start(client, clip, entry="dictation", passage={"start_ms": 2000, "end_ms": 62000})
    attempt = attempt_of(client, session)
    submit(client, attempt["id"], session, "Hello cap")
    run_scoring(migrated_url, client, attempt["id"])
    response = dispute(client, attempt["id"], 1)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["accuracy"] == 100
    with psycopg.connect(migrated_url) as conn:
        assert (
            conn.execute(
                "SELECT c.word_index,p.span FROM content.transcript_corrections c "
                "JOIN content.passage_transcripts p ON p.id=c.passage_transcript_id "
                "WHERE c.user_id=%s",
                [learner_id(client)],
            ).fetchone()[0]
            == 0
        )


def test_corrections_deleted_by_account_purge_while_shared_cache_remains(
    client, make_client, attempt, migrated_url, storage, monkeypatch
):
    async def unexpected_s3(*args, **kwargs):
        pytest.fail("Account purge must use the test's storage, not the real S3 bucket")

    monkeypatch.setattr(S3Storage, "delete_prefix", unexpected_s3)
    other = make_client()
    _, media = share_clip(client, other, attempt, migrated_url)
    assert dispute(client, attempt["id"]).status_code == 200
    user = uuid.UUID(learner_id(client))
    own_key = f"users/{user}/media/recording.mp4"
    other_key = f"users/{learner_id(other)}/media/recording.mp4"
    for key in (own_key, other_key):
        storage.arrive(key, 10)
    assert delete_me(client).status_code == 202
    make_due(migrated_url, user)
    assert sweep_queues_purge(migrated_url, user)
    deliver(migrated_url)
    assert own_key not in storage.objects
    assert other_key in storage.objects
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT count(*) FROM identity.users WHERE id=%s", [user]
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM content.transcript_corrections WHERE user_id=%s", [user]
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT words FROM content.passage_transcripts WHERE media_object_id=%s", [media]
        ).fetchall() == [(["cat"],)]
