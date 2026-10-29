# Retention sweep validation (#93, PR #249)

## Scope and authorization

The owner instructed this session on 2026-10-29 to post the fresh review, fix all
findings in #249, and merge only if everything is okay. This authorizes the current
remediation of the existing `93_shadow_retention` migration; no new migration is
added. It does not establish the original session's historical migration ownership.
E1 is independently recorded in the owner comment on #93. #93 remains open and
both YouTube sweeps remain deferred to #38. OQ-6 is cleared for BUILD only; written
legal advice remains required before beta, launch and production YouTube enablement.
#103 text work is done; only the retention statements are synchronized here.

## Remediation plan

1. Keep the existing PR and compliant `feat/93-retention-sweeps` branch.
2. Reproduce the NULL-trigger, transaction-lifetime and normal-traffic failures.
3. Use 1,000-row SKIP LOCKED selection, then storage deletion outside transactions.
4. Preserve immutable recording keys as durable retry state until conditional clear.
5. Correct the existing trigger with NULL-safe comparison; keep one Alembic head.
6. Introduce private managed scratch with ownership markers and lifetime locks.
7. Pass a lease descriptor through the media launcher to protect orphan children.
8. Give only the maintenance child its pool root and sweep export scratch separately.
9. Keep legacy/unrelated scratch and refuse symlink/FIFO ownership markers.
10. Publish privacy/voice `2026-2` labels; retain previous accepted texts unchanged.
11. Use ADR 0087 (main ends at 0085, open #247 uses 0086); restore E2's 0074 reference.
12. Record tests honestly, run applicable checks and re-review material changes.

## Actual red/green records

Commands below run from `apps/api` using the installed `.venv/bin/python`.

| Criterion | Named tests and command | Red observed before fix | Green |
| --- | --- | --- | --- |
| Immutable recorded timestamp, FR-SH-17 | `pytest tests/integration/test_retention_sweeps.py -k 'clearing_recorded_at_to_null or storage_calls_hold_no or database_rollback or overlap_does' -q` | 3 failed, 1 passed: NULL clear accepted; storage call held a transaction; concurrent normal update hit lock timeout | Same four tests: 4 passed |
| Crash rollback and retry | `test_recording_database_rollback_keeps_key_for_retry` in command above | Passed on original implementation: characterization, not Red | Actual transaction rollback keeps the key; retry repeats deletion and clears it |
| Private scratch ownership, liveness, overlap, supervisor root and default export pool | `pytest tests/unit/test_scratch.py -q` | Collection failed because the deliberately specified `platform.scratch` interface did not exist | Initial seven tests passed after implementation; expanded cases run in final suite |
| FIFO marker must not hang cleanup | `pytest tests/unit/test_scratch.py -k fifo_marker -q` | Failed with bounded subprocess TimeoutExpired while opening a FIFO marker | Passed after nonblocking open |
| Current legal labels | `pytest tests/unit/test_consents.py -k retention_revision -q` | 1 failed: defaults still privacy/voice `2026-1` | Included in passing neighbor/final suites |
| Accurate current text, preserving old labels | From `apps/web`: `pnpm vitest run src/features/legal/texts.test.ts` | 1 failed: new revision text missing | Legal feature suite: 19 passed |

Additional scratch denial/error/lease cases, the exact retention boundary cases
(one microsecond before/at/after), and the full non-recording-column preservation
assertion were added as characterization/strengthening after the initial fixes;
they are not claimed as separately observed pre-implementation Red cycles.
The original builder's missing-module failure and later broad Red claims remain
historical author reports; this session cannot establish their chronology.

`test_recording_storage_calls_hold_no_database_transaction` sets the actual worker
role and its 30-second idle timeout. `test_recording_overlap_does_not_lock_normal_traffic`
uses events and bounded waits, checks a normal write while storage is blocked, then
requires both sweeps to converge with exactly one persisted removal.
`test_recording_sweep_preserves_all_nonrecording_round_data` compares every shipped
round field except the four intentionally cleared fields. Shadow grades and word
labels do not yet have a shipped persistence/read path; this test does not claim
end-to-end visibility of unimplemented grading. The sweep updates the round rather
than deleting it, preserving the future grading parent.

## Verification

- Focused neighboring suite: 136 passed (retention, scratch, recording, exports,
  consent, supervisor, worker registration).
- Ruff lint/format passed; mypy passed (214 source files); six import contracts kept.
- Disposable PostgreSQL 16: upgrade, drift check, downgrade one, upgrade and drift
  check passed. `alembic heads`: exactly `93_shadow_retention`; parent is
  `89_content_deletion`. No new table/grant/RLS policy is introduced.
- Full final backend coverage, performance, web checks, changed-line coverage,
  deployed media sandbox check and final CI/re-review: pending at this checkpoint.
  No pending result is a pass. Results will be updated after completion.
- Actual-host performance and real speech-model acceptance remain outside this
  retention change and are not established by synthetic/unit/CI results.
