# ADR 0016: Live events over Server-Sent Events, fed by PostgreSQL NOTIFY

- Status: Accepted
- Date: 2026-10-03

## Context

Long jobs (download, transcription, grading) finish in the background, and the learner's page must learn about it without a polling storm (CI-B, FR-CI-5). The Software Architecture chose Server-Sent Events with polling as the fallback; the System Design (9.1) adds that workers `NOTIFY user_events` with an id-only payload, that each API process holds one listening connection and a map of open streams per user, that streams send a comment every 25 s, and that a reconnecting browser sends `Last-Event-ID` and refetches anything still pending. It does not say what an event id is or how much a reconnect can recover.

## Decision

- **Publish in the caller's transaction.** `publish(session, user_id, type, resource_id)` in `listenup.platform.events` runs `pg_notify('user_events', ...)` through the caller's session. PostgreSQL delivers it only on commit, so a rolled-back result is never announced. The payload is `{"u": user, "t": type, "r": resource id}`, about 120 bytes; anything over 1000 bytes is refused. Types are `job.progress`, `content.ready`, `grade.ready` and `attempt.voided`.
- **One listener and one hub per process.** `EventListener` keeps a dedicated autocommit psycopg connection (application name `listenup-events`) on `LISTEN user_events`, pings it after 30 quiet seconds and reconnects with backoff from 0.5 s to 30 s. `EventHub` forwards each notification to the open streams of that user only. Both start in the app's lifespan.
- **The route lives in platform, the sign-in check is passed in.** `events_router(current_learner)` builds `GET /api/v1/events`; `main.py` passes identity's `current_learner`, so the platform package never imports a module. The learner's database transaction ends before the stream starts, so an open stream holds no connection.
- **Event ids and `Last-Event-ID`.** An id is `<hub id>-<sequence>`: a random hub id per process and a sequence that rises with every event. The hub keeps the last 50 events per learner for 2 minutes. A reconnect to the same process whose buffer still covers the gap gets the missed events replayed; any other reconnect (another process, a restart, an expired or overflowed buffer, an unknown id) gets one `resync` event, and the browser refetches everything it still shows as pending. When the listener reconnects, notifications sent meanwhile are lost without a sequence number, so every open stream gets `resync` and older ids can no longer be replayed. A stream that falls 100 events behind has its backlog replaced by one `resync`.
- **Browser.** `useLiveEvents` (apps/web/src/events) opens an `EventSource`, invalidates the TanStack Query keys the caller maps each event to, invalidates the pending keys on `resync` and after any reconnect, and while the stream is down invalidates the pending keys every 5 s.

## Consequences

Events carry ids only, so the browser always refetches through the normal access checks and nothing private passes through the hub. Replay is best effort and per process; correctness rests on `resync` plus refetching pending resources, which works the same behind a load balancer with several API processes. At stage 2 the source can move to Redis publish and subscribe behind the same hub without a client change.

Open streams keep uvicorn from finishing a graceful shutdown or a `--reload` until they close, because uvicorn waits for running responses before it runs the lifespan shutdown that closes them. Run uvicorn with `--timeout-graceful-shutdown` (for example 5 s); browsers reconnect on their own.
