# Story #45 validation

Branch: `feat/45-passage-transcription`, based on main `598eccad861e00e28baa0faf16d6902e9057631d`.
Dependencies #42 and #43 were merged in PR #126 (merge `035d6ea4158ee8bdbe857cd033a06a44d5d03374`), which is an ancestor of this base. Their issue statuses are not blockers.

## Acceptance criteria

| Criterion | Named tests | Result / limit |
| --- | --- | --- |
| AT-1 / FR-TX-1: a selected three-minute passage reaches transcribed with word timings | `test_selection_queues_intake_transactionally`, `test_passage_reaches_transcribed_and_provenance_round_trip`, `test_three_minute_passage_real_storage_decode_and_configured_gateway`, `test_absolute_word_offsets_and_sentence_boundaries`, `test_padding_clamped` | Functional path tested with real PostgreSQL, S3 and ffmpeg; deterministic provider boundaries. |
| AT-1 timing: p95 under two minutes after playable on stage 0 | Functional tests above do **not** establish this criterion. The planned `test_stage0_transcription_p95` was not added or run without a stage-0 target and real-model corpus. | **Unverified; blocks completion of the story.** No container timings are presented as stage-0 evidence. |
| Learner B processes only uncovered audio | `test_second_learner_reuses_shared_media_only`, `test_overlap_processes_only_gaps`, `test_overlap_reuses_cache_and_retry_keeps_completed_spans`, `test_retry_resumes_after_partial_success_within_one_job` | Shared-media fixture proves reuse across learners; upload fingerprints remain learner-scoped. |
| FR-TX-3 / NFR-AI-5: origin, provider, model and version retained | `test_passage_reaches_transcribed_and_provenance_round_trip`, `test_absolute_word_offsets_and_sentence_boundaries`, `test_three_minute_passage_real_storage_decode_and_configured_gateway` | Exact stored values and provider configuration asserted. |
| Exclusion constraint, including concurrency | `test_exclusion_rejects_overlap`, `test_concurrent_database_writers_cannot_overlap`, `test_concurrent_requests_reuse_spans`, `test_cache_span_must_be_finite_nonempty_and_nonnegative` | PostgreSQL constraint tested separately from worker serialization. |
| Access isolation and step gating / FR-TX-5 | `test_reads_enforce_learner_isolation_and_step_gate`, `test_api_cannot_read_shared_transcripts`, `test_second_learner_reuses_shared_media_only`, `test_deleted_session_and_wrong_job_owner_never_call_provider`, `test_privileged_caller_still_cannot_read_another_learner` | Restricted API-role reads deny another learner and locked steps before worker-role access. Real storage test runs the job with `SET ROLE listenup_worker`. |
| Retry and failure handling | `test_exhausted_provider_failure_is_reported_and_retry_recovers`, `test_provider_failures_never_publish_ready`, `test_recovered_failure_does_not_mark_unprocessed_gap_failed`, `test_silence_is_valid_cached_coverage`, `test_invalid_provider_timings_rejected`, `test_decode_failure_is_permanent_and_cleans_process` | Transient/gateway failure, missing storage, malformed timing, silence and permanent decode failure covered. |
| Commit ordering and interruption | `test_ready_event_after_commit_and_rollback_suppresses_notification`, `test_cancelled_worker_releases_lock_and_cleans_scratch`, `test_deleted_account_during_provider_call_discards_result` | Committed rows visible before readiness; rolled-back notifications absent; cancellation and deactivation checked. |

## Actual red/green chronology

Commands below ran from the repository root. `DB=1` abbreviates the environment prefix `LISTENUP_REQUIRE_DB=1`, not a test setting of its own.

| Cycle | Focused command | Observed Red | Observed Green |
| --- | --- | --- | --- |
| Padding and gaps | `uv run --directory apps/api pytest tests/unit/test_transcript_spans.py -q` | Collection failed on missing `transcript.domain.spans` interface. | 9 passed. |
| Cache schema and direct grants | `DB=1 uv run --directory apps/api pytest tests/integration/test_transcript_schema.py -q` | 2 failed: `UndefinedTable` for `content.passage_transcripts`. | 2 passed after migration/model. |
| Packing | `uv run --directory apps/api pytest tests/unit/test_transcript_packing.py -q` | Collection failed on missing `transcript.packing` interface. | Packing plus span tests: 12 passed. |
| Selection/job/read service | `DB=1 uv run --directory apps/api pytest tests/integration/test_passage_transcription.py -q` | 2 failed and 2 errors: no queued job; missing job/service interfaces. | 4 passed. |
| Concurrency and exhausted retries | Same file, `-k 'concurrent or exhausted' -q` | 2 failed: concurrent call timed out instead of rescheduling; failure read returned `transcript_not_ready` instead of `transcript_failed`. | 6 tests passed after implementation. An intermediate import typo was corrected; it is not behavioral Red evidence. |
| Finite ranges | `DB=1 uv run --directory apps/api pytest tests/integration/test_transcript_schema.py -q` | 2 failed: PostgreSQL accepted `[0,)` and `(,100)`. | Schema and job suites: 16 passed. |
| Stale failure markers | Job suite, `-k recovered_failure -q` | Returned `transcript_failed` for a new uncovered gap after the old failed span recovered. | 1 passed after checking failures only within current gaps. |

**TDD deviation:** direct tests for notification commit ordering, scratch cleanup and the post-inference account guard were added after those paths were implemented. They are not claimed as test-first work. Following `docs/testing.md`, isolated copies of the source under `work/45-mutation/src` were tested with `PYTHONPATH` pointing at the copy:

- Removing readiness publication made `test_ready_event_after_commit_and_rollback_suppresses_notification` fail (its injected notification abort was never reached).
- Removing automatic scratch cleanup made `test_cancelled_worker_releases_lock_and_cleans_scratch` fail because the scratch directory remained.
- Removing the post-inference account check made `test_deleted_account_during_provider_call_discards_result` fail with one cached row instead of zero.

All mutations stayed outside the working source. Supplemental real-storage, multi-learner, direct database concurrency, job-owner and partial-retry tests were added as characterization/validation of existing implementation; passing them is not retroactive Red evidence. Schema-generation and documentation changes have no executable behavior requiring artificial Red.

## Stage-0 gap

Checked issue #16, issue #112, ADR 0034, the B1 report, deployment runbooks, and the managed environment's configured access. The issues remain open, the documents say the stage-0 server is not provisioned/deployed, and this environment has no configured host/credentials/VPN for it. No reachable target was available to test; no deployment is inferred from local Docker services.

When stage 0 is available, run the real configured `small.en` adapter with warmed media workers against the B1 three-minute corpus, selecting passages immediately after playable. Record host/CPU/thread/model settings, playable timestamps, queue start/wait and committed readiness timestamps, sample count and p95. Include cache misses and normal competing worker load. The acceptance threshold is p95 <120 seconds from playable; provider-only or container benchmarks do not satisfy it. Independent review and required CI are also prerequisites to merge.

## Final checks

Results are recorded in the PR after the complete checks finish. Local commands use PostgreSQL 16 and SeaweedFS. The first full coverage attempt had 1050 passes and seven setup errors because `pg_dump`/`pg_restore` were missing after the environment restart; those tools were supplied from the existing PostgreSQL 16 image, and all seven backup tests then passed. That incomplete run is not claimed as the final successful run.


Final local results (2026-10-16):

- `uv run ruff format --check .`: 252 files formatted; `uv run ruff check .`: passed.
- `uv run mypy`: passed, 134 source files; `uv run lint-imports`: all six contracts kept.
- `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest -m 'not performance' --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html`: **1059 passed**, one performance test deselected, one existing Starlette deprecation warning. PostgreSQL 16 client tools were added to PATH for backup checks.
- Supplemental focused suite with `--cov --cov-append`: **41 passed**; subsequent explicit privileged-caller denial and concurrent-job check: **2 passed**. These include tests added after the full-suite collection; production code was unchanged.
- `uv run pytest -m performance --no-cov`: **1 passed** (existing scoring budget; not transcription or stage 0).
- `uv run python ../../.github/scripts/check-coverage.py api coverage/coverage.xml`: every runtime source resolves. `uv run diff-cover coverage/coverage.xml --compare-branch origin/main --fail-under=90`: **96%**, 279/289 changed executable lines covered.
- `uv run alembic upgrade head`, `uv run alembic check`, `uv run alembic downgrade -1`, `uv run alembic upgrade head`: passed; no drift detected.
- `uv run python scripts/export_openapi.py` and `pnpm api:generate`: passed, no generated-file differences. The initial pnpm invocation needed a noninteractive reinstall after restart; `CI=true pnpm install --frozen-lockfile` resolved it without lockfile changes.
- No new HTTP route or web runtime change: access-registry additions and the web build/test suite are not applicable. Existing cross-learner endpoint tests pass in the backend suite.
- `git diff --check`: passed. Migration/model, service boundaries, packed arrays, retries and exclusion enforcement reviewed against the cited design sections.

Coverage gaps were reviewed, not excluded: ffmpeg termination during a cancelled decode, database unlock failure/connection invalidation, nonfinite timing defense, unavailable playback metadata, and no-op late failure settlement have unexecuted defensive paths. The report also marks the contention raise line uncovered although `test_concurrent_requests_reuse_spans` asserts `Reschedule` and verifies that the second request processes only the gap. The read-service executable lines are fully covered. Independent review should inspect these failure boundaries; coverage is not a substitute for their assertions.
