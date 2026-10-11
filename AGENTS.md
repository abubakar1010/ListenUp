# Repository instructions

Read `CLAUDE.md` for project context, commands, architecture constraints and commit rules. Read `docs/conventions.md` for the area being changed.

## Test-driven development is required

Follow `docs/testing.md` and `docs/workflow.md` for every behavior change:

- Before changing production code, turn the acceptance criterion or bug into a focused automated test. Run it and observe the expected failure.
- Make the smallest implementation that passes, then refactor with the relevant tests green. Repeat in small behavior slices.
- Test observable outcomes, relevant boundaries and failure paths. Use the test level that can expose the real defect; preserve database, ownership and provider contract checks.
- Record the actual red and green commands and outcomes, map acceptance criteria to named tests, and review coverage of changed code. Never claim an unrun, skipped or blocked check passed.
- Existing untested behavior needs characterization before refactoring. Documentation, formatting and other changes without executable behavior use the explicit applicability rules in `docs/testing.md`; do not invent meaningless tests.
- Finish with the applicable checks in `docs/workflow.md`. CI coverage is supporting evidence; reviewers must also assess assertions and test-first evidence.

These rules apply to Codex, Claude and human contributors. Do not defer tests until after implementation or weaken assertions, coverage thresholds or exclusions to make a change pass.
