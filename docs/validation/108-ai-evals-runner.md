# Story #108: AI evals runner validation

Branch: `feat/108-ai-evals-runner`, from current main `2800167`.
Owner-approved plan, implementation with Codex, and explicit unavailable live
Shadow integration. See [ADR 0052](../adr/0052-ai-evals-runner-and-report-format.md)
and [format/commands](../../ai-evals/README.md).

## Scope and evidence limits

All committed datasets are **synthetic harness fixtures, not model-quality
evidence**. #106/#107's teacher sets are absent. No real provider was evaluated,
no calibration value was chosen, and no provider was enabled. Live Shadow grading
is explicitly unavailable until the public scoring service exists (owner decision).

No changes to AI providers, prompts, `text_tasks.py`, gateway, review, admin or web.
No schema migration, application API or generated client change. PR #173 remains
independent; public interfaces available on main are used without copying its code.

## Acceptance criteria and named tests

| Criterion / requirement | Tests and observable result |
| --- | --- |
| One command reports either set | `test_cli_reports_each_suite` (gist/Shadow); JSON and Markdown, hashes, counts, three attempts; Shadow explicitly synthetic report contract |
| Teacher agreement and numeric errors | `test_teacher_agreement_and_mae`; exact independent examples for absolute errors and level-match denominator |
| AT-15 / AT-21 three-run consistency | `test_three_run_consistency_uses_worst_case_range`; max-minus-min across all three attempts, per dimension/measure; filler MAE also checked |
| Existing SRS limits retained, calibration out of scope | `test_production_thresholds_preserve_only_existing_requirements`, `test_missing_thresholds_or_smoke_cases_cannot_pass`, `test_incomplete_metric_configuration_cannot_pass`, `test_optional_diagnostic_metrics_do_not_require_calibration` |
| CI exact path selection | `test_smoke_path_selection`, `test_unrelated_paths_do_not_run_smoke`, `test_workflow_detects_prompt_add_delete_and_rename`, `test_new_branch_push_compares_against_main` |
| CI fails below configured bound and uploads reports | `test_threshold_failure_writes_report_and_exits_nonzero`, `test_ci_smoke_is_conditional_offline_and_uploads_failure_reports` |
| No networked/paid AI in smoke | `test_smoke_forbids_networked_ai_configuration`; all AI unit tests use `tests.network_guard` and injected accounting; actual command uses only existing fake AI and PostgreSQL accounting |
| AT-22 role/provider configuration switch | `test_config_provider_switch_changes_report_and_verdict`; same dataset and thresholds, different configured provider yields different provenance and PASS/FAIL; `test_task_override_is_identified_as_requested_provider` covers task override |
| Gateway eligibility, quota, fallback | `test_ineligible_provider_never_sees_fixture_input`, `test_gateway_quota_denial_is_reported_and_not_dropped`, `test_gateway_eligibility_denial_and_fallback_are_visible` |
| Persistent admission/log contract | Integration `test_evals_respects_persistent_quota_and_logs_each_admitted_attempt`: two admitted attempts plus one quota-denied attempt, failure report and matching persisted outcomes |
| Scope/claim correctness | `test_synthetic_limits_cannot_evaluate_teacher_manifest`, `test_offline_teacher_data_cannot_be_scored`, `test_fake_provider_never_establishes_teacher_quality`, `test_synthetic_shadow_exercises_report_contract_only`, `test_live_shadow_is_explicitly_unavailable` |
| Invalid/boundary/failure cases | `test_invalid_manifests_are_rejected`, `test_invalid_numeric_scores_are_rejected`, `test_invalid_thresholds_are_rejected`, `test_level_boundaries_must_be_ordered`, `test_missing_runs_or_scores_cannot_look_like_perfect_results` |
| Safe reports / input budget | `test_report_does_not_include_input_or_feedback`, `test_configuration_errors_do_not_echo_private_content`, `test_unexpected_execution_failure_still_writes_safe_report`, `test_reference_trimming_is_recorded`, `test_oversized_learner_text_is_refused_before_admission`, `test_unknown_covered_point_is_not_accepted` |
| Score/report provenance | `test_gist_weights_follow_existing_rubric`, `test_report_hashes_the_dataset_bytes_used_for_evaluation` |

## Actual red/green record

Commands run from `apps/api`. Early `uv run --frozen` attempts were blocked by
cache permissions/build downloads; those failures are **not Red evidence**.
The existing virtual environment with `PYTHONPATH=src .venv/bin/python -m pytest`
was used until scoped network permission allowed `uv sync --frozen --python 3.12`.
Subsequent commands use `uv run pytest`. No assertion/coverage gate was weakened.

| Cycle | Observed Red before implementation | Green/refactor outcome |
| --- | --- | --- |
| Grade/metrics interface | `tests/unit/ai/test_evals_metrics.py -q`: collection failure, no `listenup.ai.evals` | Same file: **7 passed** |
| Gateway runner / AT-22 / denials / privacy | `tests/unit/ai/test_evals_runner.py -q`: collection failure, no `listenup.ai.evals.runner` | Runner + metrics: **12 passed** |
| CLI / report gate / offline restriction | `tests/unit/ai/test_evals_cli.py -q`: collection failure, no `listenup.ai.evals.cli` | CLI + runner + metrics: **19 passed** |
| Exact smoke paths | `tests/unit/ai/test_evals_paths.py -q`: collection failure, no `listenup.ai.evals.paths` | Same file: **12 passed** |
| Unexpected error report / fake-quality claim | `tests/unit/ai/test_evals_cli.py -q`: **2 failed, 5 passed** (uncaught RuntimeError; fake teacher run claimed quality) | Same file: **7 passed** |
| Optional diagnostics need no extra calibration | `test_evals_runner.py::test_optional_diagnostic_metrics_do_not_require_calibration -q`: **1 failed**, incorrectly unconfigured | All eval unit tests then: **57 passed** |
| Retain approved SRS limits in teacher config | `test_evals_models.py::test_production_thresholds_preserve_only_existing_requirements -q`: **1 failed**, missing range rule | Same test: **1 passed** |
| Dataset fingerprint / task override provenance | Focused `test_report_hashes_the_dataset_bytes_used_for_evaluation` and `test_task_override_is_identified_as_requested_provider`: **2 failed** (post-evaluation hash; missing argument) | All eval unit tests then: **61 passed** |
| PR path selection against diverged main | `test_evals_workflow.py::test_pr_ignores_ai_changes_only_on_the_base_branch -q`: **1 failed**, base-only AI change triggered smoke | Focused workflow suite: **4 passed**, then **5 passed** after the next cycle |
| Change-detector failures fail CI | `test_evals_workflow.py::test_change_detection_failure_fails_ci_step -q`: **1 failed**, `echo` hid failing command substitution | Focused workflow suite: **5 passed** |

Supplemental schema, real-Git workflow, Shadow unavailability, budget and durable
accounting tests were added after their implementation and are characterization/
regression evidence, **not claimed as test-first work**. Initial Shadow fixture
tests failed because fixture files were missing; that is not behavior Red evidence.
The substantive metric/gateway/CLI behaviors above were built in red/green cycles.
The chronology gaps are disclosed here for independent review under `docs/testing.md`.

## Assertion checks

Temporary copies under ignored `work/` were used; production files were not mutated.
Each focused mutant produced **1 failed**: replacing consistency range with zero;
removing absolute error; reversing the minimum threshold comparison; ignoring
synthetic/teacher scope; allowing fake results as quality evidence; and enabling
live Shadow report replay. Removing duplicate-case validation, removing complete
dimension validation, and removing rename-source detection also each produced
**1 failed** in isolated copies. All nine mutants were detected. These checks
support the supplemental characterization tests without changing their chronology.

## Final verification

- `uv sync --frozen --python 3.12`: passed; the installed `ai-evals` entry point works.
- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`:
  passed (336 formatted files, 169 typed source files).
- `uv run lint-imports`: all **6** contracts kept. Architecture tests also pass.
- `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest -m 'not performance'
  --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html`:
  **1681 passed, 1 deselected**, 3 dependency deprecation warnings, 377.60 seconds.
  PostgreSQL 16 and real SeaweedFS were healthy; no required service tests skipped.
- `uv run pytest -m performance --no-cov`: **1 passed**, 1681 deselected.
- Final supplemental `uv run pytest tests/unit/ai/test_evals* -q --cov --cov-append
  --cov-report=xml --cov-report=html --cov-report=term-missing:skip-covered`:
  **67 passed**. This includes the final shell/configuration cases and targeted
  coverage follow-ups for the module entry point, parser refusal, missing Shadow
  filler counts and missing synthetic samples. These follow-ups are supplemental
  checks, not new test-first chronology claims.
- `uv run python ../../.github/scripts/check-coverage.py api coverage/coverage.xml`:
  every runtime source file resolves; coverage inventory passed.
- `uv run diff-cover coverage/coverage.xml --compare-branch origin/main --fail-under 90`:
  **99%** changed-line coverage (262/264). Every executable eval line except the
  two NUL-input/print lines in the path-selector module entry point is covered.
  Those two lines execute in the real-Git subprocess tests; child-process coverage
  is not collected. No production coverage exclusion was introduced.
- Actual installed CLI: both synthetic smoke suites exit **0** and write JSON/Markdown.
  A deliberately impossible synthetic agreement bound exits **1** and still writes
  its failed threshold decision. These are harness results, not quality evidence.
- `bash -n .github/scripts/ai-evals-changes.sh`, branch-name validation and
  `git diff --check`: passed. Protected areas have no diff.
- No migrations, application API/client regeneration or web changes: those local
  checks are not applicable. Normal repository CI still runs its standard jobs.

An earlier full coverage run was interrupted when the task-override and snapshot
fixes required production changes; it is not counted as a passing full run.
Shell/configuration refinements after the final full run were verified by the
targeted workflow suite and the final 67-test supplemental run; Python runtime
source was unchanged during that full run.

Hosted CI and fresh-session review are checked on the PR. Because this story does
not modify the exact AI trigger paths, the new conditional smoke job is expected
to skip on this PR; its executable command was run locally and its selection,
failure propagation and upload configuration are tested above.

No model-quality or real-server performance claim is made. Fresh-session independent
review and required green CI remain owner merge gates; the owner merges.

## PR #175 review remediation

The independent review identified two assertion gaps, not runtime defects:
synthetic-only acceptance tests short-circuited the smoke/fallback restrictions,
and the filler metric example asserted MAE without asserting its worst error.
This follow-up changes only tests and this evidence record; runtime code, provider
configuration, production thresholds and the approved live Shadow limitation remain
unchanged. These are characterization/regression tests for existing behavior, not
new test-first implementation or evidence of model quality.

| Review finding | Named tests and independent expectations |
| --- | --- |
| Provider-acceptance restrictions | `test_teacher_primary_acceptance_excludes_smoke`: full primary success accepts, smoke does not; `test_teacher_fallback_success_never_accepts_requested_provider`: fallback-only and mixed-provider success do not accept; `test_teacher_task_override_acceptance_uses_effective_provider`: a successful task override accepts, fallback to the role primary does not |
| Worst filler-count error / AT-17 boundary | `test_three_run_consistency_uses_worst_case_range` now asserts maximum filler error **2** alongside MAE **1**; `test_shadow_filler_gate_checks_worst_error_at_inclusive_bound` accepts maximum error **1** and rejects **2**, across two cases with six successful attempts, while the diluted MAE remains below **1** |

Teacher scope in these unit tests is simulated with deterministic test doubles
and invented inputs solely to exercise otherwise short-circuited report branches.
No teacher dataset or real provider has been evaluated or accepted. Synthetic
Shadow samples still exercise report mechanics without AI or audio access.

Actual commands ran from `apps/api` with the existing Python 3.12 environment:

- `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/ai/test_evals_runner.py
  tests/unit/ai/test_evals_metrics.py -q -p no:cacheprovider`: **35 passed**.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/ai/test_evals* -q
  -p no:cacheprovider`: **75 passed** (the reviewed baseline had **67 passed**).
- `LISTENUP_REQUIRE_DB=1 PYTHONPATH=src .venv/bin/python -m pytest tests/unit/ai
  tests/architecture tests/integration/test_ai_evals.py -q -p no:cacheprovider`:
  **382 passed**, one dependency deprecation warning. This includes the real
  PostgreSQL persistent-quota integration check and all neighboring AI and
  architecture tests.
- `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy`,
  `.venv/bin/lint-imports`: passed; **336** formatted files, **169** typed source
  files and all **6** import contracts kept. One formatting/line-length failure
  during editing was corrected before these final checks.

Independent in-memory mutations used `inspect.getsource`, `exec` in the affected
module's namespace, and `pytest.main(['tests/unit/ai/', '-q', '-k', 'evals', '-p',
'no:cacheprovider'])` in a fresh subprocess for each mutant. No tracked runtime
file was edited. The previous review observed that removing the smoke/provider
restrictions together and substituting mean filler error each left all **67**
tests green. The expanded suite now rejects each defect independently:

| Mutation | Actual result |
| --- | --- |
| Remove `and not smoke` | **1 failed, 74 passed** |
| Remove the requested-provider equality guard | **3 failed, 72 passed** |
| Compare actual providers with the role primary instead of the effective task provider | **2 failed, 73 passed** |
| Replace `float(max(errors))` with `float(mean(errors))` | **3 failed, 72 passed** |
| Replace the inclusive maximum comparison `<=` with `<` | **17 failed, 58 passed** |

All five mutant processes exited **1** due to assertion failures; the normal
suite exited **0**. These mutation failures demonstrate assertion quality, not
test-before-implementation chronology.

Initial PostgreSQL connection attempts failed before local services were started;
an initial broader unit run was interrupted while local connections were restricted
by the command sandbox. Neither is counted as a pass. Starting the configured
PostgreSQL/SeaweedFS services and granting the test command network access allowed
the **382-test** run above to complete, with AI calls still guarded against network
access. Full service-backed coverage and performance checks are delegated to the
normal CI run for the remediation commit; historical CI on `4fd50e4` is not claimed
as verification of that new head. No changed runtime lines, schema, API or web
behavior were introduced by this follow-up.

The review also noted a pre-existing policy tension between the gateway's
`accepted: true` eligibility precondition and NFR-AI-6's evaluation-before-acceptance
sequence. The owner has not specified a new candidate-evaluation procedure here.
This follow-up neither bypasses eligibility nor enables a production provider;
that policy question remains explicit rather than inventing a decision.

## Integration with current main before merge

The owner requested merging PR #175 after the review fixes. Branch protection
requires the PR to include current main, now `57ff878`. Its integration is a merge
commit, preserving the reviewed commit and remediation history.

- Main's legal-text decision already uses ADR 0051. The eval decision is renumbered
  to **ADR 0052**, with its links updated; the decision itself is unchanged.
- Main now provides `text_tasks.run_task`. The eval runner uses that public helper
  as anticipated by the eval ADR and current AI conventions, retaining the fitted
  input budget, gateway admission, output validation and reported trimmed fields.
  This is a behavior-preserving refactor: the existing **75** eval tests passed
  before and after it. No new test-first behavior is claimed.
- `uv sync --frozen --python 3.12` passed against main's updated dependency lock.
- The same neighboring-AI/architecture/persistent-quota command above passed
  **436 tests**, with one dependency deprecation warning, after integration.
- Backend Ruff format/lint, strict mypy and all six import contracts passed:
  **345** formatted files and **173** typed source files.
- Protected AI providers/prompts, `text_tasks.py`, gateway, review, admin and web
  match current main; the integration adds no story-specific changes there.

Required hosted CI must be checked for the integrated PR head before merge;
neither the original green run nor the earlier remediation head substitutes for it.
