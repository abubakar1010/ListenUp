"""JSON logs that carry the request id (Architecture 12.3; acceptance criteria of #25)."""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from listenup.platform.log import (
    JsonFormatter,
    RequestIdMiddleware,
    current_request_id,
    request_id_bound,
)

logger = logging.getLogger("listenup.test")


def make_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/work")
    def work() -> dict[str, str | None]:
        logger.info("doing work", extra={"step": "dictation"})
        return {"request_id": current_request_id()}

    return TestClient(app)


def formatted(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    formatter = JsonFormatter()
    return [json.loads(formatter.format(r)) for r in caplog.records if r.name == logger.name]


def test_logs_are_json_and_include_the_request_id(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    response = make_client().get("/work")

    request_id = response.headers["x-request-id"]
    assert response.json()["request_id"] == request_id
    [entry] = formatted(caplog)
    assert entry["message"] == "doing work"
    assert entry["level"] == "INFO"
    assert entry["request_id"] == request_id
    assert entry["step"] == "dictation"


def test_a_callers_request_id_is_kept() -> None:
    response = make_client().get("/work", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


def test_an_unsafe_request_id_is_replaced() -> None:
    response = make_client().get("/work", headers={"X-Request-ID": 'bad"\nid'})
    assert response.headers["x-request-id"] != 'bad"\nid'
    assert len(response.headers["x-request-id"]) == 32


def test_a_job_can_carry_the_request_id(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    with request_id_bound("from-request"):
        logger.info("job ran")
    logger.info("after job")

    first, second = formatted(caplog)
    assert first["request_id"] == "from-request"
    assert "request_id" not in second
