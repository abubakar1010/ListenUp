# Story #73: Card audio validation

## Scope and decisions

FR-CA-2 and NFR-SEC-2; owner-approved plan, including refusing marked phrases
longer than six seconds. ADR 0061 records timing, private delivery, retries,
cleanup and legacy-card behavior. YouTube intake remains disabled; no card review,
shared-player, gist recovery, reference-profile or Shadow implementation changes.

Prerequisite #72 merged as PR #205 (`fb13202`). The session used the supplied
isolated checkout on `feat/73-card-audio-snippets`, initially from main `2281d73`.
Open PRs were checked: #210 overlapped nearby media UI and conventions, without
changing Cards. It subsequently merged; main `cfc7197` was integrated before broad
checks. Main `5db1333` was integrated before the final web checks; its only further
change is `docs/design/ux-decisions.md`. No migration/generated-file conflict arose.
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
- OpenAPI export and `pnpm api:generate` completed. Web typecheck, lint, format, build and size passed before the final readiness announcement; affected final checks are being repeated.
- Initial JavaScript: **125.6/200 kB gzip**.
- Branch-name validation and `git diff --check` pass.

## Checks still running at draft PR creation

- Complete required-service backend coverage suite and separate uninstrumented
  performance test; coverage inventory and changed-line gate.
- Final serial web lint/format/types/coverage, build/size and full Chromium suite.
- CI image builds, sandbox contract, audits and remaining repository CI checks.

Earlier overlapping broad runs on this two-CPU environment caused unrelated
Testing Library/Playwright timeouts. The web coverage and browser runs were
interrupted; **they are not passing results**. Final web coverage uses one worker,
then browser checks run separately. No assertions, production exclusions or
coverage thresholds were relaxed.

Required CI and fresh-session independent review remain merge gates. No merge is
authorized. Actual-host latency remains unverified under the repository's staging
and pre-launch validation policy (#155). Existing cards have no backfill, and
expired/missing playback cannot produce a new snippet until source media exists.
Documentation and generated output have no artificial TDD requirement.
