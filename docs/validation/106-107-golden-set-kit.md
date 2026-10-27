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
| Committed templates are valid and empty | `test_committed_templates_are_valid_and_hold_no_data` |
| Kit cannot be mistaken for finished data | `test_complete_mode_refuses_while_no_real_data_is_committed` |
| Matrix: levels, AT-10 to AT-13, CEFR, passages | `test_gist_coverage_and_privacy_rules` (13 cases) |
| Matrix: 4+ accent groups with 3+ speakers, AT-17 pairs, fillers, durations | `test_shadow_coverage_and_privacy_rules` (11 cases) |
| No personal data, no absolute or URL audio paths, coded teachers | same two tests |
| Agreement reported for double-graded cases | `test_agreement_is_reported_only_for_cases_with_two_teachers`, `test_agreement_with_one_teacher_per_case_reports_nothing` |
| A matching set passes | `test_a_set_that_meets_the_matrix_passes_complete_mode` |

All grades and cases in the tests are invented and live in temporary directories.

## Red / green

From `apps/api`.

- Red: `uv run pytest tests/unit/ai/test_golden_set_kit.py -q --no-cov` failed at
  collection, `FileNotFoundError` for `scripts/check_golden_sets.py`.
- First green attempt: **31 passed, 3 failed**. Two were test mistakes (suite directory is
  `gists/`; a truncated dataset kept all grades) and one a mutation that left four strong
  accent groups. Fixed in the tests and the directory map; no assertion was weakened.
- Green: `uv run pytest tests/unit/ai/test_golden_set_kit.py -q --no-cov`: **34 passed**.
  `uv run pytest tests/unit/ai -q --no-cov`: **466 passed**.
- `uv run ruff format`, `uv run ruff check .`, `uv run mypy` (207 files): clean.
- `uv run python scripts/check_golden_sets.py`: `gist: ok`, `shadow: ok`.
  With `--require-complete` both report `dataset.json is missing` and exit 1, as intended.

The script lives outside `src/listenup`, so it is not in the coverage gate; its branches are
exercised by the tests above. Not run: the full backend and web suites (no runtime code,
API or web change).

## Decisions the owner should confirm

- Coverage minimums (5 per level, 3 per AT case, 8 per CEFR band, 4 accent groups with 3+
  speakers, 3 AT-17 pairs) are proposals for "about 50"; the figures are in the matrices and
  the script constants.
- The consent forms are templates, not legal advice, and promise only what a public
  repository can keep (see their withdrawal wording).
- Accent groups are proposed, self-reported and must be agreed with the teacher first.
