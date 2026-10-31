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
11. Use ADR 0087 (#247 owns 0086, now merged on main); restore E2's 0074 reference.
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
The real-launcher lease contract was added as characterization; a separate process
that removes descriptor inheritance from the subprocess boundary makes it fail,
confirming the test detects loss of the orphan-child protection.
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

Source fix: `ea39d4b`. Current main `39dffb1` (#247 restore checks) was subsequently
merged cleanly; final aggregate CI and independent re-review of the combined head
remain required before merge.

- Focused neighboring suite: 136 passed. Focused coverage after the final FIFO fix:
  137 passed, complete runtime inventory, **98% changed executable lines**; only
  scratch race-guard lines 63 and 72 uncovered. No coverage exclusion was changed.
- Added real-launcher lease contract: passes; removal of inherited descriptors in
  an isolated process makes it fail as expected. This is characterization/mutation
  evidence, not a fabricated pre-implementation Red record.
- Ruff lint/format passed; mypy passed (214 source files); six import contracts kept.
- Disposable PostgreSQL 16: upgrade, drift check, downgrade one, upgrade and drift
  check passed. `alembic heads`: exactly `93_shadow_retention`; parent is
  `89_content_deletion`. No new table/grant/RLS policy is introduced.
- CI on `ea39d4b`: **2,616 backend tests passed**, one opt-in real-model test skipped;
  required PostgreSQL and S3 flags were set. Separate performance: **1 passed**;
  spike regression checks: **106 passed**. Required changed-line coverage passed.
- Local web: **739 tests passed**; lint/format/types/build/size passed. Initial JS
  126.7 KB gzip (200 KB budget). CI browser smoke, accessibility, deployed media
  sandbox/real scanner, API client and vulnerability checks passed. Deploy checks,
  including Arm64 images, passed.
- The first CI worker-media image build failed during apt dependency installation:
  Debian returned a package whose size differed from the index (mirror sync).
  Failed/cancelled image jobs were requeued. Final aggregate CI is still required.
- Broad local backend/browser runs were stopped in favor of complete CI evidence;
  they are not passing results. The local browser run had 23 passes before being
  interrupted; 238 cases did not run. A local scoring performance run failed under
  concurrent coverage/browser load, then passed after that load stopped; CI's
  separate uninstrumented performance run also passed. Neither result is hidden.
- Actual-host performance and real speech-model acceptance remain outside this
  retention change and are not established by synthetic/unit/CI results.

## Independent re-review remediation, 2026-10-30

The owner instructed this session to post the independent review, fix all findings
and merge only if everything is fine. The review of `8f488bc` is posted at
https://github.com/abubakar1010/ListenUp/pull/249#issuecomment-6526165898.
It found a scratch pathname-replacement race and stale completion documentation.
This instruction authorizes the current fixes and conditional merge; it does not
establish historical migration ownership, initial plan approval or TDD chronology.
No migration is changed in this remediation. Main `61a5d92` (#253 and #252) is
integrated without conflicts. E1, #93's open status and all legal gates still apply.

| Criterion | Named test / check | Actual Red | Green |
| --- | --- | --- | --- |
| A replaced directory must not redirect deletion | `test_directory_replaced_during_scan_is_not_deleted` | Sweep removed the unmarked replacement; expected 0, got 1 | Passed after descriptor-relative removal |
| A replacement marker with an active lease must survive | `test_marker_replaced_by_active_lease_during_scan_is_preserved` | Sweep removed the directory despite the new shared lease | Passed after marker identity revalidation |
| Reject a namespace writable by other users | `test_nonprivate_namespace_is_refused_and_not_swept` | Sweep removed a stale directory from a mode-0777 namespace | Passed after owner/mode validation |
| Preserve completion after recording expiry, FR-SH-17 | Read completion convention against `complete_recording` and `test_step_completes_when_an_older_recording_was_swept` | Documentation-only; no artificial Red | Convention now uses preserved `recorded_at` as completion evidence |

The three regression tests above were run before the fix with
`.venv/bin/python -m pytest tests/unit/test_scratch.py -k 'replaced or nonprivate' -q`:
**3 failed**. The expanded focused command is
`.venv/bin/python -m pytest tests/unit/test_scratch.py tests/unit/test_media_sandbox.py tests/unit/test_worker_modules.py tests/unit/test_consents.py -q --cov=listenup.platform.scratch --cov-report=term-missing`:
**79 passed; scratch line and branch coverage 100%**. Added late-removal, final-unlink,
nested-symlink, missing-namespace and invalid-marker/owner cases are strengthening
after implementation, not invented pre-implementation Red cycles. Their assertions
check retained foreign contents and retained active lease markers, not just counts.
The permission-error test now injects refusal at `rmdir`, the filesystem boundary
used by descriptor-relative cleanup, and still requires the other entry to progress.

Backend Ruff lint/format passed; mypy passed on 214 source files; all six import
contracts passed. Full required-service suites, changed-line coverage and deployed
boundary/image checks must pass in CI on the final pushed head. Material fixes need
fresh-session re-review before merge. Results on older heads do not satisfy that gate.
The implementation now explicitly states its Unix-user trust boundary: another
process running as the same worker user is not an isolated hostile principal.

Additional local PostgreSQL 16 validation passed: **71** retention, Shadow recording
and export integration tests. The initial final-head CI attempt then failed its
real dependency audit: locked `joserfc` 1.7.5 has CVE-2026-119284, fixed in 1.7.6.
`uv lock --upgrade-package joserfc==1.7.6` changed only that package in `uv.lock`.
This is a security patch required to clear CI, not a waived audit or added ignore.
Actual Red: CI job 124145396510 reported that vulnerability and exited 1. Green:
`uv export --frozen --no-dev --no-hashes --no-emit-project` followed by
`uvx pip-audit -r <exported requirements>` reported **No known vulnerabilities**.
Authentication neighbors on the patched dependency passed **119 tests**:
`test_google_oidc.py`, `test_google_data.py`, `test_auth.py`, integration/unit
`test_consents.py`, and `test_google_redirects.py`. Final CI must rerun on this
patched head; the earlier failed attempt remains disclosed.
