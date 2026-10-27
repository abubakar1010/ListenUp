# Issue #75 — saved cards and marks review

Implements FR-CA-5 on the merged #72 cards and #73 private snippet implementation.
No dependency on #61 or PR #214; no scheduling or phrase suggestions.

## Acceptance evidence

| Criterion | Evidence |
| --- | --- |
| Owned deck and keyset pagination | Existing `test_list_and_delete_isolated_and_paginated`; `test_marks_across_sessions_and_equal_timestamp_pages` also checks the deck across two sessions with equal timestamps; restricted-role route registry; `DeckPage.test.tsx` paginated navigation and reveal reset |
| Listen before revealing either form | `keeps both forms and labels hidden until snippet ends and saves a result`; playback failure, pause, and unavailable audio cases; actual browser playback of the private S3 snippet |
| Durable heard/unsure/missed results | `test_review_results_persist_and_replay` checks all three values, ordered history, same-key replay, invalid input, CSRF, foreign reads/writes and private/no-store |
| Marks across sessions, newest first | `test_global_marks_keyset_and_source`; `test_marks_across_sessions_and_equal_timestamp_pages` checks the UUID tie-breaker, distinct sessions, malformed/naive cursors and limits |
| Source content at the right time | `MarksPage.test.tsx` verifies source/session URLs; live browser follows the source link and observes audio `currentTime >= 10.9` for `at_ms=11000` |
| Persistence after a second sign-in | `test_second_login_retrieves_deck_marks_and_reviews`; live check in two independent Chromium contexts with separate cookie jars and separate logins |
| Learner isolation | `test_access_cross_learner.py`, route registry entries for all new endpoints, explicit other-learner history/write/list refusals, expanded `sessionIsolation.test.tsx` private cache keys |
| Database boundaries | `test_review_foreign_key_result_constraint_and_card_cascade` rejects an owner-mismatched review even as the DB owner, rejects invalid results, verifies history cascades and deleted-card 404 |
| Accessibility and layout | axe states for hidden/revealed/empty cards, pending/failed/legacy audio, saved/failed results and empty/populated marks at desktop, 360 px and dark theme; live 360 px overflow and keyboard checks; focused controls stay in place after deck completion and result saving |

## Test-first evidence

- Before implementation: `.venv/bin/pytest tests/integration/test_saved_review.py -q --no-cov`
  failed both initial tests on 404 for the missing reviews and global marks routes.
  After implementation: those two tests passed; subsequent cases extend persistence,
  constraints and timestamp boundary coverage.
- Before the deck page existed: `pnpm exec vitest run src/features/cards/DeckPage.test.tsx`
  failed on the missing `DeckPage` public interface. The initial interaction test
  then passed after the page/player implementation.
- Keyboard regression: `pnpm exec vitest run src/features/cards/DeckPage.test.tsx -t 'keeps the next control'`
  failed because Next disappeared at the end; it passed after keeping a guarded,
  focusable control in place.
- Saved-result focus regression: `pnpm exec vitest run src/features/cards/DeckPage.test.tsx -t 'keeps both forms'`
  failed because the result button became natively disabled; it passed after
  using guarded `aria-disabled` controls and retaining focus.
- The marks page tests and additional failure/constraint cases were added after
  the initial implementation; they are regression/characterization evidence,
  not separate test-first cycles. Generated API types and documentation have no
  executable behavior requiring a red test.

The isolation assertions would detect a missing owner check/RLS by requiring
foreign history/write 404 and an empty foreign list. The database constraint test
would fail if the composite foreign key or result CHECK were removed. The reveal
assertions reject forms in both visible content and pre-reveal markup/labels.

Two additional regressions were found during final verification:

- The full backend run exposed a snippet-lifecycle migration test that used
  `downgrade -1`. After #75 this removed the review table instead of reaching the
  lifecycle writer barrier. The test still requires the same barrier exception;
  it now names revision `73_card_audio` and restores head afterward because Alembic
  commits each successfully crossed migration. The regression run including that
  test, all export tests and the new saved-review tests passed (28 tests).
- `pnpm exec vitest run src/api/client.test.ts` initially failed on the existing
  bodyless `202 Accepted` snippet-retry response (`Unexpected end of JSON input`).
  The shared client now accepts a 202 without a content type, while preserving
  accepted JSON payloads and rejecting missing JSON on ordinary 200 reads. That
  boundary test and the deck retry-refresh test pass together.

## Live browser procedure

A local development database was migrated and seeded with one learner's existing
card and mark, plus real private S3 audio objects. The API ran with a restricted
`listenup_api` login; Vite proxied to that API. No API response was mocked.

1. Open context A at 360 px, sign in, verify forms absent and reveal disabled.
2. Play the three-second private snippet through `/cards/{id}/audio`, await its
   natural end, and use Enter to reveal the forms.
3. Save Unsure through the real CSRF/idempotency-protected endpoint; retain focus
   on the result control and verify no horizontal page overflow.
4. Open independent context B and sign in to the same account. Repeat playback
   and reveal, then read A's stored result in Recent results.
5. Open Saved marks, follow the 11-second source link, and verify the URL and the
   loaded audio time. Confirm a signed-out context receives 401 on the deck API.

This live check passed. The audio fixtures exercise storage, ownership, browser
playback, reveal and persistence; snippet generation itself remains covered by
#73's existing API/job/storage tests. Separate mocked browser accessibility scans
prove the named UI states and do not claim live server persistence.

## Final checks

| Check | Result |
| --- | --- |
| Full API functional/coverage suite with PostgreSQL and S3 required | 2,308 passed; 1 unrelated opt-in real-model test skipped |
| Migration regression + complete export suite + saved review API cases | 28 passed |
| Uninstrumented performance suite | 1 passed |
| `pnpm test:coverage` | 652 passed across 63 files; 96.41% line coverage |
| Focused API client, deck, marks and account-isolation tests | 21 passed |
| Chromium browser suite | 59 passed |
| New axe states, desktop/360 px/dark | 30 passed |
| Live independent browser contexts against restricted API + private S3 | Passed, repeated on final code |
| Web lint, formatting, typecheck, build and bundle budget | Passed; initial JS 126.2 KB gzip / 200 KB budget |
| Ruff lint/format, mypy, import contracts | Passed; 207 typed source files, 6 import contracts |
| Alembic schema comparison | No new upgrade operations detected |
| Generated OpenAPI/client | Regenerated; no remaining drift |
| API and web coverage inventories + changed-line gates | All runtime files resolve in both reports; 100% changed executable lines covered in each app |

The cross-session timestamp-tie case was strengthened after the full run to
include cards as well as marks, then rerun by name: 1 passed. No production code
changed after the final full-suite runs. The skipped real-model profile test
requires an opt-in LibriSpeech fixture and is outside this story's scope.

The 360 px screenshots were visually inspected: the header navigation wraps,
forms and results remain inside the card, focus remains visible, and the mark
list/source links fit without overlap, clipping or horizontal page scrolling.
Independent review and CI remain separate gates before merge; no merge or deploy
is part of this task.
