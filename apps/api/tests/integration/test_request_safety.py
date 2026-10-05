"""Idempotency keys, rate limits and database rule codes through a real app.

Acceptance criteria of #25: a repeated POST with the same Idempotency-Key returns the
first response.
"""

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import text

from listenup.main import create_app
from listenup.platform.config import Settings
from listenup.platform.database import DbSession, set_learner
from listenup.platform.errors import ProblemError
from listenup.platform.idempotency import IdempotencyKeyHeader, request_fingerprint, run_once
from listenup.platform.rate_limit import Limit, RateLimiter
from tests.integration.conftest import conninfo_to_url, with_csrf

LOGIN = Limit("login", max_hits=3, window=timedelta(minutes=15))


def build_app(database_url: str, learner: uuid.UUID) -> FastAPI:
    app = create_app(Settings(database_url=database_url, log_json=False))
    router = APIRouter()
    calls: list[dict[str, Any]] = []
    app.state.calls = calls

    @router.post("/submit")
    async def submit(
        request: Request, session: DbSession, idempotency_key: IdempotencyKeyHeader = None
    ) -> JSONResponse:
        await set_learner(session, learner)
        payload = await request.json()

        async def work() -> tuple[int, Any]:
            calls.append(payload)
            if payload.get("fail"):
                raise ProblemError(409, "card_limit_reached", "Two cards already.")
            return 201, {"attempt": len(calls), "text": payload["text"]}

        return await run_once(
            session, learner, idempotency_key, await request_fingerprint(request), work
        )

    @router.post("/login")
    async def login(request: Request, session: DbSession) -> dict[str, str]:
        limiter: RateLimiter = request.app.state.rate_limiter
        await limiter.enforce(LOGIN, f"login:test:{learner}")
        # A refused sign-in rolls its own transaction back; the count must survive.
        raise ProblemError(401, "invalid_credentials", "Wrong email or password.")

    @router.post("/rule")
    async def rule(session: DbSession) -> None:
        await session.execute(
            text(
                "DO $$ BEGIN RAISE EXCEPTION 'step_locked: card cannot open before step 3' "
                "USING ERRCODE = 'check_violation'; END $$"
            )
        )

    app.include_router(router)
    return app


@pytest.fixture
def client(migrated_url: str, learner: uuid.UUID) -> Iterator[TestClient]:
    with TestClient(
        build_app(conninfo_to_url(migrated_url), learner), raise_server_exceptions=False
    ) as test_client:
        yield with_csrf(test_client)


def test_a_repeated_post_with_the_same_key_returns_the_first_response(
    client: TestClient,
) -> None:
    headers = {"Idempotency-Key": "gist-1"}
    first = client.post("/submit", json={"text": "hello"}, headers=headers)
    second = client.post("/submit", json={"text": "hello"}, headers=headers)

    assert first.status_code == second.status_code == 201
    assert second.json() == first.json() == {"attempt": 1, "text": "hello"}
    assert second.headers["Idempotent-Replayed"] == "true"
    assert len(client.app.state.calls) == 1  # type: ignore[attr-defined]


def test_the_same_key_with_another_body_is_refused(client: TestClient) -> None:
    headers = {"Idempotency-Key": "gist-2"}
    client.post("/submit", json={"text": "hello"}, headers=headers)
    response = client.post("/submit", json={"text": "changed"}, headers=headers)

    assert response.status_code == 422
    assert response.json()["code"] == "idempotency_key_reused"


def test_without_a_key_every_post_runs(client: TestClient) -> None:
    client.post("/submit", json={"text": "a"})
    client.post("/submit", json={"text": "a"})
    assert len(client.app.state.calls) == 2  # type: ignore[attr-defined]


def test_a_failed_request_does_not_keep_its_key(client: TestClient) -> None:
    headers = {"Idempotency-Key": "card-1"}
    failed = client.post("/submit", json={"text": "x", "fail": True}, headers=headers)
    retried = client.post("/submit", json={"text": "x", "fail": True}, headers=headers)

    assert failed.json()["code"] == retried.json()["code"] == "card_limit_reached"
    assert len(client.app.state.calls) == 2  # type: ignore[attr-defined]


def test_an_expired_key_is_used_again(
    client: TestClient, migrated_url: str, learner: uuid.UUID
) -> None:
    headers = {"Idempotency-Key": "old"}
    client.post("/submit", json={"text": "first"}, headers=headers)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE ops.idempotency_keys SET created_at = now() - interval '25 hours' "
            "WHERE user_id = %s",
            [learner],
        )

    response = client.post("/submit", json={"text": "second"}, headers=headers)

    assert response.json() == {"attempt": 2, "text": "second"}


def test_a_bad_key_is_refused(client: TestClient) -> None:
    response = client.post("/submit", json={"text": "a"}, headers={"Idempotency-Key": "has space"})
    assert response.json()["code"] == "invalid_idempotency_key"


def test_the_rate_limit_counts_refused_requests_and_then_blocks(client: TestClient) -> None:
    codes = [client.post("/login").json()["code"] for _ in range(4)]

    assert codes == ["invalid_credentials"] * 3 + ["rate_limited"]
    blocked = client.post("/login")
    assert blocked.status_code == 429
    assert 0 < int(blocked.headers["Retry-After"]) <= 15 * 60


def test_a_database_rule_becomes_its_stable_code(client: TestClient) -> None:
    response = client.post("/rule")

    assert response.status_code == 409
    assert response.json()["code"] == "step_locked"
