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
resume strictly under 300 ms. Component checks use a controlled media boundary
and prove application scheduling, not deployed storage latency. Actual-server
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
| NFR-PERF-4: seek resume <300 ms | `seek_resumes_within_300ms_at_the_controlled_media_boundary`: immediate exact target assignment, preserved playing state, playing event at 299 ms, and rejection of a 300 ms sample. `transcript_keyboard_controls_at_360px` additionally exercises actual browser media seek/replay target positions. Actual-server measurement is deferred to #155, not passed. |
| FR-PL-5: opening Transcript locks entry | `test_opening_transcript_persists_entry_lock`: timestamp persisted by the existing completion transition, fresh version receives entry_locked, timestamp stays stable. Screen test asserts Entry locked and no Change entry action. |
| UI-3, UI-4: keyboard, 360 px, non-colour highlight | `supports_player_shortcuts_without_hijacking_controls`; `highlights_current_line_at_boundaries_without_colour_or_focus_changes`; `transcript_keyboard_controls_at_360px` (native Enter/Space, focus retention, slider arrows, speed selection, structural border, Current line label, no horizontal overflow). |
| Readiness/failure/recovery | `test_transcript_reports_readiness_refusals`, `test_silent_transcript_has_no_lines`; `shows_loading_and_empty_transcript`; `shows transcript_not_ready and refetches on retry`; `shows transcript_failed and refetches on retry`; `generic_API_errors_use_ErrorPanel`; `TranscriptEvents.test.tsx` ready/failed invalidation and reconnect coverage. |

Security assertions check exact problem codes as well as status: replacing the step
gate with a cache readiness refusal cannot satisfy them. Foreign and signed-out
reads assert the existing ownership/authentication refusal; privileged transaction
spies fail if denied requests reach the cache. Ready reads use a worker-role
connection, while the HTTP request database uses api_role_url. The shared-cache
privilege-denial tests remain part of the complete suite.

No migration or new learner data is introduced. Correction persistence/editor and
autosave are deferred to #56; marks/completion are outside this story. No forbidden
backend Dictation, transcript jobs, marks, or AI gateway files are changed.


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
