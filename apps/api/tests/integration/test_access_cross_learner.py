"""Learner B reaches nothing of learner A's, on every route (#34, NFR-SEC-2, FR-CI-6).

The routes and what each must answer are registered in `access_registry.py`; read its
docstring to register a new route. This file holds the checks:

- every route of the app is registered, and every registered route exists;
- signed out, every protected route answers 401 `not_signed_in`;
- as B, every route answers as registered, never shows A's ids or email, and never
  changes A's rows or stored files;
- A's events never reach B's live event stream, even on a reconnect that names A's
  last event id;
- the checks themselves fail when a protection is removed: a route run as the
  database owner (no row-level security), a list without its learner filter, and an
  event hub that ignores the learner. So CI proves the test can catch a leak.

Learner A's data comes from the fixture script `seed.py` (Database Design 12.3).
"""

import asyncio
import queue
import socket
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import httpx
import psycopg
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from psycopg import sql

from listenup.main import create_app
from listenup.modules.content import repository as content_repository
from listenup.platform.config import Settings
from listenup.platform.database import Database
from listenup.platform.events import Event, EventHub, EventType, publish
from tests.integration.access_registry import (
    REGISTRY,
    Owned,
    Public,
    Scoped,
    Stream,
    World,
)
from tests.integration.intake_helpers import ClientFactory, FakeStorage, client_factory
from tests.integration.seed import seed_learner_data, sqlalchemy_ready
from tests.integration.test_events import Stream as EventStream
from tests.integration.test_events import signed_in

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}
REGISTRY_FILE = "tests/integration/access_registry.py"


# -- route coverage ------------------------------------------------------------------


def app_routes(app: FastAPI) -> set[tuple[str, str]]:
    """Every (method, path template) the app serves: its API routes and OpenAPI paths.

    Both, so a route hidden from the schema (`include_in_schema=False`) is still found.
    """
    routes = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    for path, operations in app.openapi()["paths"].items():
        routes |= {(method.upper(), path) for method in operations if method in HTTP_METHODS}
    return routes


def registry_problems(app: FastAPI) -> list[str]:
    routes = app_routes(app)
    problems = [
        f"{method} {path} is not in the access registry. Add it to REGISTRY in "
        f"{REGISTRY_FILE} with what learner B must get (Owned, Scoped, Stream or Public); "
        "the docstring there shows how."
        for method, path in sorted(routes - REGISTRY.keys())
    ]
    problems += [
        f"{method} {path} is in the access registry but the app has no such route; "
        f"remove or rename it in {REGISTRY_FILE}."
        for method, path in sorted(REGISTRY.keys() - routes)
    ]
    return problems


def test_every_route_is_registered() -> None:
    problems = registry_problems(create_app(Settings(log_json=False)))

    assert not problems, "\n".join(problems)


def test_a_route_missing_from_the_registry_is_reported() -> None:
    app = create_app(Settings(log_json=False))

    @app.get("/api/v1/secret-things/{thing_id}")
    def secret_thing(thing_id: str) -> dict[str, str]:  # pragma: no cover - never called
        return {}

    @app.post("/api/v1/hidden", include_in_schema=False)
    def hidden() -> None:  # pragma: no cover - never called
        return None

    problems = registry_problems(app)

    assert len(problems) == 2
    assert problems[0].startswith("GET /api/v1/secret-things/{thing_id} is not in the access")
    assert problems[1].startswith("POST /api/v1/hidden is not in the access registry")
    assert REGISTRY_FILE in problems[0]


# -- what B can reach ----------------------------------------------------------------


def snapshot(owner_url: str, user_id: uuid.UUID) -> dict[str, str]:
    """A digest of each table's rows that belong to `user_id`, read as the owner.

    Every table with a `user_id` (or `uploaded_by`) column is included, so a table
    added later is covered without changing this test.
    """
    with psycopg.connect(owner_url) as conn:
        columns = conn.execute(
            "SELECT c.table_schema, c.table_name, c.column_name "
            "FROM information_schema.columns c "
            "JOIN information_schema.tables t "
            "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE t.table_type = 'BASE TABLE' AND c.column_name IN ('user_id', 'uploaded_by') "
            "  AND c.table_schema NOT IN ('pg_catalog', 'information_schema', 'procrastinate') "
            "ORDER BY 1, 2, 3"
        ).fetchall()
        columns.append(("identity", "users", "id"))
        digests: dict[str, str] = {}
        for schema, table, column in columns:
            row = conn.execute(
                sql.SQL(
                    "SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) "
                    "FROM {}.{} t WHERE {} = %s"
                ).format(sql.Identifier(schema), sql.Identifier(table), sql.Identifier(column)),
                [user_id],
            ).fetchone()
            assert row is not None
            digests[f"{schema}.{table}"] = row[0]
    return digests


def request(client: TestClient, method: str, path: str, body: object) -> httpx.Response:
    # Redirects are never followed: a redirect to another learner's media is itself the
    # leak, and following it would only reach a path the test app does not serve.
    if body is None:
        return client.request(method, path, follow_redirects=False)
    return client.request(method, path, json=body, follow_redirects=False)


def problem_code(response: httpx.Response) -> object:
    try:
        payload: Any = response.json()
    except ValueError:
        return None
    return payload.get("code") if isinstance(payload, dict) else None


def describe(response: httpx.Response) -> str:
    code = problem_code(response)
    return f"{response.status_code} {code}" if code else str(response.status_code)


def check_access(
    world: World,
    a: TestClient,
    b: TestClient,
    signed_out: TestClient,
    storage: FakeStorage,
) -> list[str]:
    """Call every registered route signed out and as B; return every violation found.

    GET routes run first, so a read sees the data before any write of B's.
    """
    violations: list[str] = []
    a_prefix = f"users/{world.a.user_id}/"
    entries = sorted(REGISTRY.items(), key=lambda item: (item[0][0] not in SAFE_METHODS, item[0]))
    for (method, template), entry in entries:
        if isinstance(entry, Public):
            continue
        route = f"{method} {template}"
        params = entry.params(world) if isinstance(entry, Owned) else {}
        path = template.format(**{name: str(value) for name, value in params.items()})
        body = entry.body(world) if isinstance(entry, Owned | Scoped) and entry.body else None

        answer = request(signed_out, method, path, body)
        if answer.status_code != 401 or problem_code(answer) != "not_signed_in":
            violations.append(
                f"{route}: signed out it answered {describe(answer)}, not 401 not_signed_in"
            )
        if isinstance(entry, Stream):
            continue  # B's side is checked over a real server: entry.covered_by

        before = snapshot(world.owner_url, world.a.user_id)
        deleted_before = len(storage.deleted)
        answer = request(b, method, path, body)
        after = snapshot(world.owner_url, world.a.user_id)

        changed = sorted(table for table in before if before[table] != after.get(table))
        if changed:
            violations.append(f"{route}: B's request changed A's rows in {', '.join(changed)}")
        if any(key.startswith(a_prefix) for key in storage.deleted[deleted_before:]):
            violations.append(f"{route}: B's request deleted A's stored files")
        if isinstance(entry, Owned):
            if answer.status_code != entry.status or problem_code(answer) != entry.code:
                violations.append(
                    f"{route}: B got {describe(answer)}, not {entry.status} {entry.code}"
                )
        elif answer.status_code != entry.status:
            violations.append(f"{route}: B got {describe(answer)}, not {entry.status}")
        leaked = [secret for secret in world.secrets_of_a() if secret in answer.text]
        if leaked:
            violations.append(f"{route}: B's answer contains A's {', '.join(leaked)}")
        if isinstance(entry, Scoped) and entry.check and answer.status_code == entry.status:
            problem = entry.check(world, answer)
            if problem:
                violations.append(f"{route}: {problem}")

        if method in SAFE_METHODS:
            own = request(a, method, path, body)
            assert own.is_success or own.is_redirect, (
                f"{route}: A's own request failed: {own.status_code}"
            )
            if isinstance(entry, Scoped) and entry.a_sees:
                missing = [str(i) for i in entry.a_sees(world) if str(i) not in own.text]
                assert not missing, f"{route}: A's own answer lacks {missing}; fix the fixture"
    return violations


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def clients(api_role_url: str, storage: FakeStorage) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, storage)


@pytest.fixture
def owner_clients(migrated_url: str, storage: FakeStorage) -> Iterator[ClientFactory]:
    """Clients of an app that connects as the database owner: row-level security is off."""
    yield from client_factory(sqlalchemy_ready(migrated_url), storage)


def seeded_world(a: TestClient, owner_url: str, storage: FakeStorage) -> World:
    me = a.get("/api/v1/me").json()
    seeded = seed_learner_data(owner_url, uuid.UUID(me["id"]))
    storage.arrive(seeded.pending_upload_key, seeded.pending_upload_size)
    return World(seeded, me["email"], owner_url)


def signed_out_client(clients: ClientFactory) -> TestClient:
    client = clients()
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/me").status_code == 401
    return client


def test_learner_b_reaches_nothing_of_learner_a(
    clients: ClientFactory, migrated_url: str, storage: FakeStorage
) -> None:
    a, b = clients(), clients()
    world = seeded_world(a, migrated_url, storage)

    violations = check_access(world, a, b, signed_out_client(clients), storage)

    assert not violations, "\n".join(violations)


def test_the_check_catches_a_route_that_skips_row_level_security(
    clients: ClientFactory,
    owner_clients: ClientFactory,
    migrated_url: str,
    storage: FakeStorage,
) -> None:
    """The mutation check: B's API connects as the owner, so row-level security is off.

    Cancelling and confirming an upload rely on row-level security alone to find
    only the caller's upload, so both must now be reported.
    """
    a = clients()
    b = owner_clients()
    world = seeded_world(a, migrated_url, storage)

    violations = check_access(world, a, b, signed_out_client(clients), storage)

    reported = " ".join(violations)
    assert "DELETE /api/v1/uploads/{upload_id}: B got 204" in reported
    assert "POST /api/v1/contents: B got 200, not 404 upload_not_found" in reported
    assert f"POST /api/v1/contents: B's answer contains A's {world.a.content_id}" in reported
    assert "changed A's rows in content.uploads" in reported


def test_the_check_catches_a_list_without_its_learner_filter(
    clients: ClientFactory,
    owner_clients: ClientFactory,
    migrated_url: str,
    storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mutation check: the content list forgets `WHERE user_id = :learner`.

    Under the API role, row-level security still hides A's items (defence in depth);
    once B's API also runs as the owner, both lists that read it leak A's clip.
    """
    from sqlalchemy import text

    async def list_everyone(
        session: Any, learner: uuid.UUID, limit: int, after: tuple[datetime, uuid.UUID] | None
    ) -> list[content_repository.ContentRow]:
        rows = await session.execute(
            text(content_repository._CONTENT_COLUMNS + " ORDER BY c.created_at DESC LIMIT :n"),
            {"n": limit},
        )
        return [content_repository.ContentRow(*row) for row in rows]

    monkeypatch.setattr(content_repository, "list_contents", list_everyone)
    a = clients()
    world = seeded_world(a, migrated_url, storage)
    signed_out = signed_out_client(clients)

    assert check_access(world, a, clients(), signed_out, storage) == []
    violations = check_access(world, a, owner_clients(), signed_out, storage)

    reported = " ".join(violations)
    for route in ("GET /api/v1/contents", "GET /api/v1/library/contents"):
        assert f"{route}: B's answer contains A's {world.a.content_id}" in reported


# -- live events -----------------------------------------------------------------------

WAIT = 5.0
QUIET = 0.5


@pytest.fixture(scope="module")
def server(api_role_url: str) -> Iterator[str]:
    """The API in a real uvicorn server: an event stream never ends, so a test client
    that buffers the whole response cannot read it (as in test_events.py)."""
    api = create_app(Settings(database_url=api_role_url, log_json=False))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    instance = uvicorn.Server(uvicorn.Config(api, log_level="warning", timeout_graceful_shutdown=2))
    thread = threading.Thread(target=instance.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not (instance.started and api.state.event_listener.connected.is_set()):
        assert time.monotonic() < deadline, "the server or its event listener did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    instance.should_exit = True
    thread.join(10)
    sock.close()


@pytest.fixture
def streams() -> Iterator[list[EventStream]]:
    opened: list[EventStream] = []
    yield opened
    for stream in opened:
        stream.close()


def open_stream(
    streams: list[EventStream], client: httpx.Client, last_event_id: str | None = None
) -> EventStream:
    stream = EventStream(client, last_event_id)
    streams.append(stream)
    return stream


def publish_for(database_url: str, user_id: uuid.UUID, resources: dict[EventType, str]) -> None:
    """Publish one event of each type for `user_id`, as a worker would, and commit."""

    async def run() -> None:
        database = Database(sqlalchemy_ready(database_url), pool_size=1)
        try:
            async with database.transaction() as session:
                for event_type, resource in resources.items():
                    await publish(session, user_id, event_type, resource)
        finally:
            await database.dispose()

    asyncio.run(run())


def received_within(stream: EventStream, seconds: float) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    deadline = time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0:
        try:
            messages.append(stream.next(timeout=left))
        except queue.Empty:
            break
    return messages


def events_of_a_reaching_b(server: str, migrated_url: str, streams: list[EventStream]) -> list[str]:
    """Publish A's events of every type; return every way one of them reached B."""
    client_a, learner_a = signed_in(server)
    client_b, _ = signed_in(server)
    world = seed_learner_data(migrated_url, learner_a)
    resources = {
        EventType.JOB_PROGRESS: str(world.media_id),
        EventType.CONTENT_READY: str(world.content_id),
        EventType.GRADE_READY: str(world.sessions["card"]),
        EventType.ATTEMPT_VOIDED: str(world.sessions["blind"]),
    }
    tab_a, tab_b = open_stream(streams, client_a), open_stream(streams, client_b)

    publish_for(migrated_url, learner_a, resources)

    own = [tab_a.next() for _ in resources]
    assert {m["event"] for m in own} == {t.value for t in resources}, "A missed its own events"
    secrets = [*resources.values(), str(learner_a)]
    violations = [
        f"B's open stream received A's {message.get('event')} event: {message.get('data')}"
        for message in received_within(tab_b, QUIET)
        if any(secret in message.get("data", "") for secret in secrets)
    ]
    # A reconnect that names A's last event id must not replay A's events to B.
    replayed = open_stream(streams, client_b, last_event_id=own[0]["id"])
    violations += [
        f"B's reconnect with A's event id replayed A's {message.get('event')} event"
        for message in received_within(replayed, QUIET)
        if any(secret in message.get("data", "") for secret in secrets)
    ]
    return violations


def test_events_of_a_never_reach_b(
    server: str, migrated_url: str, streams: list[EventStream]
) -> None:
    violations = events_of_a_reaching_b(server, migrated_url, streams)

    assert not violations, "\n".join(violations)


def test_the_check_catches_a_hub_that_ignores_the_learner(
    server: str, migrated_url: str, streams: list[EventStream], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mutation check: the hub fans every event out to every open stream."""
    dispatch = EventHub.dispatch

    def dispatch_to_everyone(
        hub: EventHub, user_id: uuid.UUID, event_type: str, resource_id: str
    ) -> Event:
        event = dispatch(hub, user_id, event_type, resource_id)
        for other, subscriptions in hub._streams.items():
            if other != user_id:
                for subscription in subscriptions:
                    hub._put(subscription, event)
        return event

    monkeypatch.setattr(EventHub, "dispatch", dispatch_to_everyone)

    violations = events_of_a_reaching_b(server, migrated_url, streams)

    assert any("B's open stream received A's content.ready" in v for v in violations)
