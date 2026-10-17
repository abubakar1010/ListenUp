# Test-driven development

TDD is required for new behavior and bug fixes in ListenUp. This policy applies to human contributors and coding agents. It starts with the next change; existing tests do not establish that earlier work used TDD.

## The development cycle

1. **Specify.** Map each acceptance criterion (and SRS ID where available) to an observable result and a named test. Include the relevant boundary, invalid input and failure cases. For a complex story, include this map in the plan required by `workflow.md`.
2. **Red.** Write the smallest useful test for one result before implementing it. Run that test against the current code and observe it fail because the behavior is missing or wrong. An intentionally missing public interface can be the first failure; broken syntax, missing tools, unavailable services and unrelated failures are not evidence of the behavior. For a bug, reproduce it in a failing regression test before fixing it.
3. **Green.** Implement only enough production behavior to pass that test. Run it again, then run the relevant neighboring tests. Add the next failing example before adding another behavior or branch.
4. **Refactor.** Improve structure with those tests passing. Preserve their observable assertions. Run the affected tests after refactoring; add a failing test first if the refactor reveals a new requirement.
5. **Verify.** Run the applicable final checks in `workflow.md`, inspect changed-code coverage and record the actual results. Preserve any blocked checks as unresolved work until they run successfully in a suitable environment or CI. Actual-server performance measurements alone may be deferred to the mandatory pre-launch gate under [the workflow policy](workflow.md#development-checks-and-the-pre-launch-performance-gate); deferral is not a passing result.

Keep red failures local. Atomic commits must still be working commits; the red test and its passing implementation can be committed together. Record the real red/green evidence while working instead of trying to infer chronology from commit timestamps. Never fabricate a failure or describe tests added after implementation as test-first work. If test-first work was missed, disclose it and validate that the regression test detects the old behavior in an isolated checkout.

If a test unexpectedly passes during Red, check its setup and assertions. If the behavior already exists, treat it as characterization; it does not justify adding production behavior. Missing infrastructure must be repaired before depending on that test as TDD evidence.

## Choose tests that can detect the defect

Use the cheapest reliable level for each behavior; add another level when it covers a distinct risk.

| Area | Required evidence when affected |
| --- | --- |
| Domain rules, scoring, state transitions | Focused examples, boundary values and invalid transitions. Use Hypothesis for meaningful invariants and combinations, with an independently stated expected result. |
| API, database and jobs | Integration tests for persisted results, constraints and error responses. Cover transaction rollback, retry/idempotency, stale versions or concurrency when affected. Use the restricted API role and the cross-learner access registry. |
| Authentication, ownership and private data | Allowed and denied cases, including another learner, expiry and sensitive output where relevant. Assert absence of unauthorized data and side effects. |
| Web behavior | Testing Library interactions through accessible roles/names, observable results, relevant loading/error states, keyboard behavior and async races. Use browser tests for navigation, media and browser-specific behavior. |
| Storage, email and AI adapters | Deterministic boundary fakes for caller logic and integration/contract tests for the real adapter boundary. Changes to prompts, models or grading also need the applicable evaluation cases; a fake cannot establish model quality. |
| Operations, migrations and configuration | Validate the affected behavior with the appropriate tool or integration test: alert firing and quiet cases, migration/restore checks, or configuration validation. Custom scripts and rules follow the same red/green cycle as application code. |

The current Playwright suite mocks API responses. It proves browser behavior against those responses; API/database integration tests must independently prove server behavior. Do not report it as a full live-stack test.

Tests assert externally meaningful outcomes, not the implementation's own calculation repeated in the test. Mock external boundaries rather than the rule under test. Prefer explicit examples and assertions over broad snapshots. Control clocks, randomness and network responses; use events or bounded waits instead of arbitrary sleeps. A retry that hides an intermittent failure is not a fix.

For changed security rules, scoring and state transitions, verify that the assertions reject a plausible defect (for example a reversed boundary, a removed ownership check or a duplicate retry). Use a targeted mutation tool or a temporary mutation in an isolated checkout when practical, and restore it afterward. Record the result or the specific test assertions that expose the defect. Repository-wide mutation testing is not required for unrelated changes.

## Coverage and existing code

- CI measures backend and frontend line and branch coverage and retains reports, including unimported production files. Generated types and test helpers are excluded; production code is not excluded merely because it is difficult to test.
- Pull requests must cover at least **90% of changed executable lines** in each application. This is a minimum gate, not a target that replaces the acceptance criteria: changed domain/security decisions and their relevant outcomes still need meaningful assertions.
- Review the reports for uncovered branches and explain any relevant gap. Coverage proves execution, not correctness, test quality or test-first chronology. Do not weaken a threshold, add an ignore directive or broaden an exclusion just to pass the gate.
- Whole-repository coverage is reported without an invented baseline. Establish any future repository-wide floor from a complete successful run; raise it as gaps are addressed. Do not present a partial run as the baseline.
- When modifying untested legacy code, first add passing characterization tests for behavior that must remain. Then add a failing test for the intended change. Track untouched gaps separately; an existing gap does not excuse missing tests for the behavior being changed.

Coverage commands and the PR gate are configured in `apps/api/pyproject.toml`, `apps/web/vite.config.ts` and `.github/workflows/ci.yml`. Backend discovery includes namespace packages without `__init__.py`. Vitest and the coverage completeness check share `apps/web/coverage-exclusions.json`; this list contains only tests, declarations, named test helpers and generated schema types.

Before calculating changed-line coverage, CI runs `.github/scripts/check-coverage.py` for each application. It inventories all runtime source files and requires an entry that resolves through diff-cover's own Cobertura path lookup. Missing files, empty reports that omit runtime files, and mismatched paths fail rather than silently shrinking the coverage denominator. Empty Python packages and types-only TypeScript files may have entries with no executable lines. Documentation/test-only diffs still pass when the runtime reports are complete. The script runs with the backend dev environment; from `apps/api`, use `uv run python ../../.github/scripts/check-coverage.py api coverage/coverage.xml` (or `web ../web/coverage/cobertura-coverage.xml`). Regression checks run with `uv run pytest tests/unit/test_coverage_gate.py`.

From `apps/api`, with PostgreSQL and S3 running:

```sh
LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest -m 'not performance' --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html
uv run pytest -m performance --no-cov
```

From `apps/web`, run `pnpm test:coverage`. Reports are written under each application's `coverage/` directory. Backend wall-clock performance budgets run separately without instrumentation so coverage overhead does not distort them; plain `uv run pytest` still includes those tests. CI uses the same split and both required-service flags so missing services fail instead of skipping.

## Applicability and review evidence

Pure documentation, formatting, generated output and changes without executable behavior do not need artificial failing tests. State why TDD is not applicable and record an appropriate validation (for example formatting, schema regeneration or configuration validation). A behavior-preserving refactor starts with green characterization/regression tests and ends with them green; it does not require inventing a new behavior to get Red. A dependency or configuration change that alters behavior still needs tests of that behavior.

Use the PR template to provide:

- Acceptance criterion/SRS ID → named test and relevant edge/failure cases.
- Red: exact focused command, expected failure and observed outcome before implementation.
- Green/refactor: command and observed outcome after implementation and cleanup.
- Final checks and coverage report results, including skipped or blocked checks and any justified applicability notes.

A concise table can group related examples from the same development cycle; do not paste long logs, secrets or learner data. If no PR is requested, put the same evidence in the handoff. The independent reviewer checks both the evidence and whether the assertions would catch the intended regression. Missing tests for changed behavior, unexplained gaps or unverified required development checks mean the work is not ready to merge. An explicitly tracked actual-server performance deferral may accompany development completion, but still blocks public launch until measured and accepted. CI enforces executable checks and coverage; it cannot prove when a test was written. Branch protection must require the CI checks for GitHub to block a merge automatically.
