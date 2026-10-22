# Story #66: text-AI adapters and versioned prompt files, validation

Branch `feat/66-text-ai-adapters`, started from `main` after PR #159 (merge `a74e930`) and merged with `main` at `aeb64ee`. Decisions are in ADR 0046. No route, schema, migration or web change.

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
| Gateway wiring | `test_text_gateway.py` (an import typo in my test was fixed first, not counted): **19 failed, 3 passed** (the 3 were vacuous before registration) | **21 passed, 1 failed**: the gateway logs adapter-side invalid output as `error`, not `invalid_output`; expectation corrected, decision in ADR 0046; `tests/unit/ai` **246 passed** |
| Fake defaults, contract, key scan | **4 failed, 21 passed** (3 fake-default failures; 1 scan false positive on my own field name, renamed) | `tests/contract` + `tests/unit/ai`: **271 passed** |
| PostgreSQL version test | Passed on first run: integration coverage of behavior already driven red by the unit tests above | 1 passed |
| Remaining `prompt_files` branches | Added after coverage review: characterization | 24 passed |

Mutation checks (temporary edits, restored): 17 mutants (trim learner text, drop field allowlist, skip delimiter check, drop budget check, temperature 0.7, hosted over http, accept truncated reply, accept fenced reply in schema mode, send without key, no output cap, wrong provenance model, 429 permanent, ignore filename/version, allow several active versions, budget ignoring prompt overhead, main idea not first, edit a released prompt without the manifest). One survived (trim learner text: the learner field was never listed before the reference field); `test_learner_text_is_refused_even_when_listed_before_the_reference_text` was added and **all 17 are killed**.

## Original validation (before main integration)

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` (150 files), `uv run lint-imports` (6 contracts kept): passed.
- Full backend with PostgreSQL and required S3 flags, coverage: **1434 passed, 2 failed**, 1 deselected. The two failures, `test_three_minute_passage_real_storage_decode_and_configured_gateway` and `test_a_real_upload_is_private_bound_to_its_size_and_confirmed`, **fail identically on a clean `origin/main` worktree** in this environment. The upload test expects a tampered signed PUT to be refused, which the S3 stand-in does not do; the other raises `accounting unavailable` in this environment. Neither touches this change; CI with SeaweedFS is the check for them.
- S3 was served by **moto**, not SeaweedFS, because no S3 server was available here.
- `uv run pytest -m performance --no-cov`: 1 passed.
- Coverage inventory complete. Changed executable lines: **98%** (304/308) before the last four tests, which cover the remaining `prompt_files` branches; the gate is 90%.
- `docker compose config` (default and `--profile llm`) passed; the services were not started (no daemon and no model download).
- Not applicable: Alembic (no schema change), OpenAPI export and access registry (no route), web checks (no web change).
- `scripts/record_ai_contract.py text_ai` was exercised once against a mock server by hand; it is not in the test suite.

## Independent review fixes

A fresh-session review found no blocker and seven low-severity findings; all seven are fixed in separate commits. Commands from `apps/api` with `--no-cov`.

| Finding | Named tests | Red | Green |
| --- | --- | --- | --- |
| `api_key_env` accepted any variable, so a database URL or session secret could be sent as a key (NFR-AI-7) | `test_unsafe_or_unknown_options_are_refused_at_construction` (3 new cases) | `-k unsafe_or_unknown`: **3 failed, 10 passed** | only `LISTENUP_AI_<NAME>_API_KEY`; `tests/unit/ai` + `tests/contract` **279 passed** |
| The version left out `reasoning_effort` and `seed`, which change the output (NFR-AI-5) | `test_settings_that_change_the_output_change_the_recorded_version`; an unbounded seed case | `assert 2 == 6`, **1 failed** | **281 passed** |
| The field allowlist was top-level only; nested values could carry ids or keys (FR-BL-13) | `test_input_that_does_not_match_the_task_input_model_is_refused` (11 cases, refusal never quotes the input), `test_input_that_matches_the_task_input_model_is_sent_unchanged`, prompt fields equal the input model | `test_prompt_render.py`: **11 failed, 12 passed**; `test_prompt_files.py`: collection error (no `TASK_INPUTS`) | `TASK_INPUTS` in `tasks.py`; the recordings' `rhythm` measure became `timing` (the Database Design name); **294 passed** with the integration file |
| Untested branches: marker-only refusal, non-text trimmable field, smallest budget across providers, admission boundary, provenance from a reply | `test_refused_when_only_the_truncation_marker_would_remain`, `test_a_trimmable_field_that_is_not_text_is_never_changed`, `test_text_input_budget_is_the_smallest_across_the_tasks_providers`, `test_input_of_exactly_the_budget_is_sent_and_one_byte_more_is_refused`, `test_provenance_never_comes_from_the_reply` | Characterization of existing code, so red is shown by mutants that all survived before: drop the marker refusal, stringify a trimmable field, `min` to `max`, budget plus one, version and model from the reply. Each now fails its test (budget plus one fails 4) | **298 passed** |
| Stale text-adapter ADR number; a `--text` recording flag that does not exist | comments and notes only | not applicable (documentation) | text-adapter references now cite ADR 0046 |

After the fixes: `ruff format --check`, `ruff check`, `mypy` (153 files) and `lint-imports` (6 kept) pass. The full coverage run with both required-service flags (moto again for S3) gives **1460 passed, 2 failed**: the same two tests named above, which fail identically on a clean `main` with moto (rechecked by the reviewer). Changed-line coverage is **100%** against both the PR base (342 lines) and the pre-fix head (37 lines). `pytest -m performance`: 1 passed.

The earlier review suggested per-version schemas, stricter deployment trust and automatic fitting in `generate`. These are optional follow-ups, not requirements changed by this PR: ADR 0046 already specifies one task schema, operator-controlled local entries and explicit fitting before gateway admission. This revision preserves those decisions and does not enable a provider.

## Not verified

- Recordings are **hand-written** in each server's documented response shape (no key or network). Real recordings, the NFR-AI-6 golden set and model quality are unverified, so both providers stay disabled and unaccepted.
- Groq strict `json_schema` support for every schema keyword is unverified against the service.
- The Ollama image is pinned by digest; the **model digest is not**: the Ollama registry was unreachable from this environment.
- Latency on the deployment host and Groq limits for the actual organization are launch evidence (tracker #155).
- Provider activation still requires the real-service and golden-set evidence above; this PR leaves both providers disabled. Final-head CI and coverage results are recorded in PR #168.


## Main integration and final review revision

- Merged `origin/main` at `4efc101` with merge commit `7eede35`; no rebase or force-push. Integrated the six concurrently published review-fix commits through `d9bcefd` without dropping them.
- Renamed the Text AI ADR to [0046](../adr/0046-text-ai-adapter-and-versioned-prompts.md), including references in source, tests, Compose and design documents. Main's admin ADR 0045 is unchanged.
- Reviewed the diff against main: only #66 adapters, prompts, configuration, tests and supporting docs remain. The optional LLM Compose profile is explicitly in #66's scope; no sandboxing, review, identity or Shadow-module changes are carried in the diff. No unrelated or redundant changes required removal. #67 and #68 remain out of scope.
- Re-read the issue, current PR, inline comments, reviews and review threads: there are no GitHub review threads to resolve. This Codex session independently reviewed the prior implementation and six review-fix commits, including eligibility, nested input validation, provenance, fallback, prompt versions and assertion quality. It found the incomplete-first-word bug below and stale ADR references; both are fixed. No further blocking findings remain. Review suggestions about schema layout and explicit fitting retain the existing ADR decisions above.

### Additional regression cycle

| Criterion | Named tests | Actual red | Green |
| --- | --- | --- | --- |
| Oversized reference input is cut at complete words; learner input is preserved | `test_refused_when_the_first_complete_reference_word_cannot_fit` (plain and leading-space cases), `test_trimming_keeps_a_complete_first_word_at_the_exact_boundary` | `uv run pytest tests/unit/ai/test_prompt_render.py -k 'first_complete or exact_boundary' -q --no-cov`: **2 failed, 1 passed** before the fix, including after integrating `d9bcefd`. The original code sent part of the first word instead of refusing. | `uv run pytest tests/unit/ai tests/contract tests/integration/test_text_ai_calls.py -q --no-cov`: **324 passed**, including the regression cases. |

The fix returns the existing marker-only refusal when no complete word fits; an exactly fitting whole word, including its leading whitespace, is retained. The two failing assertions directly reject the old implementation. Prompt text and schemas are unchanged, so the released prompt manifest remains unchanged. ADR renumbering, comments and regeneration have no executable behavior and need no artificial Red.

### Verification for this revision

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` (**157 source files**) and `uv run lint-imports` (**6 contracts**) passed.
- `uv run pytest -m performance --no-cov -q`: **1 passed**, 1506 deselected.
- Regenerated using `uv lock`, `pnpm install --lockfile-only`, `uv run python scripts/export_openapi.py` and `pnpm api:generate`; lockfiles and generated API files match the merged source with no resulting diff. No generated files were edited by hand.
- `docker compose config --quiet` and `docker compose --profile llm config --quiet` passed. PostgreSQL 16 and actual SeaweedFS are running for the required-service coverage suite; local PostgreSQL client tools are version 16.15 from the official image.
- The full required-service coverage command, inventory check, changed-line gate and final-head CI outcomes are reported in PR #168. Historical moto failures above do not represent the final verification environment.
- No new route or database schema: migrations and access-registry additions are not applicable. No web source changes: web behavior checks run in required CI. Real-service model-quality acceptance remains a provider activation gate; no provider is enabled by this revision.
