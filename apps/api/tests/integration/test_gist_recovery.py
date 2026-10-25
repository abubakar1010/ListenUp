"""Gist recovery uses the API role and never changes learner progress (#70)."""

from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from tests.integration.test_blind import SENTENCES_3
from tests.integration.test_blind import client as client
from tests.integration.test_blind import clock as clock
from tests.integration.test_blind import make_client as make_client
from tests.integration.test_blind import storage as storage
from tests.integration.test_gist_feedback import submitted


def test_deadline_boundary_preserves_gist_and_plan(client, clock, migrated_url):
    session, attempt = submitted(client, clock, migrated_url, "blind")
    before = client.get(f"/api/v1/sessions/{session}").json()
    clock.advance(29_999)
    body = client.get(f"/api/v1/gists/{attempt}/grade").json()
    assert body["status"] == "pending"
    assert body["wait_ms"] == 1
    clock.advance(1)
    body = client.get(f"/api/v1/gists/{attempt}/grade").json()
    assert body["status"] == "unavailable"
    assert body["gist"] == SENTENCES_3
    assert client.get(f"/api/v1/sessions/{session}").json() == before
    with psycopg.connect(migrated_url) as conn:
        assert (
            conn.execute(
                "SELECT status FROM grading.gist_grades WHERE attempt_id=%s", [attempt]
            ).fetchone()[0]
            == "unavailable"
        )


def test_stored_unavailable_and_delayed_are_visible(client, clock, migrated_url):
    _, attempt = submitted(client, clock, migrated_url, "blind")
    for state in ["unavailable", "delayed"]:
        with psycopg.connect(migrated_url) as conn:
            conn.execute(
                "UPDATE grading.gist_grades SET status=%s WHERE attempt_id=%s", [state, attempt]
            )
        clock.advance(30_000)
        body = client.get(f"/api/v1/gists/{attempt}/grade").json()
        assert body["status"] == state
        assert body["gist"] == SENTENCES_3


def test_retry_coalesces_waiting_and_concurrent_requests(client, clock, migrated_url):
    session, attempt = submitted(client, clock, migrated_url, "blind")
    path = f"/api/v1/grades/{attempt}/retry"
    before = client.get(f"/api/v1/sessions/{session}").json()
    clock.advance(30_000)
    # Waiting work is reused even though feedback is already unavailable.
    assert client.post(path).status_code == 202
    with psycopg.connect(migrated_url) as conn:
        rows = conn.execute(
            "SELECT id FROM procrastinate.procrastinate_jobs WHERE queueing_lock=%s",
            [f"gist-grade:{attempt}"],
        ).fetchall()
        assert len(rows) == 1
        conn.execute(
            "UPDATE procrastinate.procrastinate_jobs SET status='failed' WHERE id=%s", [rows[0][0]]
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(path), range(2)))
    assert [r.status_code for r in responses] == [202, 202]
    with psycopg.connect(migrated_url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM procrastinate.procrastinate_jobs "
                "WHERE queueing_lock=%s AND status IN ('todo','doing')",
                [f"gist-grade:{attempt}"],
            ).fetchone()[0]
            == 1
        )
    assert client.get(f"/api/v1/sessions/{session}").json() == before
    assert client.get(f"/api/v1/gists/{attempt}/grade").json()["status"] == "pending"


def test_retry_owner_and_submission_checks(client, clock, migrated_url, make_client):
    _, attempt = submitted(client, clock, migrated_url, "both")
    other = make_client()
    assert other.post(f"/api/v1/grades/{attempt}/retry").status_code == 404
    import uuid

    assert client.post(f"/api/v1/grades/{uuid.uuid4()}/retry").status_code == 404
    # A retry carries no private text, including while D4 hides details.
    response = client.post(f"/api/v1/grades/{attempt}/retry")
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}


@pytest.mark.parametrize("seconds", [1, 45])
def test_configured_feedback_deadline(client, clock, migrated_url, monkeypatch, seconds):
    from listenup.platform.config import get_settings

    monkeypatch.setattr(get_settings(), "gist_feedback_timeout_seconds", seconds)
    _, attempt = submitted(client, clock, migrated_url, "blind")
    assert client.get(f"/api/v1/gists/{attempt}/grade").json()["wait_ms"] == seconds * 1000
    clock.advance(seconds * 1000)
    assert client.get(f"/api/v1/gists/{attempt}/grade").json()["status"] == "unavailable"


def test_retry_rejects_unsubmitted_and_csrf(client, clock, migrated_url):
    from tests.integration.test_blind import attempt_id, start_attempt, start_session

    session = start_session(client, migrated_url, "blind")
    attempt = attempt_id(start_attempt(client, session))
    assert client.post(f"/api/v1/grades/{attempt}/retry").status_code == 409
    assert (
        client.post(
            f"/api/v1/grades/{attempt}/retry", headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )


def test_retry_queue_failure_rolls_back_cycle(client, clock, migrated_url, monkeypatch):
    from listenup.modules.grading import service

    _, attempt = submitted(client, clock, migrated_url, "blind")
    clock.advance(30_000)
    assert client.get(f"/api/v1/gists/{attempt}/grade").json()["status"] == "unavailable"
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "UPDATE procrastinate.procrastinate_jobs SET status='failed' WHERE queueing_lock=%s",
            [f"gist-grade:{attempt}"],
        )

    async def fail(*args):
        raise RuntimeError("deadline queue unavailable")

    monkeypatch.setattr(service, "queue_deadline", fail)
    assert client.post(f"/api/v1/grades/{attempt}/retry").status_code == 500
    with psycopg.connect(migrated_url) as conn:
        assert (
            conn.execute(
                "SELECT status FROM grading.gist_grades WHERE attempt_id=%s", [attempt]
            ).fetchone()[0]
            == "unavailable"
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE queueing_lock=%s",
                [f"gist-grade:{attempt}"],
            ).fetchone()[0]
            == 1
        )


def test_retry_recovers_reference_work_while_grading_is_already_waiting(
    client, clock, migrated_url
):
    session, attempt = submitted(client, clock, migrated_url, "blind")
    from tests.integration.test_blind import media_for_session

    media = media_for_session(migrated_url, session)
    assert client.post(f"/api/v1/grades/{attempt}/retry").status_code == 202
    with psycopg.connect(migrated_url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM procrastinate.procrastinate_jobs "
                "WHERE task_name='grading.extract_key_points' AND args->>'media_id'=%s",
                [media],
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE queueing_lock=%s",
                [f"gist-grade:{attempt}"],
            ).fetchone()[0]
            == 1
        )
