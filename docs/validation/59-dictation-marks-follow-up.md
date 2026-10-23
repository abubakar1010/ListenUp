# #59 follow-up validation

Done criterion: one PR for the story, opened for owner review; do not merge.
This session continues existing PR #204 on `feat/59-confirm-dictation-marks`.
A concurrent implementation was discovered when the initial push was rejected;
its history, PUT status route, immediate confirm/remove saves and ADR 0056 were
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

ADR 0056 settles the technical-notes question: removal deletes the mark, with
no third status and no filters for downstream readers. Its independent creation
analytics remains. This fix restores the saved data after a refused removal and
introduces no new data rule or API.

The owner questions already in PR #204 (Undo after a saved removal and finishing
with suggestions) remain visible for review; this follow-up does not silently
answer them. Fresh-session independent review and required CI remain merge gates.
Actual-server latency is **deferred until staging — unverified** under ADR 0039
and [launch validation tracker #155](https://github.com/abubakar1010/ListenUp/issues/155).
