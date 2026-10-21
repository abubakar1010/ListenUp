import base64

import pytest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from listenup.platform import telemetry
from listenup.platform.config import Settings


def test_media_telemetry_queues_otlp_without_contacting_collectors(monkeypatch):
    from listenup.platform import telemetry_relay

    queued = []
    monkeypatch.setattr(telemetry_relay, "submit", lambda kind, data: queued.append((kind, data)))
    telemetry.configure_telemetry(
        Settings(
            otel_enabled=True,
            otel_traces_endpoint="http://unreachable/traces",
            otel_metrics_endpoint="http://unreachable/metrics",
        ),
        "worker-media",
    )
    try:
        with telemetry.tracer().start_as_current_span("job content.convert_upload"):
            carrier = telemetry.job_trace_args()
            telemetry.record_ai_call("faster-whisper", "transcribe", 0.5, True)
        telemetry._state.tracer_provider.force_flush()
        telemetry._state.meter_provider.force_flush()
    finally:
        telemetry.shutdown_telemetry()
    assert "traceparent" in carrier[telemetry.TRACE_ARG]
    traces = ExportTraceServiceRequest.FromString(
        next(data for kind, data in queued if kind == "traces")
    )
    assert traces.resource_spans[0].scope_spans[0].spans[0].name == "job content.convert_upload"
    metrics = ExportMetricsServiceRequest.FromString(
        next(data for kind, data in queued if kind == "metrics")
    )
    assert any(
        m.name == "listenup.ai.latency_seconds"
        for r in metrics.resource_metrics
        for s in r.scope_metrics
        for m in s.metrics
    )


@pytest.mark.anyio
async def test_default_pool_relay_uses_configured_endpoint_and_retries_http_errors(monkeypatch):
    from unittest.mock import AsyncMock

    import httpx

    from listenup.platform import telemetry_relay

    settings = Settings(otel_enabled=True, otel_metrics_endpoint="https://collector/metrics")
    monkeypatch.setattr(telemetry_relay, "get_settings", lambda: settings)
    request = httpx.Request("POST", settings.otel_metrics_endpoint)
    response = httpx.Response(503, request=request)
    post = AsyncMock(return_value=response)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(httpx.HTTPStatusError):
        await telemetry_relay.export(
            None, kind="metrics", data=base64.b64encode(b"metric").decode()
        )
    assert post.call_args.args == (settings.otel_metrics_endpoint,)
    assert post.call_args.kwargs["content"] == b"metric"
    post.return_value = httpx.Response(200, request=request)
    await telemetry_relay.export(None, kind="metrics", data=base64.b64encode(b"metric").decode())


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind,data",
    [
        ("unknown", ""),
        ("traces", "!"),
        ("metrics", "eA==" * 9),
        ("traces", base64.b64encode(b"123456789").decode()),
    ],
)
async def test_relay_rejects_invalid_or_oversized_batches(monkeypatch, kind, data):
    from listenup.platform import telemetry_relay
    from listenup.platform.jobs import PermanentError

    monkeypatch.setattr(telemetry_relay, "get_settings", lambda: Settings(otel_enabled=True))
    monkeypatch.setattr(telemetry_relay, "MAX_BATCH_BYTES", 8)
    with pytest.raises(PermanentError):
        await telemetry_relay.export(None, kind=kind, data=data)


@pytest.mark.anyio
async def test_relay_drops_batches_when_telemetry_or_signal_is_disabled(monkeypatch):
    from listenup.platform import telemetry_relay

    for settings in (Settings(), Settings(otel_enabled=True)):
        monkeypatch.setattr(telemetry_relay, "get_settings", lambda settings=settings: settings)
        await telemetry_relay.export(None, kind="traces", data="eA==")


def test_exporters_report_failures_without_exposing_exception_text(monkeypatch, caplog):
    from opentelemetry.sdk.metrics.export import MetricExportResult
    from opentelemetry.sdk.trace.export import SpanExportResult

    from listenup.platform import telemetry_relay
    from tests.telemetry_helpers import capture

    submit = telemetry_relay.submit

    def unavailable(*args):
        raise ConnectionError("private input must not be logged")

    monkeypatch.setattr(telemetry_relay, "submit", unavailable)
    assert telemetry.QueuedSpanExporter().export([]) == SpanExportResult.FAILURE
    with capture() as captured:
        telemetry.record_ai_call("local", "transcribe", 0.2, True)
        data = captured.reader.get_metrics_data()
    exporter = telemetry.QueuedMetricExporter()
    assert exporter.export(data) == MetricExportResult.FAILURE
    assert exporter.force_flush()
    exporter.shutdown()
    assert "private input" not in caplog.text
    monkeypatch.setattr(telemetry_relay, "MAX_BATCH_BYTES", 1)
    with pytest.raises(ValueError):
        submit("traces", b"too large")


def test_child_trace_context_preserves_supervisor_ancestry():
    from tests.telemetry_helpers import capture

    carrier = {"traceparent": "00-12345678901234567890123456789012-1234567890123456-01"}
    with capture() as captured, telemetry.continued_trace(carrier):
        with telemetry.enqueue_span("next.job", "intake"):
            pass
        span = captured.span("enqueue next.job")
        assert span.parent.span_id == int("1234567890123456", 16)
        assert span.context.trace_id == int("12345678901234567890123456789012", 16)
