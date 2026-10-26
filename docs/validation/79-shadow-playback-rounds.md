# Story #79: Shadow playback rounds

## Scope and prerequisites

- #77 merged in PR #191 as `e8901a4`; verified as an ancestor of main.
- Owner approved the plan before implementation. This isolated checkout uses
  `feat/79-shadow-playback-rounds`, initially main `2281d73`, refreshed to `5db1333`
  after #210/#189 merged. No worktree or delegated agent was used.
- FR-SH-2/3, AT-6: three numbered playback rounds with a three-second count-in,
  fixed original speed and transcript in round 1 only. UI-2: round status and
  keyboard controls within Shadow.
- Playback-ended is independent of recording success. No microphone/consent,
  recording/upload, grading, comparison or plan-completion implementation.
  `recorded_at` remains null and no recording-completed analytics event is emitted.
  Rounds do not inspect reference-profile readiness (ADR 0050).
- [ADR 0061](../adr/0061-shadow-playback-rounds.md) records lifecycle, disclosure,
  schema, recovery and future integration with #78/#81/#87. Transcript disclosure
  here governs Shadow responses, not the learner's existing Transcript review or
  export. Round 1 cannot be fetched as historical text after advancing.

## Acceptance and failure cases

| Requirement | Named tests / assertions |
| --- | --- |
| FR-SH-2, AT-6 / three rounds and disclosure | `test_three_rounds_disclosure_fourth_refusal_and_no_recording`: exact segment text in round 1, outside word excluded; text field/word values absent in round 2/3; history text-free; replayed round-1 POST bodyless; stale fresh start refused. Deletes transcript cache after round 1; later rounds still work. |
| Fourth-round refusal and numbering | Same aggregate test rejects API and SQL round 4 after round 3. `test_database_rejects_invalid_or_skipped_round` checks 0, 2-before-1, 4. `test_round_numbers_are_sequential_and_end_requires_current_round` rejects skipped starts, premature advancement and ending a noncurrent round. |
| Database visibility and identity | `test_database_generated_visibility_and_immutable_number` rejects changing generated visibility, renumbering, and duplicate insertion. `test_round_ownership_is_enforced_by_composite_fk_and_rls` checks composite ownership and API-role RLS denial. |
| Ownership and step gating | New GET/start/playback-ended routes are in `access_registry.py`; cross-learner suite verifies 404 and no unauthorized side effects. `test_round_operations_require_shadow_step`, `test_round_replay_after_skip_refuses` cover unopened/closed steps, including replay keys. |
| Concurrency and locking | `test_concurrent_round_start_serializes` uses independent API-role transactions and observes actual PostgreSQL lock waits for start/start, start/edit and start/skip, then checks exact persisted count. Existing segment concurrency tests cover entry/edit/skip ordering. |
| No fabricated completion | Aggregate API test checks null `recorded_at`, Shadow still open, null plan completion and zero recording-completed analytics events after all playbacks. |
| FR-SH-3 / count-in, bounds, 1x | Player tests: `counts in, enforces 1x, and reports only bounded playback ending`, `preview offers original speed only and repairs rate changes`, `does not rewrite an already-correct media rate on ratechange`. No speed selector; native rate attempts reset to 1. |
| Interruption, failure and media events | Player tests cover cancelled count-in, interruption/restart, unmount cleanup, hidden pages, media error, autoplay refusal/direct retry, native pause-before-ended and premature media ending. No end callback for unsuccessful playback. |
| Segment/race and focus | `requires saving edited segment handles before starting a round`; `uses the authoritative round segment while segment refresh is delayed` ensures one audio element and immediate lock; existing pending-save test; round UI test verifies focus moves to the new heading, text disappears and no fourth-round action exists. Retry test checks exact original action and stable idempotency key. |
| Keyboard and mobile | `e2e/shadow.spec.ts`: Tab/Enter/Space through actual controls, numbered status, count-in before playback, one audio element after locking, fixed speed, text only in round 1, explicit advancement and no horizontal overflow at 360px. Existing 45s/150s selection cases retained. |

## Actual test-first evidence

Commands below ran from the indicated application directory. Logs remain in the
session's ignored `work/` directory; the outcomes below distinguish failures from
successful checks.

| Cycle | Observed Red | Green |
| --- | --- | --- |
| API flow | API: `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_shadow_rounds.py -q --maxfail=1`: aggregate acceptance test failed at missing start endpoint (404 instead of 204). Tests were written before implementation. | Focused final round suite: 12 passed. Includes transcript, database/API refusal, ownership, RLS, gating and lock-wait examples. |
| Round player public interface | Web: `pnpm vitest run src/features/shadow/ShadowRoundPlayer.test.tsx`: missing public player module. | Initial 2 player examples passed; expanded final player suite has 7 passing examples. |
| Round UI public interface | Web: `pnpm vitest run src/features/shadow/ShadowRounds.test.tsx`: missing public round UI module. | Disclosure/advancement/focus and exact retry examples pass. |
| Fixed-speed preview | Web: `pnpm vitest run src/features/shadow/ShadowScreen.test.tsx -t 'preview offers original'`: speed selector was present. | Shadow-local preview removes selector and repairs rate changes. |
| Unsaved selection and focus | Web: two screen/round UI tests failed: round start remained enabled after handle edits; heading lacked focus after advancement. | Both pass after gating dirty/pending selection and moving focus on explicit advancement. |
| Native end handling | Web: `pnpm vitest run src/features/shadow/ShadowRoundPlayer.test.tsx`: 2 failed / 4 passed. Boundary pause failed to end; premature media end incorrectly ended playback. | Both pass with boundary-aware native pause/end handling. |
| Delayed segment refresh | Web: focused `-t 'authoritative round segment'`: failed with two audio elements after start. | Screen now reads the same authoritative round query and immediately uses its locked segment; focused suite passes. |
| Rate-event loop | Web: focused `-t 'does not rewrite'`: 1 failed / 6 skipped because rate handler rewrote a correct rate. | 7 player tests passed after conditional rate writes. |

Supplemental denial/concurrency, retry and interruption cases added after the
initial missing-interface cycle are characterization/expanded validation, not
invented individual Red results. The exact retry behavior was corrected during
inspection before its characterization test; no test-first claim is made for
that correction. Formatting, documentation, generated files and the shared
BusyButton integration do not need artificial Red failures.

Initial API checks exposed two test mistakes: the analytics column is
`event_type`, and the session response field is `open_step`. These were corrected;
they are not implementation defects or behavioral Red evidence.

Browser history: the new browser case initially timed out during count-in, then a
paused fake clock blocked query notification, then a full-200 audio fixture failed
at seeking. The final test uses real timers, byte-range media responses and the
fixed rate handler. Its three cases pass. These fixture/setup outcomes are not
claimed as successful checks or fabricated TDD evidence.

## Validation

Implementation commit `96efc5385dc7ab0364de673f6f49cbf9cb024350` passed
[CI run 40208791517](https://github.com/abubakar1010/ListenUp/actions/runs/40208791517).
Current main was rechecked as `5db1333`; its migration chain ends at `72_cards`,
so `79_shadow_rounds` follows it without a fork. The validation-document follow-up
changes no runtime, test, generated or migration files.

- Backend formatting/lint, strict mypy (194 source files) and all six import
  contracts pass. Migration upgrade, drift check, downgrade and upgrade pass;
  Alembic reports no new operations and one head (`79_shadow_rounds`).
- Separate uninstrumented performance: 1 passed, 2089 deselected.
- Focused Shadow browser suite: 3 passed.
- Full frontend coverage attempt: 617 passed, 2 failed (Dictation busy-submit
  timeout and subsequent missing textbox); 59/60 files passed. Both failing cases
  pass in isolation (2 passed, 27 deselected). No assertions or timeouts changed.
  These are retained as failed outcomes; resource contention is a possible cause,
  not a proven root cause. The complete implementation-commit CI run passes all
  621 frontend tests and supersedes these local failures for the full-suite gate.
- Latest focused Shadow coverage: 21 passed; includes the delayed-refresh fix and
  end-callback-to-API/status interaction. Its application-wide percentage is not a
  whole-suite baseline. Changed-line and inventory results are recorded below.
- Complete required-service backend coverage in CI: **2089 passed**, 1 performance
  test deselected, no skips; 619.02 seconds. Separate uninstrumented performance:
  **1 passed**. Spike harness regressions: **62 passed**. The second local full
  backend run has no completion summary (its log ends during Dictation tests), so
  it supplies no whole-suite passing result; CI supplies the complete evidence.
- Complete frontend coverage in CI: **621 passed**, 60 files. Whole-suite coverage:
  **96.25% lines / 88.66% branches**. This is the complete CI result, distinct from
  the focused Shadow report.
- Downloaded the implementation-commit CI coverage artifacts and ran the same
  inventory and `diff-cover --compare-branch origin/main --fail-under 90` checks
  from each app directory: both inventories pass; **backend 81/81 (100%)** changed
  executable lines and **web 161/164 (98%)**. The three uncovered web lines are
  initial/cached round-read and content-read error/retry render callbacks in
  `ShadowRounds.tsx` (37, 113, 115). Normal lifecycle, disclosure, rate enforcement,
  API end callback, selection race and mutation retry have direct assertions.
  No source, threshold or coverage exclusion was changed to satisfy the gate.
- Web lint, formatting, TypeScript and build pass; size is 125.6 kB gzip against
  200 kB. Complete CI Playwright suite: **55 passed**. API export, TypeScript
  generation and committed-file reproducibility pass in CI. Dependency scans,
  Docker builds, the real media sandbox/scanner contract and observability checks
  pass. AI smoke is correctly skipped because no AI smoke paths changed.
- The push workflow skips its PR-only changed-coverage job by design; the explicit
  artifact checks above pass. The PR workflow must also pass that job before merge.

An early backend coverage run was stopped after API documentation changes and is
not a final result. An initial concurrent frontend coverage run produced failures
in untouched asynchronous tests and was stopped; a subsequent one-worker local
run finished with the two failures recorded above. Neither stopped run is claimed green. No timeout, assertion, coverage
threshold or exclusion was weakened.

## Assertion quality and remaining gates

The aggregate test asserts literal expected text and absence of all reference
words in hidden-round JSON; it would reject disclosure on round 2/3 or a replay
response. SQL denial tests reject a missing range/sequence constraint, generated
column or ownership FK/RLS policy. Concurrency tests wait for a real database lock
and then assert outcomes and row count rather than relying on elapsed sleeps.
Player regressions explicitly reject premature end and repeated rate writes.

Playwright mocks the API: it proves browser behavior, not live-stack persistence
or security. API-role/PostgreSQL integration independently proves server rules.
Real microphone, consent, upload and completion acceptance remain in their
excluded stories. Grading/model-quality/launch gates remain unchanged.

Required CI and fresh-session independent review remain merge gates. This session
opens one PR and does not merge it.

## PR #218 review remediation (2026-10-26)

Review of `03ab474` against current main `2764892` found one P2 client disclosure
race: a focus refetch could restore round-1 text during a delayed round-2 start,
then a failed settlement refresh left that text visible after advancement.
The review was posted as review `5650355563`; the owner requested remediation in
this PR. This section records new evidence and does not infer historical TDD.

- Red, before changing production code: from `apps/web`,
  `node node_modules/vitest/vitest.mjs run src/features/shadow/ShadowRounds.test.tsx -t 'focus refetch|failed refresh'`
  produced **2 failed, 1 passed, 3 deselected**. The failures found the literal
  round-1 transcript still in the rendered DOM after the failed authoritative
  refresh. The late-response example already passed and is characterization.
- The parameterized `keeps transcript hidden when a focus refetch resolves %s
  and advancement refresh fails` controls POST/GET promises independently,
  triggers React Query focus handling, and asserts both the rendered result and
  absence of the transcript in cache after settlement. It covers a refetch that
  completes during the mutation and one that resolves after settlement.
- `hides cached transcript after a failed refresh and restores it only after a
  successful retry` covers the failed-read visibility gate and recovery without
  weakening round-1 disclosure on a successful read.
- Green: `node node_modules/vitest/vitest.mjs run src/features/shadow/ShadowRounds.test.tsx`
  passed **6 tests** after cancelling outstanding reads and clearing text again
  at settlement, plus hiding transcript-bearing cached data after failed reads.
  The original code fails the new DOM assertions; a display-only fix would
  still fail the cache assertion for the refetch completed during mutation.
- ADR 0061, conventions and UX-07 now explicitly describe Shadow's native
  Tab/Enter/Space policy and failed-refresh behavior. The round panel includes
  its native keyboard hint. This clarifies the existing mode-specific policy;
  shared transport shortcuts and other practice modes are unchanged.
- Setup failures are not Red evidence: an initial test harness omitted a Router
  needed by ErrorPanel; the corrected harness then exposed the DOM regression.
  Two commands used the wrong working-directory path. The local pnpm launcher
  attempted dependency setup and refused noninteractive module replacement;
  checks therefore use the installed tool binaries directly. Coverage inventory
  checks invoked before report generation finished found no report and supply
  no coverage result.
- Final source: full web coverage **624 passed / 60 files**; **96.28% lines,
  88.70% branches**. Command: `node node_modules/vitest/vitest.mjs run --coverage`.
  A prior full run also passed 624; the final run followed the keyboard-copy edit.
- Final lint, formatting and types passed using the installed `eslint`,
  `prettier --check .` and `tsc -b` entry points. `vite build` and
  `node scripts/check-bundle-size.mjs` passed: **125.6 kB gzip / 200 kB**.
- Full Playwright: **55 passed** with system Chromium and an independently
  started production preview. After the final build, a fresh
  `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium node node_modules/@playwright/test/cli.js test e2e/shadow.spec.ts`
  passed **3 tests**, including keyboard/numbered rounds at 360px.
- Final coverage inventory passed. From `apps/web`,
  `../api/.venv/bin/diff-cover coverage/cobertura-coverage.xml --compare-branch origin/main --fail-under 90`
  passed **163/165 changed executable lines (98%)**. Remaining uncovered lines
  are `ShadowRounds.tsx` initial-read retry (37) and content-read retry (117).
  The mutation helper's absent-cache branch remains uncovered; both relevant
  cached-text paths are asserted. No thresholds, exclusions, timeouts or existing
  assertions were weakened. Player lifecycle branch gaps from the original review
  remain disclosed; this fix changes no player lifecycle behavior.
- No backend, schema or generated-client changes were needed. The review's local
  PostgreSQL limitation still applies; prior-head integration evidence does not
  substitute for CI on the remediation head. Required CI and fresh independent
  review of material changes remain merge gates. The owner merges.
