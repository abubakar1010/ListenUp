## Story

Closes #

## What changed and why

## Test-first evidence (docs/testing.md)

<!-- Map each changed behavior/acceptance criterion to named tests. Group related
examples when useful. Record real outcomes; do not reconstruct or invent Red.
For documentation/formatting/generated output or behavior-preserving refactors,
explain applicability and the validation or characterization performed. -->

| Acceptance criterion / SRS ID | Named test(s), including relevant edge/failure cases | Red: command and observed failure before implementation | Green/refactor: command and result |
| --- | --- | --- | --- |
| | | | |

## Verification and coverage

<!-- Final commands/results, CI coverage reports and changed-line coverage for each
affected app. Explain uncovered branches and skipped/blocked checks. Required
checks must pass before merge. For high-risk rules, describe the plausible defect
the assertions detect or the targeted mutation check performed. -->

## Decisions

<!-- Each significant decision with its ADR, or "None". -->

## Not done

<!-- Acceptance criteria not met, with the reason, or "None". -->

## Checklist (docs/workflow.md)

- [ ] Every acceptance criterion maps to named tests, including relevant boundary and failure cases
- [ ] Actual red/green evidence is recorded for behavior changes, or applicability is explained per docs/testing.md
- [ ] Changed-line coverage passes; uncovered branches and assertion quality reviewed
- [ ] Backend checks pass (format, lint, mypy, import contracts, coverage suite and uninstrumented performance checks), or no backend change
- [ ] Migrations checked (upgrade, check, downgrade and back), or no schema change
- [ ] Generated API client refreshed and new routes in the access registry, or no API change
- [ ] Web checks pass (lint, format, types, tests with coverage, build, size, e2e), or no web change
- [ ] ADR added for each significant decision; area conventions updated in docs/conventions.md
- [ ] Independent review done and its findings fixed
