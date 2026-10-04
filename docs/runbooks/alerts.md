# Alert runbook

One entry per alert in `infra/observability/alerts.yml` (ADR 0031). Each entry says what the alert means for learners, how to confirm it, and what to do. Times are UTC.

## Where to look

- **Traces:** Jaeger, http://localhost:16686 locally (the `observability` Compose profile). Search by service `listenup-api` or `listenup-worker-default` / `listenup-worker-media`, or by a request id: every span carries `listenup.request_id`.
- **Metrics and alerts:** Prometheus, http://localhost:9090 (the *Alerts* page shows pending and firing alerts); Alertmanager, http://localhost:9093.
- **Logs:** JSON lines on each container's stdout (`docker compose logs api worker worker-media`). Every line has `request_id`, and `trace_id` when tracing is on, so `docker compose logs | grep <trace id>` finds a trace's log lines.
- **Failed jobs:** `SELECT id, task_name, attempts, args FROM procrastinate.procrastinate_jobs WHERE status = 'failed' ORDER BY id DESC LIMIT 50;` (the admin view, #11, will show the same through `failed_jobs`).

Turn it all on locally with `LISTENUP_OTEL_ENABLED=true docker compose --profile observability up --build`. Alerts are emailed to Mailpit (http://localhost:8025).

## Where alerts go

Locally, Alertmanager emails every alert to Mailpit. On the stage 0 server (#112, not deployed yet) set the receiver in `infra/observability/alertmanager.yml` to the team's address through the production SMTP provider, or to a free push service (for example a self-hosted ntfy topic). Also set up, as part of #112:

- **An external uptime monitor** (System Design 11.1, "the stage 0 server is lost"): a free external checker such as UptimeRobot's free plan or Uptime Kuma on another host, calling `GET https://<host>/api/v1/health` every 5 minutes and alerting the same people. It must run outside the VM, since Prometheus and Alertmanager die with it.
- **Database monitoring** (Database Design 12.3): `pg_stat_statements`, connection count near the limit and table bloat, from the managed PostgreSQL provider's own alerts.

## JobBacklogGrowing

**Meaning.** At least 10 jobs are due on one lane and the number has grown over the last 15 minutes, for 15 minutes: work arrives faster than the pool finishes it. On `intake`, new clips take longer to become playable; on `ai`, gist feedback is delayed; on `speech-interactive`, Shadow feedback is late.

**Confirm.** In Prometheus, `listenup_job_backlog` and `listenup_job_oldest_wait_seconds` for the lane; `rate(listenup_job_runs_total[5m])` by outcome shows whether jobs finish at all.

**Act.**
1. Check the worker pool for the lane is up and ready: `docker compose ps worker worker-media` (both have health checks on the ready file). Restart a stuck pool with `docker compose restart worker` (lanes ai, background) or `worker-media` (speech-interactive, intake).
2. If jobs run but slowly, look at `listenup_job_duration_seconds` and a few slow job traces in Jaeger: a slow provider (ai), a slow conversion (intake) or a database wait.
3. If jobs keep retrying (`outcome="retried"`), see JobFailureRateHigh.
4. A sustained intake backlog with a healthy pool is a capacity problem: System Design 10 says when to move the media worker to a bigger machine. Speech-interactive work already pauses intake (backpressure, System Design 4.2).

## JobWaitTooLong

**Meaning.** The oldest due job on a lane has waited longer than learners tolerate: 60 s on `speech-interactive` (Shadow feedback is due 120 s after a round), 30 s on `ai` (gist feedback is due 30 s after submitting), 15 minutes on `intake`, 30 minutes on `background` (emails such as password resets).

**Confirm.** `listenup_job_oldest_wait_seconds{lane="..."}`; find the job with `SELECT id, task_name, scheduled_at, attempts FROM procrastinate.procrastinate_jobs WHERE status = 'todo' AND queue_name = '<lane>' ORDER BY id LIMIT 10;`.

**Act.** As for JobBacklogGrowing. A single old job on an otherwise empty lane usually means its lock (`lock` column) is held by a stuck job of the same resource: find the `doing` job with that lock and check its worker. A job a worker crashed on is retried once its lock expires (System Design 11.1).

## JobFailureRateHigh

**Meaning.** More than 5% of a lane's job runs in 30 minutes failed for good (attempts used up, or a `PermanentError`), and at least 3 did. Learners see a failed clip, a missing email or "feedback unavailable" with a retry action (NFR-REL-2).

**Confirm.** `sum by (job) (increase(listenup_job_runs_total{outcome="failed"}[30m]))` names the job type. List the failed jobs (query above) and open a failed run's trace in Jaeger: the job span's `error.type` names the exception, and the worker's log lines with the same `trace_id` hold the details.

**Act.**
1. One job type, one exception: fix the cause, then retry the failed jobs: `UPDATE procrastinate.procrastinate_jobs SET status = 'todo', attempts = 0, scheduled_at = now() WHERE status = 'failed' AND task_name = '<job>';`.
2. Storage or database errors on every lane: check S3 and PostgreSQL health first.
3. `content.convert_upload` failing with `PermanentError` is a bad file and needs no action beyond checking the learner saw the refusal.

## GradingFailureRateHigh

**Meaning.** More than 5% of gist and Shadow gradings in 30 minutes failed (at least 20 gradings in the window). Learners see "feedback unavailable" with a retry; the plan continues (grading never blocks the learner).

**Data.** The grading jobs call `record_grading(kind, ok)` (`listenup.platform.telemetry`). They are not built yet (gist grading #61/#62, Shadow stories), so until then this alert has no data and stays quiet.

**Confirm.** `sum by (kind, outcome) (increase(listenup_grading_results_total[30m]))` shows which kind fails; the failed grading jobs' traces show whether the provider call, the output schema check or the speech pipeline failed.

**Act.**
1. Provider errors or timeouts: check AiQuotaLow and `listenup_ai_latency_seconds` by provider. The gateway (#64) should already fall back to the next provider; if every provider fails, switch the active provider in the gateway configuration.
2. Output schema failures after a provider or prompt change: roll back the prompt or provider version (prompts live in versioned files, NFR-AI-4) and rerun the evaluation set (NFR-AI-6).
3. Once fixed, learners can retry from the session; failed jobs can also be requeued as under JobFailureRateHigh.

## AiQuotaLow

**Meaning.** A provider has less than 20% of its free quota left for the current period (NFR-AI-8). When it runs out, the gateway moves to the next provider, then to template feedback, then to "feedback delayed" (System Design 7.2, 11.1).

**Data.** The AI gateway (#64) reports `record_ai_quota(provider, remaining_ratio)` from its quota counters. It is not built yet, so until then this alert has no data and stays quiet.

**Confirm.** `listenup_ai_quota_remaining_ratio` by provider, and the call rate `sum by (provider, task) (rate(listenup_ai_latency_seconds_count[1h]))` to see which task is using it up.

**Act.**
1. If it is a usage spike from one task, check for a retry loop (JobFailureRateHigh on lane `ai`) or one learner generating unusual load.
2. Make sure the next provider in the gateway configuration has quota left; if not, enable quota-saving mode early or add another eligible free provider (NFR-AI-7: no training on our data).
3. The quota resets at the provider's period boundary; note the date and rate in the usage view (NFR-AI-10) to plan the move to a paid plan.

## ApiErrorRateSpike

**Meaning.** More than 5% of API requests in 5 minutes answered with a server error (5xx), with at least 20 requests in the window, for 5 minutes. Learners see "something went wrong" on some screens.

**Confirm.** `sum by (route, status_class) (increase(listenup_http_server_requests_total[5m]))` names the route. In Jaeger, search service `listenup-api` with tag `error=true` (or `http.response.status_code=500`); the span's `listenup.request_id` finds the `unhandled error` log line with the exception.

**Act.**
1. All routes failing: check PostgreSQL and the API container (`docker compose logs api`).
2. One route failing after a deploy: roll back to the previous image tag (`docker compose up -d` with the old tag) and fix forward.
3. Storage errors on media routes: check the S3 provider's status.

## BackupMissing

**Meaning.** No database dump has reached storage in 26 hours, or the backup service stopped reporting for 30 minutes (NFR-REL-4, ADR 0032). Nothing is wrong for learners yet, but the RPO of 24 hours is no longer met. Locally the alert also fires when the observability profile runs without the `backup` profile; ignore it there or start `docker compose --profile backup up backup`.

**Confirm.** `docker compose ps backup` and `docker compose logs backup` (`database dump stored`, or `database dump failed` with the pg_dump error); `docker compose run --rm backup python -m listenup.ops.backup list` shows the newest backup.

**Act.**
1. Container down: `docker compose up -d backup`. On start it reports the newest backup in storage, which clears the alert if that one is recent.
2. Dump failing: the log names the cause. Common ones: the database URL or password changed (`LISTENUP_BACKUP_DATABASE_URL`), the storage credentials or bucket changed (`LISTENUP_S3_*`, `LISTENUP_BACKUP_BUCKET`), or the disk under `/tmp` in the container is full.
3. Once fixed, take a backup now: `docker compose run --rm backup python -m listenup.ops.backup dump`, and check it with `restore-test` (see `backups.md`).
