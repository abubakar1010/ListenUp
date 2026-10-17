# Story #64: AI gateway safeguards validation

Branch: `feat/64-ai-gateway-safeguards`. Dependencies verified by merge commits,
not issue status: #43 via PR #126 (`035d6ea`), #23 via PR #145 (`598ecca`).
Started from then-current main; integrated #45 (PR #154) and subsequent main
through `799005a`. Existing gateway/port calls still work. No hosted text adapter,
prompt, new model, learner-facing route or web behavior is introduced.

## Acceptance criteria and tests

| Criterion / requirement | Named tests and observable result |
| --- | --- |
| AT-22; NFR-AI-1/2/9 | `test_switching_the_provider_in_ai_yaml_changes_the_provider_used`, `test_role_and_task_configuration_order`, `test_all_roles_keep_their_public_methods`: configuration selects the actual adapter and task order. |
| AT-23; NFR-AI-8 | `test_exhausted_quota_falls_back`, `test_concurrent_admission_never_exceeds_quota`, `test_rate_limit_and_monthly_audio_exhaustion`, `test_failed_calls_keep_reservations_and_month_denial_is_atomic`, `test_each_retry_requires_fresh_admission`: no unmetered call or partial counter increment; next provider is used. |
| AT-24; NFR-AI-4 | `test_invalid_output_falls_back`, `test_text_schema_revalidates_constructed_values_and_finite_numbers`, `test_schema_coercion_cannot_introduce_nonfinite_values`, `test_transcript_invalid_boundaries`, `test_alignment_invalid_boundaries`: malformed, non-finite, misindexed and out-of-range values cannot escape. |
| NFR-AI-5 | `test_recorded_speech_outputs_pass_gateway_validation`, `test_settlement_is_idempotent_and_counts_actual_usage`, `test_provenance_cannot_put_email_or_path_in_logs`: model/version/prompt provenance is retained and validated. |
| NFR-AI-7; FR-BL-13 | `test_ineligible_provider_never_receives_data`, `test_hosted_controls_are_each_enforced`, `test_unknown_hosted_quotas_are_ineligible`, `test_unaccepted_local_text_model_is_not_called`: training, controls, consent, population/region, quota and acceptance denials happen before invocation. |
| Logging privacy | `test_logs_exclude_input_paths_and_error_messages`, `test_ai_logs_are_content_free_and_api_cannot_write`, `test_gateway_fallback_persists_content_free_attempts`, `test_no_provider_raises_content_free_ai_unavailable`: DB rows, telemetry and public errors exclude payloads/identifiers and raw provider messages. |
| Timeouts/retries/cancellation | `test_a_timeout_is_retried_with_backoff`, `test_transient_errors_are_retried_until_attempts_run_out`, `test_timeout_falls_back`, `test_cancellation_is_logged_and_never_falls_back`, `test_cancellation_survives_accounting_failure`. |
| Persistent usage and concurrency | `test_reset_and_settlement_use_original_utc_buckets`, `test_logs_distinguish_actual_usage_from_reservations`, `test_worker_role_admits_but_api_role_cannot_write`, `test_accounting_failure_prevents_unmetered_calls`: committed reservations survive independent store instances and failures; settlement occurs once in the original bucket. |
| ADR 0037 saving/headroom/cost | `test_saving_mode_signals_templates_and_preserves_round_three`, `test_saving_threshold`, `test_routine_requests_leave_reserved_grading_headroom`, `test_projected_cost_is_metered_without_paid_routing`, `test_task_specific_token_caps_are_reserved_and_passed_to_adapter`, `test_fallback_and_queue_delay_are_content_free_metadata`. |
| Alerts and retention | Promtool `AiQuotaLow` cases: 25% remaining fires, 25.1% stays quiet; `test_partition_retention_drops_only_expired_months`, `test_partitions_cover_next_three_months_and_maintenance_is_restricted`, `test_scheduled_maintenance_updates_quota_metrics_and_partitions`, `test_scheduled_jobs_run_only_in_the_pool_of_their_lane`. |
| No provider can serve | `test_no_provider_raises_content_free_ai_unavailable`, `test_a_role_without_providers_is_unavailable`: explicit `AIUnavailable`; callers own retained data and durable retry/delayed states. |

## Actual red/green evidence

Commands below ran from `apps/api` (the session used the equivalent
`uv run --directory apps/api ...` from the root). Counts are observations at the
corresponding development step, not claims that earlier suites contained later tests.
Initial unchanged AI/contract suite: **47 passed**.

| Cycle | Red command and observed result before implementation | Green/refactor command and observed result |
| --- | --- | --- |
| Routing, eligibility, validation, public errors | `uv run pytest tests/unit/ai/test_safeguards.py -q`: **7 failed**, showing no fallback, no revalidation, raw exception leakage and missing eligibility/task configuration. | `uv run pytest tests/unit/ai tests/contract -q`: **54 passed**. |
| Persistent accounting boundary | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_ai_accounting.py -q`: collection failed because the planned new `listenup.ai.accounting` interface did not exist. This is the intended missing-interface Red, not an unavailable-service failure. | Same file plus `tests/integration/test_migrations.py`: **8 passed** against PostgreSQL 16. |
| Admission/logging/saving connection | Safeguards file: **6 failed, 8 passed**: exhausted quota still invoked primary, logs were absent, saving API missing. | AI/contract suite: **61 passed**. |
| Hosted quota, usage, finite output and shared limits | Safeguards file: **4 failed, 16 passed**. | AI/contract suite after fixing generic output-schema validation: **67 passed**. |
| Provenance and operational metadata | Safeguards: **2 failed, 20 passed**; accounting integration: **2 failed, 7 passed**, for missing cost/maintenance interfaces. | AI/contract: **69 passed**; accounting + migrations + #45 passage tests: **34 passed**. |
| Alignment reference text and local acceptance | `uv run pytest tests/unit/ai/test_validation.py tests/unit/ai/test_safeguards.py -q`: **2 failed, 36 passed**. | AI/contract: **85 passed**. |
| Audio reservation containment and skipped budget logs | Safeguards: **2 failed, 37 passed**. | AI/contract: **103 passed**. |
| Actual versus estimated usage | `test_ai_accounting.py::test_logs_distinguish_actual_usage_from_reservations`: **1 failed**, missing `usage_estimated`. | Accounting + migrations: **18 passed**. |
| Per-task token caps | `test_safeguards.py::test_task_specific_token_caps_are_reserved_and_passed_to_adapter`: **1 failed**, missing configuration field. | AI/contract: **104 passed**. |
| Numeric coercion | `test_validation.py::test_schema_coercion_cannot_introduce_nonfinite_values`: **1 failed**, string `NaN` was accepted. | Validation file: **16 passed** after checking the validated representation too. |
| Cancellation during accounting outage | `test_safeguards.py::test_cancellation_survives_accounting_failure`: **1 failed**, cancellation became `AIUnavailable`. | Safeguards: **41 passed**. |
| Alert at 75% consumption | `promtool test rules alerts.test.yml`: behavioral failure, expected boundary alert but got none under the old 20% rule. An earlier container file-permission error was corrected and is not counted as Red. | Same command: **SUCCESS**, including the quiet case at 25.1% remaining. |

Additional boundary, permission, UTC reset, recorded-response and compatibility
assertions were added as passing characterization of behavior already present in
those cycles; they are not represented as new Red observations. In particular,
invalid `Usage` subset/value assertions were added after the initial usage model,
so those additional assertions do not establish test-first chronology themselves.
Documentation, SQL formatting and main synchronization have no independent
executable behavior requiring an artificial Red.

A full-run regression initially reported **1 failed, 1157 passed**: the scheduler
test's expected set omitted `ai.maintain`. It now asserts the exact three background
schedules, no media schedule and no duplicates, without depending on import order.
The focused gateway/accounting/contract/scheduler suite then passed **122 tests**.

A temporary mutation changed the ineligible-provider denial to allowance.
`test_ineligible_provider_never_receives_data` failed as expected; the original
file was restored in `finally`. This verifies that the privacy assertion catches
removal of the eligibility rule. Concurrent admission tests independently require
exactly three successes and persisted `(calls, units) == (3, 30)` for 12 contenders.

## Final verification

- Full backend: `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest -m 'not performance' --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html` — **1209 passed, 1 performance test deselected**, no skipped tests, 179.62 seconds. PostgreSQL 16, SeaweedFS, ffmpeg and PostgreSQL 16 client tools were available. The run reported 96% whole-backend line/branch coverage.
- Coverage review added passing characterization for provenance/task/prompt mismatch, output caps, valid/oversized reported usage, quota configuration, reverse timestamps and skipped-provider persistence. Final focused AI/contract/accounting/scheduler run with `--cov --cov-append --cov-report=xml --cov-report=html`: **135 passed**. Runtime source did not change between the full run and this coverage append.
- Coverage inventory: `uv run python ../../.github/scripts/check-coverage.py api coverage/coverage.xml` — every runtime file resolves. `uv run diff-cover coverage/coverage.xml --compare-branch origin/main --fail-under 90` — **100% of 399 changed executable lines**, zero missing changed lines. No threshold or exclusion was weakened.
- Branch review: remaining gateway gaps are the pre-existing empty `entry()` helper, cached/non-loadable preload paths and the bounded retry loop's unreachable normal-exhaustion edge; the maintenance duplicate-provider skip is unexercised. Admission, actual/estimated settlement, eligibility and result-validation decisions have explicit allowed/denied assertions. Existing real-engine loading gaps are unchanged and model-free contracts do not establish model quality.
- `uv run pytest -m performance --no-cov` — **1 passed** (1209 deselected). This is a runner regression check, not deployment-host latency evidence.
- Backend formatting, ruff, strict mypy (**142 source files**), coverage-gate script checks and import-linter (**6 contracts**) — passed.
- `uv run alembic upgrade head`, `uv run alembic check`, `uv run alembic downgrade -1`, upgrade again — passed. Single head: `0064_ai_gateway`. Integration upgrade/downgrade/check, full downgrade, role permissions, backup/restore and partition-retention cases passed.
- Final schema-filter review found that a broad `calls_` prefix could hide an unrelated table. `test_schema_check_ignores_only_monthly_partition_names` first failed because Alembic did not report `ai.calls_unexpected`; after restricting the filter to monthly names, accounting + migration checks passed **20 tests**. This final change affects only Alembic reflection; application runtime source and its coverage are unchanged. A final `alembic check` also passed.
- Promtool alert tests and Prometheus configuration/rule validation — **SUCCESS**, eight rules valid. Branch-name policy and staged whitespace checks passed.
- No web or HTTP API change: web checks, OpenAPI export and generated client updates are not applicable. Docker image builds and vulnerability scans are left to required CI; they were not run locally.

## Scope and remaining gates

- ADR 0041 records the admission, reservation, privacy, retention and saving decisions.
  Saving mode retains 3.5 estimated calls/session, not the old 2.5 estimate; actual
  task calls, retries, fallback depth, queue delay, token/audio usage and projected
  cost are recorded. Failed/unknown attempts conservatively retain reservations.
- Migration `0064_ai_gateway` has a distinct revision ID and follows current main's
  `32_google_oidc` after #45's `0017`; a single Alembic head is required.
- #45's production files were not edited. Its passage transcription tests and the
  existing recorded speech contracts exercise compatibility.
- No HTTP schema/routes or web source changed: client generation, access-registry
  additions and web checks are not applicable to this diff.
- Hosted text adapters/prompts and their real-provider golden-set acceptance belong
  to #66. No new provider/model is enabled; deterministic gateway tests do not
  establish model accuracy. Existing deployment-host speech benchmarks retain their
  recorded gates, including launch tracker #155 under ADR 0039 where applicable.
- Independent review and passing required CI remain merge gates. The owner merges.
