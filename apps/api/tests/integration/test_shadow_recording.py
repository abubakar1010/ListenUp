"""FR-SH-5/8/16/17, AT-16: each Shadow round is recorded, uploaded privately and replayed."""

import functools
import uuid

import psycopg
import pytest

from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import FakeStorage, client_factory, learner_id
from tests.integration.test_shadow_rounds import base, end_round, setup, start_round

MB = 1024 * 1024


@pytest.fixture
def storage():
    return FakeStorage()


@pytest.fixture
def make(api_role_url, migrated_url, storage):
    url = conninfo_to_url(migrated_url) + "?options=-c%20role%3Dlistenup_worker"
    for factory in client_factory(api_role_url, storage):
        yield functools.partial(factory, transcript_read_database_url=url)


@pytest.fixture
def client(make):
    return make()


def recording_path(sid, number):
    return f"{base(sid)}/{number}/recording"


def request_upload(client, sid, number, mime="audio/webm", size=200_000):
    return client.post(recording_path(sid, number), json={"mime": mime, "size_bytes": size})


def complete(client, round_id, key=None):
    return client.post(
        f"/api/v1/shadow/rounds/{round_id}/complete",
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
    )


def key_of(upload):
    return upload["url"].split("/bucket/", 1)[1].split("?", 1)[0]


def record_round(client, storage, sid, number, mime="audio/webm", size=200_000):
    assert start_round(client, sid, number).status_code == 204
    assert end_round(client, sid, number).status_code == 204
    started = request_upload(client, sid, number, mime, size)
    assert started.status_code == 200, started.text
    body = started.json()
    storage.arrive(key_of(body["upload"]), size, mime)
    assert complete(client, body["round_id"]).status_code == 204
    return body


def test_three_rounds_produce_three_replayable_recordings(
    client, migrated_url, api_role_url, storage
):
    sid = setup(client, migrated_url, api_role_url)
    user = learner_id(client)
    ids = []
    for number in (1, 2, 3):
        mime = "audio/mp4" if number == 3 else "audio/webm"
        body = record_round(client, storage, sid, number, mime)
        ids.append(body["round_id"])
        key = key_of(body["upload"])
        assert key.startswith(f"users/{user}/shadow/{sid}/round-{number}-{body['round_id']}")
        assert key.endswith(".m4a" if number == 3 else ".webm")
        assert body["upload"]["method"] == "PUT"
        assert body["upload"]["headers"] == {"Content-Type": mime}
        assert (key, mime, 200_000) in storage.signed
    state = client.get(base(sid)).json()
    assert [r["id"] for r in state["rounds"]] == ids
    for entry in state["rounds"]:
        assert entry["recorded_at"] is not None
        assert entry["recording_available"] is True
        assert entry["feedback"] == "unavailable"
    for round_id in ids:
        replay = client.get(f"/api/v1/shadow/rounds/{round_id}/recording", follow_redirects=False)
        assert replay.status_code == 307
        assert replay.headers["location"].startswith(f"http://storage.test/bucket/users/{user}/")
        assert replay.headers["cache-control"] == "private, no-store"
    assert all(ttl is not None and ttl <= 120 for _, ttl in storage.downloads)
    session = client.get(f"/api/v1/sessions/{sid}").json()
    assert session["open_step"] == "shadow" and session["completed_at"] is None
    with psycopg.connect(migrated_url) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM practice.shadow_rounds WHERE session_id=%s "
                "AND recorded_at IS NOT NULL AND uploaded_at IS NOT NULL",
                [sid],
            ).fetchone()[0]
            == 3
        )


def test_other_learner_gets_404_on_recording(make, migrated_url, api_role_url, storage):
    owner = make()
    sid = setup(owner, migrated_url, api_role_url)
    body = record_round(owner, storage, sid, 1)
    other = make()
    for method, url in (
        ("GET", f"/api/v1/shadow/rounds/{body['round_id']}/recording"),
        ("POST", f"/api/v1/shadow/rounds/{body['round_id']}/complete"),
    ):
        response = other.request(
            method, url, headers={"Idempotency-Key": str(uuid.uuid4())}, follow_redirects=False
        )
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "round_not_found"
        assert body["round_id"] not in response.text
    assert request_upload(other, sid, 1).json()["code"] == "session_not_found"
    assert len(storage.downloads) == 0


@pytest.mark.parametrize(
    ("mime", "size", "code"),
    [
        ("audio/mpeg", 1000, "recording_type"),
        ("video/webm", 1000, "recording_type"),
        ("audio/webm", 0, "recording_size"),
        ("audio/webm", 5 * MB + 1, "recording_size"),
    ],
)
def test_recording_mime_and_size_validated(client, migrated_url, api_role_url, mime, size, code):
    sid = setup(client, migrated_url, api_role_url)
    start_round(client, sid, 1)
    end_round(client, sid, 1)
    response = request_upload(client, sid, 1, mime, size)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == code


def test_limits_and_codec_parameters(client, migrated_url, api_role_url, storage):
    sid = setup(client, migrated_url, api_role_url)
    start_round(client, sid, 1)
    end_round(client, sid, 1)
    ok = request_upload(client, sid, 1, "audio/webm;codecs=opus", 5 * MB)
    assert ok.status_code == 200, ok.text
    assert storage.signed[-1][1:] == ("audio/webm", 5 * MB)


def test_stored_object_must_match_the_declared_size_and_type(
    client, migrated_url, api_role_url, storage
):
    sid = setup(client, migrated_url, api_role_url)
    start_round(client, sid, 1)
    end_round(client, sid, 1)
    body = request_upload(client, sid, 1).json()
    key = key_of(body["upload"])
    missing = complete(client, body["round_id"])
    assert (missing.status_code, missing.json()["code"]) == (409, "upload_incomplete")
    storage.arrive(key, 123, "audio/webm")
    wrong_size = complete(client, body["round_id"])
    assert (wrong_size.status_code, wrong_size.json()["code"]) == (409, "upload_size_mismatch")
    assert key in storage.deleted
    storage.arrive(key, 200_000, "audio/mpeg")
    wrong_type = complete(client, body["round_id"])
    assert (wrong_type.status_code, wrong_type.json()["code"]) == (409, "upload_type_mismatch")
    assert client.get(base(sid)).json()["rounds"][0]["recorded_at"] is None


def test_failed_upload_retried_without_rerecording(client, migrated_url, api_role_url, storage):
    sid = setup(client, migrated_url, api_role_url)
    start_round(client, sid, 1)
    end_round(client, sid, 1)
    first = request_upload(client, sid, 1).json()
    # The browser's PUT failed: ask again for the same round and upload the same blob.
    again = request_upload(client, sid, 1).json()
    assert again["round_id"] == first["round_id"]
    assert key_of(again["upload"]) == key_of(first["upload"])
    storage.arrive(key_of(again["upload"]), 200_000, "audio/webm")
    key = str(uuid.uuid4())
    assert complete(client, first["round_id"], key).status_code == 204
    assert complete(client, first["round_id"], key).status_code == 204
    assert complete(client, first["round_id"]).status_code == 204
    once = client.get(base(sid)).json()["rounds"][0]["recorded_at"]
    assert complete(client, first["round_id"]).status_code == 204
    assert client.get(base(sid)).json()["rounds"][0]["recorded_at"] == once
    locked = request_upload(client, sid, 1)
    assert (locked.status_code, locked.json()["code"]) == (409, "recording_exists")


def test_recording_needs_consent_ended_playback_and_the_shadow_step(
    client, make, migrated_url, api_role_url
):
    sid = setup(client, migrated_url, api_role_url)
    early = request_upload(client, sid, 1)
    assert (early.status_code, early.json()["code"]) == (409, "round_order")
    start_round(client, sid, 1)
    playing = request_upload(client, sid, 1)
    assert (playing.status_code, playing.json()["code"]) == (409, "round_order")
    end_round(client, sid, 1)
    client.post("/api/v1/me/consents/withdraw", json={"kind": "voice_recording"})
    refused = request_upload(client, sid, 1)
    assert (refused.status_code, refused.json()["code"]) == (403, "voice_consent_required")


def test_database_keeps_recordings_private_and_write_once(
    client, migrated_url, api_role_url, storage
):
    sid = setup(client, migrated_url, api_role_url)
    user = learner_id(client)
    body = record_round(client, storage, sid, 1)
    with psycopg.connect(migrated_url, autocommit=True) as db:
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "UPDATE practice.shadow_rounds SET recording_key=%s WHERE id=%s",
                [f"users/{uuid.uuid4()}/shadow/x.webm", body["round_id"]],
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "UPDATE practice.shadow_rounds SET recording_mime='audio/mpeg' WHERE id=%s",
                [body["round_id"]],
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "UPDATE practice.shadow_rounds SET recording_bytes=%s WHERE id=%s",
                [5 * MB + 1, body["round_id"]],
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "UPDATE practice.shadow_rounds SET recording_key=%s WHERE id=%s",
                [f"users/{user}/shadow/other.webm", body["round_id"]],
            )


def test_unrecorded_round_has_no_replay_and_cannot_complete_without_an_upload_url(
    client, migrated_url, api_role_url
):
    sid = setup(client, migrated_url, api_role_url)
    start_round(client, sid, 1)
    end_round(client, sid, 1)
    round_id = client.get(base(sid)).json()["rounds"][0]["id"]
    replay = client.get(f"/api/v1/shadow/rounds/{round_id}/recording", follow_redirects=False)
    assert (replay.status_code, replay.json()["code"]) == (409, "recording_not_ready")
    early = complete(client, round_id)
    assert (early.status_code, early.json()["code"]) == (409, "round_order")


def test_asking_again_with_another_type_deletes_the_unreferenced_object(
    client, migrated_url, api_role_url, storage
):
    sid = setup(client, migrated_url, api_role_url)
    start_round(client, sid, 1)
    end_round(client, sid, 1)
    first = request_upload(client, sid, 1, "audio/webm").json()
    old = key_of(first["upload"])
    storage.arrive(old, 200_000, "audio/webm")
    second = request_upload(client, sid, 1, "audio/mp4").json()
    assert key_of(second["upload"]) != old
    assert old in storage.deleted
    assert key_of(second["upload"]) not in storage.deleted


def test_completion_is_refused_and_the_upload_dropped_after_consent_is_withdrawn(
    client, migrated_url, api_role_url, storage
):
    sid = setup(client, migrated_url, api_role_url)
    start_round(client, sid, 1)
    end_round(client, sid, 1)
    body = request_upload(client, sid, 1).json()
    storage.arrive(key_of(body["upload"]), 200_000, "audio/webm")
    client.post("/api/v1/me/consents/withdraw", json={"kind": "voice_recording"})
    refused = complete(client, body["round_id"])
    assert (refused.status_code, refused.json()["code"]) == (403, "voice_consent_required")
    assert key_of(body["upload"]) in storage.deleted
    assert client.get(base(sid)).json()["rounds"][0]["recorded_at"] is None
