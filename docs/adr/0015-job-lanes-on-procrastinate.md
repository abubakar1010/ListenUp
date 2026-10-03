# ADR 0015: Job lanes on Procrastinate, with a vendored schema

- Status: Accepted
- Date: 2026-10-03

## Context

ADR 0004 chose a PostgreSQL-backed queue (Procrastinate). The System Design (section 4) adds four priority lanes, two worker pools, per-lane timeouts and attempt limits, backoff with jitter, unique job keys, transactional enqueue and backpressure. Procrastinate covers some of this directly (queues, locks, queueing locks, retry strategies) but not all of it: it has no per-job timeout, no per-queue slot limit inside one worker, its enqueue uses its own connection rather than the caller's transaction, and it creates its tables in whatever schema comes first on the search path.

## Decision

- **Schema.** Migration 0003 creates Procrastinate's tables in a `procrastinate` schema from Procrastinate's own SQL, vendored at the installed version (`migrations/sql/procrastinate-<version>.sql`). The database's search path gains `procrastinate` after `public`, because Procrastinate names its objects without a schema. A test fails when the installed library's schema differs from the vendored file; upgrading Procrastinate then needs a migration that applies its migration files.
- **Lanes** are Procrastinate queues with a priority each (lane 1 highest). `@job(lane, name)` registers a handler with the lane's timeout and attempt limit, which a job may lower.
- **Enqueue in the caller's transaction.** `enqueue(session, ...)` calls Procrastinate's `procrastinate_defer_jobs_v1` function through the request's own SQLAlchemy session, inside a savepoint, so a rolled-back change never queues its job and a duplicate unique key returns None without aborting the transaction. The request id travels in the job's arguments and is bound again while the job runs.
- **Retries.** About 10 s, 40 s, 160 s, varied by up to 20%. `PermanentError` fails a job at once; every other exception, including a timeout, is retried until the lane's attempt limit, after which the job is `failed` and listed by `failed_jobs`.
- **Pools.** Each pool is one process running two Procrastinate workers. The media pool runs one worker on lanes 1 and 2 and one on lane 1 only, so speech work can use both slots and intake at most one. The default pool runs eight concurrent AI jobs and one background job.
- **Backpressure.** Before an intake job starts, a gate checks the speech-interactive lane. Once a job there has waited more than 30 s, intake jobs re-queue themselves 10 s later instead of running, without using up an attempt, until that lane has drained.

## Consequences

Job handlers are `async`, take `JobDeps` and must be idempotent. CPU-heavy work (speech analysis) must run in a subprocess or it would block the pool's event loop and its other slot. Local databases that still have Procrastinate's tables in `public` lose them on upgrade when they are empty; otherwise the migration stops and asks for them to be cleared.
