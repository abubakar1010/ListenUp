# ADR 0031: Unique keys cover running jobs, and stalled jobs are recovered

- Status: Accepted
- Date: 2026-10-08
- Source: the review of pull request #131 (account deletion); [System Design 4, 11.1 and 11.3](https://claude.ai/code/artifact/98274889-96ba-4424-afad-c2cd056206e2); ADRs 0015 and 0029

## Context

ADR 0015 maps unique job keys to Procrastinate's queueing locks, which allow one *waiting* job per key. Two cases were not covered:

- **A copy queued while the job runs.** The account purge sweep runs every 15 minutes, and a purge may run for up to 30. A sweep during a purge queued a second job with the same key, because the running one was no longer waiting. If the running purge then failed, its retry had to go back to waiting beside the copy. Procrastinate's retry does not handle that conflict, so the job stayed `doing` for good, its attempts were never counted and `on_give_up` never ran.
- **A worker that dies mid-job.** A worker that is killed, redeployed or runs out of memory leaves its job `doing`. That job still holds its lock (the purge's `deletion_request:<id>`), so every later job with that lock waits behind it for ever. Procrastinate notices dead workers through their heartbeats, but it does not put their jobs back in the queue by itself.

## Decision

- **`enqueue` with a `unique_key` queues nothing while a job with that key is waiting or running** (status `todo` or `doing`), and returns None. The running job does the work, and if it fails, its retry can always go back to the queue. This applies to every job with a key; for all of them, the running job covers what a copy would have done.
- **`platform.recover_stalled_jobs`** runs every 5 minutes on the background lane (a scheduled job, ADR 0029). A `doing` job is stalled when its worker has sent no heartbeat for a minute, or Procrastinate has already dropped the worker. Its run counts as a failed attempt:
  - with attempts left, it goes back to the queue at once;
  - after its last attempt, its `on_give_up` runs (the purge marks its request `'failed'`) and the job is marked failed;
  - if a copy with the same key is already waiting (for example one postponed by backpressure), the stalled job is marked failed and the copy does the work.

## Consequences

- A purge whose worker dies resumes within about five minutes, from the step its request records. Every other job gets the same protection.
- A handler must still be idempotent: a job whose worker died may have done part of its work, and it runs again.
- The recovery runs only in the default pool, like every background-lane job. When that pool is down, nothing is recovered until it is back, and nothing could run then anyway.
- System Design 4 and 11.1 should mention the recovery job and that a unique key covers running jobs. That document lives outside the repository and is not updated here.
