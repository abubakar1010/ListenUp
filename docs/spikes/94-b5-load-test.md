# Spike #94 (B5): API and Blind heartbeat load test

- Issue: [#94](https://github.com/abubakar1010/ListenUp/issues/94). Requirements: NFR-PERF-3. Sources: System Design 1.1, 2.3, 9.2, 12.1 (B5); Database Design 11.1; [ADR 0024](../adr/0024-blind-heartbeats-resume-and-attempt-bound-media.md).
- Decision: [ADR 0065](../adr/0065-b5-load-test-method.md) (Proposed). Launch gate: [#155](https://github.com/abubakar1010/ListenUp/issues/155) ([ADR 0039](../adr/0039-performance-validation-before-launch.md)).
- Raw results: [`data/b5/`](data/b5/): `results.json`, `results.md` and `requests.csv.gz` (every request) for each run, produced by `spike-b5` (`spikes/`, see its README).

> **Local evidence only — not stage-0.** The stage-0 server (#16) does not exist. Every number here comes from the Docker Compose stack on the cloud container below, with the load generator on the same machine. **Whether B5 passes on stage 0 is deferred until staging and is unverified.** These results cannot close #94 or satisfy #155.

**Machine:** Intel Xeon Processor @ 2.10 GHz (model name as reported), 4 cores, 15.7 GB RAM, Linux x86_64, Docker 29.9.2, Compose 5.6.1. Run date: 2026-10-25.
**Software:** API and worker images built from this branch (`infra/docker/backend.Dockerfile`, targets `api` and `worker`). The default run's image is `sha256:fda18fbf…`. The diagnostic run is commit `44cdb31` (the harness commit; the results documents were still uncommitted, so `git_dirty` is true). The default run measured the same harness and application code before that commit (recorded as `5db1333` plus uncommitted harness files). PostgreSQL 16 (`postgres:16-alpine`), SeaweedFS, k6 1.3.0 (`grafana/k6:1.3.0`).

## Question and answer

| Question (#94) | Local answer (preliminary) |
| --- | --- |
| With 15 req/s of mixed traffic plus 20 Blind learners sending heartbeats, do reads and writes stay within p95 200 ms and 300 ms at under 30% CPU? | **Locally, the latency and CPU targets are met with wide margin.** Read p95 22 ms; write p95 31 ms (47 ms in the error-free diagnostic run); server CPU (API + DB + worker) 6.6% of the host on average, 10.5% at p95. The default configuration fails the proposed error check because of heartbeat failures (#216); the diagnostic run passes every check. **On stage 0: unverified.** |
| Slow queries (pg_stat_statements) | **None.** No statement averaged 10 ms or more; the highest mean was 2.3 ms (job-queue functions). See [statements](#slow-queries). |
| Other findings | About 10% of heartbeats failed without a response, because the API's 5 s keep-alive equals the 5 s heartbeat interval: follow-up [#216](https://github.com/abubakar1010/ListenUp/issues/216). |

## Method

The method is ADR 0065's; in short:

- **Stack.** `infra/compose/compose.yml` plus [`spikes/load/compose.b5.yml`](../../spikes/load/compose.b5.yml), with:
  - PostgreSQL with `pg_stat_statements` preloaded and `track_io_timing`;
  - the API as one uvicorn process without reload;
  - the default worker;
  - the fake AI configuration;
  - storage.

  No media worker, ClamAV or speech models: speech is B1 to B4. Each run started from empty volumes.
- **Data.** 150 learners (the stage-0 daily figure). Each has:
  - the fixture script's clip with a session at each step, including an active Blind attempt, a Dictation draft, a mark and a card (`tests/integration/seed.py`);
  - a cached ten-word transcript;
  - 10 more clips with 6 sessions each, so 1,650 clips and 9,900 sessions in total;
  - a login session.

  The first 20 learners also have 8 fresh sessions open at Blind. Seeding took about 12 minutes and is outside the measurement. The manifest of session tokens is written owner-only into a private temporary folder outside the results, and removed however the run ends. The harness now deletes the seeded learners after a run unless `--keep-data` is given; this change came after the two runs below.
- **Sign-in and CSRF.** The login sessions are written through the identity repository: `POST /auth/login` is limited per IP, which would refuse 150 sign-ins from one generator. Every request sends the session cookie and the CSRF double-submit pair (the same value as cookie and `X-CSRF-Token`), so the real middleware checks it.
- **Mixed traffic.** k6 `constant-arrival-rate` at 15 req/s, round-robin over the learners, so a learner's previous flow has always finished:

  | Flow | Requests | Weight |
  | --- | --- | --- |
  | `GET /sessions/{id}` (any step) | read | 20 |
  | `GET /me`, `GET /sessions` | read | 10 each |
  | `GET /library/contents`, `GET /sessions/{id}/transcript`, `GET /sessions/{id}/marks` | read | 8 each |
  | `GET /contents`, `GET /cards`, `GET /sessions/{id}/blind`, `GET /dictation/attempts/{id}` | read | 4 each |
  | Dictation autosave: `POST /sessions/{id}/dictation/attempts` (resume), then `PUT …/draft` at its version | 2 writes | 6 |
  | Mark then unmark: `POST /sessions/{id}/marks`, then `DELETE` it | 2 writes | 5 |
  | Mark note: `PATCH /sessions/{id}/marks/{id}` | write | 6 |

  That is about 74% reads and 26% writes by request.
- **Blind learners.** 20 learners, each:
  1. starts an attempt;
  2. sends a heartbeat at once, then every 5 s, with the real-time position;
  3. sends `ended` after the 120 s passage;
  4. moves to its next fresh session.

  A beat without a response does not end the listen: the next beat follows, as the player's clock does. The 20 learners start in step, so the starts and beats arrive in bursts. That makes the test harsher than real traffic.
- **Window.** 60 s warm-up, then 600 s measured. pg_stat_statements is reset at the end of warm-up. Since these runs, the runner picks a wall-clock start that k6 waits for, so the reset and the CPU window follow k6's own clock. In the two runs below, the runner estimated k6's start as one second after the container started.
- **Measures.**
  - p95 is nearest rank over every measured request, failures and timeouts included. A second p95 over the answered requests shows how far fast failures pull it down.
  - An error is no response, or any status of 400 or more.
  - Heartbeats count as writes for the 300 ms target, and are also shown alone.
  - CPU comes from the `docker stats` stream, about two samples a second (1,200 per container in 600 s), as a share of all 4 host cores. The **server** figure (API + DB + worker) is checked against the 30% target; the load generator is shown separately.
  - **Run validity (proposed, for the owner to confirm; added after these runs).** Reads and writes each fail under 1% of the time, and at least 95% of the planned mixed and heartbeat rates is delivered. Otherwise, fast failures or a short-changed load would pass the latency targets.

## Results

Two runs at the same load. The **default** run uses the compose command as committed. The **diagnostic** run adds `spikes/load/compose.keepalive.yml` (`--timeout-keep-alive 10`) to test the cause of the heartbeat errors. The default is the configuration under test.

### Delivered load

| Run | Mixed req/s | Heartbeats/s | Blind listens voided |
| --- | --- | --- | --- |
| default | 15.21 | 4.20 | 0 |
| keep-alive 10 s (diagnostic) | 15.18 | 4.19 | 0 |

20 learners at one beat per 5 s is 4.0 beats/s. The extra 0.2/s is the immediate first beat of each listen. Mixed traffic includes about 100 Blind attempt starts.

### Latency (ms, measured window)

| Group | Run | Requests | p50 | p95 | p99 | max | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- |
| read | default | 6,623 | 11.6 | **22.4** | 29.8 | 177.5 | 0 |
| read | diagnostic | 6,659 | 11.5 | 22.4 | 31.6 | 169.8 | 0 |
| write (heartbeats included) | default | 5,021 | 13.7 | **31.1** | 83.9 | 236.5 | 249 (4.96%) |
| write (heartbeats included) | diagnostic | 4,958 | 17.1 | 46.9 | 110.5 | 211.3 | 0 |
| heartbeat | default | 2,520 | 14.6 | 30.5 | 68.0 | 218.7 | 249 (9.88%) |
| heartbeat | diagnostic | 2,512 | 22.7 | 53.4 | 108.8 | 202.2 | 0 |

**The failures hardly move the default run's percentiles.** The 249 failed heartbeats took under 8 ms each (235 of them under 3 ms) and are counted, as the method requires. Taking only the answered requests from `requests.csv.gz`, the default run's heartbeat p95 is 31.9 ms (2,271 requests) and its write p95 31.8 ms, against 30.5 ms and 31.1 ms with the failures. So the failures explain about 1 ms, and the gap to the diagnostic run's heartbeat p95 of 53.4 ms is **unexplained**: the longer keep-alive may cost something, or it may be run-to-run variance, and with one run each this can't be told apart. Both are well under 300 ms.

The slowest endpoint is starting a Blind attempt: p95 205 ms in the default run, median 53 ms. Each start runs `require_step`, inserts the attempt, signs a token and queues the expiry job. The 20 starts arrive together every 125 s with the matching heartbeats. All other endpoints have p95 at or under 34 ms (`results.md` per run).

### CPU (share of all 4 host cores)

| Role | Default mean | Default p95 | Default max | Diagnostic mean | Diagnostic p95 |
| --- | --- | --- | --- | --- | --- |
| API | 4.5% | 6.9% | 17.4% | 4.4% | 6.5% |
| Database | 1.9% | 3.1% | 13.7% | 2.0% | 3.3% |
| Worker | 0.3% | 0.9% | 4.1% | 0.3% | 0.8% |
| **Server (API + DB + worker)** | **6.6%** | **10.5%** | 31.9% | 6.7% | 10.4% |
| Load generator (k6) | 1.0% | 1.5% | 2.6% | 0.9% | 1.2% |

The 32% maximum is one-second samples during the Blind start bursts. The target is the window's mean, and that holds up to the 95th-percentile second. The API used about 0.18 of one core on average. That's consistent with System Design 2.3's "a few percent of one Python process", though on this container's CPU rather than stage 0's.

### Against System Design 1.1 and 12.1 (local only)

| Check | Target | Default run | Diagnostic run |
| --- | --- | --- | --- |
| Read p95 | under 200 ms | 22.4 ms: meets | 22.4 ms: meets |
| Write p95 | under 300 ms | 31.1 ms: meets | 46.9 ms: meets |
| Server CPU, mean | under 30% | 6.6%: meets | 6.7%: meets |
| Error rate, reads and writes each (proposed) | under 1% | writes 4.96%: **misses** | 0%: meets |
| Delivered load (proposed) | at least 95% of 15 req/s and 4 beats/s | 15.21 and 4.20: meets | 15.18 and 4.19: meets |
| **Stage 0** | the same | **deferred until staging — unverified** | |

The two run-validity rows were added to the runner after these runs; this table applies them to each run's `results.json`. The committed `results.md` files show only the three targets.

### Slow queries

No statement in either run averaged 10 ms or more, so there's no index change and no slow-query follow-up. The heaviest statements by total time (default run):

| Statement | Calls | Mean ms | Max ms | Note |
| --- | --- | --- | --- | --- |
| `SELECT identity.resolve_auth_session($1)` | 11,383 | 0.75 | 13.1 | Every request; 0.07 ms is its inner query, the rest the function call. About two thirds of all statement time, but not slow. |
| Session by id, its steps, consents | 8,000–11,400 | 0.04–0.07 | under 4 | Primary-key and index lookups (Database Design 11) |
| Procrastinate fetch, defer and finish | 100–650 | 0.4–2.3 | under 9 | The job queue: Blind expiry jobs and periodic tasks |
| Card list with source URLs | 328 | 1.1 | 4.9 | 21 rows per call on average |

The heartbeat's own `UPDATE practice.blind_attempts … WHERE id = $1` (Database Design 11.1) averaged under 0.2 ms.

## Findings

1. **Heartbeats meet closed keep-alive connections.** uvicorn's default keep-alive timeout (5 s) equals the heartbeat interval, so a beat that reuses the connection can arrive as the server closes it. k6 reports `connection reset by peer` or EOF (error codes 1220 and 1000).
   - In the default run, 249 of 2,520 heartbeats (9.9%) failed this way. With `--timeout-keep-alive 10` there were none.
   - k6 saw no listen stopped by the server: one lost beat is a 10 s gap, under the 15 s limit. These runs didn't record the attempts' final outcomes, though. A listen whose `ended` beat got no answer stays unfinished, and the expiry worker voids it where k6 can't see. The runner now records every Blind attempt's outcome at the end of a run.
   - The web player is less forgiving than k6. It stalls after 10 s without an answered beat (`STALL_AFTER_MS` in `apps/web/src/features/blind/listen.ts`), so two lost beats in a row use up the listen's one resume, and a second stall voids it. At a 9.9% loss rate that would hit real learners.
   - Deployment settings belong to the deploy pipeline, so this is filed as [#216](https://github.com/abubakar1010/ListenUp/issues/216) rather than changed here.
2. **No slow queries** at stage-0 data volume (150 learners, about 3 months of clips). The hot paths use the indexes Database Design 11 lists.
3. **Signing in costs about 0.75 ms per request** in `identity.resolve_auth_session`. It's the largest share of database time, but far from a constraint at stage 0. Revisit only if a later stage shows it matters.
4. **Bursty Blind starts** produce the highest per-endpoint p95 (205 ms) and the one-second CPU peaks. Real learners do not start in step; the stage-0 run may keep this as a worst case.

## Runs excluded

Two earlier full runs were discarded, not averaged in:
- One overlapped a unit-test run on the same machine during its measured window.
- The other exposed a harness bug: a heartbeat without a response ended the listen, so learners used up their sessions and delivered only about 45% of the planned heartbeats. The fix (keep beating) is in `spikes/load/b5.js`. The runner now reports the delivered rates so a short-changed run shows up.

Short smoke runs (25 learners, 30 s) were used only to develop the harness.

## Limits of this evidence

- One 4-core cloud container ran the stack and the load generator together. Stage-0 hardware, network and its reverse proxy are absent.
- The fake AI configuration and no media worker: speech and AI work compete for CPU on stage 0 (System Design 5.2), and B5 does not measure them.
- Seeded clips have no audio, so media redirects and signed-URL downloads are not in the mix. Uploads, sign-ins and the event stream are not in it either (ADR 0065).
- One run per configuration, 600 s each. No repeat-run variance is reported.
- The two runs were made before the fixes from the review on the pull request: the private manifest, deleting the seeded learners, the agreed wall-clock start, the answered p95, the attempt outcomes and the run-validity checks. Their `results.json` and `results.md` are kept as produced.

## Rerunning on stage 0

Follow ADR 0065's stage-0 section and `spikes/README.md` (B5):
- Run `spike-b5 --stage0 --skip-up --base-url <deployment>` against the deployed release candidate, with `--database-url` naming the deployment's database owner.
- Use the load generator on another machine where possible.
- Record the deployment's own CPU.
- Keep the raw `requests.csv.gz`.
- Link the reviewed result from #94 and #155.

## #216 configuration follow-up

Normal API commands now explicitly use 30 s idle keep-alive, with Caddy upstream
pooling at 15 s. See [the follow-up record](216-connection-timeouts.md) for
semantics, passing configuration tests, the blocked local rerun, and exact
outstanding stage-0 verification. The historical results above are unchanged.
