# ADR 0065: B5 load-test method, with the stage-0 result outstanding

- Status: Proposed; the stage-0 pass/fail below is deferred until staging — unverified
- Date: 2026-10-25
- Sources: issue #94; System Design 1.1, 2.3, 9.2, 12.1 (B5); Database Design 11.1; NFR-PERF-3; [ADR 0024](0024-blind-heartbeats-resume-and-attempt-bound-media.md); [ADR 0039](0039-performance-validation-before-launch.md); launch gate #155; results in [docs/spikes/94-b5-load-test.md](../spikes/94-b5-load-test.md)

## Context

B5 asks whether, at stage 0, 15 requests per second of mixed traffic plus 20 Blind
learners sending a heartbeat every 5 s keep API reads under 200 ms and writes under
300 ms at p95, at under 30% CPU (System Design 1.1 and 12.1). The capacity plan
assumes the API and database are never the constraint at stage 0 (System Design 2.3).
The stage-0 server (#16) does not exist yet, so ADR 0039 defers the qualifying run to
the pre-launch gate #155. What can be settled now is how B5 is measured, so that the
stage-0 run repeats a reviewed method rather than inventing one under launch pressure.

## Decision

- **Tool: k6** (`grafana/k6:1.3.0`, pinned image). Its constant-arrival-rate executor
  keeps sending at the planned rate when responses slow down, so a slow server cannot
  lower its own load and flatter its percentiles (coordinated omission). A Go load
  generator also leaves more CPU to the server when both share a machine. Seeding,
  orchestration and the tested analysis stay in Python (`spikes/`, `spike-b5`).
- **Workload.** 15 req/s of mixed traffic at a constant arrival rate, about 74% reads
  and 26% writes by request, spread round-robin over the seeded learners: the session,
  session list, library, contents, transcript, marks, cards, Blind state and Dictation
  reads; Dictation autosave (resume then save at the draft version), mark create and
  delete, and mark notes as writes. On top, 20 Blind learners each start a listen,
  send a heartbeat every 5 s with a real-time position, finish with `ended` and move
  to their next fresh session. Heartbeats count as writes for the 300 ms target and
  are also reported alone. 60 s warm-up, 600 s measured.
- **Data.** 150 learners (the stage-0 daily figure), each with the fixture script's
  clip and a session at every step including an active Blind attempt
  (`tests/integration/seed.py`), a cached transcript, 10 more clips with their
  sessions, and a login session. Sign-in is seeded through the identity repository,
  because the per-IP sign-in limit would refuse 150 sign-ins from one load generator.
  CSRF goes through the real double-submit check. The manifest of session tokens is
  written owner-only into a private temporary folder outside the results and removed
  however the run ends; the seeded learners, with their data and login sessions, are
  deleted after the run unless `--keep-data` is given.
- **Measures.** p95 is nearest-rank over every request in the measured window, failed
  requests and timeouts included; a second p95 over the requests that got a response
  shows how far fast failures pull it down. The error rate counts no response and
  every status of 400 or more. CPU comes from the `docker stats` stream (about two
  samples a second) as each container's share of all host cores; the **server** figure
  (API + database + worker, summed per sampling round, leaving out and counting any
  round that misses one of them), averaged over the window, is what the 30% target is
  checked against, with the load generator reported separately. pg_stat_statements is
  reset at the end of warm-up and its top 20 statements by total and by mean time are
  recorded, through the owner's database URL; any statement with a mean of 10 ms or
  more is listed for a fix or a follow-up story. The Blind sessions' attempts are
  counted by outcome at the end of the run (listened, unfinished, voided by reason).
- **Window.** The runner picks a wall-clock start; k6 waits for it in `setup()` and
  fails if it starts late, so the warm-up, the statement reset and the CPU window all
  follow one clock.
- **Run validity (proposed, for the owner to confirm).** A run passes only if, besides
  the three targets, reads and writes each fail under 1% of the time and at least 95% of
  the planned mixed and heartbeat rates is delivered. Fast failures would otherwise
  pass the latency targets, and #155 keeps failures in the outcome.
- **Labels.** A run is local unless started with `--stage0`, which needs `--skip-up` and
  the deployment's `--base-url`; local results say they are not stage-0 evidence in the
  report's first lines, and every report records the host name and base URL.

## Local result (preliminary, not stage-0 evidence)

See [docs/spikes/94-b5-load-test.md](../spikes/94-b5-load-test.md).

On a 4-core cloud container, with the load generator on the same machine, 2026-10-25:

- **Default configuration:** read p95 22.4 ms, write p95 31.1 ms (heartbeats 30.5 ms),
  server CPU 6.6% mean and 10.5% at p95. 15.21 mixed req/s and 4.20 heartbeats/s were
  delivered. No statement averaged 10 ms or more.
- **Errors:** 249 heartbeats (9.9%) failed without a response, because the API's
  default 5 s keep-alive equals the 5 s heartbeat interval. With
  `--timeout-keep-alive 10` there were none, and heartbeat p95 was 53.4 ms. The
  failures hardly moved the default run's figure: its answered heartbeats alone have a
  p95 of 31.9 ms (30.5 ms with the failures). The difference to 53.4 ms is unexplained;
  there is one run of each configuration and no repeat-run variance. k6 saw no listen
  stopped by the server; these runs did not record the attempts' final outcomes, so a
  listen whose `ended` beat got no answer may have been voided later by the expiry
  worker. This is follow-up [#216](https://github.com/abubakar1010/ListenUp/issues/216)
  for the deployment settings.
- **Against the run-validity checks** (added after these runs, applied to their
  `results.json`): the default run misses the error check (4.96% of writes failed); the
  diagnostic run meets every check.

Locally, the latency and CPU targets are met with wide margin, and the default
configuration fails on heartbeat errors (#216). That says nothing about stage 0.

## Stage-0 pass/fail: deferred until staging — unverified

Not run. The stage-0 server (#16) and the release candidate deploy (#112) do not exist.
Whether B5 passes on stage 0 is **unknown**; no local or GitHub-hosted result may be
read as passing it. Before public launch, under #155:

1. Deploy the release candidate to the stage-0 host with its real configuration.
2. Run `spike-b5 --stage0` with this method against it, the load generator on another
   machine where possible, and record the deployment's CPU.
3. Record commit and image ids, hardware, settings, raw durations, failures and the
   percentile method (the runner writes them), have the evidence independently
   reviewed, and update this ADR's status to Accepted or replace the decision.

Targets that stay unverified until then: read p95 under 200 ms, write p95 under
300 ms, server CPU under 30% (System Design 1.1, 12.1 B5; NFR-PERF-3).

## Consequences

- The stage-0 run reuses a tested harness: seeding, statements and attempt outcomes go
  through `--database-url`, and k6 can run from another machine. The CPU sampling still
  relies on `docker stats` on the same host; where it cannot see the deployment's
  containers the server CPU is missing and the check fails, so the deployment's own CPU
  must be recorded instead.
- The seeded learners are deleted after a run, so the stage-0 database is left as it
  was apart from the run's log and statistics.
- The mix excludes media playback, uploads and the event stream: media goes straight
  to storage with signed URLs, uploads are rate-limited and rare, and the event
  stream is long-lived rather than per-request. Speech work is B1 to B4.
- #94 stays open until the stage-0 run is recorded.
