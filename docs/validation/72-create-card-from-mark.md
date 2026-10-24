# Story #72: cards from marks

Scope: FR-CA-1, FR-CA-2 without the #73 audio snippet, FR-CA-3, C3, AT-5 and D14.
Implementation is on `feat/72-create-card-from-mark`. Dependency #60 was closed
before implementation. The owner approved the plan and proceeding in Codex because
Claude Code was unavailable in this environment.

## Acceptance criteria and assertions

| Criterion | Named tests and observed result |
| --- | --- |
| AT-5: two saved cards, third blocked, no definition/translation | API `test_two_cards_succeed_third_refused` asserts 201/201/409, slots 1/2, `card_limit_reached`, count and two analytics events. UI `blocksThirdCardWithoutDefinition and deletion frees its slot (AT-5, D14)` asserts no extra POST and no definition/translation input. Chromium `cards_keyboard_at_360px` also asserts exactly two creates. |
| D14: deletion frees its slot | `test_delete_frees_slot` asserts the replacement uses the deleted slot. The UI and Chromium tests above assert the remaining count and available Save action after confirmed deletion. |
| Concurrent last slot | `test_concurrent_last_slot_creates_one` submits two requests through the restricted API role and asserts exactly one 201, one 409 and two persisted cards. `test_db_unique_slots_and_composite_owner` independently proves the database constraint. |
| Both forms: 1–100 characters | `test_form_boundaries` covers 0/1/100/101 for each field. `test_db_refuses_invalid_cards` independently checks invalid lengths and slots. UI `forms expose the 1 to 100 character limits` checks required/min/max attributes. |
| Keyboard and 360 px | Chromium `cards_keyboard_at_360px` selects the mark with ArrowDown, tabs through forms, saves with Enter, checks safe dialog focus, Escape/return focus, deletion, completion and no horizontal overflow. Responses are mocked; persistence and security are proved separately through PostgreSQL. |
| Source content and absolute time | `test_two_cards_succeed_third_refused` checks the server's mark time/source link. `test_removing_mark_preserves_card_source_and_forms` checks that removing the mark preserves the card. `a card source link starts the media at its saved time (video: %s)` checks audio/video media fragments; invalid-time examples preserve normal playback. |
| Session gates, ownership, CSRF, replay | `test_creation_replay_and_completion`, `test_locked_and_foreign_session`, `test_list_and_delete_isolated_and_paginated`, `test_mark_from_another_session_cannot_be_used`, `test_cards_rls_grants_and_cascade`, `test_card_mutations_require_csrf` (create/delete/complete), and the cross-learner registry suite. All four new routes are registered. The existing access suite checks unauthenticated calls and unchanged foreign rows; global CSRF coverage applies to all new mutation routes. |
| Loading, error and transition behavior | UI tests cover empty marks, unavailable transcript, read retries, preserved forms after refusal, deletion/finish refusals, confirmed skip and Escape cancellation. `save remains blocked while the authoritative count refreshes` covers the post-save request race. |
| Export and account deletion | The full `test_export.py`, `test_account_deletion.py` and access suites exercise a seeded card, data isolation, export inventory and cascade deletion. |

The assertions reject a removed card cap, slot uniqueness or ownership guard:
they check exact status codes, persisted counts, replacement slot identity,
foreign learner reads/deletes and composite-FK rejection rather than mirroring the
allocation calculation. No coverage exclusions or thresholds were changed.

## Actual development evidence

Commands below run in `apps/api` or `apps/web`, with the environment activation
script sourced. Logs are local scratch files, not committed learner-data artifacts.

| Cycle | Red observed before implementation | Green/refactor |
| --- | --- | --- |
| Cards API | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_cards_api.py -q`: **15 failed**, because the Cards routes were missing. Initial dependency-download and stopped-database errors were setup failures and are not red evidence. | Same command: **15 passed** after the minimal API, service, repository and migration. Final Cards API/schema plus export suite: **29 passed**, including supplementary source-preservation and wrong-session-mark examples. |
| Card screen public interface | `pnpm vitest run src/features/cards/CardScreen.test.tsx`: failed to resolve the intentionally missing `CardScreen` public interface. | Corrected the test harness to use the repository's existing Testing Library `fireEvent` (user-event is not installed). Five initial UI cases passed; final expanded Cards suite: **9 passed**. Harness mistakes are not behavior-red evidence. |
| Source-time navigation | `pnpm vitest run src/features/content/ContentPage.test.tsx`: **2 failed, 12 passed**; audio/video sources lacked the requested time fragment. | Cards plus content-player suites: **19 passed** after optional validated `at_ms` navigation. |
| Save/count race | `pnpm vitest run src/features/cards/CardScreen.test.tsx -t 'authoritative count'`: **1 failed**, Save had `aria-disabled="false"` while the post-save count read was held. | Mutation remains pending until invalidation finishes. The same example passes as part of the final nine-test Cards suite and full web run. |

The additional SQL constraint tests and native browser interaction checks were
added after the initial implementation; they are supplementary/characterization
coverage, not claimed as test-first chronology. The SQL tests were also run in an
isolated archive of pre-change `8dd1a67`: the first test failed with
`UndefinedTable: practice.cards`, confirming that the old schema lacks the feature.
The isolated archive was removed afterwards. Generated OpenAPI/types, documentation
and formatting have no executable behavior requiring artificial red tests.

## Verification

- Backend format, Ruff, strict mypy and all six import contracts pass.
- Full required-service coverage command:
  `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest -m 'not performance' --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html`:
  **1,990 passed, one performance test deselected, no skips**, about 11 minutes.
  The final supplementary source/ownership/CSRF Cards API examples also pass in the final focused
  29-test Cards/API schema plus export run. Cards coverage is refreshed with `--cov-append`
  after final formatting/OpenAPI annotation changes; previous Cards entries were
  purged first, preserving the full-suite reports for other modules.
- `uv run pytest -m performance --no-cov`: **1 passed** when run on its own.
  An earlier concurrent run measured **210 ms** against the unchanged **200 ms**
  budget and failed while coverage/browser suites were running. This is local
  regression evidence, not eventual deployment latency evidence.
- An initial neighboring run had **84 passed, one existing export-expiry failure**;
  the complete required-service suite subsequently passed that test as well.
  No export-expiry implementation or assertion was changed.
- Migration: `alembic upgrade head`, `alembic check`, `alembic downgrade -1`,
  upgrade and check again pass. Learner RLS, grants, ownership FK and slot uniqueness
  are separately checked through the restricted API role.
- OpenAPI exported and TypeScript regenerated; all four routes registered.
- Web lint, formatting, types and **523 tests with coverage** pass.
- Production build and size pass: **124.8 kB gzip**, below the **200 kB** budget.
- Coverage completeness checks pass for both applications. Changed executable-line
  coverage is **99% (170/171)** for the API and **97% (86/88)** for the web app,
  above the unchanged 90% gate. The remaining backend gap is the timezone-less
  cursor-refusal branch (other malformed cursors are covered). Web gaps are the
  one-second announcement callback and manual written-form input handler; form
  attributes, prefilling, server boundaries and the native browser form flow are
  covered. Cards API/repository/service have 100% line coverage.
- Final Chromium suite: **41 passed**. Its initial 40/41 run exposed an outdated
  Transcript-to-Card fixture returning `{status: 'ok'}` for the new Cards read;
  supplying the proper empty Cards response fixed the fixture. No Transcript
  implementation or assertion was changed.

## Decisions and handoff

ADR 0057 records the source-time snapshot and slot/completion serialization.
The database design and Cards API resource row were synchronized; the requirement
meaning and audio-snippet scope are unchanged. `SessionPage.tsx` changes only by
one import and the Card-step registration. No review internals, review feature,
Shadow, Blind, grading or AI implementation was changed.

Current main was merged without rebasing. It added the B2 documentation/spike
change and ADR 0056, then a database-documentation alignment, with no new migration; the new cards revision remains chained
after `68_gist_grades`. Required CI and independent fresh-session review remain
pre-merge gates. The owner merges; this task does not merge the PR.

## Review remediation (2026-10-24)

The owner authorized fixes for all three review findings. Current main `757b19d`
(#207, cross-browser Transcript resume coverage) was merged into the story branch
without rebasing. Both sets of Transcript browser tests were preserved. Main
added no migration, so `down_revision` remains `68_gist_grades`.

| Finding | Actual regression red before the fix | Green and resulting behavior |
| --- | --- | --- |
| Mark removed between lookup and insert | From `apps/api`: `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_cards_api.py -k mark_deleted_during -q --tb=short`: **1 failed**, expected 404 but received 500. | The same test passes. It coordinates a real second API DELETE after `review.service.list_marks` returns, then asserts `404 mark_not_found`, no card or analytics event, successful reuse of the same idempotency key and slot, and one card after replay. Only the specific PostgreSQL mark FK failure is translated; the request transaction rolls back. |
| Failed refresh after the second save leaves a third Save enabled | From `apps/web`: `pnpm exec vitest run src/features/cards/CardScreen.test.tsx -t 'failed count refresh'`: **1 failed**, the expected `0 left` was absent. | The same test passes in the **12-test** Cards suite. Confirmed creation updates the cached list and count before refetch, and a failed list read blocks further creation. The assertion rejects an extra POST even after the form is filled again. |
| Deletion restores focus to an element subsequently removed | From `apps/web`: `pnpm exec playwright test e2e/cards.spec.ts -g 'fails: false'`: **1 failed**, main did not receive focus while the post-delete read was held. | `pnpm exec playwright test e2e/cards.spec.ts`: **2 passed**. Confirmed deletion removes the cached row before closing the dialog; its existing focus fallback reaches main. Both browser variants hold the post-delete GET and assert focus before and after release. One variant exhausts the production retries on the earlier post-save GET and still blocks a third POST. |

The PostgreSQL regression uses the restricted API role for both concurrent
requests; the owner connection only inspects the absence of analytics. It does
not replace the insertion or FK rule with a mock. Browser tests still mock the
API and do not establish server persistence or security.

Additional tests added after these fixes are supplementary: an unrelated media
FK failure remains an internal error and rolls back; a lost-response replay keeps
the same submission key and does not consume another cached slot; an uncertain
save stays blocked until the failed list read recovers. Cache writes occur
synchronously inside the existing account-scoped mutation callbacks. No schema,
route, generated contract, review, Shadow, Blind, grading or AI implementation
changed during remediation. An initial incorrectly located pnpm command was a
command/setup failure, not regression-red evidence.

Final remediation verification (supersedes the earlier counts above):

- Backend formatting, Ruff, strict mypy and all six import contracts pass.
- The full required-PostgreSQL/required-S3 coverage command recorded above:
  **1,998 passed**, one performance test deselected, no skips, in 530.82 s.
  This includes migration round trips/drift, access isolation, account deletion
  and export. `uv run pytest -m performance --no-cov -q --tb=short` then ran
  separately with the other suites finished: **1 passed**.
- Web lint, formatting, typecheck and coverage: **526 tests passed**. Production
  build and size pass (**124.8/200 kB gzip**). Full Chromium: **43 passed**,
  including #207's independent-browser resume test and both Card variants.
- OpenAPI export and TypeScript regeneration produce no contract changes.
- Runtime coverage inventories pass. Against current main, changed executable
  lines are **176/177** for the API and **93/95** for the web app. The remediation
  itself has **100%** reported changed-line coverage in both applications. No
  thresholds, exclusions or assertions were weakened.
- Cards service has complete line/branch coverage, including the unrelated-FK
  refusal path. The earlier timezone-less cursor, one-second announcement and
  manual written-input line gaps remain. Web branch coverage is **90.27%** for
  CardScreen and **75%** for Cards hooks; the remaining hooks gap is the defensive
  delete-cache guard when its row/data is already absent. Lost-response key reuse,
  duplicate replay, failed count reads and recovery now have explicit assertions.

Required CI for the pushed revision and fresh review of the fixes remain merge
gates. The owner merges. If main gains a migration before merge, merge it without
rebasing, update `down_revision` and repeat migration/drift validation.
