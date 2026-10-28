# #80 — E2 speech assessment contract

## Scope and status

Owner exception E2 was approved on 2026-10-28; [ADR 0074](../adr/0074-speech-assessment-contract-split.md)
records its boundary. This change reuses the existing port/schema and gateway,
documents the contract, registers a disabled second synthetic adapter and proves
configuration-only switching. #43 and #76 are closed; E2 removes #21/#22 as
dependencies only for this contract portion.

#80 remains open. The real-model local provider, its recorded-sample contract
evidence, reference-speaker phoneme/GOP work and B3 criterion remain unimplemented
and unverified, waiting for #21 and #22. The unchanged B3 requirement is one 75 s
recording within the stage-0 budget (System Design §12: p95 under 50 s without a
queue over 30 recordings). Synthetic output cannot satisfy it. #82–#86 wait for
the port PR to merge, then may use fakes only, subject to their other dependencies.

## Acceptance evidence

All new named tests below are in
`apps/api/tests/unit/ai/test_assessment_contract.py`.

| E2 criterion / requirement | Evidence |
| --- | --- |
| Existing vendor-neutral port and full schema, NFR-AI-1 | `test_second_fake_exercises_complete_assessment_schema`: Protocol conformance, round-trip serialization, complete signals, reference indexes, repeated deterministic output, single-word/empty/whitespace cases and gateway validation |
| Fake second provider replaces the first through configuration, AT-22 / NFR-AI-2 | `test_at22_assessment_switch_uses_only_configuration`: rewrite only the YAML, reload the ordinary `get_gateway()`, assess through it, verify distinct provider outputs and deployment/result provenance |
| Packaged registration is safe by default | `test_default_assessment_registration_is_disabled_and_production_safe`: disabled entry and successful production construction |
| Synthetic providers never run in production | `test_enabled_assessment_fakes_are_refused_in_production`: both enabled fake IDs fail at gateway construction |
| Ordinary gateway admission remains intact, NFR-AI-7 | `test_ineligible_second_fake_is_not_called`: disabled, unaccepted or training-enabled entries produce only an ineligible accounting record |
| Fallback and provenance | `test_second_fake_is_a_gateway_fallback_when_first_is_unavailable`: first fake quota refusal, second fake success and synthetic sound score |
| No paid/model dependencies, NFR-AI-3 | Both adapters operate on nonexistent audio paths under the AI tests' network guard; no new package/model dependency |

Existing neighboring tests remain relevant: `test_invalid_assessment_falls_back`
in `test_safeguards.py` rejects invalid reference indexes/text, overlapping words
and sounds outside their word. Existing contract adapter tests still pass.

## Actual test-first evidence

Commands ran from `apps/api` with `UV_CACHE_DIR=/workspace/.cache/uv`.

- Red: `uv run --no-sync pytest tests/unit/ai/test_assessment_contract.py -q`
  before implementation: **7 failed, 1 passed**. Failures showed the missing
  second adapter/registration and missing default entry. The original fake's
  production refusal was existing behavior (the passing characterization case).
- Green: the same focused file after implementation: **8 passed**. Additional
  eligibility/fallback cases characterize the existing gateway using the new
  adapter; they did not introduce a new gateway policy.
- Refactor/regression: `uv run --no-sync pytest tests/unit/ai tests/contract/test_ai_adapters.py -q`:
  **591 passed**, including the expanded **12** assessment-contract cases.
- The port/schema existed before this task. Its documentation changes need no
  invented Red cycle. ADR/workflow/design edits are documentation-only.

Production assertions detect removal of the fake-provider refusal; configuration
switch assertions detect reuse of the first adapter or incorrect provenance;
eligibility accounting assertions detect accidental admission of a disabled,
unaccepted or training-enabled provider. No assertions or coverage exclusions
were weakened.

## Final verification

Commands ran from `apps/api`, with the provided PostgreSQL 16 client directory on
`PATH` and `UV_CACHE_DIR=/workspace/.cache/uv`.

| Check | Result |
| --- | --- |
| `uv run --no-sync ruff format --check .` | Passed |
| `uv run --no-sync ruff check .` | Passed |
| `uv run --no-sync mypy` | Passed, 209 source files |
| `uv run --no-sync lint-imports` | All six contracts kept |
| `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run --no-sync pytest -m 'not performance' --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html` | **2,535 passed, 1 skipped, 1 deselected**; 98% total coverage |
| `uv run --no-sync pytest -m performance --no-cov -q` | **1 passed**, 2,536 deselected on the final isolated run |
| `uv run --no-sync python ../../.github/scripts/check-coverage.py api coverage/coverage.xml` | Every runtime source file resolves |
| `uv run --no-sync diff-cover coverage/coverage.xml --compare-branch origin/main --fail-under 90` | **100% of 17 changed executable lines**, none missing |
| `git diff --check` and branch-name validation | Passed |

The sole skipped test is `test_reference_profiles_real.py`: it requires the opt-in
`LISTENUP_REAL_PROFILE_FIXTURE` LibriSpeech fixture. Real-model evidence remains
outside this contract change. The first uninstrumented Dictation performance run
measured 0.215 s against 0.2 s during concurrent coverage work; the final run above
passed after that work finished. Neither run is B3 evidence. An early coverage
attempt was interrupted to correct the PostgreSQL client PATH; it is not counted
as a passing suite.

The new adapter and its registered version resolver have 100% coverage. Existing
uncovered gateway paths are outside the changed lines. Empty references, single
and multiple words, voiced/unvoiced samples and production/eligibility refusals
are explicitly asserted rather than inferred from the coverage percentage.

[CI run 40775051384](https://github.com/abubakar1010/ListenUp/actions/runs/40775051384)
passed all jobs on the identical runtime/test diff, including the changed-line
gate, backend performance check, synthetic evaluation smoke, image builds,
scanner sandbox, browser checks and dependency scans. The replacement branch uses
a fresh commit with a reference-only issue footer, avoiding GitHub's closing-keyword
parsing of negated prose; the superseded draft was closed without merging. Its
final head must also pass required CI before merge.

No database schema, HTTP API, frontend, model, prompt or dependency changes require their
respective migration, OpenAPI/client, browser or model-quality checks.

Fresh-session independent review and required CI remain pre-merge requirements;
the owner merges. No downstream story was implemented before the port merge.

## Development configuration

In non-production, copy `ai.yaml` and enable its `speech_assessment` entry, then
point `LISTENUP_AI_CONFIG` at that file. Alternatively replace the `provider` and
`model` of the speech assessment entry in a copy of `ai.fake.yaml` with
`fake-assessment` and `synthetic-assessment-v1`. Restart the worker to reload
configuration. Keep `local: true`, `accepted: true`, `trains_on_inputs: false`.
The shared `ai.fake.yaml` keeps its original adapter for offline evaluation
compatibility. Both outputs are synthetic and must never be shown as real grades.
