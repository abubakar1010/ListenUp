# Story #60 validation

Implements FR-TR-5 and FR-PL-4. Branch: `feat/60-mark-count-and-list`, created
from current `origin/main` (57ff878); branch-name validation passed. The owner
authorized Codex in place of the prompt's Claude Code. No planning gate applies
(`Plan first: no`). Done criterion: one PR; the owner reviews and merges.

## Acceptance criteria and test-first evidence

Commands in this table run from `apps/web`, except the API command, which runs
from `apps/api`. Red failures were observed before each implementation. Browser
tests supplement the component-first cycles; they are not additional test-first
claims.

| Criterion / behavior | Named tests | Actual red | Green / refactor |
| --- | --- | --- | --- |
| AT-4 (part), FR-TR-5: ordered list; selecting a mark seeks its audio and highlights its words | `mark_list_is_in_audio_order_and_selecting_a_mark_seeks_and_highlights_its_words` (out-of-order saved input, nonzero passage start and fractional-second target); `transcript_keyboard_controls_at_360px` (native Enter with real WAV media) | `pnpm vitest run src/features/review/Marking.test.tsx -t 'mark_list_is\|mark_count_and\|list_keyboard'`: 3 failed because count/list controls were absent. | Same focused selection: 3 passed; expanded review suite: 81 passed. |
| Live count, including zero, optimistic add/remove before saving | `mark_count_and_empty_list_update_before_the_server_saves_additions_and_removals` | Included in the 3-failure cycle above. | Included in the 81-pass review suite. |
| Keyboard list controls: E edits, Delete removes, Undo restores note and count | `list_keyboard_edit_delete_and_undo_preserve_the_mark_and_note`; `transcript_keyboard_controls_at_360px` | Included in the 3-failure cycle above. | Included in the 81-pass review suite; focused Chromium run: 1 passed. |
| Safe Undo while DELETE is in flight | `undo_during_an_in_flight_delete_recreates_the_mark_with_its_note` | `pnpm vitest run src/features/review/markSync.test.ts -t undo_during`: 1 failed, restored mark disappeared when DELETE settled. | The expanded review run passed; same scenario remains in the final sync suite. |
| Remove, Undo, then remove again before saving | `remove_undo_remove_before_saving_still_deletes_the_saved_mark` | `pnpm vitest run src/features/review/markSync.test.ts -t remove_undo_remove`: 1 failed, the server retained the removed mark. | `pnpm vitest run src/features/review/markSync.test.ts`: 33 passed. |
| FR-PL-4: finish Transcript persists done and opens Card, including zero marks; repeat must not advance Card | `test_finishing_transcript_unlocks_card_and_persists_the_plan`; `test_finishing_transcript_denies_locked_foreign_missing_and_unsigned_sessions` | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_review_api.py -k finishing -q`: 2 failed because POST returned 404. | Full review/marks/access-registry targeted run: 48 passed. The first green attempt exposed a CSRF setup error in the signed-out test; refreshed the CSRF cookie before asserting authentication refusal. |
| Finish action refreshes the plan, remains busy during the request, and allows retry on failure | `finishing_Transcript_refreshes_the_plan_and_opens_Card`; `completion_failure_keeps_Transcript_and_allows_retry` | `pnpm vitest run src/features/review/TranscriptScreen.test.tsx -t 'finishing_Transcript\|completion_failure'`: 2 failed, no Finish Transcript button. | Included in the 81-pass review suite. The pending-state assertion awaits the asynchronous mutation notification. |
| Finish waits for mark persistence, including removals not present in the displayed list | `finish_waits_for_saved_marks_including_pending_removals` | `pnpm vitest run src/features/review/Marking.test.tsx -t finish_waits`: 1 failed, missing Finish action. | Included in the 81-pass review suite. |
| Refused removal restores count and allows completion once there are no pending writes | `a_refused_removal_restores_the_count_and_does_not_trap_Transcript_completion` | `pnpm vitest run src/features/review/Marking.test.tsx -t a_refused_removal_restores`: 1 failed, Finish stayed disabled after rollback. | `pnpm vitest run src/features/review`: 84 passed after exposing pending writes separately from the last save error. |
| Keyboard and 360 px / UI-4 | `transcript_keyboard_controls_at_360px` | Browser verification supplements the cycles above. | Focused Chromium run passed: real audio seeking, word outlines, E focus, Delete/Undo, 500-character unbroken note without overflow, Finish to Card. |

Assertions detect the relevant defects directly: the seek target is 140.125 seconds
rather than passage-relative 10.125; selected words have an outline; count changes
before any POST; Undo races inspect both local state and server persistence;
completion checks all four persisted step states and unchanged version on retry.
The API tests use the restricted API role. The new route is registered as Owned,
with the existing cross-learner suite checking authentication, ownership and absence
of foreign side effects. No schema migration, new domain rule or significant
architecture decision was needed. `create_mark`, Dictation, grading and AI are
unchanged. The existing marks GET and sync snapshot are reused.

Additional characterization: `list_buttons_offer_edit_remove_and_ignore_modified_or_repeated_shortcuts`
checks explicit edit/remove controls, modified/repeated keys and a mark whose words
were removed by a learner correction. Moving the live count from the list into
`MarkPanel` was a behavior-preserving presentation refactor: the existing count
and sticky-panel tests stayed green (`pnpm vitest run
src/features/review/Marking.test.tsx src/features/review/MarkPanel.test.tsx
src/features/review/MarkList.test.tsx`: 27 passed). The refused-removal test was strengthened after the initial green run to require
that the obsolete Undo notice also disappears. The focused command
`pnpm vitest run src/features/review/Marking.test.tsx -t a_refused_removal_restores`
failed once (Undo still present), then passed after the notice condition was fixed.
Browser HTTP responses are
mocked; the API tests independently prove persistence and ownership.

## Final verification

- Frontend: `pnpm lint`, `pnpm format:check`, `pnpm typecheck`,
  `pnpm test:coverage` (469 passed), `pnpm build`, `pnpm size` (124.4 kB
  initial JavaScript gzip, below 200 kB), and `pnpm e2e` (37 passed). The Transcript browser test was rerun
  after the final refusal-notice fix and passes again (one test).
- Frontend coverage: 95.56% lines and 87.92% branches overall. The coverage
  completeness check passes and staged `diff-cover --compare-branch origin/main
  --fail-under 90` reports **100% of 45 changed executable lines**. `MarkList`
  and `MarkPanel` have 100% line/branch coverage. The new absent-mark guard in
  `removeMark` has only its normal, present-mark branch exercised; it protects
  against stale callbacks. Other uncovered review branches predate this story.
  No coverage exclusion or threshold changed.
- Backend: format, lint, mypy (166 files) and all six import contracts pass.
  The first complete coverage run had 1730 passes and one unrelated audio
  integration failure: the default local database was at migration 0012,
  so gateway accounting was unavailable. After `uv run alembic upgrade head`,
  `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest
  tests/integration/test_transcript_audio.py -q` passes both tests. The final
  `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest -m 'not performance'
  --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html`
  run passes **1731 tests**, with no skips (one performance test deselected).
  `uv run pytest -m performance --no-cov` passes its one test. Backend overall
  coverage is 97%; the completeness check passes and changed-line coverage is
  **100% of six executable lines**. Both service-required flags were set; PostgreSQL
  16 client tools were on PATH for backup tests.
- API: OpenAPI export and `pnpm api:generate` completed. The access registry
  includes the new route. No schema migration is part of this change.

The initial non-TTY pnpm dependency refresh required `CI=true pnpm install
--frozen-lockfile`. Database and S3 containers were started and checked; after the
environment resumed, their stopped containers were restarted. Local PostgreSQL
16 client tools were extracted under ignored `work/` for the backup tests.
The first complete frontend coverage run picked up the new remove/Undo/remove
regression while its fix was being developed (466 passed, one failed); the final
complete run above includes the fix and passes. The very first backend collection
was interrupted to select the matching PostgreSQL 16 client tools; it is not a
passing run. No skipped or blocked check is counted as passing.

Required CI and fresh-session independent review remain merge gates; the owner
merges. No independent reviewer has been claimed in this builder session.

## Independent review remediation (2026-10-23)

The fresh-session review of `d4a3a74` is posted at
https://github.com/abubakar1010/ListenUp/pull/188#pullrequestreview-5624988789.
The owner then authorized fixes in this PR and chose the documented submission
idempotency rule for Finish Transcript. UX-22 is followed without changing its
policy: the visible count remains immediate, counter announcements wait one second,
and mark notices/refusals share one polite region. No new ADR or exception is needed.

Actual focused cycles, run before each corresponding implementation:

| Finding / boundary | Regression and observed red | Green |
| --- | --- | --- |
| Saved mark lost locally after Undo and a refused create; saved note rollback | From `apps/web`: `pnpm vitest run src/features/review/markSync.test.ts src/features/review/Marking.test.tsx -t 'undo_cancels_an_unsent\|a_refused_note_after_undo\|finish_waiting_for_marks'`: 3 failed. Both sync tests received an empty local list despite the saved server mark. | Same selection: 3 passed. Undo now cancels unsent deletion while retaining its server snapshot; refused notes roll back to that snapshot. |
| Finish must remain focusable with a linked reason and refuse premature activation (UX-10) | `finish_waiting_for_marks_stays_focusable_and_explains_why_without_completing`, in the same command above, failed on native disabled. | Same selection passed. Existing pending-state assertions now check `aria-disabled`; the new interaction asserts focus and absence of completion requests. |
| One polite region and debounced counter announcements (UX-22) | `pnpm vitest run src/features/review/MarkPanel.test.tsx -t the_visual_count`: 1 failed, two status regions instead of one. | Expanded review suite passed; fake-clock assertions cover the one-second boundary and cancellation when the count changes again. |
| Undo while an in-flight DELETE is refused | `pnpm vitest run src/features/review/markSync.test.ts -t undo_of_an_in_flight_refused`: 1 failed, local mark vanished. | Expanded sync coverage also checks a changed note and remove–Undo–remove after refusal, with local and fake-server assertions. |
| Undo after DELETE commits but its response is lost | `pnpm vitest run src/features/review/markSync.test.ts -t undo_after_a_lost_delete`: 1 failed against the initial remediation (server mark missing). | Deletion-attempt tracking distinguishes a safely canceled queued DELETE from an uncertain/committed one that needs recreation. |
| Rapid Finish activation before mutation notifications render | `pnpm vitest run src/features/review/TranscriptScreen.test.tsx -t 'completion_with_a_lost\|repeated_finish_activation'`: 1 passed, 1 failed (two completion requests). The lost-response example is characterization, not a test-first claim. | A synchronous activation guard prevents the duplicate and resets when the request settles. The waiting reason also covers an in-flight completion. |
| Submission replay and concurrent duplicate requests | From `apps/api`: `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_review_api.py -k 'replays_a_key or consume_its_retry_key or concurrent_completion' -q --tb=short`: 3 failed (retry/concurrent request returned 409). | Focused API completion suite: 7 passed, including CSRF, ownership/authentication on replay, failed-key rollback, empty replayed 204, and one persisted version increment under concurrent requests. |
| Browser sends one stable submission key across retries | From `apps/web`: `pnpm vitest run src/features/review/TranscriptScreen.test.tsx -t completion_retries_send`: 1 failed (both keys undefined). | Stable session-scoped key added to the existing mutation. |

Supplementary coverage includes
`undo_keeps_the_saved_count_and_note_when_a_create_would_be_refused`, which checks
visible count/list/note and no unnecessary POST or DELETE. The 360 px Chromium test
now reaches the pending Finish action through Tab, activates it with Enter, checks
focus on the linked reason and zero completion requests, then releases the held mark
write. Browser API responses remain mocked; PostgreSQL API tests independently prove
persistence, idempotency, authentication, ownership and CSRF. Generated OpenAPI/client
updates are mechanical and need no artificial red test. `review/service.py` and
`create_mark` are unchanged by remediation, as are Dictation, grading and AI.

Final remediation verification:

- Web: lint, formatting, typecheck, **481 tests** with coverage, production build,
  bundle budget (**124.4/200 kB gzip**) and **37 Chromium tests** pass.
- Backend: format, lint, mypy and all **six import contracts** pass. With PostgreSQL
  and S3 required, full coverage run passes **1736 tests**, no skips (one performance
  test deselected). The separate uninstrumented performance test passes.
- Coverage: runtime-source completeness checks pass for both apps. Web changed-line
  coverage is **100% of 68 executable lines**; `MarkList` and `MarkPanel` retain 100%
  line/branch coverage. The stale absent-mark callback guard and pre-existing review
  branches remain uncovered; the new cancellation, refusal and rapid-completion
  decisions have exercised outcomes. Backend changed-line coverage is **100% of 11 executable lines**; overall
  coverage remains **97%**.
- OpenAPI and TypeScript client regenerated; no migration, coverage exclusion or
  threshold changed. PostgreSQL 16 client binaries were extracted under local
  `work/` for the backup checks; the default database was migrated before the full
  run. Red results above are regression evidence, not passing validation.

The fixes require CI on their new commit and fresh-session re-review before merge;
the review of `d4a3a74` does not claim independence for changes made afterward in
this remediation session. The owner merges.
