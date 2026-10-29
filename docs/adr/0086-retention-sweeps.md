# ADR 0086: Retention sweeps as scheduled background jobs

- Status: Accepted
- Related: #93, #38, ADRs 0015, 0029 and 0070; SRS FR-SH-17, NFR-SEC-4
- Owner exception E1 (2026-10-28) splits #93: the sweeps below are built now; the two
  YouTube sweeps stay open for #38, so #93 stays open.

## Decision

Each sweep is a scheduled job in `listenup/ops/retention.py` (ADR 0029 scheduling),
working in batches of 1,000 rows chosen with `FOR UPDATE SKIP LOCKED`, one
transaction per batch. A sweep returns what it removed and finds nothing on a
second run, so it is safe to repeat and to run beside normal traffic.

| Job | Rule | Lane |
| --- | --- | --- |
| `ops.sweep_shadow_recordings` | recording older than `LISTENUP_SHADOW_RECORDING_RETENTION_DAYS` (default 90, D7): delete the file, then clear the recording columns | background |
| `ops.sweep_login_sessions` | `expires_at` in the past | background |
| `ops.sweep_one_time_tokens` | used or expired more than 7 days ago | background |
| `ops.sweep_idempotency_keys` | older than 24 hours | background |
| `ops.sweep_rate_counters` | window older than 1 day | background |
| `ops.sweep_scratch_files` | our scratch entries untouched for `LISTENUP_SCRATCH_MAX_AGE_SECONDS` (default 1 hour) | intake |

- **Shadow recordings.** The file goes first. A crash before the row is cleared leaves
  a key whose file is gone, and the next sweep deletes again (deleting a missing
  file is not an error). Migration `93_shadow_retention` lets the
  `check_shadow_round` trigger accept exactly one change to a recorded round:
  clearing `recording_key`, `recording_mime`, `recording_bytes` and `uploaded_at`
  together while `recorded_at` is unchanged. The round keeps `recorded_at`, so its
  grades and word labels stay, and the round reports no recording.
- **Batches and failures.** Recording deletes are serial storage calls made while the
  batch's row locks are held, and the worker role ends a transaction idle for 30 s, so
  this sweep uses batches of 50 (`SHADOW_BATCH`), not 1,000. A storage error on one key is
  logged and that row keeps its key; the other rows in the batch are cleared, the run
  skips the failed rows, and it ends by raising so the job retries them. Shadow
  completion counts a round as recorded by `recorded_at`, which retention leaves in
  place, so a session whose early round expired before the learner finished can still
  complete.
- **Scratch files** sit on the media pool's disk, so the sweep is on the intake lane,
  which that pool serves. It touches only entries named with the prefixes our jobs
  use, skips a directory with a file written inside the age limit, and does nothing
  when `LISTENUP_MEDIA_SCRATCH_DIR` is unset (the system temporary directory is shared).
  The directory must be set for the media pool; export archives are built in the default
  pool, so their `listenup-export-` scratch is swept only where both pools share that
  directory. One entry that cannot be removed is logged and does not stop the pass.
- **AI call log partitions** are already created ahead and dropped after 90 days by
  `ai.maintain` (#64, every five minutes), so no new job is added.
- **Not built here:** expired YouTube playback files and unreferenced YouTube media
  (#38, behind the YouTube feature flag).

## Consequences

The 90-day recording deletion in the privacy policy and voice notice is now enforced
in code. Their wording still says expiry is not implemented; revising the legal drafts
and their versions is the owner's decision (`docs/legal/README.md`, note 1).
