# Story #61: tag a mark

Scope: FR-TR-4 (PRD TR-4), UI-4. Implementation is on `feat/61-mark-tags`, made from
`main` at `5db1333`. Dependency #60 was merged (PR #188) before work started. The owner
approved the plan and chose the recommended options (own `PUT .../tag` route, native
select, 2 s debounce, `mark_tag_invalid`); they are recorded in
[ADR 0066](../adr/0066-mark-tags.md). No migration: `practice.marks.tag` and its CHECK
of the four values have existed since migration `58_marks`, and `alembic check` reports
no drift.

## Acceptance criteria and assertions

| Criterion | Named tests and observed result |
| --- | --- |
| Set, change and clear a tag (API) | `test_a_tag_can_be_set_changed_and_cleared` walks all four tags and null, checks the answer, `Cache-Control` and the stored column, and that the rest of the mark is untouched. `test_a_new_mark_can_carry_its_tag` covers a create with a tag and its resend. `test_a_dictation_mark_can_be_tagged_and_keeps_its_source`. |
| A value outside the four is refused by the API | `test_a_tag_outside_the_four_is_refused_and_nothing_changes` (`accent`, empty, `Linking`, `weak form`) on PUT and on POST: 422 `mark_tag_invalid`, stored tag unchanged, no row created. `test_the_tag_body_must_name_the_tag` (missing, number, list: 422). Unit: `test_any_other_tag_is_refused`, `test_a_known_tag_or_no_tag_is_kept`, `test_the_four_tags_match_the_database_check`. |
| …and by the database | `test_the_database_refuses_a_tag_the_api_would_refuse` (API role, row-level security on: a valid UPDATE succeeds, `accent` raises `CheckViolation`); the existing owner-role `test_the_database_refuses_invalid_marks[values5]`. |
| Ownership | Route registered in `access_registry.py` (`Owned`, `session_not_found`); `test_access_cross_learner.py` (7 passed). `test_another_learner_cannot_reach_the_marks` and `test_a_mark_is_reached_only_through_its_own_session` include the tag route. |
| CSRF | `test_tagging_needs_the_csrf_header` (403 `csrf_failed`, nothing stored). |
| Step gate | `test_marks_wait_for_the_transcript_step` includes the tag route (409 `step_locked`). |
| Idempotency | `test_the_same_tag_sent_twice_answers_with_the_same_mark`; `test_tagging_an_unknown_mark_is_refused` (404 `mark_not_found`). |
| Offline sync of a tag change | `markSync.test.ts`: tag shown at once, kept on the device, sent after the debounce; only the last of quick changes is sent; changing it back sends nothing; carried by an unsent create; note then tag order; a failure after the note resends only the tag; a refused tag puts back the server's tag; kept offline through a reload and sent on reconnect; follows a resent create after a lost answer; an older device copy without a tag leaves the server's tag; Undo (unsent and sent removal, Dictation restore) keeps the tag; a mark removed elsewhere is dropped. Screen: `a_tag_changed_offline_is_kept_through_a_reload_and_saved_once_back_online`. |
| Set from the mark and from the list; shown in the list | `MarkPanel.test.tsx` `the_tag_of_the_selected_mark_can_be_set_changed_and_cleared`, `words_not_yet_marked_have_no_tag_choice`. `MarkList.test.tsx` `each_mark_in_the_list_shows_its_tag_in_words`, `the_tag_can_be_set_changed_and_cleared_from_the_list`, `the_list_select_shows_the_current_tag_as_its_state`. `Marking.test.tsx` `a_tag_set_from_the_mark_and_cleared_from_the_list_is_saved_and_described` (PUT bodies, word description `Marked Tag: Weak form`). |
| Mouse and keyboard, accessible name and state | Native `<select>` labelled "Tag (optional)" / "Tag for mark {phrase}" (name and selected value asserted in the component tests). Chromium `transcript_keyboard_controls_at_360px`: ArrowDown sets Linking in the panel, the tag survives reload and Undo, ArrowDown changes it to Reduction and Home clears it from the list, the mock server stores each, and there is no horizontal overflow at 360 px. |

Mutation checks: removing `require_reached` from `review.service.change_tag` made
`test_marks_wait_for_the_transcript_step` and `test_another_learner_cannot_reach_the_marks`
fail (restored). Replacing the panel's `onTag` with a no-op made the 360 px Chromium test
fail at `toHaveValue` (restored).

## Actual development evidence

| Cycle | Red observed before implementation | Green/refactor |
| --- | --- | --- |
| Tag rules | `uv run pytest tests/unit/review/test_marks.py -q`: collection error, `MARK_TAGS` missing from `review.domain`. | Same: **25 passed**. |
| Tag API | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_marks_api.py -q`: **15 failed, 24 passed**; the route answered 404 `not_found` and `Mark` had no `tag`. The CSRF and API-role CHECK tests passed at once: they characterise the existing CSRF middleware and migration constraint. | Same: **38 passed** (the `3` type case moved to the body-shape test, since a non-string is the generic 422). |
| Access registry | `test_access_cross_learner.py`: **2 failed**, the tag route is not in the registry. | **7 passed**. |
| MarkSync | `pnpm vitest run src/features/review/markSync.test.ts`: **17 failed** (`setTag` missing; create body had no tag). | **80 passed**. One test of mine was wrong (it advanced 0 ms where the restore waits for the debounce) and was corrected. |
| Panel and list | `pnpm vitest run src/features/review/MarkList.test.tsx src/features/review/MarkPanel.test.tsx`: **4 failed** (no tag select, no tag text). | **9 passed**, after fixing a lost space in the hidden label ("Tagfor"). |
| Screen | `pnpm vitest run src/features/review/Marking.test.tsx -t tag`: the description test failed (no tag in the word description). My first offline-reload test was flawed: its two fakes disagreed. I rewrote it with one shared server and the offline poll instead of the `online` event. | **2 passed**; review suite **156 passed**. |

The Chromium extension and the "mark removed elsewhere" test were written after the code
they exercise. They add coverage and are not test-first evidence; the mutation check
above shows the browser test detects a broken panel.

## Final checks

- Backend: `ruff format --check`, `ruff check`, `mypy` (194 files), `lint-imports`
  (6 kept): clean. `LISTENUP_REQUIRE_DB=1 uv run pytest -m 'not performance' --cov ...`:
  **2092 passed, 8 skipped**, total coverage 97 %. `uv run pytest -m performance --no-cov`:
  **1 passed**. `alembic check`: no new operations.
- Changed lines: API **100 %** (44 lines), web **100 %** (45 lines); the one uncovered
  changed branch (tag for a deleted mark) got a test.
- Web: `pnpm lint`, `format:check`, `typecheck`: clean. `pnpm test:coverage`: **58 files,
  631 tests passed**. `pnpm build`: ok. `pnpm size`: 125.6 kB of 200 kB. `pnpm e2e`:
  **54 passed**.
- `export_openapi.py` and `pnpm api:generate` were run; the generated client is committed.

## Not run here

- **S3 integration tests.** There is no Docker daemon in this container, so the S3
  storage service could not start. All 8 skipped tests skip because S3 is unreachable
  (`test_storage.py` ×3, `test_uploads.py` ×2, `test_conversion.py`,
  `test_transcript_audio.py`, `test_backup_store.py`); `LISTENUP_REQUIRE_S3=1` was not
  set for the final run. This story does not
  touch storage. CI runs them with both required-service flags.
## Fresh-session review

The review found three things, all fixed on this branch:

- **A tag changed back while its save was on its way was lost** (`markSync.ts`). The
  `setTag` shortcut compared against the server copy from before the request, so the
  PUT stored the old choice and nothing was left to send. Red:
  `pnpm vitest run src/features/review/markSync.test.ts -t changed_back_while`:
  `a_tag_changed_back_while_its_save_is_on_its_way_is_sent_again` **failed** (last PUT
  was `linking`, not `null`). Fix: `settled()` queues an update again when the learner's
  copy still differs from what was stored. Green: **83 passed**; reverting the fix makes
  that test fail again. `a_tag_changed_back_while_the_note_is_on_its_way_is_not_left_on_the_server`
  passed before the fix: the changed note keeps the entry queued, so that path was never
  broken. It stays as a guard.
- **ADR number taken again:** main added ADR 0065 (B5 load test, #217), so this one is
  now [ADR 0066](../adr/0066-mark-tags.md); references and the generated client follow.
- **Architecture API table:** the Transcript row now also lists the confirm route
  (`PUT .../marks/{mark_id}/status`, ADR 0058).

After merging main (`da4fff1`) and these fixes: `pnpm lint`, `format:check`, `typecheck`
clean; `pnpm test:coverage` **60 files, 664 passed**; `build` ok; `size` 125.6 kB;
`pnpm e2e` **59 passed**. The backend results are in the PR. The S3 tests were still not
run locally (no Docker daemon); CI runs them.
