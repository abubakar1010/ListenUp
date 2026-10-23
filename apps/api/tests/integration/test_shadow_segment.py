"""AT-6 (part): real API-role requests and PostgreSQL constraints, no rounds."""

import uuid

import psycopg
import pytest

from listenup.modules.practice.service import Step
from tests.integration.intake_helpers import FakeStorage, client_factory, learner_id
from tests.integration.test_sessions_api import add_clip, finish, start


@pytest.fixture
def client(api_role_url):
    for make in client_factory(api_role_url, FakeStorage()):
        yield make()


def open_shadow(client, migrated_url, api_role_url, end=120_000):
    content = add_clip(migrated_url, learner_id(client))
    session = start(client, content, "dictation", passage={"start_ms": 0, "end_ms": end})
    finish(api_role_url, client, session["id"], Step.DICTATION, Step.TRANSCRIPT, Step.CARD)
    return str(session["id"])


def path(sid):
    return f"/api/v1/sessions/{sid}/shadow/segment"


def test_proposal_is_persisted_and_learner_choice_survives_reload(
    client, migrated_url, api_role_url
):
    sid = open_shadow(client, migrated_url, api_role_url)
    response = client.get(path(sid))
    assert response.status_code == 200, response.text
    assert response.json()["chosen_by"] == "system"
    assert response.json()["end_ms"] == 90_000
    changed = client.put(path(sid), json={"start_ms": 20_000, "end_ms": 80_000})
    assert changed.status_code == 200, changed.text
    assert changed.json()["chosen_by"] == "learner"
    assert client.get(path(sid)).json() == changed.json()


@pytest.mark.parametrize("end", [59_999, 90_001, 120_001])
def test_api_refuses_invalid_segment_length(client, migrated_url, api_role_url, end):
    sid = open_shadow(client, migrated_url, api_role_url)
    response = client.put(path(sid), json={"start_ms": 0, "end_ms": end})
    assert response.status_code == 422
    assert response.json()["code"] == "segment_span"


def test_45_second_passage_allows_only_whole_passage(client, migrated_url, api_role_url):
    sid = open_shadow(client, migrated_url, api_role_url, 45_000)
    assert client.get(path(sid)).json()["end_ms"] == 45_000
    for start_ms, end_ms in [(0, 44_999), (1, 45_000), (0, 60_000)]:
        assert (
            client.put(path(sid), json={"start_ms": start_ms, "end_ms": end_ms}).status_code == 422
        )
    assert client.put(path(sid), json={"start_ms": 0, "end_ms": 45_000}).status_code == 200


def test_locked_segment_refuses_changes(client, migrated_url, api_role_url):
    sid = open_shadow(client, migrated_url, api_role_url)
    client.get(path(sid))
    with psycopg.connect(migrated_url, autocommit=True) as db:
        db.execute(
            "UPDATE practice.shadow_segments SET locked_at = now() WHERE session_id = %s", [sid]
        )
        with pytest.raises(psycopg.errors.CheckViolation, match="segment_locked"):
            db.execute(
                "UPDATE practice.shadow_segments SET span = '[10000,70000)' WHERE session_id = %s",
                [sid],
            )
        with pytest.raises(psycopg.errors.CheckViolation, match="segment_locked"):
            db.execute(
                "UPDATE practice.shadow_segments SET locked_at = NULL WHERE session_id = %s", [sid]
            )
    response = client.put(path(sid), json={"start_ms": 10_000, "end_ms": 70_000})
    assert response.status_code == 409
    assert response.json()["code"] == "segment_locked"


@pytest.mark.parametrize("span", ["[0,59999)", "[0,90001)", "[60000,120001)", "empty", "(,90000)"])
def test_database_enforces_segment_length(client, migrated_url, api_role_url, span):
    sid = open_shadow(client, migrated_url, api_role_url)
    with psycopg.connect(migrated_url) as db, pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO practice.shadow_segments (session_id,user_id,span,chosen_by,mark_count) "
            "VALUES (%s,%s,%s::int4range,'system',0)",
            [sid, learner_id(client), span],
        )


def test_database_short_passage_must_be_whole(client, migrated_url, api_role_url):
    sid = open_shadow(client, migrated_url, api_role_url, 45_000)
    with psycopg.connect(migrated_url) as db, pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO practice.shadow_segments (session_id,user_id,span,chosen_by,mark_count) "
            "VALUES (%s,%s,'[0,40000)','system',0)",
            [sid, learner_id(client)],
        )


def test_marks_are_counted_in_proposed_and_adjusted_segment(client, migrated_url, api_role_url):
    sid = open_shadow(client, migrated_url, api_role_url)
    with psycopg.connect(migrated_url) as db:
        for index, at in enumerate([10_000, 90_000, 100_000, 110_000]):
            db.execute(
                "INSERT INTO practice.marks (id,session_id,user_id,word_from,word_to,at_ms,source) "
                "VALUES (%s,%s,%s,%s,%s,%s,'manual')",
                [uuid.uuid4(), sid, learner_id(client), index, index, at],
            )
    proposed = client.get(path(sid)).json()
    assert proposed["mark_count"] == 3
    changed = client.put(path(sid), json={"start_ms": 0, "end_ms": 60_000})
    assert changed.json()["mark_count"] == 1


def test_shadow_requires_open_step(client, migrated_url):
    content = add_clip(migrated_url, learner_id(client))
    sid = start(client, content)["id"]
    for method in ["get", "put"]:
        response = getattr(client, method)(
            path(sid), **({"json": {"start_ms": 0, "end_ms": 60_000}} if method == "put" else {})
        )
        assert response.status_code == 409
        assert response.json()["code"] == "step_locked"
