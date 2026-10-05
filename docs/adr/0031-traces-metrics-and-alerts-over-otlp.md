# ADR 0031: Traces, metrics and alerts over OTLP, off unless configured

- Status: Accepted
- Date: 2026-10-04
- Source: issue #96; [SRS NFR-REL-2, NFR-AI-8](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd); [Software Architecture 2 (structured logs, OpenTelemetry traces, an error tracker behind its SDK), 12.2 and 12.3](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13); [System Design 4, 7.2, 7.3, 11.1 and 11.2](https://claude.ai/code/artifact/98274889-96ba-4424-afad-c2cd056206e2); [Database Design 12.3](https://claude.ai/code/artifact/ba05f7b3-f881-41e5-86d6-dcb94a509644); ADRs 0004, 0009 and 0015

## Context

Architecture 12.3 asks for OpenTelemetry traces across the API, the queue and the workers; metrics for job wait time, job duration, failure rate, AI latency and remaining free quota per provider; and alerts on a growing job backlog, a provider quota under 20%, grading failures over 5% and error-rate spikes. Issue #96 adds that a request that queues a job must show one trace spanning the API and the worker, and that logs and traces must hold no learner email or media content. The stage 0 budget is zero, so the collectors must be self-hosted or on a free tier, and tests and local runs must not export anything. The AI gateway (#64) and the grading jobs are not built yet.

## Decision

### Instrumented by hand with the OpenTelemetry SDK, exported over OTLP/HTTP

`listenup.platform.telemetry` holds every span and instrument. Dependencies are only `opentelemetry-api`, `-sdk` and `-exporter-otlp-proto-http`; no contrib auto-instrumentation. The FastAPI and HTTP-client instrumentations record full URLs, query strings and sometimes headers, and our paths carry signed media tokens (`/blind/attempts/{id}/media/{token}`); writing the few spans ourselves keeps every attribute on an allowlist we can test.

- **API:** `TelemetryMiddleware` (inside `RequestIdMiddleware`) opens a server span per request named `METHOD /route/{template}`, with method, route template, status and request id. The template is rebuilt from the path and the matched path parameters, because a route inside an included router knows only its own part of the path; an unmatched path is labelled `unmatched`. Each request starts a new trace: a trace context sent by a browser is not trusted.
- **Queue:** `enqueue` opens a producer span (`enqueue <job>`) and stores its W3C `traceparent` and the queue time in the job's arguments under `_trace`, next to `_request_id`. Both are popped before the handler runs, kept when backpressure postpones a job, and hidden from `failed_jobs`. While telemetry is off, `_trace` is not added at all.
- **Workers:** the job runner opens a consumer span (`job <job>`) whose parent is that producer span, so the request, the enqueue, the job and any job it queues in turn are one trace. The span carries the job name, lane, id, attempt, request id and outcome.
- **Errors** are recorded on spans by exception type only (`error.type`), never the message or stack, which may quote input.
- **Logs** gain `trace_id` and `span_id` whenever a span is active, so a log line leads to its trace.

### Metrics, named for the alert rules

Instrument names are Prometheus-style (`listenup.job.wait_seconds`), so Prometheus' OTLP receiver keeps them and only adds `_total` to counters and `_bucket`/`_sum`/`_count` to histograms. This was checked against Prometheus 3.5's receiver.

| Metric | Kind | Labels | Recorded by |
| --- | --- | --- | --- |
| `listenup_http_server_requests_total`, `listenup_http_server_duration_seconds` | counter, histogram | method, route, status_class | API middleware |
| `listenup_job_wait_seconds` | histogram | job, lane | job runner: from when the job was due (queued, or scheduled for a retry or postponement) until a worker took it |
| `listenup_job_duration_seconds`, `listenup_job_runs_total` | histogram, counter | job, lane, outcome | job runner; outcome is `succeeded`, `retried`, `failed` (attempts used up or `PermanentError`), `postponed` or `cancelled` (the worker was shutting down; no alert counts it) |
| `listenup_job_backlog`, `listenup_job_oldest_wait_seconds` | gauge | lane | `sample_queue`, every 30 s in the default worker pool |
| `listenup_grading_results_total` | counter | kind, outcome | `record_grading`, a seam for the grading jobs |
| `listenup_ai_latency_seconds` | histogram | provider, task, outcome | `record_ai_call`, a seam for the AI gateway (#64) |
| `listenup_ai_quota_remaining_ratio` | gauge | provider | `record_ai_quota`, a seam for the AI gateway (#64) |
| `listenup_backup_last_success_timestamp_seconds` | gauge | | the backup service (ADR 0032) |

### Off by default; self-hosted or a free tier when on

`LISTENUP_OTEL_ENABLED` is false by default, and every tracer and meter is then a no-op; a signal without an endpoint (`LISTENUP_OTEL_TRACES_ENDPOINT`, `LISTENUP_OTEL_METRICS_ENDPOINT`) stays off even when enabled. ListenUp never sets the global OpenTelemetry providers, so libraries that use them (FastAPI's own telemetry hooks included) stay silent too. `LISTENUP_OTEL_HEADERS` carries an authorization header for a hosted free tier (for example Grafana Cloud's free OTLP endpoint).

For local runs and the stage 0 server, the `observability` Compose profile runs Jaeger (traces, UI on :16686), Prometheus 3 with its OTLP receiver and the alert rules (:9090), and Alertmanager (:9093), which emails alerts to Mailpit locally. There is no separate OpenTelemetry Collector: Jaeger and Prometheus both accept OTLP directly, so one fewer service runs on the free VM. Prometheus scrapes nothing; the app pushes.

### Alerts are Prometheus rules with unit tests

`infra/observability/alerts.yml` holds the rules, `alerts.test.yml` proves with `promtool test rules` that each one fires on simulated data and stays quiet just below its threshold, and CI runs both. Each alert links to its entry in `docs/runbooks/alerts.md`.

| Alert | Fires when |
| --- | --- |
| JobBacklogGrowing | a lane has at least 10 jobs due and more than 15 minutes ago, for 15 minutes |
| JobWaitTooLong | the oldest due job waited over 60 s (speech-interactive), 30 s (ai), 15 min (intake) or 30 min (background), for 5 minutes |
| JobFailureRateHigh | over 5% of a lane's runs in 30 minutes failed for good, and at least 3 did |
| GradingFailureRateHigh | over 5% of gradings in 30 minutes failed, with at least 20 gradings |
| AiQuotaLow | a provider has under 20% of its free quota left, for 2 minutes |
| ApiErrorRateSpike | over 5% of API requests in 5 minutes answered 5xx, with at least 20 requests, for 5 minutes |
| BackupMissing | no dump reached storage in 26 hours, or the backup service stopped reporting |

The quota threshold follows Architecture 12.3 and the issue (20% left). System Design 7.3 mentions an alert at 75% use and 7.2 a quota-saving mode below 25% left; that mode belongs to the gateway (#64), and the alert stays at 20%.

### Learner data stays out

Spans and metrics carry only the attributes above; a test fails if any other span attribute or any span event appears. The JSON and plain-text log formatters replace anything shaped like an email address with `[email]`, whatever logged it. Job arguments are ids only (ADR 0017), so Procrastinate's own job logs carry none either. An integration test registers, signs in, saves a Dictation draft and requests a password reset that a real worker sends, then asserts that the address and the draft text appear in no log line, span or metric.

## Consequences

- One trace in Jaeger shows a request, the job it queued and the jobs that job queued, with the request id on each span; a log line's `trace_id` finds it.
- Tests and local runs export nothing unless asked; tests use `tests/telemetry_helpers.capture()` for in-memory spans and metrics.
- The AI gateway (#64) must call `record_ai_call` around each provider call and `record_ai_quota` from its quota counters; the grading jobs must call `record_grading`. Until they exist the AI and grading alerts have no data and stay quiet. Their rules are already tested on simulated series.
- Not done here: the error tracker behind its open SDK (Architecture 12.3; GlitchTip with the Sentry SDK is the free, self-hosted candidate, and it needs request-body capture off and the same address scrubbing), and the external uptime monitor and the production Alertmanager receiver, which belong to the stage 0 deployment (#112). The runbook says what to set up.
- Database-level monitoring from Database Design 12.3 (`pg_stat_statements`, connection count, bloat) depends on the managed PostgreSQL provider and is also left to #112.
