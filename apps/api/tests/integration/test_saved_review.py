"""Saved reviews and marks use learner RLS and durable storage."""

import base64
import uuid

from tests.integration import test_cards_api as cards

create = cards.create
card_session = cards.card_session
client = cards.client
clip = cards.clip
make_client = cards.make_client
session_id = cards.session_id
worker_url = cards.worker_url


def test_review_results_persist_and_replay(client, card_session, make_client):
    card = create(client, card_session).json()
    path = f"/api/v1/cards/{card['id']}/reviews"
    assert client.get(path).status_code == 200
    for result in ("heard", "unsure", "missed"):
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        response = client.post(path, json={"result": result}, headers=headers)
        assert response.status_code == 201, response.text
        assert client.post(path, json={"result": result}, headers=headers).json() == response.json()
    history = client.get(path)
    assert history.headers["cache-control"] == "private, no-store"
    assert [r["result"] for r in history.json()["reviews"]] == ["missed", "unsure", "heard"]
    other = make_client()
    assert other.get(path).status_code == 404
    assert other.post(path, json={"result": "heard"}).status_code == 404
    assert client.post(path, json={"result": "easy"}).status_code == 422
    assert (
        client.post(path, json={"result": "heard"}, headers={"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    assert len(client.get(path).json()["reviews"]) == 3


def test_global_marks_keyset_and_source(client, card_session, make_client):
    from tests.integration.test_marks_api import new_mark

    session, mark_id = card_session
    added = client.post(f"/api/v1/sessions/{session}/marks", json=new_mark(word_from=2, word_to=2))
    assert added.status_code == 201
    page = client.get("/api/v1/marks?limit=1")
    assert page.status_code == 200, page.text
    data = page.json()
    assert data["marks"][0]["id"] == added.json()["id"]
    assert data["marks"][0]["source_url"].endswith("?at_ms=30000")
    second = client.get("/api/v1/marks", params={"limit": 1, "cursor": data["next_cursor"]}).json()
    assert [m["id"] for m in second["marks"]] == [mark_id]
    assert second["next_cursor"] is None
    assert make_client().get("/api/v1/marks").json()["marks"] == []
    naive = base64.urlsafe_b64encode(f"2026-10-26T10:00:00|{uuid.uuid4()}".encode()).decode()
    for cursor in ("bad", naive):
        assert client.get("/api/v1/marks", params={"cursor": cursor}).status_code == 422
    for limit in (0, 51):
        assert client.get("/api/v1/marks", params={"limit": limit}).status_code == 422


def test_second_login_retrieves_deck_marks_and_reviews(client, card_session, make_client):
    from tests.integration.intake_helpers import PASSWORD

    card = create(client, card_session).json()
    path = f"/api/v1/cards/{card['id']}/reviews"
    response = client.post(
        path, json={"result": "heard"}, headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    assert response.status_code == 201
    second = make_client()
    assert second.post("/api/v1/auth/logout").status_code == 204
    email = client.get("/api/v1/me").json()["email"]
    assert (
        second.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code
        == 200
    )
    assert second.get("/api/v1/cards").json()["cards"] == [card]
    assert second.get(path).json()["reviews"] == [response.json()]
    assert second.get("/api/v1/marks").json()["marks"][0]["id"] == card_session[1]


def test_marks_across_sessions_and_equal_timestamp_pages(
    client, card_session, clip, api_role_url, migrated_url
):
    import psycopg

    from listenup.modules.practice.service import Step
    from tests.integration.test_marks_api import new_mark
    from tests.integration.test_sessions_api import finish, start

    other = start(client, clip, "dictation", passage={"start_ms": 10000, "end_ms": 40000})
    finish(api_role_url, client, other["id"], Step.DICTATION)
    mark = client.post(f"/api/v1/sessions/{other['id']}/marks", json=new_mark()).json()
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE practice.marks SET created_at='2026-10-26T10:00:00Z' WHERE id IN (%s,%s)",
            [card_session[1], mark["id"]],
        )
    first = client.get("/api/v1/marks?limit=1").json()
    second = client.get("/api/v1/marks", params={"limit": 1, "cursor": first["next_cursor"]}).json()
    ids = [first["marks"][0]["id"], second["marks"][0]["id"]]
    assert ids == sorted([card_session[1], mark["id"]], reverse=True)
    assert {first["marks"][0]["session_id"], second["marks"][0]["session_id"]} == {
        card_session[0],
        other["id"],
    }
    assert second["next_cursor"] is None

    first_card = create(client, card_session).json()
    finish(api_role_url, client, other["id"], Step.TRANSCRIPT)
    other_card = create(client, (other["id"], mark["id"])).json()
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE practice.cards SET created_at='2026-10-26T10:00:00Z' WHERE id IN (%s,%s)",
            [first_card["id"], other_card["id"]],
        )
    page = client.get("/api/v1/cards?limit=1").json()
    following = client.get(
        "/api/v1/cards", params={"limit": 1, "cursor": page["next_cursor"]}
    ).json()
    assert [page["cards"][0]["id"], following["cards"][0]["id"]] == sorted(
        [first_card["id"], other_card["id"]], reverse=True
    )
    assert {page["cards"][0]["session_id"], following["cards"][0]["session_id"]} == {
        card_session[0],
        other["id"],
    }
    assert following["next_cursor"] is None


def test_review_foreign_key_result_constraint_and_card_cascade(
    client, card_session, migrated_url, make_client
):
    import psycopg
    import pytest

    from tests.integration.intake_helpers import learner_id

    card = create(client, card_session).json()
    other = learner_id(make_client())
    with psycopg.connect(migrated_url, autocommit=True) as db:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            db.execute(
                "INSERT INTO practice.card_reviews(id,card_id,user_id,result) VALUES (%s,%s,%s,%s)",
                [uuid.uuid4(), card["id"], other, "heard"],
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "INSERT INTO practice.card_reviews(id,card_id,user_id,result) VALUES (%s,%s,%s,%s)",
                [uuid.uuid4(), card["id"], learner_id(client), "easy"],
            )
    path = f"/api/v1/cards/{card['id']}/reviews"
    assert (
        client.post(
            path, json={"result": "missed"}, headers={"Idempotency-Key": str(uuid.uuid4())}
        ).status_code
        == 201
    )
    assert client.delete(f"/api/v1/cards/{card['id']}").status_code == 204
    assert client.get(path).status_code == 404
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT count(*) FROM practice.card_reviews WHERE card_id=%s", [card["id"]]
        ).fetchone() == (0,)
