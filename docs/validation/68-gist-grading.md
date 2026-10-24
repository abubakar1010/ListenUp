# Story #68: Gist grading validation

Branch: `feat/68-gist-grading`, created from `c298108` after #67 merged in PR #184.
Owner approved the plan and 50/70/90 inclusive level cutoffs. ADR 0054 records the
rubric, persistence and versioning decisions. Display (#69), failure UX (#70),
review, cards, shadow and web features are outside scope.

## Acceptance criteria and tests

| Criterion | Named tests |
| --- | --- |
| AT-10: main idea and key points score Good/Excellent | `test_at10_good_gist` |
| AT-11: unrelated gist scores Needs work and missed points are named | `test_at11_unrelated_gist` |
| AT-12: spelling/grammar do not change the level | `test_at12_meaning_over_grammar` |
| AT-13: injected demand does not override the replayed grade | `test_at13_injection`; `test_wire_payload_is_delimited_data_without_identity` |
| D3 weights read from the rubric file; code computes overall | `test_rubric_weights_are_loaded`; `test_job_reads_changed_rubric_weights_without_code_changes`; `test_rounding_is_half_up` |
| Ready-grade DB CHECK | `test_ready_grade_requires_score_level_feedback`; `test_database_rejects_invalid_ready_values`; `test_pending_grade_can_be_incomplete` |
| Levels, range and configuration validity | `test_level_boundaries`; `test_invalid_overall_rejected`; `test_invalid_dimension_scores_are_rejected`; `test_invalid_rubric_configuration_rejected`; `test_weighted_score_stays_between_dimension_extremes` |
| AI lane, submission transaction and handler registration | `test_submission_queues_one_ai_job_and_pending_grade`; `test_api_submission_registers_grading_job_in_fresh_process` |
| Atomic ready event and idempotency | `test_ready_retry_does_not_call_ai_or_publish_twice`; `test_publish_failure_rolls_back_ready_grade`; `test_queue_execution_lock_coalesces_duplicate_grades` |
| Provider eligibility, identity minimization, provenance and trimming | `test_unaccepted_provider_receives_nothing`; `test_at10_good_gist`; `test_wire_payload_is_delimited_data_without_identity`; `test_reference_trimming_is_recorded_and_gist_unchanged` |
| Ownership, lifecycle and invalid results | `test_grade_ownership_and_missing_scope_fail_closed`; `test_grade_rejects_mismatched_owner_and_cascades`; `test_wrong_learner_never_calls_ai`; `test_deleted_attempt_is_not_resurrected`; `test_inactive_account_never_receives_a_grade`; `test_unknown_covered_points_never_become_ready`; `test_invalid_feedback_never_becomes_ready`; `test_missing_reference_retries_without_inference` |

AT fixtures under `apps/api/tests/recordings/gist_grading/` are explicitly
synthetic, hand-authored replay data. They run through `ai.fake.yaml`, production
gateway validation/accounting and real PostgreSQL. The wire test uses the actual
OpenAI-compatible adapter with `httpx.MockTransport`. These prove pipeline
behavior, not live provider quality; actual provider recordings and teacher-set
validation remain provider-activation gates (ADRs 0037/0046). Story #109 owns
AT-10 to AT-13 on live primary/fallback providers and teacher-set calibration;
it depends on this story. No live AI is called here.

## Actual test-first chronology

Commands below ran from `apps/api`. Integration commands set `LISTENUP_REQUIRE_DB=1`.

| Cycle | Red observed before implementation | Green / follow-up observed |
| --- | --- | --- |
| Rubric arithmetic | `uv run pytest tests/unit/test_gist_scoring.py -q`: collection failed with missing public `grading.domain.scoring` interface | Same command: **5 passed**; later boundaries, invalid configuration and Hypothesis checks: **24 passed** |
| Persistence, ownership, readiness | `uv run pytest tests/integration/test_gist_grades.py -q`: **14 failed**, missing `grading.gist_grades` table | Same command: **14 passed** after migration/models; a migration string syntax error occurred during implementation and is not Red evidence |
| Job, AT replay and submission | `uv run pytest tests/integration/test_gist_grading_jobs.py -q --tb=short`: **7 failed**, missing job/pending row | Same command: **7 passed** after implementation |
| Feedback validation | Same job-file command: **3 failed, 12 passed**; one/five/blank feedback accepted unexpectedly | After feedback validation, those cases passed; subsequent job suite expanded to **28 passed** |
| API-process job registration | `uv run pytest tests/unit/test_gist_job_registration.py -q --tb=short`: **1 failed**, API queued an unregistered job | Same command after lazy registration: **1 passed** |

Additional boundary, ownership, invalid-covered-label and retry tests were added
after the initial job implementation; they are not claimed as separate Red cycles.
An isolated source copy in `work/` verified that removing the covered-label guard
makes `test_unknown_covered_points_never_become_ready` fail. Independent mutations
also reversed level equality and ignored rubric-file changes: the level-boundary
and weight-file tests each rejected those defects. Production source was untouched
by mutation checks. Version-aware updates to existing AI tests preserve their
original assertions; the focused repaired tests/job run passed **177 tests**.

## Final verification

Documentation and lifecycle-only
retirement of v1 need no artificial Red cycle. No routes or transport models change,
so OpenAPI generation, access-registry additions and web checks are not applicable.
The migration has RLS, explicit grants and a cascading composite ownership FK.

The first full run used PostgreSQL 17 clients against the PostgreSQL 16 server:
four backup restores failed on `SET transaction_timeout = 0`. It was interrupted
after **320 passed, 4 failed**; this is not a passing full-suite result. Matching
PostgreSQL 16.15 clients were downloaded and extracted under ignored `work/`
(no system installation rights), and the full required-service run was restarted.

The next complete run produced **1,921 passed, 2 failed**: an unscoped table
assertion in the new cascade test and a pre-existing integration test hardcoding
prompt v1. The cascade assertion now targets its attempt, preserving the ownership
and deletion assertions; the version test uses the active version and a distinct
next version. Their focused rerun passed **15 tests**. The final complete run against these corrected files passed **1,929 tests**,
with the performance test intentionally selected separately.

Final commands (from `apps/api`):

| Check | Result |
| --- | --- |
| `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 LISTENUP_AI_CONFIG=src/listenup/ai/ai.fake.yaml uv run pytest -m 'not performance' --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html` | **1,929 passed, 1 deselected**, 434.76 s; PostgreSQL 16.15 and SeaweedFS healthy; matching PostgreSQL client tools on PATH |
| `uv run pytest -m performance --no-cov -q` with the same service/fake settings | **1 passed, 1,929 deselected**, 2.52 s |
| `uv run ruff format --check .`; `uv run ruff check .`; `uv run mypy`; `uv run lint-imports` | Pass; 363 files formatted, 180 source files typed, all 6 import contracts kept |
| `uv run alembic upgrade head`; `uv run alembic check`; `uv run alembic downgrade -1`; upgrade and check again | Pass; no model/schema drift |
| `uv run python ../../.github/scripts/check-coverage.py api coverage/coverage.xml` | Every runtime source file resolves in the full report |
| `uv run --with diff-cover diff-cover coverage/coverage.xml --compare-branch origin/main --fail-under 90` | **100% of 144 changed executable lines**, none missing; complete backend line/branch report: **97%** |
| `uv run ai-evals --offline --smoke` for both `ai-evals/fixtures/gist.json` and `shadow.json`, with `ai-evals/smoke.thresholds.json` and `ai.fake.yaml` | Both synthetic report gates pass; no live inference |
| `git diff --check`; branch-name validation | Pass |

Changed scoring/feedback modules and grading jobs have complete line/branch
coverage. Blind service's two remaining branch gaps are unchanged playback/heartbeat
paths (157->160 and 239->241), not the grading changes. The mutation checks above
also test assertion quality at the score and covered-point boundaries.

A final fetch before the PR still found main at `c298108`, with migration head
`67_key_points`; no competing migration needed merging/repointing. If main gains a
migration before owner merge, merge main and repoint this revision, then repeat
upgrade/check. No full suite or skipped check is represented as passing until run.
Required CI and independent fresh-session review remain merge gates; the owner merges.
