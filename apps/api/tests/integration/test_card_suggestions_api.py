"""Suggested card phrases from the session's marks (#74, FR-CA-4)."""

import uuid

import pytest

from listenup.modules.practice.service import Step
from tests.integration import test_marks_api as marks
from tests.integration.test_sessions_api import finish, start

client = marks.client
clip = marks.clip
make_client = marks.make_client
session_id = marks.session_id
worker_url = marks.worker_url
new_mark = marks.new_mark


def mark(client, session, **values):
    response = client.post(marks.marks_path(session), json=new_mark(**values))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def suggestions(client, session):
    return client.get(f"/api/v1/sessions/{session}/cards/suggestions")


def open_card(api_role_url, client, session):
    finish(api_role_url, client, session, Step.TRANSCRIPT)


def test_tagged_reduction_is_among_the_suggestions_and_first(client, session_id, api_role_url):
    plain = mark(client, session_id, word_from=2, word_to=2)  # "Again." at 30 s
    reduced = mark(client, session_id, word_from=0, word_to=1)  # "Hello world."
    client.put(f"{marks.marks_path(session_id)}/{reduced}/tag", json={"tag": "reduction"})
    open_card(api_role_url, client, session_id)
    body = suggestions(client, session_id).json()["suggestions"]
    assert [s["mark_id"] for s in body] == [reduced, plain]
    assert body[0] == {
        "mark_id": reduced,
        "phrase": "Hello world.",
        "suggested": True,
        "reasons": ["multi_word", "reduction"],
    }
    assert body[1]["suggested"] is False and body[1]["reasons"] == []


def test_reading_suggestions_creates_no_card(client, session_id, api_role_url):
    mark(client, session_id, word_from=0, word_to=1)
    open_card(api_role_url, client, session_id)
    assert suggestions(client, session_id).status_code == 200
    listed = client.get("/api/v1/cards", params={"session_id": session_id}).json()
    assert listed["cards"] == [] and listed["remaining"] == 2


def test_phrase_marked_in_an_earlier_session_is_suggested(
    client, session_id, clip, api_role_url, migrated_url
):
    mark(client, session_id, word_from=2, word_to=2)  # "Again." in the earlier session
    later = start(client, clip, "dictation", passage=marks.PASSAGE)["id"]
    finish(api_role_url, client, later, Step.DICTATION)
    first = mark(client, later, word_from=0, word_to=0)
    again = mark(client, later, word_from=2, word_to=2)
    open_card(api_role_url, client, later)
    body = suggestions(client, later).json()["suggestions"]
    assert [(s["mark_id"], s["reasons"]) for s in body] == [
        (again, ["earlier_session"]),
        (first, []),
    ]


def test_suggestions_wait_for_the_card_step(client, session_id):
    response = suggestions(client, session_id)
    assert response.status_code == 409 and response.json()["code"] == "step_locked"


def test_another_learner_gets_not_found(client, session_id, make_client):
    other = make_client()
    response = suggestions(other, session_id)
    assert response.status_code == 404 and response.json()["code"] == "session_not_found"


def test_unknown_session_is_not_found(client):
    assert suggestions(client, uuid.uuid4()).status_code == 404


@pytest.mark.parametrize("tag", ["linking", "weak_form"])
def test_other_tags_are_suggested(client, session_id, api_role_url, tag):
    one = mark(client, session_id, word_from=2, word_to=2)
    client.put(f"{marks.marks_path(session_id)}/{one}/tag", json={"tag": tag})
    open_card(api_role_url, client, session_id)
    assert suggestions(client, session_id).json()["suggestions"][0]["reasons"] == [tag]
