# Story #70: Gist grading recovery validation

Owner approved the plan on 2026-10-25, including delayed-state precedence and
recoverable stored unavailable feedback. Branch: `feat/70-gist-grading-recovery`.
Prerequisite #68 merged in #190 (`4e0ed9f`); #69 feedback is present from #203.
Reconciled with main `5db1333`, including #210's UI and #189's UX documentation.
No Cards, reference profiles, Shadow rounds or shared UI refactoring is included.
ADR 0061 records the recovery contract and configuration.

## Test-first evidence

Commands ran from the repository root with `uv run --project apps/api pytest`
and the paths below, `LISTENUP_REQUIRE_DB=1`, `-q --tb=short`.
Web commands ran with `pnpm --dir apps/web exec vitest run`.

| Criterion | Named tests and actual red result | Green |
| --- | --- | --- |
| 30-second API boundary, persisted unavailable, saved gist/progress | `test_gist_recovery.py`: `test_deadline_boundary_preserves_gist_and_plan`, `test_stored_unavailable_and_delayed_are_visible`; 2 failed: missing `wait_ms`, unavailable read as pending | Initial 2 passed |
| Owned retry, concurrent requests, reuse active job | `test_retry_coalesces_waiting_and_concurrent_requests`, `test_retry_owner_and_submission_checks`; 2 failed: retry route missing | Recovery run: 10 passed |
| AT-14 provider failure/timeout, late success, AT-23 quota waiting | `test_gist_recovery_jobs.py`: `test_late_success_overwrites_unavailable_once`, parameterized `test_exhausted_failure_and_timeout_set_unavailable`, `test_quota_wait_reschedules_and_recovers`; 4 failed: old pending-only/no-settlement behavior | Recovery run: 10 passed |
| Gateway quota signal | `test_text_gateway.py::test_quota_exhaustion_is_distinct_and_does_not_call_provider`; failed: generic unavailable reason | Gateway neighboring run: 47 passed |
| Unavailable/delayed UI and deadline | `GistFeedback.test.tsx`: guarded retry, delayed late result, server deadline; 3 failed: missing messages/control | 10 passed |
| Missing reference must preserve grading failure budget | `test_missing_key_points_wait_without_exhausting_grading`; failed: RuntimeError instead of Reschedule | Included in focused run below |
| Key-point quota wait | `test_key_point_quota_wait_preserves_reference_work`; failed: AIUnavailable instead of Reschedule | Included in focused run below |

The first quota test used the wrong fake property; corrected to its real
`exhausted` set before the recorded behavior failure. The first UI retry assertion
ran before the asynchronous CSRF preflight; it now waits for the POST. The deadline
test initially enabled fake timers after the real timer started; corrected to
control the clock before rendering. These setup issues are not product Red evidence.

Configured deadlines, guarded deadline jobs, CSRF/unsubmitted refusals, enqueue
rollback and browser navigation are additional coverage/characterization added
after the corresponding implementation, not claimed as separate Red cycles.
Existing #69 exact response assertions now include wait metadata and unavailable
state; their disclosure checks are retained. Empty-passage permanent failures now
expect unavailable. Fresh-process registration checks both AI and deadline lanes.

A later regression test, `test_retry_recovers_reference_work_while_grading_is_already_waiting`,
failed with zero reference jobs. Retry now also requeues reference preparation when
it reuses an active grading job, while retaining one grading job and its deadline.
Two isolated mutations changed the deadline to exclusive and removed the retry
unique key; the boundary and concurrent-retry tests both failed as intended.

## Validation outcomes

Focused backend before the final denial/rollback additions: **49 passed**.
Gateway neighbors: **47 passed**. Focused UI: **10 passed**.
The key-point quota propagation test then reproduced a remaining gap (pending
instead of delayed). A worker-only marker now propagates the exact reference wait;
the focused regression passed. The first full backend run was intentionally stopped
when this gap was found; it is not reported as a completed run. Initial web lint
rejected synchronous state reset in an effect; timer expiration now identifies its
originating read and the synchronous reset was removed.
Final checks and changed-line coverage are recorded below when completed.

Completed frontend checks: lint, format, types, build and size (125.6 KB gzip,
200 KB budget) pass. Full component coverage: **611 passed / 58 files**, 96.15%
line coverage. Coverage inventory passes; changed executable web lines: **100%**.
Offline synthetic gist and Shadow smoke reports both pass. These are recovery/report
mechanics only and do not establish live-model quality.

The first browser command exceeded the 120-second build/start budget while other
checks competed for CPU. The production build was then served independently.
The default 30-second test-budget run finished **54 passed, 2 timed out** (account
restoration and the unavailable-feedback browser case). Both exhausted the total
budget before a next action; the unavailable case also exceeded browser teardown.
A full run with a 60-second host test budget, unchanged assertions and assertion
timeouts, and no automatic retries is recorded below when complete. This is a
local runner adjustment, not a product deadline or repository configuration change.

The two-test reference-retry follow-up initially counted another test's reference
job; it now scopes the count to this test's media. The migration's local draft
predated the new metadata table; the local draft schema was reconciled before
repeating clean upgrade/check/downgrade/back-up/check successfully. API SELECT on
the quota metadata is denied, while worker SELECT/INSERT/DELETE are granted.


Browser tests mock API responses. Real database/API integration tests separately
prove ownership, persisted state, rollback and queue admission. No live provider
was called or enabled; model quality and actual-server latency are not established
by these tests. Required CI and fresh-session independent review remain merge gates.
