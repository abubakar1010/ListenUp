# #59 follow-up validation

Done criterion: one PR for the story, opened for owner review; do not merge.
This session continues existing PR #204 on `feat/59-confirm-dictation-marks`.
A concurrent implementation was discovered when the initial push was rejected;
its history, PUT status route, immediate confirm/remove saves and ADR 0058 were
preserved. The alternate local implementation was not pushed over it, and no
second PR was created. The owner authorized using Codex when Claude Code was
unavailable.

## Acceptance criteria and named tests

The PR body maps the original red/green cycles to its API and UI tests. This
follow-up adds a failure regression and browser coverage:

| Criterion | Evidence |
| --- | --- |
| AT-4: pre-filled after Dictation | Existing `test_after_dictation_its_marks_are_pre_filled_in_transcript` and `after_dictation_its_marks_are_pre_filled_and_told_apart_from_manual_marks_in_words`; both remain green |
| Confirm/remove saved within 1 s and survives reload | Existing `confirming_a_dictation_mark_shows_at_once_and_is_saved_within_a_second`, `removing_a_mark_is_saved_within_a_second`; new browser `dictation_marks_confirm_and_remove_with_reload_and_noncolour_cues_at_360px` checks local retention within 1 s and reload/retry after an interrupted connection for each operation |
| Dictation/manual distinguished without colour | New browser test checks text descriptions, dashed/solid borders and the manual source label, keyboard Confirm and retained row focus at 360 px |
| #60 count remains correct | New browser test asserts 2 marks before/after confirmation, 1 after removal and reload. `undo_of_a_refused_inflight_dictation_deletion_restores_the_saved_source_and_status` checks the surviving mark and its note after a refused DELETE races with Undo |
| Persistence and access boundaries | `test_dictation_marks_in_transcript.py` plus `test_access_cross_learner.py`, restricted API role, 16 tests pass with PostgreSQL/S3 required |

## Actual red/green

From `apps/web`:

- Red: `pnpm vitest run src/features/review/markSync.test.ts -t undo_of_a_refused_inflight_dictation`
  on PR head `bae5611`: **1 failed**. Undo had replaced the in-flight deletion
  with a manual/confirmed create; refusal restored the server pointer but left
  the visible source/status wrong and another update pending.
- Green: reuse the saved mark's source/status with the current note when that
  deletion is refused. `pnpm vitest run src/features/review`: **114 passed**.
  The assertion checks the specific false manual/confirmed state seen in Red;
  coverage alone would not catch it.
- The new browser test supplements already implemented acceptance behavior and
  passed on arrival: `pnpm e2e --grep dictation_marks_confirm_and_remove`:
  **1 passed**. It mocks API/network responses; actual persistence and access
  remain independently covered by the PostgreSQL tests above.

## Verification

- Web lint, formatting, typecheck: passed.
- `pnpm test:coverage`: **523 passed**; line coverage **95.82%**, branch
  coverage **88.51%**. Coverage inventory passes, and `diff-cover` against
  `origin/main --fail-under 90`: **100% (76/76 changed executable lines)**.
  The follow-up adds two executable lines, both covered by the red/green regression.
- `pnpm e2e`: **41 passed** in Chromium (2.1 min), including the new 360 px
  reload test. Its configured production build passed. `pnpm size`: **124.8 kB
  gzip / 200 kB** initial JavaScript budget.
- `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest tests/integration/test_dictation_marks_in_transcript.py tests/integration/test_access_cross_learner.py -q`:
  **16 passed** (75.19 s). The S3 service is available in this environment.
- `uv run pytest -m performance --no-cov -q`: **1 passed**.
- Backend implementation, route registry, exported schema and generated client
  are unchanged from PR head `bae5611`; its complete backend, API contract and
  coverage checks passed in [CI run 39944036997](https://github.com/abubakar1010/ListenUp/actions/runs/39944036997).
  New CI runs on the follow-up commit. No migration or backend change is
  introduced by this follow-up, so those checks are not repeated artificially.
- The full web suite and browser suite are rerun because the final code now
  follows the existing PR's implementation. Results from the superseded local
  implementation are not represented as validating this final code.

## Decisions and merge gates

ADR 0058 settles the technical-notes question: removal deletes the mark, with
no third status and no filters for downstream readers. Its independent creation
analytics remains. This fix restores the saved data after a refused removal and
introduces no new data rule or API.

The owner questions already in PR #204 (Undo after a saved removal and finishing
with suggestions) remain visible for review; this follow-up does not silently
answer them. Fresh-session independent review and required CI remain merge gates.
Actual-server latency is **deferred until staging — unverified** under ADR 0039
and [launch validation tracker #155](https://github.com/abubakar1010/ListenUp/issues/155).

## Review fixes (2026-10-24)

An independent review of `b868f7e` found two defects and four validation gaps. The owner
chose to keep a Dictation mark's source on Undo through a server-checked restore. The
existing Dictation marks route (ADR 0055) already checks words against the scored diff
and inserts by the browser's id, so Undo reuses it. ADR 0058 records this; there is no
new route, schema or generated client change.

| Finding | Fix | Red (observed) | Green |
| --- | --- | --- | --- |
| A reload after Undo of a removal whose DELETE never landed confirmed the suggestion | `restore()` takes only the note from a kept create or restore op | `pnpm vitest run src/features/review/markSync.test.ts -t a_reload_after_undo_of_an_unlanded`: **1 failed** (`confirm` called once) | `pnpm vitest run src/features/review`: 115 passed |
| Undo after a sent removal (the usual case, since removal is sent at once) remade the mark as manual and confirmed | `MarkSync.undoRemove` and a `restore` op, sent through `POST /dictation/attempts/{id}/marks` | 8 sync tests failed (`undoRemove` missing); `undo_of_a_removed_dictation_mark_brings_it_back_from_dictation_to_confirm` failed (row read "Your mark") | review and dictation web tests: 191 passed |

Named tests for the Undo fix: `undo_of_a_saved_dictation_removal_brings_the_mark_back_from_dictation_to_confirm`,
`undo_of_a_saved_removal_of_a_confirmed_dictation_mark_keeps_it_confirmed`,
`undo_during_an_in_flight_dictation_removal_restores_it_once_the_removal_lands`,
`an_unsent_dictation_undo_survives_a_reload_and_is_sent_then`,
`a_dictation_undo_on_words_marked_again_since_shows_the_mark_they_have`,
`a_refused_dictation_undo_brings_the_mark_back_as_the_learners_own`,
`removing_a_restored_dictation_mark_whose_answer_was_lost_still_deletes_it`,
`undo_of_a_removed_manual_mark_still_makes_it_again`, and the screen test above.

Tests that passed on arrival and were added for the gaps, each checked by breaking the
code it guards:

- `test_marks_wait_for_the_transcript_step` now includes `PUT .../status`. With
  `require_reached` removed from `confirm_mark` it fails (404 instead of 409).
- `a_refused_dictation_removal_raced_by_undo_keeps_the_note_written_since` changes the
  note between Undo and the refused DELETE. With `takeBack` keeping the server's note it
  fails.
- `test_undo_of_a_removed_dictation_mark_brings_it_back_from_dictation` (API) records
  that the same id comes back `dictation`/`suggested` with one `mark_created` event.
- `a_dictation_undo_after_marking_the_words_again_here_keeps_one_mark` covers the
  remaining branch of the restore answer.
- The browser test now asserts which mark survives (`m-59`) instead of re-reading its
  fixture.

While these fixes were made, commits `89a9563` and `a56030f` reached the branch from
another session with the same reload fix, the same gate and browser test changes, and
three more sync tests. They were merged in (no rebase or force-push). The merged
`restore()` keeps their branch, extended in its comment to the `restore` op, and every
test from both sides is kept.

### Checks on the fixed head

- Web: lint, format and typecheck pass. `pnpm test:coverage`: **534 passed**. Coverage
  inventory passes; `diff-cover` against `origin/main`: **100% (112/112 changed
  executable lines)**. The only partly covered new branch is a guard that mirrors the
  in-flight DELETE handling (`markSync.ts`, restore answer for a replaced entry).
- `pnpm e2e`: **41 passed** in Chromium. `pnpm size`: **124.8 kB / 200 kB** gzip.
- Backend: ruff, format, mypy (strict) and `lint-imports` (6 contracts kept) pass.
  `test_dictation_marks_in_transcript.py` and `test_marks_api.py` with PostgreSQL
  required pass. The S3 integration tests cannot run here (no S3 server is reachable);
  CI runs them with `LISTENUP_REQUIRE_S3=1`.
- Actual-server latency stays **deferred until staging — unverified** (ADR 0039, #155).
