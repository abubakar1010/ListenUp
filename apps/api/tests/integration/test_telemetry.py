"""One trace from a request into its job, and no learner data in logs or traces (#96).

The app connects as the API role and queued jobs run in a real Procrastinate worker,
as in test_password_reset. Spans and metrics go to in-memory providers.
"""

import json
import logging
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.main import create_app
from listenup.modules.identity import jobs as identity_jobs
from listenup.modules.notifications import service as notifications
from listenup.platform.config import Settings
from listenup.platform.database import Database
from listenup.platform.jobs import enqueue, sample_queue
from listenup.platform.log import JsonFormatter
from tests.integration.conftest import conninfo_to_url, with_csrf
from tests.integration.intake_helpers import FakeStorage
from tests.integration.test_password_reset import (
    PASSWORD,
    Outbox,
    deliver,
    login,
    register,
    request_reset,
)
from tests.integration.test_sessions_api import add_clip, start
from tests.telemetry_helpers import Captured, capture

RESET_ROUTE = "POST /api/v1/auth/password-reset"
JOB = identity_jobs.SEND_PASSWORD_RESET
# Stands in for what a learner typed while listening: media content.
HEARD = "zebra umbrella sentinel words the learner heard"


@pytest.fixture
def outbox(migrated_url: str) -> Iterator[Outbox]:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("DELETE FROM procrastinate.procrastinate_jobs")
    box = Outbox()
    notifications.use_transport(box)
    yield box
    notifications.use_transport(None)


@pytest.fixture
def client(api_role_url: str, outbox: Outbox) -> Iterator[TestClient]:
    app = create_app(Settings(database_url=api_role_url))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        app.state.uploads.storage = FakeStorage()
        yield with_csrf(test_client)


@pytest.fixture
def captured(client: TestClient) -> Iterator[Captured]:
    # After the client's lifespan, which turns telemetry off as the settings say.
    with capture() as found:
        yield found


def test_a_request_that_queues_a_job_is_one_trace_with_the_job(
    client: TestClient, migrated_url: str, outbox: Outbox, captured: Captured
) -> None:
    email = f"trace-{uuid.uuid4().hex}@example.com"
    register(client, email)
    client.post("/api/v1/auth/logout")

    response = request_reset(client, email)
    deliver(migrated_url)

    assert response.status_code == 202, response.text
    assert [mail.to for mail in outbox.sent] == [email]
    request = captured.span(RESET_ROUTE)
    enqueue = captured.span(f"enqueue {JOB}")
    job = captured.span(f"job {JOB}")
    assert request.context and enqueue.context and job.context
    trace_id = request.context.trace_id
    assert enqueue.context.trace_id == trace_id
    assert job.context.trace_id == trace_id
    assert enqueue.parent is not None and enqueue.parent.span_id == request.context.span_id
    assert job.parent is not None and job.parent.span_id == enqueue.context.span_id
    request_id = response.headers["x-request-id"]
    assert request.attributes and request.attributes["listenup.request_id"] == request_id
    assert job.attributes and job.attributes["listenup.request_id"] == request_id
    assert job.attributes["listenup.job.outcome"] == "succeeded"
    runs = captured.points("listenup.job.runs")
    assert ({"job_name": JOB, "lane": "background", "outcome": "succeeded"}, 1) in runs
    assert [labels for labels, _ in captured.points("listenup.job.wait_seconds")] == [
        {"job_name": JOB, "lane": "background"}
    ]


def test_logs_and_traces_hold_no_email_or_media_content(
    client: TestClient,
    migrated_url: str,
    outbox: Outbox,
    captured: Captured,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    email = f"private-{uuid.uuid4().hex}@example.com"

    assert register(client, email).status_code == 201
    client.post("/api/v1/auth/logout")
    assert login(client, email, "a wrong password").status_code == 401
    assert login(client, email, PASSWORD).status_code == 200
    me = client.get("/api/v1/me").json()
    session = start(client, add_clip(migrated_url, str(me["id"])), entry="dictation")
    attempt = client.post(f"/api/v1/sessions/{session['id']}/dictation/attempts").json()
    saved = client.put(
        f"/api/v1/dictation/attempts/{attempt['id']}/draft",
        json={"draft_text": HEARD, "draft_version": 0},
    )
    assert saved.status_code == 200, saved.text
    client.post("/api/v1/auth/logout")
    assert request_reset(client, email).status_code == 202
    deliver(migrated_url)

    assert [mail.to for mail in outbox.sent] == [email]  # the address was really handled
    traces = captured.everything()
    assert captured.spans(), "nothing was traced"
    logs = "\n".join(JsonFormatter().format(record) for record in caplog.records)
    assert caplog.records, "nothing was logged"
    for secret in (email, email.split("@")[0], HEARD):
        assert secret not in traces
        assert secret not in logs
    # Every span attribute is one of the few kinds ListenUp records.
    allowed = {
        "http.request.method",
        "http.route",
        "http.response.status_code",
        "listenup.request_id",
        "messaging.destination.name",
        "listenup.job.name",
        "listenup.job.id",
        "listenup.job.attempt",
        "listenup.job.outcome",
        "error.type",
    }
    for span in captured.spans():
        assert set(span.attributes or {}) <= allowed, span.name
        assert not span.events, span.name
    json.loads(traces)


@pytest.mark.anyio
async def test_the_queue_sample_counts_due_jobs_per_lane(migrated_url: str, outbox: Outbox) -> None:
    database = Database(conninfo_to_url(migrated_url), pool_size=1)
    try:
        async with database.transaction() as session:
            for _ in range(2):
                await enqueue(session, JOB, unique_key=uuid.uuid4().hex, user_id="u")
            later = datetime.now(UTC) + timedelta(hours=1)
            await enqueue(session, JOB, unique_key=uuid.uuid4().hex, run_at=later, user_id="u")
        with capture() as captured:
            await sample_queue(database)
    finally:
        await database.dispose()

    backlog = {labels["lane"]: value for labels, value in captured.points("listenup.job.backlog")}
    assert backlog == {"speech-interactive": 0, "intake": 0, "ai": 0, "background": 2}
    oldest = dict(
        (labels["lane"], value)
        for labels, value in captured.points("listenup.job.oldest_wait_seconds")
    )
    assert 0 <= oldest["background"] < 60
    [(_, sampled_at)] = captured.points("listenup.job.queue_sampled_timestamp_seconds")
    assert abs(sampled_at - time.time()) < 60  # the sampler's heartbeat
