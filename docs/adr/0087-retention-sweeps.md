# ADR 0087: Retention sweeps as scheduled background jobs

- Status: Accepted
- Related: #93, #38, ADRs 0015, 0029 and 0070; SRS FR-SH-17, NFR-SEC-4
- [Owner exception E1 (2026-10-29)](https://github.com/abubakar1010/ListenUp/issues/93#issuecomment-6496660979) splits #93: the sweeps below are built now; the two
  YouTube sweeps stay open for #38, so #93 stays open.

## Decision

Each sweep is a scheduled job in `listenup/ops/retention.py` (ADR 0029 scheduling),
working in batches of 1,000 rows chosen with `FOR UPDATE SKIP LOCKED`, short
transactions. Remote storage calls never run inside a database transaction. A sweep
returns the number of persisted removals and converges safely on repeated runs.

| Job | Rule | Lane |
| --- | --- | --- |
| `ops.sweep_shadow_recordings` | recording older than `LISTENUP_SHADOW_RECORDING_RETENTION_DAYS` (default 90, D7): delete the file, then clear the recording columns | background |
| `ops.sweep_login_sessions` | `expires_at` in the past | background |
| `ops.sweep_one_time_tokens` | used or expired more than 7 days ago | background |
| `ops.sweep_idempotency_keys` | older than 24 hours | background |
| `ops.sweep_rate_counters` | window older than 1 day | background |
| `ops.sweep_scratch_files` | owned, unlocked media scratch older than `LISTENUP_SCRATCH_MAX_AGE_SECONDS` (default 1 hour) | intake |
| `ops.sweep_default_scratch_files` | owned, unlocked export scratch on the default pool, same age | background |

- **Shadow recordings.** The file goes first. A crash before the row is cleared leaves
  a key whose file is gone, and the next sweep deletes again (deleting a missing
  file is not an error). Migration `93_shadow_retention` lets the
  `check_shadow_round` trigger accept exactly one change to a recorded round:
  clearing `recording_key`, `recording_mime`, `recording_bytes` and `uploaded_at`
  together while `recorded_at` is unchanged. The round keeps `recorded_at`, so its
  grades and word labels stay, and the round reports no recording.
- **Batches and failures.** Recording selection uses 1,000 rows with `FOR UPDATE
  SKIP LOCKED`; that transaction commits before any storage deletion. The immutable
  key on the round is durable retry state. After each successful object deletion,
  a short conditional UPDATE clears only the same key on the still-expired round.
  Overlapping workers may delete the same immutable key (S3 deletion is idempotent),
  but only one wins finalization. A crash or database rollback retains the key for
  retry. Per-key storage failures preserve that key, allow other rows to progress,
  and raise at the end for bounded job retries; daily schedules recover exhausted runs.
  No schema or additional claims table is needed. Completion uses `recorded_at`,
  which retention preserves. The trigger uses a NULL-safe equality check.
- **Scratch files.** `platform.scratch.directory` creates a directory in the private
  `listenup-scratch-v1` namespace with an ownership marker and a shared lifetime lock.
  Media supervisors pass a shared lease descriptor through the process launcher so
  an orphan child still using its files remains protected. The sweep takes an
  exclusive nonblocking lock, checks marker/entry identity without following symlinks,
  and removes only entries whose descendants are all older than the configured age.
  Namespace and entry directories must belong to the worker's effective user and
  have no group/other permissions. Markers must be regular, singly linked, owned
  by that user and not writable by other users. Inspection and removal use open
  directory descriptors; replacing the entry pathname cannot redirect deletion.
  Entries are created with `mkdir(dir_fd=)` and scanned through open descriptors, never
  `/proc`, so the scratch code also runs on macOS development machines.
  Scanning uses an explicit work list and reopens each path component from the
  pinned entry descriptor with `O_NOFOLLOW`. Ancestor descriptors and scanners
  are closed before visiting descendants, keeping scan descriptor use constant
  with depth at the cost of reopening ancestors. A child removed before it is
  opened is skipped; disappearance during stat leaves the entry for a later pass.
  Entry and marker identities are rechecked after scanning and before final unlink.
  Code running as the worker's own Unix user is trusted not to tamper with live
  leases; these checks are not an isolation boundary between same-user processes.
  Unmarked/legacy/unrelated entries remain for operator inspection; age is not proof
  of abandoned ownership. Each pool sweeps its own disk every 15 minutes: intake
  `ops.sweep_scratch_files` on media, background `ops.sweep_default_scratch_files` on
  default (including export scratch). The media supervisor supplies the parent root
  only to its maintenance child via `LISTENUP_SCRATCH_CLEANUP_ROOT`; ordinary children
  receive only their per-job directory. With no media root configured the media
  sweep is disabled. Default export scratch uses the private namespace under the
  configured root or the system temp directory, never unrelated temporary files.
- **AI call log partitions** are already created ahead and dropped after 90 days by
  `ai.maintain` (#64, every five minutes), so no new job is added.
- **Not built here:** expired YouTube playback files and unreferenced YouTube media
  (#38, behind the YouTube feature flag).

## Consequences

The 90-day recording deletion in the privacy policy and voice notice is now enforced
in code. The retention synchronization publishes `privacy-2026-2` and `voice-2026-2`,
preserving the previous labels. Legal advice and #90 remain separate launch gates.
