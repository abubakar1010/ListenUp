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
Final checks and changed-line coverage are recorded below.

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
A subsequent local run used a 60-second host test budget with unchanged
assertions and assertion timeouts and no automatic retries, but was interrupted. This is a
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

## CI evidence

Implementation commit: `b9bfd04bac29237c7ce1993abf9b25a5b428a773`.
[Push validation run](https://github.com/abubakar1010/ListenUp/actions/runs/40230592892).
CI web checks, the full Playwright suite with the normal repository timeouts,
API generation, dependency scan, observability checks and real media sandbox pass.
The preceding local 60-second run was interrupted and is not a completed result;
it exposed the existing Blind browser fake's missing grade endpoint, now fixed to
return an explicit pending response. Its separate passage playback assertion also
failed under contention; that shared UI was not changed in this story. CI's full
browser pass validates the final fixture with the normal time budgets.

The local coverage run was interrupted when the environment stopped during the
previous active turn; its partial output is not reported as passed. Final full
backend and coverage evidence follows below. The final focused recovery
run passed **17 tests**. No inference, rubric, eligibility or enabled-provider
configuration changed.

The initial published commit body contains literal newline escapes from command
quoting. Its subject and owner authorship are correct; published history is kept
in accordance with the no-rewrite rule.

## Final validation against current main

Main was re-fetched and reconciled at `2764892` (#211). Its only changes are
conventions and #69 review evidence; production source is identical to the green
implementation run. After that reconciliation, Ruff format/check, strict mypy
(194 source files), all six import contracts and diff checks pass again.

The complete push CI run above passed:

- Backend required-PostgreSQL/S3 coverage suite: **2,095 passed**, one performance
  test deliberately deselected, 619.93 seconds. Full backend coverage: **98%**.
- Separate uninstrumented performance suite: **1 passed**.
- Spike pure-helper regressions: **62 passed**.
- Web: **611 passed / 58 files**; **56 browser tests passed** with the normal
  repository test timeouts. Lint, format, types, build and bundle size pass.
- API generation matches; all four images build; dependency vulnerability,
  observability and real media sandbox/scanner checks pass.
- Synthetic AI smoke is skipped by the push path detector; both synthetic suites
  were explicitly run locally and passed, as recorded above.

The restricted environment could not download the coverage archive through the
Actions blob redirect. The authorized GitHub connector downloaded the same CI
artifact instead. Local inventory validation confirms every backend runtime file
resolves in that XML report. `diff-cover` against current main reports **97% of
134 changed executable backend lines**, and **100% of 16 web lines**. No threshold,
ignore directive or coverage exclusion changed.

Coverage review found three unexecuted backend lines: missing reference fallback,
missing-grade refusal and ready-grade retry no-op. Two additional characterization
cases now explicitly assert that ready/missing retries preserve the grade, queue
and practice state; **2 passed** locally. They were added after implementation,
not claimed as Red cycles. The reported CI coverage remains the conservative 97%
from before those two additions. The absent-reference defensive display fallback
remains outside that report; normal successful grading always stores a reference.

Local broad coverage reruns were stopped/interrupted without a completed result;
full-suite evidence is the linked CI run, not partial local progress. The final
recovery-specific run passed **17 tests**, followed by the two characterization
cases above. Full CI reruns for the final test/documentation commit and PR.
Fresh-session independent review remains required before the owner merges.

## PR #220 independent review remediation

Review of `bafce90` against main `2764892` found a quota-to-reference-exhaustion
gap: a delayed grade could remain delayed forever after reference preparation
stopped, hiding retry. Review also identified missing browser assertions for
nonempty Transcript marks and an active Dictation draft during `grade.ready`.

Before changing production code, ran:

```sh
LISTENUP_REQUIRE_DB=1 uv run --frozen --project apps/api pytest apps/api/tests/integration/test_gist_recovery_jobs.py -k reference_quota_then_exhaustion -q --tb=short
```

Actual Red: **4 failed**. Provider failure left the grade delayed; invalid output,
timeout and permanent failure left the quota marker present. After adding reference
failure settlement and conditional delay clearing, the same command: **4 passed**.
Each case also retries preparation, asserts one active job per grading/reference
key, receives a ready grade and verifies unchanged practice progress. Additional
characterization checks the original deadline at -1, 0 and +1 ms remaining.

`e2e/gist-recovery.spec.ts` adds two characterization cases: a real SSE
`grade.ready` keeps the active Dictation text/focus/step and the Transcript
mark/highlight/note/focus/step. It asserts no session refetch, attempt restart or
unexpected writes. Both passed. An isolated mutation broadening `grade.ready`
invalidation to all session queries made **both fail** on extra session reads;
the production mapping was restored. These tests characterize existing UI
behavior, not a new production UI implementation. The first browser run used the
wrong Dictation field label and failed setup; correcting it is not product Red.

The review itself ran 107 focused backend tests, 11 migration/access tests, 10
component tests and two recovery browser tests successfully. Its first backend
attempt had 75 setup errors because PostgreSQL was stopped; starting the local
service and rerunning resolved them. Two extra read-only checks verified retry
consent denial without queue effects and API denial/worker grants on quota
metadata. Review checked final-head CI run 40231985444: 2,097 backend, 611 component,
56 browser tests; changed-line coverage 99% backend and 100% web. This supersedes
the earlier implementation-run evidence for the reviewed head.

Completed remediation checks before push:

- Focused neighboring backend run: **111 passed**, then all seven new recovery
  and deadline cases with the final assertions: **7 passed**.
- Full web component coverage: **611 passed / 58 files**, 96.15% line coverage;
  runtime coverage inventory and **100% of 16 changed web lines** pass.
- Full browser suite with repository timeouts and no retries: **58 passed**.
- Ruff lint/format, strict mypy (194 source files), all six import contracts,
  web lint/format/types, production build and size (125.6 KB / 200 KB) pass.
- API schema/client regeneration produces no changes. No schema or migration
  changes are needed for this fix.

The full required-PostgreSQL/S3 local backend coverage run was still in progress
when this remediation was committed, and is not counted as passed here. Its
completed result, separate uninstrumented performance result, backend changed-line
coverage and final-head CI outcomes are reported in PR #220's remediation follow-up
and checks. No threshold or exclusion was weakened. No live provider or
deployment-latency claim is made. The owner still merges after required CI and
independent review of the material fix.
