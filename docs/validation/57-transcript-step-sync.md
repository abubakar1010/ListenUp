# Story #57 validation

Implements FR-TR-1, FR-TX-5, FR-PL-5, NFR-PERF-4, UI-3 and UI-4.
Owner approved the plan before implementation. Branch name validated with
`.github/scripts/check-branch-name.sh feat/57-transcript-step-sync` (exit 0).

## Test-first evidence

Commands below run from the repository root unless stated otherwise.

| Cycle | Red | Green / refactor |
| --- | --- | --- |
| API route and lock characterization | `LISTENUP_REQUIRE_DB=1 uv run --directory apps/api pytest tests/integration/test_review_api.py -q`: 2 failed (404 instead of 409 step_locked), 1 passed (existing persisted lock) | See expanded cycle below. No practice production change. |
| API response, readiness and denial | Same command, expanded tests: 7 failed, 1 passed (missing route/state) | `LISTENUP_REQUIRE_DB=1 uv run --directory apps/api pytest tests/integration/test_review_api.py tests/integration/test_access_cross_learner.py tests/architecture -q`: 19 passed. Request connections use api_role_url; the privileged connection sets role=listenup_worker. |

| Cycle | Red / characterization | Green / refactor |
| --- | --- | --- |
| Player extraction | From `apps/web`: `pnpm vitest run src/features/dictation/policy.test.ts src/features/dictation/DictationScreen.test.tsx`: 31 passed before extraction (characterization; behavior-preserving refactor). An initial attempt was blocked by pnpm's non-TTY dependency refresh; `CI=true pnpm install --frozen-lockfile` repaired setup, without changing the lockfile. | See combined screen run below. |
| Transcript screen | From `apps/web`: `pnpm exec vitest run src/features/review/TranscriptScreen.test.tsx`: 8 failed against the original placeholder (no word controls). | `pnpm exec vitest run src/features/review/TranscriptScreen.test.tsx src/features/dictation/DictationScreen.test.tsx src/features/dictation/policy.test.ts`: 39 passed after implementation/extraction. |
| Line replay count | `pnpm exec vitest run src/features/review/TranscriptScreen.test.tsx -t replays_current_line`: 1 failed, 7 skipped; line replay left the visible count at zero. | `pnpm exec vitest run src/features/review src/features/dictation src/features/session/SessionPage.test.tsx`: 45 passed after fixing the counter and expanding boundary/error checks. |
| Event mapping | Mapping tests were added after implementation; this is regression-detection evidence, **not test-first evidence**. `pnpm exec vitest run src/features/review/TranscriptEvents.test.tsx` with the original `HEAD` guards file temporarily substituted: 2 failed because transcript events returned no invalidation keys. The working guards file was restored by an EXIT trap. A second check used an isolated `git archive HEAD apps/web` under `work/events-original`, copied only the new event tests/API hook and linked installed dependencies: `node /workspace/ListenUp/apps/web/node_modules/vitest/vitest.mjs run src/features/review/TranscriptEvents.test.tsx` also failed both assertions against the original guards. | Same command with the implemented guards: 2 passed. |
| Browser | Browser tests supplement the component-first screen cycle. First execution was blocked by TypeScript mock annotations, not a behavioral red. | `pnpm exec playwright test e2e/transcript.spec.ts`: 1 passed using real Chromium WAV playback against mocked HTTP responses at 360 px. |

## Performance

NFR-PERF-4: passage seeking/looping must be frame-accurate to the segment and
resume strictly under 300 ms. Component checks assert synchronous target assignment
and playback state, not media resume latency. Actual-server
browser-to-media seek latency is **deferred until staging — unverified** under
[tracker #155](https://github.com/abubakar1010/ListenUp/issues/155). Before launch,
record release commit/image, host, browser/device, network conditions, passage and
seek targets, warmup, sample count, raw action-to-playing durations, position
accuracy, failures/timeouts and percentile method. Do not omit failed seeks.


The event-mapping chronology gap is disclosed above. Additional post-implementation
checks improve boundaries/coverage; they are not retroactive evidence of TDD.

## Acceptance criteria to named tests

| Criterion | Tests and relevant boundaries |
| --- | --- |
| FR-TX-5: Dictation returns 409 step_locked | `test_transcript_before_unlock_returns_step_locked[dictation]` and `[blind]`; `test_transcript_denials_do_not_open_worker_transaction` verifies early denials, missing/foreign session, signed-out and malformed IDs. `test_every_route_is_registered` and `test_learner_b_reaches_nothing_of_learner_a` enforce Owned/404 and no side effects. |
| FR-TR-1: synced transcript/full controls | `test_transcript_returns_sentence_lines_with_absolute_word_timings` (nonzero passage, padding omitted, sentence grouping, completed-session read); `highlights_current_line_at_boundaries_without_colour_or_focus_changes`; `replays_current_line_changes_speed_and_word_activation_jumps`; `replay_in_leading_silence_starts_first_line_and_paused_seek_stays_paused`. Silence/empty and media-error cases are covered separately. |
| NFR-PERF-4: seek resume <300 ms | `seek_sets_exact_target_without_debounce_and_preserves_playback_state`: immediate fractional-second target assignment without advancing timers, retained playing state and no autoplay on a paused seek. This does not establish resume latency. `transcript_keyboard_controls_at_360px` exercises actual browser media seek/replay target positions. Actual-server measurement is deferred to #155, not passed. |
| FR-PL-5: opening Transcript locks entry | `test_opening_transcript_persists_entry_lock`: timestamp persisted by the existing completion transition, fresh version receives entry_locked, timestamp stays stable. Screen test asserts Entry locked and no Change entry action. |
| UI-3, UI-4: keyboard, 360 px, non-colour highlight | `supports_player_shortcuts_without_hijacking_controls`; `highlights_current_line_at_boundaries_without_colour_or_focus_changes`; `transcript_keyboard_controls_at_360px` (native Enter/Space, focus retention, slider arrows, speed selection, structural border, Current line label, no horizontal overflow). |
| Readiness/failure/recovery | `test_transcript_reports_readiness_refusals`, `test_silent_transcript_has_no_lines`; `shows_loading_and_empty_transcript`; `shows transcript_not_ready and refetches on retry`; `shows transcript_failed and refetches on retry`; `generic_API_errors_use_ErrorPanel`; `TranscriptEvents.test.tsx` ready/failed invalidation and reconnect coverage. |

Security assertions check exact problem codes as well as status: replacing the step
gate with a cache readiness refusal cannot satisfy them. Foreign and signed-out
reads assert the existing ownership/authentication refusal; privileged transaction
spies fail if denied requests reach the cache. Ready reads use a worker-role
connection, while the HTTP request database uses api_role_url. The shared-cache
privilege-denial tests remain part of the complete suite.

The initial screen implementation introduced no migration. The final overlay work
below adds the designed correction table and read-only composition; the editor,
dispute/re-scoring and autosave remain #56. Marks/completion are separate stories.
Backend Dictation, transcript jobs, marks and AI gateway files remain unchanged.


## Additional regression/characterization evidence

- The first full `pnpm test:coverage` run found 1 failure (324 passed):
  `SessionChanges.test.tsx > Transcript has no skip` caught the lost existing
  explanatory copy. Restoring that copy in the review layout made
  `pnpm exec vitest run src/features/session/SessionChanges.test.tsx src/features/review`
  pass all 21 tests. The subsequent full coverage run passed all 325 tests.
- Coverage inspection prompted stronger characterization of existing transport
  bounds and generic retry. `pnpm exec vitest run src/features/review/TranscriptScreen.test.tsx`
  passed 10 tests; a fresh full coverage run passed 325 tests, with all changed
  executable web lines covered. A later focused run of the same 10 tests also
  passed with 140125 ms sentence/word targets, rejecting whole-second rounding.
- New pool cleanup regression: `uv run --directory apps/api pytest tests/unit/test_lifespan_shutdown.py -q`
  initially reported 1 failed / 1 passed: a listener shutdown failure skipped
  transcript-pool disposal. Moving disposal into a finally block yielded 2 passed.
  Telemetry still flushes if cleanup fails. The backend checks/coverage were rerun
  after this fix rather than reusing the earlier 1144-test coverage result.
- Schema naming refactor: `LISTENUP_REQUIRE_DB=1 uv run --directory apps/api pytest tests/integration/test_review_api.py -q`
  passed all 8 cases; mypy passed. Naming the DTO TranscriptPassage avoids changing
  the existing PassageRange schema names. Generated types were regenerated, never
  hand-edited.

## Final development checks

Services: real PostgreSQL 16 and SeaweedFS S3; PostgreSQL 16 pg_dump/pg_restore
available on PATH. No new model/provider call is introduced by #57. The existing
adapter tests and uninstrumented performance suite retain their normal scope.

Web (from apps/web): `pnpm lint`, `pnpm format:check`, `pnpm typecheck`,
`pnpm test:coverage` (325 passed), `pnpm build`, `pnpm size`, `pnpm e2e`
(34 passed). All passed. After the no-skip copy fix, lint/format/types/build/size
and `pnpm exec playwright test e2e/transcript.spec.ts` were repeated successfully.
Web runtime inventory check passed; diff-cover against origin/main reported
**189 changed executable lines, 0 missing, 100%**. Whole-application line coverage
is 94.26%; branch coverage is 85.58%. Reports were inspected; no changed line is
uncovered. No coverage exclusion or threshold was changed.

Backend (apps/api): `uv run ruff check .`, `uv run ruff format --check .`,
`uv run mypy`, `uv run lint-imports`, `uv run alembic upgrade head`,
`uv run alembic check` all passed after the cleanup fix. The first format check
found one formatting issue in the new setting; formatting it and rechecking passed.

Final coverage command:
`LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest -m 'not performance' --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html`
passed **1145 tests**, with 1 performance test intentionally deselected.
`uv run pytest -m performance --no-cov` passed that **1 test** separately.
No required-service tests were skipped. Runtime coverage inventory passed;
`uv run diff-cover coverage/coverage.xml --compare-branch origin/main --fail-under 90`
reported **56 changed executable lines, 0 missing, 100%**. Backend review-module
lines/branches are fully covered; no changed executable line is uncovered.

For web, the equivalent inventory check and
`../api/.venv/bin/diff-cover coverage/cobertura-coverage.xml --compare-branch origin/main --fail-under 90`
passed. Final initial JavaScript is **120.8 kB gzip**, below the 200 kB budget.

Both `uv run python scripts/export_openapi.py` (apps/api) and `pnpm api:generate`
(apps/web) ran successfully, including after the DTO naming refactor. The generated
OpenAPI and TypeScript files are included. Alembic drift check applies; a migration
round trip is not applicable because this story changes no schema.

Branch validation and `git diff --check` pass. Fetched main again before final
validation: #54 had not merged and origin/main remained 799005a, so no merge was
required. Before merge, required CI and a fresh-session independent review must
pass; this validation record does not claim either has happened locally.

Branch review: new review lines/query code is fully branch-covered; the screen's
report shows 97.72% (the empty-transcript keyboard replay no-op was subsequently
asserted in the final focused 10-test run). The moved transport hook retains
63.63% branch coverage: absent-element guards, preloaded metadata, animation-loop
exit timing and restarting from the end are not exhaustively combined in jsdom.
Passage boundary correction, pause/play, replay, speed and real-browser seek are
covered. These gaps are disclosed rather than excluded; the required changed-line
gate remains 100%. The shared control component is fully branch-covered.


## Main integration after PR creation

After the first PR CI run passed all jobs, main advanced to a74e930 with merged
PR #159. #54 had not merged. GitHub marked #165 behind, so current main was merged
without editing any gateway source. Its ADR occupied 0041; this story's ADR was
renumbered to 0042, with links updated. Protected paths have no diff against main.
The full local counts above describe validation before this integration, not a
new whole-repository baseline for main's additional gateway implementation.
OpenAPI export and client generation were repeated on the integrated branch.
The focused review/access/architecture/lifecycle checks and the final PR CI run
validate the integrated head; final CI also inventories complete runtime coverage
before enforcing the 90% changed-line gate.


Integrated-head local checks: `LISTENUP_REQUIRE_DB=1 uv run --directory apps/api pytest tests/integration/test_review_api.py tests/integration/test_access_cross_learner.py tests/architecture tests/unit/test_lifespan_shutdown.py -q`
passed **21 tests**. Ruff lint/format, mypy (145 source files), import-linter
(6 contracts), Alembic upgrade to main's new gateway migration and drift check
all passed. OpenAPI export and `pnpm api:generate` produced no additional diff.

## Resumption audit, 2026-10-18

Continued the existing PR #165 on `feat/57-transcript-step-sync`, based on current
main `a74e930`, after owner approval of the continuation plan. No duplicate branch
or PR was created. Dependency #45 is merged, with stage-0 latency still unverified.
#48's implementation is on main; its issue remains open for the first-time-learner
usability test in #118. That uncompleted usability validation was not rerun here.

### Evidence corrections and characterization

The earlier `seek_resumes_within_300ms_at_the_controlled_media_boundary` test
injected a `playing` event after 299 ms, then after 300 ms. That measured its own
injected clock, not media latency. It has been replaced by
`seek_sets_exact_target_without_debounce_and_preserves_playback_state`, which
asserts an immediate 140.125-second target before advancing timers, retains playing
state, and then checks that seeking to 141.25 seconds while paused does not autoplay.
The actual-server performance target is unchanged and remains unverified under #155.

This is a test-quality correction of retained behavior, not a new production
behavior or a test-first implementation cycle. The initial focused command from
`apps/web`, `npx --yes pnpm@10.28.0 exec vitest run
src/features/review/TranscriptScreen.test.tsx -t seek_sets_exact_target`, passed
1 test with 9 deselected. In an isolated `git archive` copy under `work/seek-mutation`
(not a worktree), the same test failed on two separate temporary mutations:

- Whole-second rounding: expected 140.125, received 140.
- Deferring target assignment by 1 ms: expected 140.125, received 130.

These are mutation results, not retroactive Red evidence. The real implementation
was not mutated. The original story's recorded implementation cycles remain above,
including the disclosed event-mapping chronology deviation.

The successful transcript response test now also asserts `Cache-Control: private,
no-store`. This characterizes the existing privacy header; no production behavior
changed. `LISTENUP_REQUIRE_DB=1 uv run --directory apps/api pytest
tests/integration/test_review_api.py -q` passed all 8 tests after that assertion.

### Validation before the overlay addition

- Backend: Ruff format/lint, strict mypy (145 source files), all 6 import contracts,
  Alembic upgrade and drift check passed. No schema changed, so a new migration
  round trip is not applicable; migration integration tests ran in the full suite.
- Full backend coverage with PostgreSQL 16 and SeaweedFS, both service flags
  required: **1,250 passed, 1 performance test deselected, no skips**, 258.81 s.
  PostgreSQL 16.15 client tools were supplied from the PostgreSQL 16 Bookworm image
  under `work/pg16`, on PATH for the run. The separate uninstrumented performance
  command passed **1 test**; that existing Dictation-scoring check is not a seek
  latency measurement. The added header assertion also passed in the focused
  8-test rerun noted above.
- Web: pinned pnpm 10.28.0, lint/format/types, final coverage **325 passed**,
  build and size **120.8 kB gzip / 200 kB** passed. The initial coverage attempt
  was blocked by a missing installed `@vitest/coverage-v8`; a frozen-lockfile
  install repaired the environment without changing dependency files.
- Playwright: **34 passed**, system Chromium at `/usr/bin/chromium`, including
  real WAV playback and keyboard use at 360 px. HTTP API responses are mocked;
  this is not a live-stack or stage-0 performance result.
- Complete runtime coverage inventories passed. Diff-cover from each application's
  directory against `origin/main`: API **56/56** and web **189/189** changed
  executable lines covered (**100%**). Web whole-application lines are 94.26%,
  branches 85.63%; the reused transport's branch gaps remain disclosed above.
- OpenAPI export and client generation passed and produced no final diff.
  Branch-name validation and `git diff --check` passed.

### Final scope and release gates

The learner-correction scope gap identified during this audit is resolved by the
read-only overlay implementation below. The editor and dispute/re-scoring remain
#56. Marks are separately scoped in #58–#60; #57 explicitly excludes mark creation.
Card, Shadow and Blind gist implementation remain outside this story.

Actual-server NFR-PERF-4 remains **deferred until staging — unverified** under #155.
A fresh-session independent review remains outstanding; no sub-agents were spawned
and this builder's audit does not replace that review. Do not merge automatically.

## Learner correction overlay implementation

The approved continuation plan included resolving the correction-overlay gap
against #57's scope. The final implementation uses the table already specified in
Database Design §4, rather than deferring the read behavior to #56. Migration
`57_transcript_corrections` follows `0064_ai_gateway` and introduces own_rows RLS,
bounded correction text and cascading account/cache-row deletion. API grants are
SELECT only; workers retain CRUD. No correction editor or write endpoint is added.

`transcript.service.read_passage` checks ownership, the Transcript step and complete
cache coverage before reading the learner's overlays in its request transaction.
An explicit learner filter protects privileged callers as well as API-role RLS.
Overlay keys use cache-row identity and local word index, before passage-global
indices are composed. Shared cache text, original sentence boundaries, word indices
and timings are preserved, including empty corrections. Review emits `edited` and
the screen shows a textual Edited label; a removed word retains an accessible audio
jump target. The learner's export includes only their own correction rows.

### Actual Red / Green cycles

| Cycle | Observed Red before implementation | Green / refactor |
| --- | --- | --- |
| Correction storage, privacy and cascade | Root: `LISTENUP_REQUIRE_DB=1 uv run --directory apps/api pytest tests/integration/test_review_api.py -k 'correction_storage or correction_rows' -q`: **4 failed**, all UndefinedTable for the missing designed correction table. This is a missing behavior/schema failure, not unavailable infrastructure. | After migration/model: same four cases passed in the expanded run, while overlay behavior still failed. Negative index and 61-character text are rejected; missing learner sees no rows, learner A sees only their row, account/cache deletion cascades. |
| Overlay API | Root: same file with `-k 'correction_storage or correction_rows or overlays'`: **1 failed, 4 passed**, KeyError `edited` before the overlay reader/response metadata. | `test_transcript_overlays_only_own_corrections_without_changing_word_identity` now checks two learners sharing one media cache, out-of-passage corrections, unchanged shared reference, original indices/times and empty replacements. API-role and privileged-service reads agree. Full review file after the supplemental cache-composition example: **14 passed**. |
| Correction export | Root: `LISTENUP_REQUIRE_DB=1 uv run --directory apps/api pytest tests/integration/test_export.py -k test_export_holds_every_learner_table -q`: **1 failed**, correction table absent from export. | Adding `transcript.service.export_data` to contributors made review/export suites pass **34 tests**. The export test was then strengthened with populated own/foreign correction rows. The neighboring review/export/passage/migration/architecture run passed **64 tests** before the final privileged-reader assertion was added; the review file subsequently passed all 14 cases. |
| Edited/removed-word UI | Web: `npx --yes pnpm@10.28.0 exec vitest run src/features/review/TranscriptScreen.test.tsx -t shows_learner_edits`: **1 failed, 10 skipped**, missing `Jump to Greetings (edited)` before the UI labels. | Same command: **1 passed, 10 skipped** after the display change. Edited and removed-word controls preserve their original audio targets; unedited words have no Edited label. Neighboring review/Dictation run: **44 passed**. |

The cache-composition example and strengthened populated-export/privileged-reader
assertions supplement the original cycle; they are not separately claimed as
new test-first implementation cycles. Refactoring converts edited-index lookup to
a set and preserves all observable results. No threshold or assertion was weakened.

For security regression detection, an isolated source copy under
`work/correction-mutation` removed only the explicit learner filter from the
correction query. Running `test_transcript_overlays_only_own_corrections_without_changing_word_identity`
failed on its privileged read: expected `(2, "Again.", False)`, received
`(2, "Foreign edit", True)`. The normal implementation passes; it was never mutated.
This is supplemental mutation evidence, not a replacement for the Red cycles above.

### Additional scope-to-test mapping

| Scope | Named tests |
| --- | --- |
| Learner-only correction overlay, original timing/index identity, unchanged shared reference, gate still enforced | `test_transcript_overlays_only_own_corrections_without_changing_word_identity` |
| Cache-local correction identity and unchanged sentence boundaries across cached spans | `test_correction_identity_and_sentence_boundaries_survive_cache_composition` |
| RLS, fail-closed missing identity, account/cache cascade | `test_correction_rows_are_private_and_cascade` |
| Correction text/index constraints | `test_correction_storage_rejects_invalid_values` |
| Data export contains own corrections only | `test_export_holds_every_learner_table_and_only_the_learners_data` |
| Non-colour edited label, removed-word accessibility and audio activation | `shows_learner_edits_and_removed_words_with_original_audio_targets` |

### Final overlay validation

- Backend format/lint, strict mypy, all six import contracts passed. The new
  migration passed downgrade/re-upgrade and Alembic drift check locally; full
  migration integration tests also passed in the coverage run.
- With PostgreSQL and S3 required and PostgreSQL 16 client tools on PATH, the
  final backend coverage command passed **1,256 tests**, one performance test
  deselected, **no skips**, 219.18 s. The separate uninstrumented performance
  command passed **one test** (the existing scoring budget, not media latency).
- Web lint/format/types, coverage **326 passed**, production build and size
  **120.8 kB gzip / 200 kB**, and full Playwright **34 passed** all passed after
  the overlay implementation. The component-first edited-word cycle above also
  covers removed-word audio activation. The browser fixture additionally checks
  the Edited label at 360 px: `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium
  npx --yes pnpm@10.28.0 exec playwright test e2e/transcript.spec.ts` passed
  **one test** after that fixture assertion, with lint/types rechecked.
- Runtime coverage inventories passed. Changed-line coverage against
  `origin/main`: API **84/84**, web **189/189**, both **100%**. Review and transcript
  read-service lines/branches are fully covered; the Transcript screen also has
  full line/branch coverage. The cache repository's uncovered advisory-lock
  cleanup exception (lines 129–131) is pre-existing and unchanged. Reused transport
  branch gaps remain disclosed above. No exclusions or thresholds changed.
- OpenAPI export and client generation ran again after the response change.
  Generated files are committed rather than hand-edited. Branch validation and
  `git diff --check` pass. Remote main remains `a74e930`.

The correction editor and dispute/re-scoring flow are intentionally left to #56;
there is no public correction write endpoint in #57. The migration must be applied
before deploying this API version. Actual-server NFR-PERF-4 and independent review
remain the outstanding validation/release gates described above. CI must validate
the final pushed head; earlier-head CI is not evidence for this addition.
