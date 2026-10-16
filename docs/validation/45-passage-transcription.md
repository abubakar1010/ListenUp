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


Original PR local results, before reconciliation (2026-10-16):

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

## Reconciliation on the existing PR

The follow-up continues from pushed commit `0e4f04f` on PR #154. Its explicit
learner check, worker-role read boundary, failed-span recovery and lock-contention
rescheduling are retained. The independently implemented local branch was preserved
rather than replacing or rewriting this pushed history. Only useful missing
behavior and validation were brought across.

| Behavior | Named tests | Actual Red | Green |
| --- | --- | --- | --- |
| Sentence boundaries within/across acoustic chunks; reject zero-duration words | `test_sentences_follow_punctuation_across_provider_segments`, `test_empty_word_timing_is_rejected` | `uv run pytest tests/unit/test_transcript_packing.py tests/integration/test_transcript_schema.py -q`: two packing failures, nine schema failures, ten passes. Sentence indexes were `[0,1]` rather than `[0,2]`; zero-duration words were accepted. | Same focused suite passed after implementation. |
| Ready cache confidence, sentence indexes and required provenance | `test_ready_cache_rejects_invalid_confidence_sentence_indexes_and_provenance` | Nine invalid updates were accepted before the new CHECK constraints. An additional focused schema run observed three failures for null array entries and a JSON array posing as provenance (16 passes). | Packing/schema suite: 24 passed after non-null array checks and the provenance-object/type/key checks. |
| Browser subscription to both named transcript events | `useLiveEvents.test.tsx`: `handles every event type and ignores malformed data` | `pnpm vitest run src/events/useLiveEvents.test.tsx -t 'handles every event type'`: one failed, nine skipped; expected five events, received three. Both transcript events were ignored. | Entire hook file: ten passed after adding both subscriptions. |

Reconciliation tests first passed against the existing job implementation, with no
changes to job orchestration: `test_slow_provider_does_not_hold_an_idle_transaction`,
`test_session_deleted_during_provider_call_discards_result`, and
`test_real_intake_worker_retries_provider_failure`. They are characterization and
additional boundary evidence, not new test-first claims. The real worker is observed
at `todo`/attempt 1 after a provider failure and `succeeded`/attempt 2 after retry,
with exactly one ready cache span and no premature failed marker.

`test_extraction_seeks_to_requested_audio_and_keeps_duration` verifies the actual
PCM samples and frame count for a 1.25–2.5 second audio window. The existing direct
SQL concurrency test now observes `pg_blocking_pids` before committing the first
writer; it passes with a real competing insert blocked on the exclusion constraint.
`test_cache_complement_covers_each_millisecond_once` adds an independently stated
Hypothesis set-complement invariant to the existing range arithmetic. These are
supplemental validation of retained behavior.

The original TDD deviation above remains disclosed. The reconciliation does not
retroactively claim that notification, cleanup or deactivation code was test-first.
SSE descriptions and generated API files now list `transcript.ready` and
`transcript.failed`; no new route is added. ADR 0038 and the database design reflect
sentence handling and cache integrity checks.

Migration 0017 remains an unmerged PR migration. The local database that had already
applied an earlier 0017 was downgraded to 0016 before reapplying it, then passed the
normal upgrade/check/downgrade/upgrade round trip. This is not a deployed-database
migration procedure.

A final read-path regression, `test_cached_spans_do_not_split_a_continuing_sentence`,
was then run Red: `uv run pytest tests/integration/test_passage_transcription.py::test_cached_spans_do_not_split_a_continuing_sentence -q`
failed with `[0,1,2]` instead of `[0,2]`. The service had treated every cache-span
start as a sentence start even when the sentence continued across the span.
Packing and reads now share the punctuation rule; the service preserves actual
stored internal boundaries without adding a false boundary between cached spans.
Packing plus the job/read suite passed all 26 focused tests after the fix. The
backend coverage suite is rerun for this source change; the prior 1,079-test run
is retained as intermediate evidence, not the final result.

### Reconciliation validation before the final title guard

- Backend format/lint pass (254 files), strict mypy passes (135 source files), and
  all six import contracts pass.
- With PostgreSQL 16/SeaweedFS and PostgreSQL 16 client tools on PATH:
  `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest -m 'not performance' --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html`
  passed **1,081 tests**, one performance test deselected, no service skips, in
  221.85 seconds. This run includes the final sentence-composition fix and all new
  characterization/property tests.
- `uv run pytest -m performance --no-cov`: **one passed**. This remains the scoring
  budget, not a stage-0 transcription measurement.
- Runtime inventory passes `check-coverage.py` for both applications. Backend
  changed-line coverage against `origin/main`: **96% (266/276)**. Transcript service
  executable lines and both transcript domain helpers are fully covered.
- Reviewed remaining ten changed uncovered lines: unavailable playback metadata;
  ffmpeg termination during cancellation; unexpected context-error propagation;
  late no-op failure settlement; nonfinite provider timing; advisory-unlock failure
  invalidation; and the contention raise line (the contention test still asserts
  `Reschedule` and verifies gap-only processing). No exclusions/assertions weakened.
- Migration upgrade/check/downgrade/re-upgrade passes with no drift; the full
  integration suite also validates migration round trips and a full downgrade.
- OpenAPI export and pinned-pnpm API generation pass; generated descriptions list
  both transcript events. No new route, so no access-registry addition is needed.
- Pinned pnpm 10.28.0: lint, format, typecheck, coverage (**300 tests in 32 files**),
  build and size (**120.3 KB gzip / 200 KB budget**) pass. Playwright with system
  Chromium passes **30 tests** against its mocked API.
- Web diff-cover reports no changed executable lines: the runtime edit adds two
  array members whose initializer is instrumented on existing line 5. Complete
  runtime inventory passes; the red/green hook test explicitly asserts delivery of
  both new event types. Generated API files retain existing coverage policy.
- `git diff --check` passes. The existing PR's pushed history is retained. CI on the
  new commit and fresh-session independent review remain separate checks.
- Stage-0 p95 is still unavailable/unverified for the reasons and measurement
  procedure above; neither local wall-clock results nor deterministic AI establish it.


### Final title-abbreviation regression

`uv run pytest tests/unit/test_transcript_packing.py -q` observed **six failures,
five passes** before the title guard: each case of
`test_person_titles_do_not_end_sentences` (Dr., Mr., Mrs., Ms., Prof., Rev.) produced
an extra sentence boundary before the person's name. The shared punctuation helper
now excludes these common person titles. Packing plus the job/read suite then
passed **32 tests**. This is an additional observed Red → Green cycle, not a
supplemental test-first claim. The full final-state backend/CI results are recorded
in the PR after revalidation; the 1,081-test result above predates this small guard.
