# Stories #106 and #107: golden-set collection kit

Branch `docs/106-107-golden-set-kit`, from main `6e83ba2`. This PR prepares the kit
only. **#106 and #107 stay open**: no teacher grade, learner gist, recording, consent
record or audio exists or was invented, and nothing here is model-quality evidence.

## What the kit adds

- `ai-evals/gists/` and `ai-evals/shadow/`: README (source, consent, no personal data,
  consent records kept outside), teacher grading guide matching ADR 0054 / ADR 0050,
  consent form template, selection checklist, coverage matrix, and empty templates in
  the runner's format (`dataset`, `teacher-grades`, `passages`, and for Shadow
  `word-labels`).
- `apps/api/scripts/check_golden_sets.py`: validates templates, and real files once they
  exist (runner `Dataset` model, sidecar schemas, privacy scan, referential rules);
  `--require-complete` enforces the matrix and fails while `dataset.json` is missing;
  `--agreement` reports two-teacher agreement.
- Runner changes: none. Teacher datasets cannot be empty in the runner (`cases` needs one
  case), so the committed examples are `*.template.json`, not loadable `dataset.json`.

## Acceptance mapping

| Requirement | Test |
| --- | --- |
| Committed templates are valid and empty | `test_committed_templates_are_valid_and_hold_no_data`, `test_template_rules_reject_data_and_odd_shapes` (6), `test_a_template_that_is_not_json_is_reported`, `test_unknown_template_file_is_reported` |
| Kit cannot be mistaken for finished data | `test_complete_mode_refuses_while_no_real_data_is_committed`, `test_complete_mode_needs_every_sidecar` |
| Matrix: levels, AT-10 to AT-13, CEFR, passages, topics, accents, key points, teacher grades | `test_gist_coverage_and_privacy_rules` (43 cases) |
| Matrix: 4+ accent groups with 3+ speakers, AT-17 pairs, fillers, segment duration, word labels, teacher grades | `test_shadow_coverage_and_privacy_rules` (31 cases) |
| Privacy and format rules hold without `--require-complete` | `test_shadow_privacy_and_format_rules_apply_without_complete_mode` (15) |
| No personal data; phone numbers found, dates and long numbers not | `test_phone_numbers_are_found_and_ordinary_numbers_are_not` (12), `test_a_long_number_in_a_public_source_url_is_not_personal_data` |
| No audio or `external/` folder in a suite folder | `test_audio_files_cannot_enter_a_suite_directory`, `test_an_external_folder_cannot_enter_a_suite_directory` |
| Agreement: two and three teachers, missing levels, fillers, Shadow overall formula, bad input | `test_agreement_*` (6, including the command's exit codes), `test_shadow_agreement_includes_filler_counts_and_the_overall_formula`, `test_the_overall_formula_leaves_accent_out` |
| Usage errors | `test_conflicting_options_are_a_usage_error` (2), `test_main_exit_codes` |
| A matching set passes; an agreed grade may differ from the first teacher | `test_a_set_that_meets_the_matrix_passes_complete_mode`, `test_expected_may_be_the_agreed_grade_when_two_teachers_graded` |

All grades and cases in the tests are invented and live in temporary directories.
TDD does not apply to the Markdown guides, forms, checklists and matrices (no executable
behavior); they are checked against ADR 0054, ADR 0050 and the SRS by review, and the rules
they state as "script" are the ones the tests above exercise.

## Red / green

From `apps/api`. Test-first chronology is not visible in the history: the first commit
holds the docs, the second the checker, its tests and the templates, and both carry the same
timestamp. The record below is what was run.

First version (commit `867ee88`):

- Red: `uv run pytest tests/unit/ai/test_golden_set_kit.py -q --no-cov` failed at
  collection, `FileNotFoundError` for `scripts/check_golden_sets.py`.
- First green attempt: **31 passed, 3 failed**. Two were test mistakes (suite directory is
  `gists/`; a truncated dataset kept all grades) and one a mutation that left four strong
  accent groups. Fixed in the tests and the directory map; no assertion was weakened. (This
  was recorded by the author at the time and cannot be re-observed from history.)

Review fixes (independent review of `31178b5`, comment on the PR):

- Red: the rewritten test file against the unchanged script: **73 failed, 56 passed**
  (false passes such as an at-12 case as its own clean version, `/home/jane/rec.wav` in the
  default run and the phone regex on dates; plus the new rules: tags, identifiers, key points,
  teacher grades, word labels, passage variety, segment duration, agreement edge cases).
- Green after the script change: one failure, `1 000 000 000` read as a phone number; the
  pattern now needs a `+`, a leading `0` and a non-zero digit, or 3-3-4 groups. Then
  **129 passed**.
- Mutation check (`docs/testing.md`, scratch copy, nothing committed): every
  `problems.append(...)` removed one at a time, every threshold relaxed, and the agreement,
  exit-code and phone-regex rules reversed: 93 mutations. First run: 11 survived (the
  passage-count and AT-17 count messages hidden by other messages with the same words, the
  at-11 level rule, the invalid-JSON template message, the duplicate single-passage-tag rule,
  the self-twin guard, the single-teacher `expected` rule, the phone lookbehind). Fixed by
  more exact assertions, tests for the at-11 level, invalid JSON, an agreed grade that equals
  the second teacher, and numbers inside URLs, and by deleting a redundant rule. Last run:
  **134 passed** and **0 of 93 survived**.
- Green: `uv run pytest tests/unit/ai/test_golden_set_kit.py -q --no-cov`: **134 passed**.
  `uv run pytest tests/unit/ai -q --no-cov`: **566 passed**.
- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` (207 files): clean.
  `scripts/` and the tests are outside mypy's `packages = ["listenup"]` scope, as for the
  existing scripts and tests.
- `uv run python scripts/check_golden_sets.py`: `gist: ok`, `shadow: ok`.
  With `--require-complete` both report `dataset.json is missing` and exit 1, as intended.
  `--agreement` exits 1 while `teacher-grades.json` is missing.

The script lives outside `src/listenup`, so it is not in the coverage gate; its branches are
exercised by the tests above. Not run: the full backend and web suites (no runtime code,
API or web change).

## Review findings fixed

Checker: phone pattern; self-twin, duplicate and cross-passage at-12 pairs; privacy and
format rules in every mode; speaker, accent, case-id and audio-file shapes; one accent
group per speaker; empty, duplicate and upper-case tags; key points; teacher-grade keys,
levels, fillers, duplicates and `expected`; word labels against `reference_text`; unused and
duplicate passages, topics and accents; FR-SH-1 segment duration; agreement edge cases,
exit codes and the Shadow overall formula; template shape and personal-data scan; audio
files and `external/` folders (also in `.gitignore`).
Documents: both consent forms (what is kept, what is published, AI services, retention vs
FR-SH-17, learner approval), the matrices (script vs manual rows), the guides (Shadow
overall formula, AT-11) and the READMEs (withdrawal effects, agreement weighting, provider
eligibility context, unloadable templates).

## Decisions the owner should confirm

- Coverage minimums (5 per level, 3 per AT case, 8 per CEFR band, 4 accent groups with 3+
  speakers, 3 AT-17 pairs, 4 reference-speaker accents with at most 3 passages each) are proposals for "about 50"; the figures are in the matrices and
  the script constants.
- The consent forms are templates, not legal advice, and promise only what a public
  repository can keep (see their withdrawal wording).
- Accent groups are proposed, self-reported and must be agreed with the teacher first.
- The Shadow consent form's retention period ("[N] months") against the app's 90 days
  (FR-SH-17), and the sentence that grades may be used to calibrate scoring.
- The id and tag shapes the checker now enforces (`g01`, `r01`, `speaker:s12`,
  `external/rec-<n>.wav`).
