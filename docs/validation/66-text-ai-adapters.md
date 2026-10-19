# Story #66: text-AI adapters and versioned prompt files, validation

Branch `feat/66-text-ai-adapters`, started from `main` after PR #159 (merge `a74e930`) and merged with `main` at `aeb64ee`. Decisions are in ADR 0045. No route, schema, migration or web change.

## Acceptance criteria and tests

| Criterion / requirement | Named tests |
| --- | --- |
| Contract: both adapters return a validated Pydantic object per task schema, from recordings | `test_recorded_reply_becomes_a_validated_object[groq/ollama x 3 tasks]` (6), `test_both_adapters_have_a_recording_for_every_task`; failures: `test_invalid_replies_raise_value_error` (11 cases), `test_rate_limits_and_server_errors_are_transient`, `test_other_http_errors_are_permanent`, `test_timeouts_and_connection_failures_are_retryable_errors`, `test_invalid_output_from_the_first_provider_falls_back_to_the_second` |
| Changing the prompt version in a file changes the recorded version | `test_prompt_version_is_read_from_file`, `test_changing_the_prompt_version_in_the_file_changes_the_recorded_version`, `test_editing_the_prompt_version_changes_the_version_stored_with_the_call` (PostgreSQL `ai.calls`), `test_version_is_the_one_inside_the_file_not_the_name`, `test_exactly_one_active_version_per_task`, `test_released_prompt_hash_lock` |
| Input over the token budget is trimmed before sending | `test_reference_text_over_budget_is_trimmed_at_a_word_boundary`, `test_over_budget_reference_text_is_trimmed_before_it_is_sent` (gateway refuses untrimmed, accepts fitted), `test_fit_never_exceeds_the_budget_and_keeps_a_prefix` (Hypothesis), `test_text_input_budget_matches_the_gateways_own_refusal_boundary`, `test_request_is_json_schema_mode_with_temperature_zero_and_an_output_cap`; learner text: `test_learner_text_is_refused_not_trimmed`, `..._even_when_listed_before_the_reference_text` |
| NFR-AI-2 | `test_switching_provider_is_a_configuration_change_only`, `test_shipped_configuration_builds_a_gateway_with_valid_options_and_task_order` |
| NFR-AI-3 | `test_shipped_text_entries_are_disabled_until_accepted`, `test_shipped_configuration_sends_nothing_because_nothing_is_enabled`; Compose: `docker compose config` with and without `--profile llm` |
| NFR-AI-4 | `test_json_object_mode_adds_the_schema_to_the_instructions`, `test_none_mode_sends_no_response_format_and_accepts_a_fenced_reply`, `test_schema_mode_does_not_accept_a_fenced_reply`, `test_shipped_task_has_one_active_prompt_and_matching_schema`, `test_tasks.py` (key point count and main idea, score ranges, extra keys) |
| NFR-AI-5 | `test_result_carries_provenance_and_the_prompt_version_of_the_file`, `test_reported_usage_is_mapped_and_invalid_usage_is_ignored` |
| FR-BL-12 | `test_instructions_are_in_the_system_message_and_data_in_one_delimited_block`, `test_a_gist_cannot_close_the_block_early`, `test_a_nonce_that_always_collides_is_an_error`, `test_learner_text_is_only_in_the_delimited_user_block`, `test_gist_grade_rejects_out_of_range_or_extra_output` |
| FR-BL-13, NFR-AI-7 | `test_unknown_or_missing_fields_are_refused`, `test_bad_calls_are_refused_before_any_request`, `test_ineligible_hosted_provider_receives_no_request` (8 cases), `test_hosted_provider_receives_nothing_without_consent`, `test_missing_api_key_sends_nothing_to_the_hosted_server`, `test_unsafe_or_unknown_options_are_refused_at_construction` (https only for hosted) |
| CI: no network, no keys | `test_a_real_request_is_refused_in_ai_tests`, `test_repository_files_hold_no_api_keys` |

## Actual red/green evidence

Commands run from `apps/api`; `--no-cov` for focused runs.

| Cycle | Red (before implementation) | Green / refactor |
| --- | --- | --- |
| Prompt files | `uv run pytest tests/unit/ai/test_prompt_files.py -q -x`: collection error, `cannot import name 'prompt_files'` (missing interface) | **20 passed** |
| Task models | Written after `tasks.py`: **characterization**, not red; detection shown by the mutation checks below | 21 passed |
| Fit and render | `test_prompt_render.py`: collection error, no `prompt_render` | First run **9 passed, 1 failed**: Hypothesis found a real bug (leading whitespace dropped, trimmed text not a prefix); fixed; with slice 1 **51 passed** |
| Adapter | `test_openai_compatible.py`: collection error, no adapter | First run **49 passed, 2 failed** (`PromptError` was not a `ValueError`: real bug; one test bug); fixed, **71 passed** |
| Gateway wiring | `test_text_gateway.py` (an import typo in my test was fixed first, not counted): **19 failed, 3 passed** (the 3 were vacuous before registration) | **21 passed, 1 failed**: the gateway logs adapter-side invalid output as `error`, not `invalid_output`; expectation corrected, decision in ADR 0045; `tests/unit/ai` **246 passed** |
| Fake defaults, contract, key scan | **4 failed, 21 passed** (3 fake-default failures; 1 scan false positive on my own field name, renamed) | `tests/contract` + `tests/unit/ai`: **271 passed** |
| PostgreSQL version test | Passed on first run: integration coverage of behavior already driven red by the unit tests above | 1 passed |
| Remaining `prompt_files` branches | Added after coverage review: characterization | 24 passed |

Mutation checks (temporary edits, restored): 17 mutants (trim learner text, drop field allowlist, skip delimiter check, drop budget check, temperature 0.7, hosted over http, accept truncated reply, accept fenced reply in schema mode, send without key, no output cap, wrong provenance model, 429 permanent, ignore filename/version, allow several active versions, budget ignoring prompt overhead, main idea not first, edit a released prompt without the manifest). One survived (trim learner text: the learner field was never listed before the reference field); `test_learner_text_is_refused_even_when_listed_before_the_reference_text` was added and **all 17 are killed**.

## Final checks

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` (150 files), `uv run lint-imports` (6 contracts kept): passed.
- Full backend with PostgreSQL and required S3 flags, coverage: **1434 passed, 2 failed**, 1 deselected. The two failures, `test_three_minute_passage_real_storage_decode_and_configured_gateway` and `test_a_real_upload_is_private_bound_to_its_size_and_confirmed`, **fail identically on a clean `origin/main` worktree** in this environment. The upload test expects a tampered signed PUT to be refused, which the S3 stand-in does not do; the other raises `accounting unavailable` in this environment. Neither touches this change; CI with SeaweedFS is the check for them.
- S3 was served by **moto**, not SeaweedFS, because no S3 server was available here.
- `uv run pytest -m performance --no-cov`: 1 passed.
- Coverage inventory complete. Changed executable lines: **98%** (304/308) before the last four tests, which cover the remaining `prompt_files` branches; the gate is 90%.
- `docker compose config` (default and `--profile llm`) passed; the services were not started (no daemon and no model download).
- Not applicable: Alembic (no schema change), OpenAPI export and access registry (no route), web checks (no web change).
- `scripts/record_ai_contract.py text_ai` was exercised once against a mock server by hand; it is not in the test suite.

## Not verified

- Recordings are **hand-written** in each server's documented response shape (no key or network). Real recordings, the NFR-AI-6 golden set and model quality are unverified, so both providers stay disabled and unaccepted.
- Groq strict `json_schema` support for every schema keyword is unverified against the service.
- The Ollama image is pinned by digest; the **model digest is not**: the Ollama registry was unreachable from this environment.
- Latency on the deployment host and Groq limits for the actual organization are launch evidence (tracker #155).
- Fresh-session independent re-review and required CI are still to do.
