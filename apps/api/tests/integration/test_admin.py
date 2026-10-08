"""The admin job view and retries (#100, SRS 2.2, ADR 0034).

The API runs as `api_role_url`, so these tests also prove the API role may read the
queue and retry a job. Jobs are put in the queue as the owner, standing in for workers.
"""

import json
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.main import create_app
from listenup.platform.config import Settings
from tests.integration.conftest import with_csrf
from tests.integration.intake_helpers import PASSWORD

AdminFactory = Callable[..., TestClient]

# What a job's arguments may hold; none of it may reach an admin.
LEARNER_TEXT = "the quick brown fox my gist"


@pytest.fixture
def empty_queue(migrated_url: str) -> Iterator[str]:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("DELETE FROM procrastinate.procrastinate_jobs")
    yield migrated_url
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("DELETE FROM procrastinate.procrastinate_jobs")


@pytest.fixture
def accounts(api_role_url: str, migrated_url: str) -> Iterator[AdminFactory]:
    """`accounts(admin=True, verified=True)`: a signed-in client of an app whose admin
    list holds this account's email exactly when `admin` is true."""
    opened: list[TestClient] = []

    def make(admin: bool = True, verified: bool = True) -> TestClient:
        email = f"Admin-{uuid.uuid4().hex}@Example.com"
        listed = (" learner@example.com", email.lower()) if admin else ()
        app = create_app(Settings(database_url=api_role_url, log_json=False, admin_emails=listed))
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        opened.append(client)
        with_csrf(client)
        registered = client.post(
            "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
        )
        assert registered.status_code == 201
        if verified:
            with psycopg.connect(migrated_url, autocommit=True) as conn:
                conn.execute(
                    "UPDATE identity.users SET email_verified_at = now() WHERE email = %s",
                    [email],
                )
        return client

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def add_job(
    url: str,
    status: str = "todo",
    *,
    lane: str = "background",
    task: str = "test.admin_view",
    args: dict[str, Any] | None = None,
    unique_key: str | None = None,
    lock: str | None = None,
    later: bool = False,
) -> int:
    """A job in `status`, moved there as a worker would, so its events are recorded."""
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute(
            "INSERT INTO procrastinate.procrastinate_jobs "
            "(queue_name, task_name, priority, lock, queueing_lock, args, scheduled_at) "
            "VALUES (%s, %s, 0, %s, %s, %s, "
            "CASE WHEN %s THEN now() + interval '1 hour' END) RETURNING id",
            [lane, task, lock, unique_key, json.dumps(args or {}), later],
        ).fetchone()
        assert row is not None
        job_id: int = row[0]
        steps = {"todo": [], "doing": ["doing"], "failed": ["doing", "failed"]}[status]
        for step in steps:
            conn.execute(
                "UPDATE procrastinate.procrastinate_jobs SET status = %s, "
                "attempts = attempts + %s WHERE id = %s",
                [step, int(step == "failed"), job_id],
            )
    return job_id


def queued(url: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT id, queue_name, task_name, status::text, lock, queueing_lock, args, attempts "
            "FROM procrastinate.procrastinate_jobs ORDER BY id"
        ).fetchall()


# -- who may call ---------------------------------------------------------------------


def test_a_learner_gets_404_from_every_admin_route(
    accounts: AdminFactory, empty_queue: str
) -> None:
    failed = add_job(empty_queue, "failed")
    learner = accounts(admin=False)

    listing = learner.get("/api/v1/admin/jobs")
    retry = learner.post(f"/api/v1/admin/jobs/{failed}/retry")
    missing = learner.get("/api/v1/admin/no-such-route")

    for answer in (listing, retry):
        assert answer.status_code == 404
        assert answer.json()["code"] == "not_found"
        # The same as a route that does not exist, so nothing tells a learner it is there.
        assert answer.json()["detail"] == missing.json()["detail"]
    assert [row[3] for row in queued(empty_queue)] == ["failed"]


def test_a_listed_email_that_is_not_verified_is_not_an_admin(
    accounts: AdminFactory, empty_queue: str
) -> None:
    unverified = accounts(admin=True, verified=False)

    answer = unverified.get("/api/v1/admin/jobs")

    assert answer.status_code == 404
    assert answer.json()["code"] == "not_found"


def test_signed_out_callers_must_sign_in(accounts: AdminFactory, empty_queue: str) -> None:
    client = accounts()
    client.post("/api/v1/auth/logout")

    assert client.get("/api/v1/admin/jobs").status_code == 401


# -- the job view ---------------------------------------------------------------------


def test_an_admin_sees_every_lane_with_its_backlog(
    accounts: AdminFactory, empty_queue: str
) -> None:
    add_job(empty_queue, lane="ai")
    add_job(empty_queue, lane="ai")
    add_job(empty_queue, lane="ai", later=True)
    add_job(empty_queue, "doing", lane="intake")
    add_job(empty_queue, "failed", lane="intake")

    answer = accounts().get("/api/v1/admin/jobs")

    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    lanes = {lane["lane"]: lane for lane in answer.json()["lanes"]}
    assert list(lanes) == ["speech-interactive", "intake", "ai", "background"]
    assert {k: lanes["ai"][k] for k in ("waiting", "scheduled", "running")} == {
        "waiting": 2,
        "scheduled": 1,
        "running": 0,
    }
    assert lanes["ai"]["oldest_wait_seconds"] >= 0
    assert lanes["intake"]["running"] == 1
    assert lanes["intake"]["waiting"] == 0
    assert lanes["intake"]["oldest_wait_seconds"] is None
    assert lanes["background"] == {
        "lane": "background",
        "waiting": 0,
        "scheduled": 0,
        "running": 0,
        "oldest_wait_seconds": None,
    }


def test_an_admin_sees_failed_jobs_without_learner_data(
    accounts: AdminFactory, empty_queue: str, learner: uuid.UUID
) -> None:
    args = {"user_id": str(learner), "text": LEARNER_TEXT, "key": f"users/{learner}/media/x"}
    failed = add_job(empty_queue, "failed", lane="ai", task="grading.grade_gist", args=args)
    add_job(empty_queue, "doing", args=args)

    answer = accounts().get("/api/v1/admin/jobs")

    assert answer.status_code == 200
    [shown] = answer.json()["failed"]
    assert shown["id"] == failed
    assert (shown["lane"], shown["name"], shown["attempts"]) == ("ai", "grading.grade_gist", 1)
    assert shown["failed_at"] is not None
    assert str(learner) not in answer.text
    assert LEARNER_TEXT not in answer.text
    assert "users/" not in answer.text


# -- retry ----------------------------------------------------------------------------


def test_an_admin_retries_a_failed_job_once(accounts: AdminFactory, empty_queue: str) -> None:
    failed = add_job(
        empty_queue,
        "failed",
        lane="intake",
        task="content.convert_upload",
        args={"n": 1},
        lock="media:1",
        unique_key="convert:media-1",
    )
    admin = accounts()

    retried = admin.post(f"/api/v1/admin/jobs/{failed}/retry")
    again = admin.post(f"/api/v1/admin/jobs/{failed}/retry")

    assert retried.status_code == 202
    new_id = retried.json()["job_id"]
    rows = {row[0]: row for row in queued(empty_queue)}
    _, lane, task, status, lock, unique_key, args, attempts = rows[new_id]
    assert (lane, task, status, lock, unique_key, attempts) == (
        "intake",
        "content.convert_upload",
        "todo",
        "media:1",
        "convert:media-1",
        0,
    )
    assert args["n"] == 1
    assert rows[failed][3] == "failed"  # kept as it was, for the record
    assert admin.get("/api/v1/admin/jobs").json()["failed"] == []
    assert again.status_code == 404
    assert again.json()["code"] == "job_not_found"
    assert len(rows) == 2


def test_retrying_a_job_that_did_not_fail_is_refused(
    accounts: AdminFactory, empty_queue: str
) -> None:
    waiting = add_job(empty_queue)
    admin = accounts()

    for job_id in (waiting, 999_999_999):
        answer = admin.post(f"/api/v1/admin/jobs/{job_id}/retry")
        assert answer.status_code == 404
        assert answer.json()["code"] == "job_not_found"
    assert len(queued(empty_queue)) == 1


def test_a_retry_whose_work_is_already_queued_is_refused(
    accounts: AdminFactory, empty_queue: str
) -> None:
    failed = add_job(empty_queue, "failed", unique_key="convert:clip-1")
    add_job(empty_queue, unique_key="convert:clip-1")
    admin = accounts()

    answer = admin.post(f"/api/v1/admin/jobs/{failed}/retry")

    assert answer.status_code == 409
    assert answer.json()["code"] == "job_already_queued"
    # Still listed, so it can be retried once the waiting job is done.
    assert [job["id"] for job in admin.get("/api/v1/admin/jobs").json()["failed"]] == [failed]


def test_a_retry_needs_the_csrf_header(accounts: AdminFactory, empty_queue: str) -> None:
    failed = add_job(empty_queue, "failed")
    admin = accounts()
    del admin.headers["X-CSRF-Token"]

    assert admin.post(f"/api/v1/admin/jobs/{failed}/retry").status_code == 403
