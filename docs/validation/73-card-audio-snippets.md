# Story #73: Card audio validation

## Scope and decisions

FR-CA-2 and NFR-SEC-2; owner-approved plan, including refusing marked phrases
longer than six seconds. ADR 0063 records timing, private delivery, retries,
cleanup and legacy-card behavior. YouTube intake remains disabled; no card review,
shared-player, gist recovery, reference-profile or Shadow implementation changes.

Prerequisite #72 merged as PR #205 (`fb13202`). The session used the supplied
isolated checkout on `feat/73-card-audio-snippets`, initially from main `2281d73`.
Open PRs were checked: #210 overlapped nearby media UI and conventions, without
changing Cards. It subsequently merged; main `cfc7197` was integrated before broad
checks. Main `5db1333` was integrated before the final web checks; its only further
change is `docs/design/ux-decisions.md`. No migration/generated-file conflict arose. A later open-PR check found ADR 0061
reused by #215, #217 and #218, with #214 using 0062; this story was renamed
to ADR 0063. #214/#218 also touch generated contracts, and #218 adds a migration.
Their unmerged implementation stays outside this PR; current main remains `5db1333`.
Migration `73_card_audio` originally followed `72_cards`; the remediation below
reconciles the chain after #219 merged. API contracts were
regenerated after reconciliation.

## Acceptance criteria and boundaries

| Criterion | Named evidence |
| --- | --- |
| New card receives a playable snippet covering its phrase | `test_creation_snapshots_span_and_queues_once`, `test_window_contains_phrase`, `test_aac_survives_source_expiry_and_mark_deletion`, `test_intake_worker_makes_new_card_playable` |
| 3–6 s AAC; complete phrase and clip boundaries | `test_window_contains_phrase`, `test_invalid_or_long_phrase`, `test_long_phrase_refused_without_consuming_slot`; ffprobe confirms AAC/duration; decoded zero-crossing frequencies distinguish the marked 11–13 s interval from surrounding context |
| Private ownership-checked delivery | `test_audio_ownership_precedes_readiness`, `test_retry_checks_owner_before_state`, `test_real_s3_snippet_delivery_and_cleanup`; new routes registered in cross-learner access registry; CSRF parameter added to existing Card mutation tests |
| Survives playback expiry | `test_aac_survives_source_expiry_and_mark_deletion`: delete actual source bytes, expire synthetic YouTube metadata and remove the mark; snippet bytes and owner redirect remain available. Real S3 test removes source bytes and still downloads snippet |
| Storage failure, redelivery and terminal state | `test_upload_failure_retries_same_key`, `test_storage_write_then_crash_retries_one_object`, `test_expired_source_is_permanent_and_retry_is_owned`, `test_unusable_bytes_fail_and_remove_scratch` |
| Deletion, cascades and retryable cleanup | `test_delete_cleanup_retries_and_cannot_resurrect`, `test_deletion_during_encoding_never_writes_object`, `test_cascade_keeps_cleanup_record`; account-deletion integration suite |
| Disabled account / restoration | `test_disabled_account_finishes_failed_without_upload`, before generation and during encoding; failed state can be retried after restoration |
| Migration and ownership constraints | Existing `test_upgrade_downgrade_one_and_upgrade_again` includes drift check; full downgrade; linear history; restricted API-role Cards schema and cross-learner tests |
| Export privacy and durability | `test_export_omits_storage_keys_and_includes_uploaded_snippet`; whole export integration suite covers table inventory and isolation; YouTube-derived snippet files excluded |
| Accessible existing Card UI | `CardScreen.test.tsx`: play/error, focusable pending reason, refused retry, lost retry response, unmount pause, polling/readiness announcement. Cards Playwright tests exercise real browser audio and Enter/Space focus at 360 px against a mocked API |

The deterministic audio fixture uses 880 Hz during the marked interval and 220 Hz
outside it. The test checks decoded context and three points across the marked
interval; a plausible wrong seek to zero fails even if duration and codec match.
Ownership assertions require 404 and no Location for a foreign learner. Retry
assertions require one object after upload-then-error and successful redelivery;
deletion assertions reject orphan recreation and premature tombstone removal.

## Actual red/green record

Commands run from `apps/api` or `apps/web` as appropriate. Focused red logs were
kept locally under ignored `work/`; failures were not committed as broken states.

| Cycle | Actual Red | Green / subsequent evidence |
| --- | --- | --- |
| Window | `uv run pytest tests/unit/test_card_snippet.py -q`: missing `cards.domain.snippet` interface | Same command: **9 passed** |
| Creation, ownership, generation/storage/deletion | `uv run pytest tests/integration/test_card_audio.py -q`: missing `audio_status`, absent ownership-aware audio route, missing `cards.jobs` interface | Final focused command below: **27 passed**, including real S3 and AAC cases |
| Long phrase | Corrected fixture then `uv run pytest tests/integration/test_card_audio.py::test_long_phrase_refused_without_consuming_slot -q`: card creation returned 201 instead of 422 | Passes in final focused run; slot remains unused |
| Expired source | `uv run pytest tests/integration/test_card_audio.py::test_expired_source_is_permanent_and_retry_is_owned -q`: raised `ProblemError` instead of permanent job failure | Passes in final focused run |
| Export | `uv run pytest tests/integration/test_card_audio.py::test_export_omits_storage_keys_and_includes_uploaded_snippet -q`: no snippet file in export | Passes in final focused run; uploaded audio included, keys/YouTube files omitted |
| UI play/pending/retry | `pnpm vitest run src/features/cards/CardScreen.test.tsx -t audio`: **3 failed**, missing accessible controls | Focused Cards/event tests: **20 passed**, then **22 passed** after subsequent cases |
| Events | `pnpm vitest run src/app/eventKeys.test.ts -t 'card audio'`: expected Cards invalidation keys, got empty list | Included in 20/22 passing tests |
| Unmount | `pnpm vitest run src/features/cards/CardScreen.test.tsx -t 'removing the card screen'`: pause not called | Same focused test: **1 passed** |
| Lost retry response | `pnpm vitest run src/features/cards/CardScreen.test.tsx -t 'lost retry'`: pending state not reloaded | Included in **22 passing** focused tests |
| Ready announcement | `pnpm vitest run src/features/cards/CardScreen.test.tsx -t 'pending audio polls'`: readiness text absent after polling | Final serial web suite recorded below |

Supplementary evidence is distinguished from test-first work:

- The retry endpoint, some job branches, cascade/crash checks and browser extension
  received supplementary tests after their initial implementation. The retry
  contract was copied into a scratch archive of pre-story main: **1 failed**
  (owner received 404 instead of 409); it passes on the implemented route. This
  archive is not a Git worktree or a second working branch.
- Disabled-account regression setup initially violated the users table's deletion
  date constraint; those failures are **not** behavior-red evidence. After fixing
  the fixture, a scratch archive with the previous early-return behavior produced
  **2 failures: DID NOT RAISE PermanentError**. The final implementation passes both
  cases. The fix had been written before a valid red was observed; this is disclosed
  rather than claimed as a clean test-first cycle.
- An early long-phrase test used the wrong transcript column; its SQL error was
  excluded from Red. Synthetic YouTube metadata also initially kept an uploader,
  violating the source constraint; corrected before claiming expiry evidence.
- The existing unrelated-FK regression now injects a missing media ID at the insert
  boundary, because creation now reads authorized transcript data before insertion.
  It retains assertions for internal failure, rollback and a later successful save.

## Completed checks

- `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest tests/integration/test_card_audio.py tests/integration/test_cards_schema.py tests/integration/test_migrations.py tests/integration/test_export.py tests/integration/test_account_deletion.py -q`: **80 passed**.
- `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest tests/integration/test_card_audio.py tests/integration/test_card_retry_contract.py tests/unit/test_card_snippet.py -q`: **27 passed**, including the final disabled-account and tone-position checks.
- A real Procrastinate intake worker generated and exposed the new card in **2.336 s** locally. This includes queue drain and AAC generation, without model loading or staging contention. It is **not staging performance evidence**.
- Backend Ruff formatting/lint, strict mypy and all **6 import contracts** passed.
- OpenAPI export and `pnpm api:generate` completed. Final web typecheck, lint and formatting pass locally; full web build/size and suite checks pass in CI as detailed below.
- Initial JavaScript: **125.6/200 kB gzip**.
- Branch-name validation and `git diff --check` pass.

## Broad checks, coverage and follow-up

[CI run 636](https://github.com/abubakar1010/ListenUp/actions/runs/40208496763)
validated implementation head `f9a764f`:

- Backend: **2,104 passed, 1 failed, 1 performance test deselected**, with
  PostgreSQL/S3 required. The sole failure was the exact scheduled-job inventory
  still expecting three jobs after adding card cleanup. Local reproduction:
  `uv run pytest tests/unit/test_worker_modules.py -q`: **1 failed, 3 passed**.
  The inventory now explicitly checks the fourth job, its cron and background-only
  pool, plus intake registration for generation. The same command: **4 passed**.
- All migration upgrade/downgrade/upgrade/drift, lint/types/import checks passed.
  Web checks: **58 files, 615 tests passed**, lint/format/types/build/size passed.
  API regeneration, dependency audits, all four Docker images, real media sandbox
  and scanner, branch naming and observability checks passed. Synthetic AI smoke
  was correctly skipped by its path filter.
- Browser CI reported **53 passed, 1 flaky**: the failing count-refresh Cards case
  passed its configured retry. This is not accepted as clean browser evidence.
  The test could see the stale Save label immediately after Enter, before the
  mutation entered its busy state; the count then changed while refetch/retries
  were still pending. It now waits for the observable form busy state to finish
  **after** the confirmed count update, retaining the limit/focus assertions.
  `pnpm exec playwright test e2e/cards.spec.ts --workers=1 --retries=0`:
  **2 passed**. No blanket timeout or retry policy was changed.
- `uv run pytest -m performance --no-cov`: **1 passed, 2,105 deselected** locally.
- Three supplementary playback-state tests cover pause/end, rejected play and
  duplicate busy presses, and legacy unavailable audio. Final Cards/event command
  `pnpm vitest run src/features/cards/CardScreen.test.tsx src/app/eventKeys.test.ts
  --maxWorkers=1`: **26 passed**. These are characterization/coverage additions,
  not claimed as new test-first behavior.
- CI's initial web report exposed **83%** changed-line coverage (six missing lines).
  The added interaction tests cover those branches. Final targeted coverage and
  the completeness inventory: **37/37 changed web lines, 100%**. This targeted
  report is not a whole-application coverage baseline; full web evidence is CI's
  separate suite. No production exclusions or thresholds changed.
- Full CI backend artifact independently passed the completeness inventory and
  `diff-cover`: **146/150 changed lines, 97%**. The four uncovered lines are local
  ffmpeg cancellation cleanup and defensive unexpected-error/missing-span handling.
  Platform process-supervisor/sandbox checks separately pass; a Cards-specific
  cancellation assertion and those impossible-through-create DB states remain
  untested. All user-facing state, ownership, storage and deletion paths are covered.

The final CI run and exact latest-head status are recorded in
[PR #212](https://github.com/abubakar1010/ListenUp/pull/212). The inventory correction,
three web characterization cases and browser synchronization change do not alter
production behavior; the rerun validates the combined final test tree.

Earlier overlapping broad local runs on this two-CPU environment caused unrelated
Testing Library/Playwright timeouts. Web coverage and browser runs were interrupted;
a later one-worker web run and full local backend coverage run were also stopped
once equivalent complete CI runs were available. **None is reported as passing or
used as a whole-application coverage baseline.** CI supplies the full-suite evidence;
local required-service integration and focused runs supply the detailed boundary
checks. Docker image, audit and scanner checks ran in CI rather than locally.

Required CI and fresh-session independent review remain merge gates. No merge is
authorized. Actual-host latency remains unverified under the repository's staging
and pre-launch validation policy (#155). Existing cards have no backfill, and
expired/missing playback cannot produce a new snippet until source media exists.
Documentation/generated output, the scheduler inventory update and synchronization
of an existing browser assertion have no artificial TDD requirement.

## Independent review remediation, 2026-10-26

The independent review of `3a0ade5` against `2764892` found three confirmed lifecycle
defects: DB connection loss could let cleanup pass an upload, permanent refusals
bypassed the terminal callback, and a retry could be swallowed by a retiring job.
The owner requested posting the review and fixing all findings in this PR. The
[posted review](https://github.com/abubakar1010/ListenUp/pull/212#pullrequestreview-5650356972)
retains the original findings and review evidence.

| Fix | Actual Red before production change | Green / assertion evidence |
| --- | --- | --- |
| Terminal callback | `uv run pytest tests/unit/test_media_sandbox.py -k permanent_refusal -q --tb=short`: **2 failed**, callback awaited zero times. `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_card_audio.py -k 'expired_source_is or disabled_account or unusable_bytes' -q --tb=short`: **5 failed**, cards stayed pending. | Media sandbox/child and audio suites: **52 passed**. Failure tests now use `run_handler` and no manually invoked callback. A subsequent real sandboxed Procrastinate worker test asserts queue failure, persisted failed card and the committed `card.audio_updated` notification. |
| Retiring job / stale callback | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_card_audio.py -k 'old_job_is_settling or old_failure_callback' -q --tb=short`: **2 failed**, no waiting job and the newer cycle became failed. | Audio/retry suites: **20 passed**. The retiring-job regression also drains the newly queued cycle and requires a playable redirect. A supplementary queue-error assertion verifies retry transaction rollback. |
| Lost DB connection / purge | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_card_audio.py -k 'database_loss_during or purge_waits_for_snippet' -q --tb=short`: **2 failed**, cleanup had zero tombstones and purge did not wait. | A real PostgreSQL connection is terminated during a controlled upload. Cleanup must retain its tombstone, purge must postpone with the user intact, and both must finish after the writer settles. **28 passed** in the initial write/cancellation/audio/migration run. |
| Cancellation / uncertain S3 outcome | `uv run pytest tests/unit/test_card_write_cancellation.py -q --tb=short`: **3 failed**, missing cancellation helper and uncertain-write interface. | Cancellation is drained despite repeated cancel requests, and the S3 boundary classifies a failed response as uncertain. These tests are included in the passing focused lifecycle run below. |

Fixture mistakes are excluded from behavioral Red: the first purge fixture expected
200 instead of 202 and then violated the deletion-date constraint. A DB rollback
also masked an assertion raised inside the lost transaction; those observations
were moved outside that transaction before recording the two valid race failures.
A misplaced tail of an existing test was restored before the retry Green run.
Uncertainty/age, RLS/export, downgrade refusal, retry rollback and actual-sandbox
notification assertions are supplementary coverage of the fixes, not claimed as
separate clean test-first cycles.

Generation UUIDs fence old callbacks; a retry has a fresh queue key and the shared
card execution lock. A separately committed writer registration survives lost
locks and killed processes. Cleanup and a registered identity purge guard wait for
it; an additional RESTRICT FK protects account deletion. Uploads drain cancellation,
uncertain writes retain their registrations, and downgrade refuses a nonempty
registry. See ADR 0063 and the [reconciliation runbook](../runbooks/card-snippet-writers.md).
No registration is discarded by age or queue status. Export omits worker/token and
generation details. The architecture storage path and retry endpoint inventory are
also corrected. No shared-player or out-of-scope feature behavior was added.

Completed local remediation checks before current-main reconciliation:

- Audio/retry/Card API/schema/migration and cancellation/sandbox focus: **93 passed**.
- Audio/account-deletion/export/jobs/storage and architecture suites: **109 passed**,
  including the real sandbox failure and notification case.
- Ruff check and format, strict mypy, and all **6 import contracts** pass.
  A direct identity-to-Cards import initially broke a boundary contract; registration
  through `identity.service.on_account_purge` removed that dependency.
- Uninstrumented performance: **1 passed, 2,117 deselected**.
- OpenAPI export and `pnpm api:generate` reproduce the committed contracts with no
  semantic or generated-file delta.

An initial full local coverage run was stopped when main advanced to `076c6b6`
(#219, reference profiles). It is not a passing full-suite/coverage result. The
combined migration chain and event/API contracts must be revalidated against that
main; final CI and changed coverage remain required. The original four uncovered
defensive lines and actual-host latency limits above are not waived. The fixes need
fresh independent re-review; this remediation session is not its own independent
review. No merge is authorized.

Current-main reconciliation integrates `076c6b65d8bdd76d4581b19311cac8098cba2db4`
(#219) without changing its profile implementation. `73_card_audio` now follows
`76_reference_profiles`, then `73_audio_lifecycle`; the Cards and profile event-key
tests are both preserved. Combined OpenAPI/TypeScript contracts were regenerated.
Post-reconciliation Ruff check/format, strict mypy, all six import contracts and
the focused Cards/event/live-events UI checks (**37 passed**) pass. The affected
backend suites (**171 passed**, PostgreSQL/S3 required), web types/format and
regenerated contracts pass. Final CI/coverage results are recorded in the PR
follow-up. The interrupted old-tree full run is not used as passing evidence;
its partial output included a setup error and was not allowed to establish final
suite or coverage claims.

Coverage follow-up: the post-integration focused backend command (audio/retry/Card
API/migrations/account-deletion/export/jobs, cancellation and sandbox tests) passed
**164 tests**. Its report resolves every runtime source through the coverage
inventory and initially covered **248/258 changed executable lines (96%)** against
`076c6b6`. Inspection identified the second active-account check and the helper's
self-cancelled-operation branch. Two supplementary tests now exercise those
boundaries: **2 passed**; they are characterization/coverage additions, not new
test-first production changes. The combined focused report covers **253/258 changed
lines (98%)**; it is not a whole-application coverage baseline. Remaining lines are
the original ffmpeg cancellation kill/wait, unexpected source error and missing
span defenses, plus the redundant active-account defense under an already held
active-account lock. No threshold or exclusion changed. Final CI still supplies
the complete suite and coverage gate.

CI run 669 on `fa72949` found a regression in the first terminal-failure fix:
**2 failed, 2,157 passed, 1 skipped, 1 performance deselected**. The existing
`test_provider_failures_never_publish_ready[missing_audio/invalid_times]` assertions
received two `transcript.failed` notifications instead of one. Local reproduction:
`LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_passage_transcription.py
-k provider_failures_never_publish_ready -q --tb=short`: **2 failed, 1 passed**.
This is not dismissed as unrelated: changing shared `run_handler` caused it.

The shared runner change was reverted. Cards now follows the established
transcription pattern: its own registered job wrapper settles permanent errors
before raising them (including before sandbox exit 65). Shared transcription and
reference-profile implementations are unchanged. The two wrapper unit cases now
assert Cards settles exactly once in direct and isolated dispatch; all five
persisted Cards failure cases and the actual sandbox notification test remain.
The transcription assertion is unchanged. Final focused/CI results for this
correction are recorded in the PR; previous coverage numbers describe the earlier
tree and do not substitute for the corrected head's required coverage gate.

The corrected combined transcription/Card/worker suite passes **103 tests** with
PostgreSQL/S3 required and coverage enabled. Running transcription first also
exposed an existing Cards long-phrase fixture that updated every transcript cache
row; it now updates only its own clip. The first reordered run's fixture constraint
failure (**1 failed, 102 passed**) is disclosed and is not a production-regression
claim. The same reordered suite is now green, with its refusal/slot assertions
unchanged. Shared-runner production code is restored exactly to current main.
