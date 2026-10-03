"""Problem-details responses (RFC 9457; Architecture 9.1; acceptance criteria of #25)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from listenup.platform.errors import ProblemError, install_error_handlers
from listenup.platform.log import RequestIdMiddleware


def make_client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(RequestIdMiddleware)

    @app.get("/locked")
    def locked() -> None:
        raise ProblemError(409, "step_locked", "Finish Dictation first.", open_step="dictation")

    @app.get("/items/{item_id}")
    def item(item_id: int) -> dict[str, int]:
        return {"id": item_id}

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("database password is hunter2")

    return TestClient(app, raise_server_exceptions=False)


def test_a_problem_has_type_title_status_detail_and_code() -> None:
    response = make_client().get("/locked")

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "/problems/step_locked"
    assert body["title"] == "Conflict"
    assert body["status"] == 409
    assert body["detail"] == "Finish Dictation first."
    assert body["code"] == "step_locked"
    assert body["open_step"] == "dictation"
    assert body["request_id"] == response.headers["x-request-id"]


def test_an_unknown_route_is_a_not_found_problem() -> None:
    body = make_client().get("/nowhere").json()
    assert (body["status"], body["code"]) == (404, "not_found")


def test_invalid_input_is_a_validation_problem_with_field_errors() -> None:
    response = make_client().get("/items/abc")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    assert body["errors"][0]["loc"] == ["path", "item_id"]


def test_an_unexpected_error_hides_its_details_and_logs_the_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = make_client().get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert "hunter2" not in response.text
    request_id = response.headers["x-request-id"]
    assert body["request_id"] == request_id
    [record] = [r for r in caplog.records if r.getMessage() == "unhandled error"]
    assert record.request_id == request_id
