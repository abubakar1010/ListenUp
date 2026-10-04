"""Traces and metrics (#96; Architecture 12.3, ADR 0031)."""

import json
import logging
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.trace import SpanKind, StatusCode

from listenup.platform import telemetry
from listenup.platform.config import Settings
from listenup.platform.errors import install_error_handlers
from listenup.platform.log import JsonFormatter, RequestIdMiddleware, redact
from listenup.platform.telemetry import (
    TRACE_ARG,
    TelemetryMiddleware,
    configure_telemetry,
    enqueue_span,
    job_trace_args,
    observe_job,
    record_ai_call,
    record_ai_quota,
    record_grading,
)
from tests.telemetry_helpers import capture

logger = logging.getLogger("listenup.test.telemetry")


def make_client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(TelemetryMiddleware)
    app.add_middleware(RequestIdMiddleware)

    @app.get("/api/v1/blind/attempts/{attempt_id}/media/{token}")
    def media(attempt_id: str, token: str) -> dict[str, str]:
        logger.info("serving media")
        return {"ok": "yes"}

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("learner@example.com said something private")

    return TestClient(app, raise_server_exceptions=False)


def never_retried(error: BaseException) -> str:
    return "failed"


def test_telemetry_is_off_by_default() -> None:
    settings = Settings()
    assert settings.otel_enabled is False

    configure_telemetry(settings, "api")

    assert telemetry.enabled() is False
    assert job_trace_args() == {}  # job arguments stay exactly as given


def test_enabled_without_endpoints_exports_nothing() -> None:
    configure_telemetry(Settings(otel_enabled=True), "api")
    assert telemetry.enabled() is False


def test_enabled_with_endpoints_builds_exporting_providers() -> None:
    settings = Settings(
        otel_enabled=True,
        otel_traces_endpoint="http://127.0.0.1:9/v1/traces",
        otel_metrics_endpoint="http://127.0.0.1:9/v1/metrics",
        otel_metrics_interval_seconds=3600,
    )
    configure_telemetry(settings, "worker-default")
    try:
        assert telemetry.enabled() is True
        assert TRACE_ARG in job_trace_args()
    finally:
        telemetry.use_providers()  # without shutdown, so nothing is sent to the endpoints


def test_a_request_span_names_the_route_template_not_the_path() -> None:
    client = make_client()
    with capture() as captured:
        response = client.get("/api/v1/blind/attempts/a1/media/secret-media-token")

    assert response.status_code == 200
    span = captured.span("GET /api/v1/blind/attempts/{attempt_id}/media/{token}")
    assert span.kind == SpanKind.SERVER
    assert span.attributes is not None
    assert span.attributes["http.route"] == "/api/v1/blind/attempts/{attempt_id}/media/{token}"
    assert span.attributes["http.response.status_code"] == 200
    assert span.attributes["listenup.request_id"] == response.headers["x-request-id"]
    assert "secret-media-token" not in captured.everything()
    [(labels, count)] = captured.points("listenup.http.server.requests")
    assert labels == {
        "method": "GET",
        "route": "/api/v1/blind/attempts/{attempt_id}/media/{token}",
        "status_class": "2xx",
    }
    assert count == 1


def test_a_server_error_marks_the_span_without_its_message() -> None:
    client = make_client()
    with capture() as captured:
        response = client.get("/boom")

    assert response.status_code == 500
    span = captured.span("GET /boom")
    assert span.status.status_code == StatusCode.ERROR
    assert "learner@example.com" not in captured.everything()
    assert "something private" not in captured.everything()
    [(labels, _)] = captured.points("listenup.http.server.requests")
    assert labels["status_class"] == "5xx"


def test_an_unknown_path_is_not_recorded_as_a_route() -> None:
    client = make_client()
    with capture() as captured:
        client.get("/no/such/learner@example.com")

    [(labels, _)] = captured.points("listenup.http.server.requests")
    assert labels["route"] == "unmatched"
    assert "learner@example.com" not in captured.everything()


def test_a_job_continues_the_trace_of_the_request_that_queued_it() -> None:
    with capture() as captured:
        with (
            telemetry.tracer().start_as_current_span("POST /api/v1/things") as request,
            enqueue_span("test.job", "background") as producer,
        ):
            args = job_trace_args(producer)
        with observe_job(
            "test.job",
            "background",
            job_id=7,
            attempt=1,
            scheduled_at=None,
            trace_carrier=args[TRACE_ARG],
            classify_error=never_retried,
        ):
            pass

    job = captured.span("job test.job")
    enqueue = captured.span("enqueue test.job")
    assert job.kind == SpanKind.CONSUMER
    assert job.context is not None and enqueue.context is not None
    assert job.context.trace_id == request.get_span_context().trace_id
    assert job.parent is not None and job.parent.span_id == enqueue.context.span_id
    assert job.attributes is not None and job.attributes["listenup.job.outcome"] == "succeeded"


def test_job_metrics_record_wait_duration_and_outcome() -> None:
    with capture() as captured:
        carrier = {"enqueued_at": time.time() - 12}
        with observe_job(
            "test.job",
            "ai",
            job_id=1,
            attempt=1,
            scheduled_at=None,
            trace_carrier=carrier,
            classify_error=never_retried,
        ):
            pass
        with (
            pytest.raises(ConnectionError),
            observe_job(
                "test.job",
                "ai",
                job_id=2,
                attempt=4,
                scheduled_at=time.time() - 1,
                trace_carrier=None,
                classify_error=never_retried,
            ),
        ):
            raise ConnectionError("provider said: learner@example.com")

    waits = captured.points("listenup.job.wait_seconds")
    assert waits == [({"job": "test.job", "lane": "ai"}, 2)]
    runs = {labels["outcome"]: value for labels, value in captured.points("listenup.job.runs")}
    assert runs == {"succeeded": 1, "failed": 1}
    durations = captured.points("listenup.job.duration_seconds")
    assert {labels["outcome"] for labels, _ in durations} == {"succeeded", "failed"}
    [failed] = [s for s in captured.spans() if (s.attributes or {}).get("listenup.job.id") == 2]
    assert failed.status.status_code == StatusCode.ERROR
    assert failed.attributes is not None and failed.attributes["error.type"] == "ConnectionError"
    assert "learner@example.com" not in captured.everything()


def test_quota_grading_and_ai_latency_seams() -> None:
    with capture() as captured:
        record_ai_quota("groq", 0.15)
        record_ai_quota("gemini", 1.7)  # clamped
        record_grading("gist", ok=True)
        record_grading("gist", ok=False)
        record_ai_call("groq", "gist_grade", 0.8, ok=True)

    quota = {
        labels["provider"]: value
        for labels, value in captured.points("listenup.ai.quota_remaining_ratio")
    }
    assert quota == {"groq": 0.15, "gemini": 1.0}
    grading = {
        labels["outcome"]: value for labels, value in captured.points("listenup.grading.results")
    }
    assert grading == {"ok": 1, "failed": 1}
    [(labels, count)] = captured.points("listenup.ai.latency_seconds")
    assert labels == {"provider": "groq", "task": "gist_grade", "outcome": "ok"}
    assert count == 1


def test_log_lines_carry_the_trace_id_and_never_an_email(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    with capture(), telemetry.tracer().start_as_current_span("work") as span:
        logger.info("signed in learner@example.com", extra={"to": "Ana <ana.b@mail.example.org>"})

    [record] = [r for r in caplog.records if r.name == logger.name]
    entry = json.loads(JsonFormatter().format(record))
    assert entry["trace_id"] == format(span.get_span_context().trace_id, "032x")
    assert entry["message"] == "signed in [email]"
    assert entry["to"] == "Ana <[email]>"


def test_redact_keeps_text_without_addresses() -> None:
    assert redact("job listenup.platform.jobs ran in 2.5 s") == (
        "job listenup.platform.jobs ran in 2.5 s"
    )
