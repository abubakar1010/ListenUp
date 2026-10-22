# Story #67 validation

## Scope and setup

Branch: `feat/67-passage-key-points`, based on main `1a09aee` after PR #173
merged. Dependencies #45/#66 are closed and `text_tasks.run_task` is available.
PR #171 was open at implementation start, so the initial migration followed
`104_consents`. It merged before this story: the branch is now synced with main
`57ff878` and migration `67_key_points` follows **`58_marks`**.

Claude Code is unavailable in this environment; implementation used Codex under
the shared repository rules after the owner approved the plan. PostgreSQL 16,
SeaweedFS and Mailpit run through the saved local Compose setup. Backend commands
run from `apps/api` using the existing virtualenv, `UV_CACHE_DIR=/tmp/listenup-uv`
and `uv run --no-sync`. PostgreSQL client tools are from
`/workspace/listenup-tools/postgresql16/bin`.

## Acceptance criteria and test-first evidence

| Criterion / requirement | Named tests | Actual Red | Green/refactor |
| --- | --- | --- | --- |
| AC1: persist 3–6 points, exactly one main first; NFR-AI-4/5 provenance and version | `test_key_points.py::test_stores_valid_key_points_with_provenance`, `test_database_rejects_invalid_points`, `test_database_requires_result_provenance`, `test_one_cache_entry_per_passage_and_version`; `test_key_point_jobs.py::test_stores_the_valid_point_count_boundaries`, `test_rejects_invalid_points_and_retries` | `pytest tests/integration/test_key_points.py -q`: 20 failed (`UndefinedTable grading.key_points`) before migration/model | Same schema file: 20 passed. First job/schema run after implementing missing jobs: 3 failed / 28 passed; after correcting test setup, 31 passed. |
| AC2: two learners share one AI call, later reuse, retry idempotency | `test_two_learners_share_one_ai_call`, `test_retry_after_commit_does_not_call_ai_again` | `pytest tests/integration/test_key_point_jobs.py -q --tb=short`: collection ImportError for the deliberately missing `grading.jobs` interface before implementation | 31 passed in combined job/schema run. Shared producer deduplication, real queue execution lock (one doing, one todo during blocked inference), one call and one stored row asserted. |
| AC3 functional prefetch while Blind is open | `test_transcript_ready_enqueues_extraction_before_blind_submission` | Same missing jobs interface above | Real transcription job with already-cached transcript queues extraction on `ai`; result is committed while the session is still at Blind. |
| Active prompt version selects a distinct cache entry | `test_prompt_version_selects_a_distinct_cache_entry` | Expanded job file: 2 failed / 16 passed; this test observed one call instead of two after a prompt bump | Align cache-version lookup with the prompt-files root used by the task helper; focused+neighboring suite below passes. Production prompt files are unchanged. |
| Empty transcript must not invent a reference | `test_an_empty_transcript_never_calls_ai` | Same run: one AI call instead of zero | Permanent refusal before inference; focused+neighboring suite below passes. |
| Worker reference isolation, rollback, deletion and exhaustion | `test_ready_hook_checks_ownership_and_rolls_back_its_job`, `test_extraction_uses_only_original_words_in_the_selected_span`, `test_deleted_media_is_not_resurrected_after_ai`, `test_deleted_media_before_execution_never_calls_ai`, `test_missing_transcript_retries_without_calling_ai`, `test_retry_exhaustion_keeps_blind_open_and_stores_no_partial_points`; schema API denial/cascade/span tests | Ownership/rollback and deletion included in initial missing-interface Red; additional boundary/exhaustion cases passed immediately as characterization of the implemented mechanisms | `pytest tests/integration/test_key_point_jobs.py tests/integration/test_key_points.py tests/integration/test_migrations.py tests/integration/test_passage_transcription.py tests/architecture -q --tb=short`: **67 passed**. |

The first schema green attempt hung during fixture teardown: an unrolled-back
cache insertion held a media foreign-key lock while the learner fixture tried to
delete that media. The fixture now rolls back first. The first job green attempt
had three test setup failures: `wait=False` workers needed another drain after a
locked copy; `pytest.raises` was used as an async context manager; media deletion
needed content items removed first. These were corrected without weakening the
assertions. They are not counted as behavior Red evidence.

Green refactor: moved the media-liveness query into
`content.service.media_exists_for_worker` to keep Transcript out of Content's
tables. The 38 key-point tests passed afterward. This preserves existing behavior
and does not require an artificial new failing test.

Targeted mutations ran against a temporary copied source tree, without changing
the working source. Removing the job lock made
`test_two_learners_share_one_ai_call` fail with two jobs `doing` instead of one
`doing` and one `todo`. Removing the explicit session-owner check alone survived
because `content.get_content` independently rejects the wrong learner. Removing
both ownership protections made
`test_ready_hook_checks_ownership_and_rolls_back_its_job` fail (`DID NOT RAISE`).
The original assertions were retained and the temporary copies restored.

## Final verification

- Format, Ruff, strict mypy (167 files), import-linter (6 contracts): passed.
- `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run --no-sync pytest -m
  'not performance' --cov --cov-report=term-missing:skip-covered --cov-report=xml
  --cov-report=html --tb=short`: **1,707 passed**, one performance test deselected,
  **97% overall coverage**, no skipped tests (386.09 s). This run began before the
  small media-liveness boundary refactor described above.
- Post-refactor key-point tests with `--cov --cov-append` and the same three report
  formats: **38 passed**. Added two characterization cases during coverage review,
  `test_unrelated_integrity_error_is_retried` (an actual primary-key collision must
  retry rather than be swallowed as media deletion) and
  `test_invalid_job_bounds_are_permanent_without_an_ai_call`; final focused run:
  **40 passed** (13.66 s). Both existing behaviors passed immediately, so these are
  additional failure/boundary validation, not new Red claims.
- Coverage report completeness check: passed. Changed executable-line coverage:
  **100% of 83 lines**. Reviewed branches include malformed bounds, non-media
  integrity errors, missing transcripts/media, AI rejection/exhaustion, ownership
  denial and cache hit/miss. No coverage exclusions or thresholds changed.
- `pytest -m performance --no-cov -q --tb=short`: **1 passed** (uninstrumented).
- `alembic heads`: one head, `67_key_points`; `upgrade head`, `check` (no drift),
  `downgrade -1` to `104_consents` and `upgrade head` again: passed. Integration
  migration tests also passed, including full downgrade, and backup restore tests
  passed in the full suite. PR #171 was still open at that initial commit; the
  post-sync migration verification below supersedes that migration parent.
- No API routes/OpenAPI contract or web code changed; generated client and web
  checks are not applicable. No excluded review/admin area was changed.
- Existing extraction prompt/schema, manifest, adapters and provider acceptance
  settings are unchanged. Tests replay deterministic replies through the real
  adapter and gateway. They prove validation, provenance and caller behavior,
  not model quality; ADR 0046's real-provider/golden-set acceptance gate remains.

## Actual-server readiness: deferred until staging — unverified

AC3's unchanged target is key points ready **before a typical three-minute Blind
attempt ends** (issue #67; System Design 7.1). Only its actual-server latency
measurement is deferred under `docs/workflow.md` and ADR 0039 to the mandatory
pre-launch gate [#155](https://github.com/abubakar1010/ListenUp/issues/155).
The functional enqueue/prefetch, validation, sharing, retry, security and migration
requirements are not deferred.

On the stage-0 release candidate, record the host/resources, release commit,
workload/concurrency, selected passage duration, cache state, real accepted
provider/model/prompt/deployment versions, transcription completion, AI queue
delay, key-point commit time and Blind end time. Exercise cold and warm passage
paths and the shared-passage case with actual adapters. The measurements must
demonstrate the reference is committed before the three-minute attempt ends;
fake HTTP replies and development-runner timings cannot establish this target.
Missing or failed evidence blocks launch. No actual-server result is claimed here.

## Main sync and merge authorization

The owner explicitly authorized merging and confirmed that independent review
had already been completed in this conversation. The branch merged current main
`57ff878` without rewriting history. Excluded review/admin paths have no story
diff against current main. ADR 0052 replaces this story's original ADR number
0051 because main now owns ADR 0051 for versioned legal texts.

After the sync, `test_history_is_linear` failed as expected: two heads,
`58_marks` and `67_key_points`. Rechaining the story migration to `58_marks`
made the migration/key-point/architecture selection green: **48 passed**.
On a fresh scratch database, `alembic heads` reports only `67_key_points`;
upgrade, drift check, downgrade to `58_marks` and upgrade again all pass.
Ruff lint/format (338 files), strict mypy (170 files), all six import contracts
and the uninstrumented performance test also pass after the sync.

Current main's Text AI convention also requires the helper's `trimmed` fields to
be recorded with the result. Added
`test_records_reference_trimming_with_the_cached_result` for both shortened and
unchanged reference inputs. Actual Red: the focused test command failed twice
with `KeyError: 'trimmed_fields'`; the first fixture budget did not actually
trigger trimming and was corrected before counting Red. Minimal implementation
stores the returned field names in `provider_info.trimmed_fields`. Green: the
key-point/migration/architecture selection passed **50 tests**. Ruff and strict
mypy also pass. The final full required-service run was restarted for this final
code; the interrupted pre-metadata run is not claimed as a passing check.

The full post-sync required-service suite and final CI outcomes are recorded on
[PR #184](https://github.com/abubakar1010/ListenUp/pull/184). Merge requires passing
CI; the actual-server latency deferral above remains unchanged.
