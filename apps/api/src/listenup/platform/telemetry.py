"""Traces and metrics across the API, the job queue and the workers (Architecture 12.3).

OpenTelemetry is off unless `LISTENUP_OTEL_ENABLED` is set; until then every tracer
and meter here is a no-op, so tests and local runs export nothing. When it is on,
spans and metrics go over OTLP/HTTP to the endpoints in the settings: a self-hosted
Jaeger and Prometheus (the `observability` Compose profile) or any free OTLP backend
(ADR 0031).

A trace follows a request into the jobs it creates: `enqueue` stores the W3C trace
context in the job's arguments (`job_trace_args`), and the worker continues the trace
from it (`observe_job`), so one trace spans the API request, the enqueue and the job,
and every job that job queues in turn.

Privacy (NFR-SEC, Architecture 12.2): spans and metrics carry only routes, methods,
status codes, job names, lanes, ids and outcomes. No URL, query string, header,
request or response body, exception message, email address or media content is ever
recorded; exceptions are recorded by type name only.
"""

import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.metrics import Counter, Histogram, Meter, MeterProvider
from opentelemetry.metrics import _Gauge as Gauge  # public in the API, named _Gauge
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer, TracerProvider
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from listenup.platform.config import Settings
from listenup.platform.log import current_request_id

INSTRUMENTATION = "listenup"
# The job argument that carries the trace context and the time the job was queued.
TRACE_ARG = "_trace"

# Bucket bounds in seconds: requests and AI calls take milliseconds to a minute, jobs
# and queue waits up to a lane's timeout (System Design 4.1).
SHORT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)
LONG_BUCKETS = (0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 900, 1800, 3600)

_propagator = TraceContextTextMapPropagator()


@dataclass
class Instruments:
    """Every metric ListenUp records. Names are Prometheus-style on purpose: Prometheus'
    OTLP receiver keeps them and adds only `_total` to counters, so the alert rules
    in infra/observability can name them exactly."""

    http_requests: Counter
    http_duration: Histogram
    job_wait: Histogram
    job_duration: Histogram
    job_runs: Counter
    job_backlog: Gauge
    job_oldest_wait: Gauge
    grading_results: Counter
    ai_latency: Histogram
    ai_quota_remaining: Gauge

    @classmethod
    def create(cls, meter: Meter) -> "Instruments":
        return cls(
            http_requests=meter.create_counter(
                "listenup.http.server.requests", "{request}", "API requests by route and status"
            ),
            http_duration=meter.create_histogram(
                "listenup.http.server.duration_seconds",
                "s",
                "Time to answer an API request",
                explicit_bucket_boundaries_advisory=SHORT_BUCKETS,
            ),
            job_wait=meter.create_histogram(
                "listenup.job.wait_seconds",
                "s",
                "Time a job waited from due until a worker took it",
                explicit_bucket_boundaries_advisory=LONG_BUCKETS,
            ),
            job_duration=meter.create_histogram(
                "listenup.job.duration_seconds",
                "s",
                "Time a job ran",
                explicit_bucket_boundaries_advisory=LONG_BUCKETS,
            ),
            job_runs=meter.create_counter(
                "listenup.job.runs",
                "{run}",
                "Job runs by outcome: succeeded, retried, failed (final) or postponed",
            ),
            job_backlog=meter.create_gauge(
                "listenup.job.backlog", "{job}", "Jobs due and waiting for a worker, per lane"
            ),
            job_oldest_wait=meter.create_gauge(
                "listenup.job.oldest_wait_seconds", "s", "How long the oldest due job has waited"
            ),
            grading_results=meter.create_counter(
                "listenup.grading.results",
                "{result}",
                "Gist and Shadow gradings by outcome (ok or failed)",
            ),
            ai_latency=meter.create_histogram(
                "listenup.ai.latency_seconds",
                "s",
                "AI provider call time by provider, task and outcome",
                explicit_bucket_boundaries_advisory=SHORT_BUCKETS,
            ),
            ai_quota_remaining=meter.create_gauge(
                "listenup.ai.quota_remaining_ratio",
                "1",
                "Share of a provider's free quota left for the current period (0 to 1)",
            ),
        )


@dataclass
class _State:
    enabled: bool = False
    tracer_provider: TracerProvider = field(default_factory=trace.NoOpTracerProvider)
    meter_provider: MeterProvider = field(default_factory=metrics.NoOpMeterProvider)
    instruments: Instruments | None = None


_state = _State()


def use_providers(
    tracer_provider: TracerProvider | None = None, meter_provider: MeterProvider | None = None
) -> None:
    """Record through these providers from now on; with no arguments, record nothing.

    `configure_telemetry` calls it with exporting SDK providers; tests call it with
    in-memory ones.
    """
    _state.enabled = tracer_provider is not None or meter_provider is not None
    _state.tracer_provider = tracer_provider or trace.NoOpTracerProvider()
    _state.meter_provider = meter_provider or metrics.NoOpMeterProvider()
    _state.instruments = None


def enabled() -> bool:
    return _state.enabled


def tracer() -> Tracer:
    return _state.tracer_provider.get_tracer(INSTRUMENTATION)


def instruments() -> Instruments:
    if _state.instruments is None:
        _state.instruments = Instruments.create(_state.meter_provider.get_meter(INSTRUMENTATION))
    return _state.instruments


def _parse_headers(raw: str | None) -> dict[str, str]:
    """`key=value,key2=value2`, as in OTEL_EXPORTER_OTLP_HEADERS."""
    headers: dict[str, str] = {}
    for part in (raw or "").split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            headers[key.strip()] = value.strip()
    return headers


def configure_telemetry(settings: Settings, role: str) -> None:
    """Start exporting for this process (`role`: api, worker-media, worker-default, backup).

    Does nothing unless telemetry is enabled; a signal without an endpoint stays off.
    """
    if not settings.otel_enabled:
        use_providers()
        return

    # The SDK and exporters load only when telemetry is on.
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    from listenup import __version__

    headers = _parse_headers(
        settings.otel_headers.get_secret_value() if settings.otel_headers else None
    )
    resource = Resource.create(
        {
            "service.name": f"{settings.otel_service_name}-{role}",
            "service.namespace": settings.otel_service_name,
            "service.version": __version__,
            "deployment.environment.name": settings.environment,
        }
    )
    tracer_provider = None
    if settings.otel_traces_endpoint:
        tracer_provider = SdkTracerProvider(
            resource=resource,
            sampler=ParentBased(TraceIdRatioBased(settings.otel_trace_sample_ratio)),
        )
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=settings.otel_traces_endpoint, headers=headers)
            )
        )
    meter_provider = None
    if settings.otel_metrics_endpoint:
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=settings.otel_metrics_endpoint, headers=headers),
            export_interval_millis=settings.otel_metrics_interval_seconds * 1000,
        )
        meter_provider = SdkMeterProvider(resource=resource, metric_readers=[reader])
    use_providers(tracer_provider, meter_provider)


def shutdown_telemetry() -> None:
    """Flush what is buffered; call when the process stops."""
    for provider in (_state.tracer_provider, _state.meter_provider):
        shutdown = getattr(provider, "shutdown", None)
        if shutdown is not None:
            shutdown()
    use_providers()


def _record_error(span: Span, error: BaseException) -> None:
    # The type only: a message may quote input (an address, a gist, a transcript).
    span.set_status(Status(StatusCode.ERROR, type(error).__name__))
    span.set_attribute("error.type", type(error).__name__)


# --- Jobs -------------------------------------------------------------------------


def job_trace_args(span: Span | None = None) -> dict[str, Any]:
    """What `enqueue` adds to a job's arguments: the trace context and the queue time.

    Empty while telemetry is off, so job arguments stay exactly as the caller gave them.
    """
    if not _state.enabled:
        return {}
    carrier: dict[str, Any] = {}
    context = trace.set_span_in_context(span) if span is not None else None
    _propagator.inject(carrier, context=context)
    carrier["enqueued_at"] = time.time()
    return {TRACE_ARG: carrier}


@contextmanager
def enqueue_span(name: str, lane: str) -> Iterator[Span]:
    """The producer span around queueing a job, inside the request or job that queues it."""
    with tracer().start_as_current_span(
        f"enqueue {name}",
        kind=SpanKind.PRODUCER,
        attributes={"messaging.destination.name": lane, "listenup.job.name": name},
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        yield span


@dataclass
class JobRun:
    """What `observe_job` measures; the job runner sets `outcome` before it ends."""

    outcome: str = "succeeded"


@contextmanager
def observe_job(
    name: str,
    lane: str,
    *,
    job_id: int | None,
    attempt: int,
    scheduled_at: float | None,
    trace_carrier: Mapping[str, Any] | None,
    classify_error: Callable[[BaseException], str],
) -> Iterator[JobRun]:
    """Span, wait time, duration and outcome of one run of a job.

    The span continues the trace in `trace_carrier`, so it joins the request that
    queued the job. `classify_error(exc)` names the outcome of a run that raised:
    "retried" or "failed".
    """
    carrier = dict(trace_carrier or {})
    enqueued_at = carrier.pop("enqueued_at", None)
    started = time.time()
    tools = instruments()
    labels = {"job": name, "lane": lane}
    # A job is due when it was queued or, if later, when it was scheduled to run (a
    # retry's backoff or a postponement is not waiting).
    known = [t for t in (enqueued_at, scheduled_at) if t is not None]
    if known:
        tools.job_wait.record(max(0.0, started - max(known)), labels)

    run = JobRun()
    parent = _propagator.extract(carrier) if carrier else None
    attributes: dict[str, Any] = {
        "messaging.destination.name": lane,
        "listenup.job.name": name,
        "listenup.job.attempt": attempt,
    }
    if job_id is not None:
        attributes["listenup.job.id"] = job_id
    if (request_id := current_request_id()) is not None:
        attributes["listenup.request_id"] = request_id
    with tracer().start_as_current_span(
        f"job {name}",
        context=parent,
        kind=SpanKind.CONSUMER,
        attributes=attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield run
        except BaseException as error:
            run.outcome = classify_error(error)
            _record_error(span, error)
            raise
        finally:
            span.set_attribute("listenup.job.outcome", run.outcome)
            tools.job_duration.record(time.time() - started, {**labels, "outcome": run.outcome})
            tools.job_runs.add(1, {**labels, "outcome": run.outcome})


def record_queue_sample(lane: str, waiting: int, oldest_wait_seconds: float) -> None:
    tools = instruments()
    tools.job_backlog.set(waiting, {"lane": lane})
    tools.job_oldest_wait.set(oldest_wait_seconds, {"lane": lane})


# --- Seams for stories that are not built yet --------------------------------------


def record_grading(kind: str, ok: bool) -> None:
    """One gist or Shadow grading finished (`kind`: gist, shadow_round, comparison).

    The grading jobs (#61, #62 and the Shadow stories) call this; the
    GradingFailureRateHigh alert reads it.
    """
    instruments().grading_results.add(1, {"kind": kind, "outcome": "ok" if ok else "failed"})


def record_ai_call(provider: str, task: str, seconds: float, ok: bool) -> None:
    """One AI provider call. The AI gateway (#64) calls this around every call."""
    instruments().ai_latency.record(
        seconds, {"provider": provider, "task": task, "outcome": "ok" if ok else "failed"}
    )


def record_ai_quota(provider: str, remaining_ratio: float) -> None:
    """Share of `provider`'s free quota left (0 to 1). The AI gateway (#64) reports it
    from its quota counters; the AiQuotaLow alert fires under 0.20."""
    instruments().ai_quota_remaining.set(
        min(1.0, max(0.0, remaining_ratio)), {"provider": provider}
    )


# --- HTTP ---------------------------------------------------------------------------


def route_template(scope: Scope) -> str:
    """The matched route with its parameters as placeholders: `/api/v1/sessions/{id}`.

    Built from the path and the matched path parameters, because a route inside an
    included router knows only its own part of the path. "unmatched" when no route
    matched, so a mistyped or probing path never becomes a label.
    """
    if scope.get("route") is None:
        return "unmatched"
    by_value = {str(value): name for name, value in (scope.get("path_params") or {}).items()}
    segments = str(scope.get("path", "")).split("/")
    return "/".join(f"{{{by_value[s]}}}" if s in by_value else s for s in segments)


class TelemetryMiddleware:
    """A server span and request metrics for each API request.

    Records the method, the route template (`/api/v1/sessions/{session_id}`, never the
    concrete path, which may hold a signed media token) and the status. Add it inside
    RequestIdMiddleware so the span carries the request id.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        status = 500
        started = time.perf_counter()

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        # A new trace per request: the browser's trace context is not trusted.
        with tracer().start_as_current_span(
            method,
            context=trace.set_span_in_context(trace.INVALID_SPAN),
            kind=SpanKind.SERVER,
            attributes={"http.request.method": method},
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            if (request_id := current_request_id()) is not None:
                span.set_attribute("listenup.request_id", request_id)
            try:
                await self.app(scope, receive, send_with_status)
            except BaseException as error:
                _record_error(span, error)
                raise
            finally:
                route = route_template(scope)
                if route != "unmatched":
                    span.update_name(f"{method} {route}")
                span.set_attribute("http.route", route)
                span.set_attribute("http.response.status_code", status)
                if status >= 500:
                    span.set_status(Status(StatusCode.ERROR))
                labels = {"method": method, "route": route, "status_class": f"{status // 100}xx"}
                tools = instruments()
                tools.http_requests.add(1, labels)
                tools.http_duration.record(time.perf_counter() - started, labels)
