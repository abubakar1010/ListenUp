"""Live events end to end: PostgreSQL NOTIFY to a browser's SSE stream (#30).

The API runs in a real uvicorn server on a free port, because test clients that call
the ASGI app directly buffer the whole response and an event stream never ends. The
port is picked by the operating system, so test runs in parallel never collide.
"""

import asyncio
import json
import queue
import socket
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import procrastinate
import psycopg
import pytest
import uvicorn

from listenup.main import create_app
from listenup.platform.config import Settings
from listenup.platform.database import Database
from listenup.platform.events import (
    LISTENER_APPLICATION_NAME,
    EventType,
    publish,
)
from listenup.platform.jobs import JobDeps, Lane, app, configure_runtime, enqueue, job
from tests.integration.conftest import conninfo_to_url

PASSWORD = "correct horse battery"
WAIT = 5.0


@job(Lane.BACKGROUND, "test.events.finish")
async def finish(deps: JobDeps, user_id: str, clip: str) -> None:
    async with deps.database.transaction() as session:
        await publish(session, uuid.UUID(user_id), EventType.CONTENT_READY, clip)


@pytest.fixture(scope="module")
def server(api_role_url: str) -> Iterator[str]:
    api = create_app(Settings(database_url=api_role_url, log_json=False))
    # Bind first, on port 0, and hand the socket to uvicorn: no race for a free port.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    base_url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    config = uvicorn.Config(api, log_level="warning", timeout_graceful_shutdown=2)
    instance = uvicorn.Server(config)
    thread = threading.Thread(target=instance.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not instance.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.05)
    # The listener connects in the background; wait until it is listening.
    while not api.state.event_listener.connected.is_set():
        assert time.monotonic() < deadline, "the event listener did not connect"
        time.sleep(0.05)
    yield base_url
    instance.should_exit = True
    thread.join(10)
    sock.close()


def signed_in(base_url: str) -> tuple[httpx.Client, uuid.UUID]:
    client = httpx.Client(base_url=base_url, timeout=WAIT)
    client.get("/api/v1/health")
    token = next(v for k, v in client.cookies.items() if k.endswith("listenup_csrf"))
    client.headers["X-CSRF-Token"] = token
    email = f"sse-{uuid.uuid4().hex}@example.com"
    response = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    me = client.get("/api/v1/me")
    return client, uuid.UUID(me.json()["id"])


class Stream:
    """An open /events stream read on a thread; each message is a dict of its fields."""

    def __init__(self, client: httpx.Client, last_event_id: str | None = None) -> None:
        headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
        self._context = client.stream(
            "GET", "/api/v1/events", headers=headers, timeout=httpx.Timeout(WAIT, read=None)
        )
        self.response = self._context.__enter__()
        self.messages: queue.Queue[dict[str, str]] = queue.Queue()
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()
        # The first message is sent once the stream is subscribed to the hub.
        assert self.next(include_comments=True).get(":") == "connected"

    def _read(self) -> None:
        fields: dict[str, str] = {}
        try:
            for line in self.response.iter_lines():
                if not line:
                    if fields:
                        self.messages.put(fields)
                    fields = {}
                    continue
                if line.startswith(":"):
                    fields[":"] = line[1:].strip()
                else:
                    name, _, value = line.partition(":")
                    fields[name] = value.strip()
        except Exception:
            pass  # closed by the test

    def next(self, timeout: float = WAIT, include_comments: bool = False) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        while True:
            message = self.messages.get(timeout=max(0.0, deadline - time.monotonic()))
            if include_comments or "event" in message:
                return message

    def nothing_within(self, seconds: float) -> bool:
        try:
            self.next(timeout=seconds)
        except queue.Empty:
            return True
        return False

    def close(self) -> None:
        self.response.close()
        self._context.__exit__(None, None, None)


@pytest.fixture
def streams() -> Iterator[list[Stream]]:
    opened: list[Stream] = []
    yield opened
    for stream in opened:
        stream.close()


def open_stream(
    streams: list[Stream], client: httpx.Client, last_event_id: str | None = None
) -> Stream:
    stream = Stream(client, last_event_id)
    streams.append(stream)
    return stream


def send(database_url: str, user_id: uuid.UUID, resource: str, *, commit: bool = True) -> None:
    """Publish one event from a worker-like connection, committing or rolling back."""

    class RolledBack(Exception):
        pass

    async def run() -> None:
        database = Database(conninfo_to_url(database_url), pool_size=1)
        try:
            async with database.transaction() as session:
                await publish(session, user_id, EventType.CONTENT_READY, resource)
                if not commit:
                    raise RolledBack
        except RolledBack:
            pass
        finally:
            await database.dispose()

    asyncio.run(run())


def data(message: dict[str, str]) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(message["data"])
    return parsed


def test_the_stream_needs_a_signed_in_learner(server: str) -> None:
    with httpx.Client(base_url=server, timeout=WAIT) as client:
        response = client.get("/api/v1/events")

    assert response.status_code == 401
    assert response.json()["code"] == "not_signed_in"


def test_a_committed_event_reaches_only_its_learners_streams(
    server: str, migrated_url: str, streams: list[Stream]
) -> None:
    client_a, learner_a = signed_in(server)
    client_b, learner_b = signed_in(server)
    tab_1, tab_2 = open_stream(streams, client_a), open_stream(streams, client_a)
    other = open_stream(streams, client_b)
    assert tab_1.response.headers["content-type"].startswith("text/event-stream")

    started = time.monotonic()
    send(migrated_url, learner_a, "clip-a")

    for tab in (tab_1, tab_2):
        message = tab.next()
        assert message["event"] == "content.ready"
        assert data(message) == {"type": "content.ready", "resource_id": "clip-a"}
    assert time.monotonic() - started < 1.0
    # Learner B hears only their own event, never A's.
    send(migrated_url, learner_b, "clip-b")
    assert data(other.next())["resource_id"] == "clip-b"
    assert tab_1.nothing_within(0.2)


def test_a_rolled_back_event_is_never_sent(
    server: str, migrated_url: str, streams: list[Stream]
) -> None:
    client, learner = signed_in(server)
    stream = open_stream(streams, client)

    send(migrated_url, learner, "rolled-back", commit=False)
    send(migrated_url, learner, "committed")

    assert data(stream.next())["resource_id"] == "committed"
    assert stream.nothing_within(0.2)


def test_a_reconnect_with_last_event_id_gets_what_it_missed(
    server: str, migrated_url: str, streams: list[Stream]
) -> None:
    client, learner = signed_in(server)
    first = open_stream(streams, client)
    send(migrated_url, learner, "clip-1")
    last_id = first.next()["id"]
    first.close()
    streams.remove(first)

    send(migrated_url, learner, "clip-2")
    send(migrated_url, learner, "clip-3")
    time.sleep(0.2)  # let the hub buffer both before the browser comes back
    again = open_stream(streams, client, last_event_id=last_id)

    assert [data(again.next())["resource_id"] for _ in range(2)] == ["clip-2", "clip-3"]

    stranger = open_stream(streams, client, last_event_id="another-process-7")
    assert stranger.next()["event"] == "resync"


def test_an_open_stream_holds_no_database_transaction(
    server: str, migrated_url: str, streams: list[Stream]
) -> None:
    client, _ = signed_in(server)
    open_stream(streams, client)

    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE usename = 'listenup_api_test' AND datname = current_database() "
            "AND state LIKE 'idle in transaction%%'"
        ).fetchone()

    assert row == (0,)


def test_the_listener_reconnects_and_streams_resync(
    server: str, migrated_url: str, streams: list[Stream]
) -> None:
    client, learner = signed_in(server)
    stream = open_stream(streams, client)
    dbname = psycopg.conninfo.conninfo_to_dict(migrated_url)["dbname"]

    with psycopg.connect(migrated_url, autocommit=True) as conn:
        killed = conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE application_name = %s AND datname = %s",
            [LISTENER_APPLICATION_NAME, dbname],
        ).fetchall()
    assert killed == [(True,)]

    # Events sent while nobody listened are lost, so the stream asks for a refetch.
    assert stream.next(timeout=10)["event"] == "resync"
    send(migrated_url, learner, "after-reconnect")
    assert data(stream.next())["resource_id"] == "after-reconnect"


@pytest.fixture
async def worker_queue(migrated_url: str) -> AsyncIterator[Database]:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("DELETE FROM procrastinate.procrastinate_jobs")
    database = Database(conninfo_to_url(migrated_url), pool_size=2)
    configure_runtime(database)
    with app.replace_connector(procrastinate.PsycopgConnector(conninfo=migrated_url)):
        async with app.open_async():
            yield database
    await database.dispose()


@pytest.mark.anyio
async def test_a_finished_job_reaches_the_browser_within_a_second(
    server: str, worker_queue: Database, streams: list[Stream]
) -> None:
    client, learner = await asyncio.to_thread(signed_in, server)
    stream = await asyncio.to_thread(open_stream, streams, client)
    async with worker_queue.transaction() as session:
        await enqueue(session, "test.events.finish", user_id=str(learner), clip="clip-9")

    finished = datetime.now(UTC)
    await app.run_worker_async(
        queues=[Lane.BACKGROUND.value], wait=False, install_signal_handlers=False
    )
    message = await asyncio.to_thread(stream.next)

    assert (datetime.now(UTC) - finished).total_seconds() < 1.0
    assert data(message) == {"type": "content.ready", "resource_id": "clip-9"}


def test_deleting_the_account_ends_its_open_streams(server: str, streams: list[Stream]) -> None:
    """ADR 0029: a disabled account gets account.disabled, then its stream ends, and a
    reconnect is refused because every login session ended."""
    client, learner = signed_in(server)
    other, _ = signed_in(server)
    stream, others = open_stream(streams, client), open_stream(streams, other)

    deleted = client.request("DELETE", "/api/v1/me", json={"password": PASSWORD, "confirm": True})

    assert deleted.status_code == 202, deleted.text
    message = stream.next()
    assert message["event"] == "account.disabled"
    assert json.loads(message["data"]) == {
        "type": "account.disabled",
        "resource_id": str(learner),
    }
    stream._thread.join(WAIT)
    assert not stream._thread.is_alive(), "the stream did not end"
    assert others.nothing_within(0.3)
    reconnect = client.get("/api/v1/events")
    assert (reconnect.status_code, reconnect.json()["code"]) == (401, "not_signed_in")
