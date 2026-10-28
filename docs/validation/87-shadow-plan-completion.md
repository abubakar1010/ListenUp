# Story #87: complete Shadow after three recorded rounds

Owner approved the plan before code. Branch: `feat/87-shadow-plan-completion`,
based on main `11a2ddc`. #81 is merged. Implements FR-SH-6, the recorded-round
completion part of FR-SH-16 / AT-19, and SR-6 / D12 under ADR 0050 option a.
No migration, grading implementation, new ADR, design edit or delegation.

## Acceptance and boundary evidence

| Requirement | Named tests |
| --- | --- |
| Three recorded/uploaded rounds complete the session without grading | `test_three_rounds_produce_three_replayable_recordings`: persisted count 3, Shadow done, session completed, unavailable feedback and private replay |
| Two recordings / playback alone cannot complete | `test_two_recorded_rounds_do_not_complete`; `test_three_rounds_disclosure_fourth_refusal_and_no_recording` |
| Repeat finalization is harmless after completion | `test_repeat_recording_completion_is_idempotent`: same/new keys, unchanged version and completion timestamp, three rows; `test_concurrent_finalization_with_distinct_keys_is_idempotent`: two requests read before locking and both succeed |
| Version check and atomicity | `test_stale_session_version_refuses_recording_without_side_effects`; `test_completion_rolls_back_atomically`: injected failure after the practice transition rolls back both step and third recording; same key succeeds after recovery |
| Step gate | `test_round_operations_require_shadow_step`; `test_finalization_refused_after_shadow_skipped`; existing `test_round_replay_after_skip_refuses` |
| Another learner cannot read/write recordings | `test_other_learner_gets_404_on_recording`, plus `test_access_cross_learner.py`; finalization registry now supplies the version body |
| Web completion and retained recordings | `a recorded Shadow completion shows unavailable feedback after reload`; `completion remains visible when replay data cannot load and offers retry`; `final upload refreshes the authoritative session and shows completion without grading` |
| Browser and keyboard | Playwright `three Shadow rounds use keyboard controls at 360 px and original speed`: fake microphone, three uploads, authoritative completion, replay after reload |

## Actual red/green chronology

Commands from repository root unless specified:

- Red: `LISTENUP_REQUIRE_DB=1 uv run --project apps/api pytest apps/api/tests/integration/test_shadow_recording.py -k 'three_rounds_produce or two_recorded' -q`:
  1 failed (three recordings left `open_step=shadow`), 1 passed (two recordings).
  Green: same recording file, 15 passed after completion wiring.
- Red: same command with `-k 'stale_session or repeat_recording'`: 1 failed
  (stale finalization returned 204), 1 passed. Green: entire recording file,
  17 passed after adding the version contract.
- Red (apps/web): `pnpm vitest run src/features/session/SessionPage.test.tsx -t 'recorded Shadow completion'`:
  1 failed, missing "Feedback unavailable.". Green:
  `pnpm vitest run src/features/session/SessionPage.test.tsx src/features/shadow/ShadowRecording.test.tsx`:
  11 passed.
- Additional atomicity, replay/error, browser, upload-body and cache-refresh tests
  were added after the corresponding implementation. These are retrospective
  regression/characterization evidence, not claimed test-first cycles. The new
  upload-to-completion test was also run in an isolated directory copy with the
  original `shadow/api.ts`: 1 failed because "All 4 steps finished" never appeared.
  The same test passes with the changed hook. No worktree was created.
- Neighbor checks initially caught completed-read access also permitting skipped
  sessions. The existing skip-refusal test failed; the access was narrowed to a
  done Shadow step. This retains the old skip policy.

- Concurrent retry Red (apps/api): `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_shadow_recording.py -k concurrent_finalization -q`:
  1 failed, responses `[409, 204]` instead of `[204, 204]`. The locked round read
  now refreshes its ORM identity-map entry after waiting for the session lock.
  Green: `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_shadow_recording.py -k 'concurrent_finalization or repeat_recording or completion_rolls' -q`: 3 passed.
- Mutation: in an isolated API directory copy, changed the completion count from
  3 to 2; `test_two_recorded_rounds_do_not_complete` failed as intended. No mutation
  was applied to the actual checkout.

- Completion placeholder Red (apps/web): the focused `recorded Shadow completion`
  test failed because the finished page still contained "The clip's player will
  show here.". After hiding the unfinished player slot on completed plans,
  `pnpm vitest run src/features/session/SessionPage.test.tsx src/features/shadow/ShadowCompletion.test.tsx`
  passed all 7 tests.

## Validation

Infrastructure was checked with a
real psycopg connection and S3 list-buckets call; Compose reports PostgreSQL,
SeaweedFS and Mailpit healthy. PostgreSQL client tools require the saved runtime's
`/workspace/listenup-tools/postgresql16/bin` on PATH.

- Backend static checks: `uv run ruff format --check .`, `uv run ruff check .`,
  `uv run mypy` (208 source files), `uv run lint-imports` (6 contracts) passed.
- No schema change; `uv run alembic heads` reports one head,
  `81_shadow_recordings`. Fetched/merged origin/main and regenerated OpenAPI and
  TypeScript types with the documented export/generation commands.
- Web lint, formatting, type checking, production build and size passed;
  initial JavaScript is 126.2 kB gzip against 200 kB.
- Focused backend round/recording/segment/access suites: 58 passed. The later
  concurrent/idempotent/rollback run passed 3 tests, including the new race case.
- Full Playwright: 247 passed, 3 fixture failures, 2 existing skips. The failures
  were the plan-finished fixture missing its newly required rounds response in
  desktop/360px/dark. After adding three recorded rounds to that fixture,
  `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium pnpm exec playwright test -g 'plan finished|three Shadow rounds use keyboard'`
  passed all 4 tests. The two skips are the plan sheet at desktop widths (the sheet
  exists only at narrow widths), unchanged. The browser suite uses a mocked API,
  not a live backend.

- Full backend command (apps/api):
  `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest -m 'not performance' --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html`:
  2,514 passed, 1 skipped, 7 setup errors (PostgreSQL client tools not on PATH).
  The skipped test is the opt-in real-model profile test, requiring the prepared
  `LISTENUP_REAL_PROFILE_FIXTURE`; no DB/S3 integration tests skipped.
- Corrected/added coverage run:
  `PATH="/workspace/listenup-tools/postgresql16/bin:$PATH" LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest tests/integration/test_shadow_recording.py tests/integration/test_backup.py --cov --cov-append --cov-report=xml --cov-report=html -q`:
  27 passed, including all 7 prior setup errors and the later concurrency test.
  This also refreshes coverage for the final locked-read implementation.
- `uv run pytest -m performance --no-cov -q`: 1 passed.
- Final `pnpm test:coverage`: 731 passed across 68 files. Whole-app web lines
  96.54%, branches 89.38%; these are reported results, not a new baseline.
- Both coverage inventory checks passed. `diff-cover` against origin/main passed
  at **100% changed executable lines**: backend 14/14, web 10/10. Reviewed the
  state, denial, rollback and retry assertions, including the count mutation and
  reproduced concurrent retry defect; no changed executable line is uncovered.
- Final source/static/build checks passed. No main changes arrived during the
  final fetch/merge. No hooks were skipped.

## Scope limits and review

Grading retries, 120-second timeout/late feedback, delayed feedback and producing
real grades after recovery require #80/#82 and remain excluded by the owner's
explicit scope and ADR 0050. Recordings remain replayable; no pretend grading
retry is offered. This does not satisfy the launch gate for Shadow grading.
A fresh-session independent review remains required before merge; no reviewer
agent was spawned because delegation was not authorized. The owner merges.
