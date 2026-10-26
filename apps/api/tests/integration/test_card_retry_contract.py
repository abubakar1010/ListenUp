"""Supplementary retry contract; detects the missing route on pre-story main."""

from tests.integration import test_cards_api as cards

client = cards.client
make_client = cards.make_client
worker_url = cards.worker_url
clip = cards.clip
session_id = cards.session_id
card_session = cards.card_session


def test_retry_checks_owner_before_state(client, card_session, make_client):
    card = cards.create(client, card_session).json()["id"]
    path = f"/api/v1/cards/{card}/audio/retry"
    assert client.post(path).status_code == 409
    denied = make_client().post(path)
    assert denied.status_code == 404
    assert denied.json()["code"] == "card_not_found"
