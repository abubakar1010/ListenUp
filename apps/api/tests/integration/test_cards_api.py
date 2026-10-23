"""Card creation from marks: FR-CA-1..3, AT-5, D14 (#72)."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from listenup.modules.practice.service import Step
from tests.integration import test_marks_api as marks
from tests.integration.test_sessions_api import finish

client = marks.client
clip = marks.clip
make_client = marks.make_client
session_id = marks.session_id
worker_url = marks.worker_url
new_mark = marks.new_mark


@pytest.fixture
def card_session(client, session_id, api_role_url):
    mark = client.post(f"/api/v1/sessions/{session_id}/marks", json=new_mark()).json()
    finish(api_role_url, client, session_id, Step.TRANSCRIPT)
    return session_id, mark["id"]


def create(client, card_session, **changes):
    session, mark = card_session
    return client.post(
        f"/api/v1/sessions/{session}/cards",
        json={
            "mark_id": mark,
            "written_form": "could have",
            "heard_form": "kʊdəv",
            **changes,
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )


def test_two_cards_succeed_third_refused(client, card_session, migrated_url):
    one, two, third = [create(client, card_session) for _ in range(3)]
    assert [r.status_code for r in (one, two, third)] == [201, 201, 409]
    assert [one.json()["slot"], two.json()["slot"]] == [1, 2]
    assert third.json()["code"] == "card_limit_reached"
    card = one.json()
    assert card["at_ms"] == 11000
    assert card["source_url"].endswith("?at_ms=11000")
    assert "definition" not in card and "translation" not in card
    listed = client.get("/api/v1/cards", params={"session_id": card_session[0]}).json()
    assert len(listed["cards"]) == 2 and listed["remaining"] == 0
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT count(*) FROM ops.analytics_events "
            "WHERE event_type='card_created' AND session_id=%s",
            [card_session[0]],
        ).fetchone() == (2,)


def test_delete_frees_slot(client, card_session):
    first = create(client, card_session).json()
    create(client, card_session)
    assert client.delete(f"/api/v1/cards/{first['id']}").status_code == 204
    replacement = create(client, card_session)
    assert replacement.status_code == 201
    assert replacement.json()["slot"] == first["slot"]
    assert client.delete(f"/api/v1/cards/{first['id']}").status_code == 404


def test_concurrent_last_slot_creates_one(client, card_session):
    assert create(client, card_session).status_code == 201
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: create(client, card_session), range(2)))
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert next(r for r in responses if r.status_code == 409).json()["code"] == "card_limit_reached"
    assert (
        len(client.get("/api/v1/cards", params={"session_id": card_session[0]}).json()["cards"])
        == 2
    )


@pytest.mark.parametrize("field", ["written_form", "heard_form"])
@pytest.mark.parametrize("length, status", [(0, 422), (1, 201), (100, 201), (101, 422)])
def test_form_boundaries(client, card_session, field, length, status):
    assert create(client, card_session, **{field: "a" * length}).status_code == status


def test_invalid_mark_and_unknown_fields_leave_no_cards(client, card_session):
    assert create(client, card_session, mark_id=str(uuid.uuid4())).status_code == 404
    assert create(client, card_session, definition="meaning").status_code == 422
    assert client.get("/api/v1/cards", params={"session_id": card_session[0]}).json()["cards"] == []


def test_creation_replay_and_completion(client, card_session):
    path = f"/api/v1/sessions/{card_session[0]}/cards"
    body = {"mark_id": card_session[1], "written_form": "could have", "heard_form": "kuduv"}
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    first = client.post(path, json=body, headers=headers)
    again = client.post(path, json=body, headers=headers)
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    for _ in range(2):
        assert client.post(path + "/complete", headers=headers).status_code == 204
    assert client.get(f"/api/v1/sessions/{card_session[0]}").json()["open_step"] == "shadow"
    assert create(client, card_session).json()["code"] == "step_locked"


def test_locked_and_foreign_session(client, session_id, make_client):
    response = create(client, (session_id, str(uuid.uuid4())))
    assert response.status_code == 409 and response.json()["code"] == "step_locked"
    other = make_client()
    response = create(other, (session_id, str(uuid.uuid4())))
    assert response.status_code == 404 and response.json()["code"] == "session_not_found"
    assert other.get("/api/v1/cards", params={"session_id": session_id}).status_code == 404


def test_list_and_delete_isolated_and_paginated(client, card_session, make_client):
    first = create(client, card_session).json()
    second = create(client, card_session).json()
    other = make_client()
    assert other.get("/api/v1/cards").json()["cards"] == []
    assert other.delete(f"/api/v1/cards/{first['id']}").status_code == 404
    page = client.get("/api/v1/cards?limit=1").json()
    assert page["cards"][0]["id"] == second["id"]
    next_page = client.get(
        "/api/v1/cards", params={"cursor": page["next_cursor"], "limit": 1}
    ).json()
    assert next_page["cards"][0]["id"] == first["id"] and next_page["next_cursor"] is None
    assert client.get("/api/v1/cards?cursor=bad").status_code == 422


def test_removing_mark_preserves_card_source_and_forms(client, card_session):
    saved = create(client, card_session).json()
    assert (
        client.delete(f"/api/v1/sessions/{card_session[0]}/marks/{card_session[1]}").status_code
        == 204
    )
    listed = client.get("/api/v1/cards").json()["cards"]
    assert len(listed) == 1
    assert listed[0] == {**saved, "mark_id": None}


def test_mark_from_another_session_cannot_be_used(client, card_session, clip, api_role_url):
    from tests.integration.test_sessions_api import start

    other = start(client, clip, "dictation", passage={"start_ms": 10000, "end_ms": 40000})
    finish(api_role_url, client, other["id"], Step.DICTATION)
    mark = client.post(f"/api/v1/sessions/{other['id']}/marks", json=new_mark()).json()
    response = create(client, card_session, mark_id=mark["id"])
    assert response.status_code == 404 and response.json()["code"] == "mark_not_found"
    assert client.get("/api/v1/cards").json()["cards"] == []
