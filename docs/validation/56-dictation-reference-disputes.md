# Story #56 validation

Implements FR-TX-3/4. Branch `feat/56-dispute-reference-word` starts at current
`origin/main` (`8dd1a67`); #54 is closed. Before the PR it was fast-forwarded to
updated `origin/main` (`f6c05c7`) and the story reapplied without conflicts. Only
unrelated docs/spike changes arrived; hashes confirmed the tested application
sources were unchanged, and no migration head changed. The owner approved the 14-line plan and
continuation after disclosure that Claude Code is unavailable in this environment.
One PR is the done criterion. No merge is authorized.

## Acceptance criteria and test evidence

Commands run in `apps/api` with `UV_CACHE_DIR=/tmp/listenup-uv`, or in `apps/web`.
Required-service commands use `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1`.
PostgreSQL 16 and SeaweedFS run through the existing Compose services. Matching
PostgreSQL 16.15 client tools are on PATH from `/workspace/listenup-tools/postgresql16/bin`.
Web commands use the existing pnpm 10.28.0 in `/workspace/listenup-tools/node_modules/.bin`.

| Criterion / behavior | Named tests | Actual Red | Green / refactor |
| --- | --- | --- | --- |
| AC1, FR-TX-4: cat→cap changes accuracy 0→100 and produces an edited Transcript word | `test_dispute_cat_to_cap_recalculates_accuracy_and_marks_edited`; UI `disputing cat as cap updates accuracy and refreshes the Transcript`; browser `reference correction by keyboard updates score and Edited marker at 360px` | `uv run pytest tests/integration/test_dictation_disputes.py -q`: 1 failed, missing route returned 404. After fixing web tool/dependency setup (not Red evidence), `node node_modules/vitest/vitest.mjs run src/features/dictation/DictationResultPanel.test.tsx -t 'disputing cat'`: 1 failed, correction button absent. | API focused test: 1 passed; diff/result neighboring UI tests: 14 passed. Expanded result/event tests: 15 passed. |
| AC2: learner B retains the original word and score on the same shared passage | `test_dispute_keeps_shared_passage_original_for_learner_b`; `test_export_includes_disputed_reference_only_for_its_learner`; registered route exercised by `test_access_cross_learner.py` | Covered by the initial missing-route Red; isolation assertions were added as supplemental tests after the first behavior was green. | Shared test confirms B sees `cat`, edited=false, accuracy=0, and cannot dispute A's attempt. |
| AC3: content deletion removes only that learner's corrections while the shared cache survives | `test_corrections_deleted_with_content_while_shared_cache_and_other_learner_remain` | Expanded `uv run pytest tests/integration/test_dictation_disputes.py -q --tb=short`: 1 failed, 13 passed; deleting A's content retained A's correction. | Same deletion test and neighbors green; 70 passed across dispute/result/marks/review/migration tests. |
| AC3: account purge removes corrections while another learner retains shared cache; export includes only the requesting learner's correction | `test_corrections_deleted_by_account_purge_while_shared_cache_remains`; `test_export_includes_disputed_reference_only_for_its_learner`; existing export inventory test | Existing cascade/export behavior characterized, with disputes created through the new route; no new production behavior added for these existing paths. | Disputes plus export suite: 41 passed. Account test calls authenticated deletion, due-account sweep and actual purge jobs. Content cleanup test uses the existing database deletion path; no new content-deletion API is introduced. |
| Preserve #55 marks and notes/status while replacing mark candidates | `test_dispute_preserves_existing_marks_and_notes_but_replaces_candidates` | Preservation is the existing behavior (no mark writes); no artificial failing test. Candidate regeneration is covered by the initial dispute Red. | Exact saved mark rows remain equal; adding the now-correct word is refused. |
| Boundary, failure and race checks | `test_replacements_preserve_word_indices_and_audio_times`, `test_invalid_dispute_has_no_side_effects`, `test_unscored_attempt_cannot_be_disputed`, `test_retry_does_not_undo_a_later_correction`, `test_concurrent_disputes_on_different_words_keep_both_corrections_and_score`, `test_dispute_maps_partial_passage_index_to_second_cache_span`, `test_dispute_rollback_keeps_correction_score_and_events_atomic`, `test_future_attempt_is_scored_with_own_corrections` | Supplemental coverage after the initial route Red. The future-attempt test first hit a reused fixture submission key (422), not missing behavior; its setup now uses a distinct key and asserts successful submission. | Empty/multiword/60-character replacements, invalid indexes/61 characters, unscored refusal, rollback, concurrent updates, retries and cache-local mapping pass. |
| Other tabs refresh Transcript after a dispute | `dictation.scored refreshes every Dictation result, whichever session it names` | `node node_modules/vitest/vitest.mjs run src/app/eventKeys.test.ts`: 1 failed, 3 passed; Transcript key missing. | Result and Transcript keys both invalidated; expanded result/event tests: 15 passed. |
| Accessible dialog, pending/error/retry and cancellation | Result-panel tests named `correction cancellation and Escape preserve the result and return focus`, `a failed correction keeps the text and retries with the same key; editing makes a new key`, `a pending correction prevents duplicate saves and cancellation`; 360px browser test above | Supplemental interaction coverage after the missing-control Red. | Safe initial focus, tab trap, Escape, restored focus, pending guards, retained input and submission keys verified. |

A supplemental concurrency/denial run (`uv run pytest tests/integration/test_correction_deletion_race.py -q --tb=short`) passed 2 tests: `test_correction_parent_lock_refuses_another_learners_content` and `test_content_deletion_waits_for_inflight_dispute_and_removes_its_correction`. The latter observes the real PostgreSQL blocking relation before releasing the correction transaction, then verifies deletion removed the correction while shared cache survives. These tests were added after the production lock was green; they are not a separate test-first claim.

The additional web retry regression `a replayed correction refreshes the authoritative score after a newer edit` first failed with 100% displayed instead of the authoritative 0% (`pnpm vitest run src/features/dictation/DictationResultPanel.test.tsx -t 'a replayed correction'`: 1 failed, 11 skipped). Saving now refetches the current result after applying the response, so a replay cannot leave an older score on screen. The focused result/diff/event run passed **22 tests** after this fix; the repeated complete web coverage run passed **513 tests**.

The API response-model extraction was a behavior-preserving refactor with focused
UI/API tests green. Generated schema, ADR and documentation updates require no
artificial Red. The historical `test_transcript_overlay_does_not_change_dictation_scoring_reference`
assertion predated #56; it is updated to `test_transcript_overlay_applies_to_own_dictation_scoring_reference`
because scoring must now consume the learner overlay. No assertion was weakened:
it requires the explicit edited word, edited index, unchanged times and sentences.

## Verification

- Backend format/lint: pass; mypy: 181 source files pass; 6 import contracts kept.
- Upgrade/check/downgrade/upgrade: pass, no schema/model drift. The dedicated migration tests also pass.
- OpenAPI exported and TypeScript regenerated; route registered as Owned/404.
- Web lint/format/types: pass. Final coverage: 513 tests pass; 95.78% lines, 88.34% branches overall.
- Web coverage inventory resolves every runtime file; changed executable lines: 100% (24/24), including the staged new dialog. No thresholds or exclusions changed.
- Build and size: pass; 124.8 kB initial JavaScript gzip, under 200 kB.
- Playwright: 41 passed, including correction keyboard interaction, Edited marker and no horizontal overflow at 360px. API responses are mocked; database/API integration tests separately prove persistence/privacy.
- The first complete backend run: 1,979 passed, 1 failed (obsolete overlay assertion), 7 setup errors (PostgreSQL clients missing from PATH), 1 performance test deselected. Focused corrected reference and backup run: 11 passed. These failures are not reported as a successful full run.
- Final backend coverage run: **1,987 passed, 1 deselected**, 582.02 s. The two supplemental parent-lock/deletion-race tests also passed with `--cov --cov-append`, preserving the full-suite report (2 passed, 18.80 s). Overall backend coverage is 97% (line/branch report); every runtime file resolves. Uninstrumented `uv run pytest -m performance --no-cov -q`: 1 passed (1,987 deselected).
- Backend changed-line coverage: **100% of 63 executable lines**, none missing. Backend/frontend inventory checks and `diff-cover --compare-branch origin/main --fail-under 90` both pass.
- Required CI and fresh-session independent review remain merge gates; owner merges.

Dialog line coverage is 100% (branch coverage 75%); the unexercised defensive pending/non-reference entry guard and removed-word title fallback do not gate writes. Removed/empty replacements are covered at the API and existing Transcript UI boundary. Diff has 100% lines and 88.88% branches; ResultPanel has 100% lines/branches. No production coverage exclusion was added. The parent-lock denial branch is explicitly exercised by the supplemental restricted-role test.

## Assertion quality, decisions and scope

The cat/cap assertions reject re-scoring against the old reference or failure to
persist/mark the correction. B's explicit original text, edited=false and zero
accuracy reject overlay leakage. Deletion asserts A's correction is absent while
B's correction and the original cache survive; purge checks the actual account
and correction rows disappear. The retry test rejects replay overwriting a later
edit; the concurrent test requires both independent edits in the final score.
These assertions cover plausible scoring/security defects; no mutation result is
claimed.

ADR 0059 preserves all saved marks (including phrase snapshots, notes and status),
re-scores only the named historical attempt, and applies overlays to future initial
scoring. The migration changes permissions and lifecycle cleanup on the existing
table; the shared cache never changes. A key-share parent lock prevents deletion
racing past a correction write. Database Design 4 and Architecture 5.3 reflect the
same decision; relevant conventions are updated.

No changes to review mark status/styling, the gist panel, cards, shadow, blind,
grading or AI. Existing Transcript edited-marker behavior is reused unchanged.

## Review fixes (2026-10-24)

- Account-purge storage: the new test fixture now installs the same `FakeStorage`
  for requests and background workers and resets it on teardown. The regression
  refuses real S3 prefix deletion and checks that the learner's file is deleted
  while another learner's file survives. Before the fix, the file remained;
  after the fix, the account, correction and file deletion assertions pass.
- Export isolation: `test_early_expiry_keeps_a_future_job` now creates another
  learner's valid archive and checks expiry by the requesting learner's exact
  key. The old all-archives-absent assertion failed; the scoped assertion passes
  and explicitly preserves the other learner's archive.
- Pending keyboard focus: `ConfirmDialog` focuses its container while busy,
  traps Tab/Shift+Tab with no enabled controls, and restores the safe action on
  failure. The new component test and delayed-response 360px browser regression
  both failed on lost focus before the fix and pass afterwards. Existing native
  disabled controls and pending cancellation guards remain in effect.
- Focused Red commands: `uv run pytest tests/integration/test_dictation_disputes.py::test_corrections_deleted_by_account_purge_while_shared_cache_remains tests/integration/test_export.py::test_early_expiry_keeps_a_future_job -q --tb=short`
  produced **2 failed**; `pnpm vitest run src/components/ConfirmDialog.test.tsx`
  produced **1 failed**; `pnpm e2e e2e/dictation.spec.ts -g 'reference correction by keyboard'`
  produced **1 failed**. The same focused API command then passed **2 tests**;
  dialog/result component checks passed **13 tests**, and the browser check
  passed **1 test**. Required PostgreSQL was enabled for API checks.
- FR-TX-4 is synchronized with issue #56 and the accepted dispute flow, following
  the owner's request to resolve the review findings. This documentation update
  needs no artificial failing test.

Synchronization with `origin/main` at `e8901a4` keeps Shadow's accepted ADR 0057
and initially renumbered this decision to ADR 0058 (now ADR 0059). The dispute migration now follows
`77_shadow_segments`, so Alembic has one head; upgrade/check/downgrade/upgrade
pass. OpenAPI/client regeneration produces no additional diff after the merge.
The PR adds no changes to the excluded modules relative to that main.

The shared-dialog follow-up test `Tab from the busy dialog container reaches a
remaining help link in either direction` initially failed (1 failed, 1 passed):
Shift+Tab from the container was not contained while a Help link remained enabled.
Both container-to-first/last cases are now handled; both dialog tests pass.

One complete backend run was stopped before completion after noticing that the
race test module also needed to import the new storage fixture. That fixture
import is fixed, both focused race tests pass, and the complete run was restarted.
The stopped run is not counted as successful validation.

Final frontend validation after synchronization with current main:

- Lint, formatting, types, build and bundle size pass (124.9 kB gzip).
- Coverage run: **523 passed** in 52 files; 95.78% overall lines, 88.50% branches.
- Complete browser run: **44 passed**, including real Tab/Shift+Tab while the
  correction response is held pending, score/Edited refresh, restored opener
  focus, and the other flows using the shared confirmation dialog.
- Coverage inventory passes; changed executable lines are **33/34 (97%)**.
  The uncovered line is the existing shared scrim mouse-down handler; the new
  busy-focus and Tab containment paths have observable assertions. No coverage
  threshold or exclusion changed. Browser API responses remain mocked.

Final backend validation after synchronization with current main:

- Full required-service coverage run: **2,022 passed, 1 deselected** in 578.64 s;
  PostgreSQL and S3 were required, with no skips. Overall line/branch report: 98%.
- Separate uninstrumented performance run: **1 passed, 2,022 deselected**.
- Backend formatting/lint, strict mypy (187 files) and all six import contracts
  pass. Migration upgrade/check/downgrade/upgrade passes with one Alembic head.
- Coverage inventory passes; changed executable lines are **63/63 (100%)**.
- OpenAPI/client regeneration is reproducible, and all route-registry checks pass
  within the complete backend run. No application coverage gate was weakened.
- Required GitHub CI will rerun on the pushed fix commits. The original run's
  account-purge failure is retained as historical evidence, not reported green.
  The owner merges after the current required checks pass.

## Final main synchronization before merge (2026-10-25)

Required CI passed on `67afd66`, but strict branch protection required another
synchronization after main advanced to `ee09123` with #59 and #69. Those changes
merged cleanly. Main reserves ADR 0058 for mark confirmation/removal, so this
dispute decision is now ADR 0059; all its links and references are synchronized.
No new product behavior is introduced by this numbering update. Generated-client
regeneration adds no changes to the merged schema/types. Focused UI checks pass
**82 tests** across dialog, Dictation result, mark synchronization and event keys;
TypeScript checks pass. Required CI reruns the complete backend, web and browser
checks before the owner-authorized merge.
