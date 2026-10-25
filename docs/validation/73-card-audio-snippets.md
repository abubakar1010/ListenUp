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
Migration `73_card_audio` follows the current `72_cards` head. API contracts were
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
