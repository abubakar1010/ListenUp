# Story #69: gist feedback

Implements FR-BL-5, FR-BL-7, FR-BL-8, FR-BL-10 and FR-DI-3 under ADR 0054 and UX-02.
One story, one PR; the owner merges after passing CI and fresh-session review.
No changes to grading jobs/prompts, cards, Shadow, mark list or mark editing.
No schema migration or provider call is needed.

The checks and outstanding gates below are recorded chronologically. The
[final-head CI and independent review](#final-head-ci-and-independent-review)
section supersedes earlier statements that final-head CI or re-review was pending.

## Acceptance evidence

| Criterion | Named tests |
| --- | --- |
| Blind then Dictation: API excludes all hints until Transcript opens | `test_d4_grade_details_follow_transcript_gate[both]`: exact response key allowlist, no feedback/key-point ids/text, numeric parts and counts; after completing Dictation, full grade |
| Blind only: full grade immediately | `test_d4_grade_details_follow_transcript_gate[blind]`; `full grade and gist in blind use words for captured and missed` |
| Full grade beside Transcript on every path with a gist | `full gist grade beside Transcript on blind path`, `full gist grade beside Transcript on both path`; browser `full gist beside transcript at 360px on blind path` and `...both path` |
| Captured/missed without colour; 360 px | Browser tests above assert visible Captured/Missed words, long unbroken text without horizontal overflow at 360 px, desktop panel beside work; `full grade and gist in transcript use words for captured and missed` |
| Live updates and pending progress | `grade.ready fills the pending result in place without moving focus`, `submitted gist stays with its pending feedback until Continue`, `submission keeps feedback visible until Continue opens the next step` |
| Ownership and neutral pending | `test_other_learner_cannot_read_gist_grade`, access registry suite; `test_pending_grade_and_unknown_attempt`, `test_unsubmitted_and_unavailable_are_neutral`; `pending is neutral and does not offer failure or retry actions` |

Dictation-only plans have no Blind gist to display; existing Transcript tests
continue to cover that path without requesting a Blind result.

## Actual test-first chronology

- API Red: `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_gist_feedback.py -q`:
  3 failures, each expected 200 but got route 404. Earlier dependency-download and
  stopped-PostgreSQL errors were setup failures, not Red evidence. Started the
  repository PostgreSQL/S3 services and reran before implementing.
- API Green, same command: 3 passed after implementing the route and server gate.
  Additional pending and ownership examples are characterization of that boundary.
- UI Red: `pnpm vitest run src/features/blind/GistFeedback.test.tsx`: missing public
  `GistFeedback` component import, before creating it.
- Submission/event Red: `pnpm vitest run src/features/blind/GistForm.test.tsx src/app/eventKeys.test.ts`:
  2 failed / 8 passed (missing pending result after submission; grade.ready returned
  no invalidation keys).
- Green: the three feedback/form/event files: 14 passed.
- Transcript Red: `pnpm vitest run src/features/review/TranscriptScreen.test.tsx -t 'full gist grade'`:
  both paths failed because there was no side panel.
- Green/refactor: `pnpm vitest run src/features/review/TranscriptScreen.test.tsx src/features/blind src/app/eventKeys.test.ts`:
  70 passed. Subsequent event-invalidation/focus test: feedback file 5 passed.
- Browser tests supplement the component/API red-green cycles. The responsive
  grid is existing `PracticeLayout`; no new responsive layout policy was added.
  Generated schema, documentation and formatting do not require artificial Red.

The API allowlist would fail if the reveal gate were removed or inverted; its
post-Transcript assertions would fail if details remained withheld. Both reads
run as the restricted API role; shared references stay inaccessible to that role.

## Original implementation checks

- Frontend full coverage: 51 files, 517 tests passed; overall lines 95.74%,
  branches 88.42%. Coverage inventory resolves every runtime file.
- Frontend changed executable lines: 100% (22/22) via `diff-cover` against
  `origin/main`; new feedback component branches 24/26 (92.3%). Remaining branches
  are defensive fallbacks for absent dimension scores / unknown rubric labels,
  not D4 decisions. Summary/full, pending/ready, both contexts and point states run.
- `pnpm lint`, `pnpm format:check`, `pnpm typecheck`: passed.
- Production build (Playwright webServer): passed; `pnpm size`: 124.8 KB gzip,
  below the 200 KB budget. Browser suite: 42 passed (2.9 min), mocked API.
- Backend format, lint, mypy and six import contracts: passed.
- Uninstrumented `uv run pytest -m performance --no-cov`: 1 passed.
- Final focused feedback API run: 5 passed, restricted API role, real PostgreSQL.
- Backend full required-service coverage command from `docs/testing.md`:
  **1,972 passed, 1 deselected**, 477.28 s; PostgreSQL and S3 required, fake AI.
  Overall line/branch report: 97%. Runtime coverage inventory passes.
- Backend changed executable lines: **98% (49/50)** against `origin/main`.
  The single uncovered line is the defensive pending return when a stored shared
  reference disappears during the read. D4 disclosure outcomes and ownership
  refusals are covered. Blind's two branch gaps are unchanged playback paths.
- Initial full run was stopped after lint autofix removed imported fixtures;
  explicit re-export aliases fixed setup before the passing full run. This was
  test setup, not a production regression or Red evidence.
- No migration: no database schema changed. OpenAPI exported and client regenerated;
  new GET route registered as Owned in `access_registry.py`.
- Implementation CI passed on `f2cd28f`, including both application suites,
  browser tests, changed-line gate, schema contract, dependency scan, Docker builds
  and the real-scanner/media-sandbox job. Synthetic AI smoke was path-skipped:
  no prompts, jobs or provider code changed. Evidence: [PR run](https://github.com/abubakar1010/ListenUp/actions/runs/39943675664).
- Independent fresh-session review remains an owner merge gate; no merge performed.
  Final documentation update needs the current head's CI before owner merge.

## Deferred performance criterion

**p95 result within 10 s after gist submission: deferred until staging — unverified.**
Track the unchanged target in [launch validation #155](https://github.com/abubakar1010/ListenUp/issues/155).
Measure submission-to-visible-result latency on the actual staging host with the
real grading adapter and a representative workload, including grade.ready delivery.
Synthetic response tests and local browser timing do not establish this target.
This remains a pre-launch gate.

## Review remediation

The Codex review on `ca286c6` identified two P2 regressions: a fresh cached
completed listen could leave Transcript feedback pending indefinitely, and the
saved gist was hidden until grading finished. Continue now refreshes both the
session and its Blind attempt. Disclosable gist text is returned and rendered
independently of grade readiness; D4 still withholds it before Transcript on the
Blind-then-Dictation path. No grading jobs, prompts, cards, Shadow or marks changed.

Actual regression evidence:

- API Red: `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_gist_feedback.py -q -k pending_gist`:
  2 failed because pending responses omitted the saved gist after Transcript opened
  on both paths. Green: the full feedback API file passed all 7 tests. The new
  `test_pending_gist_is_visible_when_transcript_opens[blind/both]` asserts the exact
  pending response; the both-path case first asserts that the locked response
  remains exactly `{"status": "pending"}`.
- UI Red: `pnpm vitest run src/features/blind/BlindStep.test.tsx src/features/blind/GistFeedback.test.tsx -t 'fresh completed-listen|saved gist remains'`:
  3 failed (cached attempt prevented the Transcript grade panel; pending hid the
  gist in both contexts). Dependency setup errors before this run were not Red.
  Green: the affected Blind/review/event suite passed 75 tests. The cache regression
  uses the production query client with its 30-second stale time, submits a freshly
  loaded completed listen, clicks Continue and asserts gist and feedback inside
  the Transcript side panel. The pending rendering cases assert gist visibility
  and absence of fabricated scores or key points. The test re-queries the side
  panel while Transcript replaces its loading layout, avoiding a detached-node race.

Final remediation validation:

- Web coverage: 51 files / 520 tests passed; 95.74% lines, 88.50% branches.
  Runtime inventory passes; changed executable lines are 100% (21/21) against
  current `origin/main` with this report. The earlier 22/22 count above belongs
  to the original implementation run.
- Web lint, formatting, types, production build and size pass (124.8 KB gzip).
  Browser suite: 42 passed using system Chromium, mocked API, including both
  360 px Transcript gist paths. OpenAPI export and client regeneration are clean.
- Backend format, lint, strict mypy and all 6 import contracts pass.
  Uninstrumented performance regression: 1 passed.
- Required-service backend coverage was run in two parts: the documented full
  coverage command with `--ignore=tests/integration/test_backup.py` passed 1,967
  tests (1 performance test deselected), then the 7 backup tests passed with
  `--cov --cov-append --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html`.
  Both runs set `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1`; PostgreSQL 16 client
  binaries were obtained from the official `postgres:16-bookworm` image for the
  second run because the host lacked them. A resumed-environment attempt before
  restarting PostgreSQL was a setup failure, not a test result.
  Combined evidence covers all 1,974 non-performance tests; CI must still run
  the single full required-service command on the final commit.
- Backend changed executable lines: 48/49 (97% in diff-cover's integer display);
  the uncovered line remains `grading.service`'s missing-reference pending return.
  Both runtime inventories pass. The feedback component now covers 25/26 branches
  (96.15%); the remaining gap is a defensive rubric fallback, not disclosure.
- Final-head CI and independent re-review of the fixes remain owner merge gates.
  The p95 10 s staging criterion remains deferred and unverified under #155.

## Dependency-audit remediation

CI on `04fb4c3` failed the JavaScript vulnerability audit. Reproduced locally
with `corepack pnpm audit --audit-level=high`: four advisories (two high, two
moderate) for transitive Zod and Undici. The existing hooks plugin accepts Zod
4.x, so refreshing that transitive resolution upgrades 4.6.5 to 4.6.7 without
an override. Updating jsdom within its existing major, 30.1.1 to 30.1.3, allows
Undici to resolve to 8.12.3 instead of 8.11.2. Both are above the patched
minimums (4.6.6 and 8.12.2). jsdom's compatible DOM/URL dependencies update with
the parent; no audit exclusions, severity changes or suppressions were added.

Commands use the repository's pinned pnpm 10.28.0 through Corepack:

- `corepack pnpm update jsdom`, then
  `corepack pnpm update zod undici --depth 100`.
- `corepack pnpm audit --audit-level=high`: passes, no known vulnerabilities.
  A separate JSON audit reports zero vulnerabilities at every severity.
- `corepack pnpm install --frozen-lockfile`: passes.
- `corepack pnpm lint`, `corepack pnpm format:check`,
  `corepack pnpm typecheck`: pass.
- `corepack pnpm test:coverage`: 51 files / 520 tests pass, 95.74% lines and
  88.50% branches. Runtime inventory passes; current changed executable lines
  are 100% (22/22). No runtime source or coverage exclusion changed in this update.
- `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium corepack pnpm e2e`:
  production build and all 42 mocked-browser tests pass.
- `corepack pnpm size`: 124.8 KB gzip, within the 200 KB limit.

The failing audit and passing audit establish the dependency regression check;
existing lint, component and browser suites validate compatibility. No artificial
application test was added for generated lockfile resolutions. Backend code is
unchanged by this dependency update; final-head CI must run its full required
checks again. Independent re-review and owner merge remain separate gates.

## Final-head CI and independent review

Verified on 2026-10-25: [CI run 40098672524](https://github.com/abubakar1010/ListenUp/actions/runs/40098672524)
completed successfully on the final PR head
`eee2e8d88ac2e4f46cf525bfcc0a75c4ff3905fe`, against the recorded `main` base
`9c35da98cf1942a5ecb2fb4fd3240332e4030dc0`. This run includes the final sync
with main; the earlier green implementation run is not substituted for it.

- Backend: the single full coverage command from `docs/testing.md`, with
  `LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1`, passed **2,007 tests** with
  **1 performance test deselected**. The focused feedback file contributed all
  **7 passing tests**. The separate uninstrumented performance check passed
  **1 test**; the spike harness passed **62 tests**.
- Web: **52 files / 528 tests passed**; overall line coverage **95.73%** and
  branch coverage **88.56%**. The mocked-API browser suite passed **45 tests**,
  including both 360 px Transcript gist paths.
- Changed executable lines: backend **49/50 (98%)**, web **22/22 (100%)**.
  Both runtime coverage inventories passed. The backend gap remains the
  missing-reference pending return in `grading.service` (line 87 at this head).
  The earlier component branch review recorded the defensive rubric-label
  fallback as uncovered; line coverage does not establish branch completeness.
- Backend lint, format, types and import contracts; web lint, format, types,
  build and size; API schema/client consistency; dependency audits; Docker image
  builds; and the real-scanner/media-sandbox job all passed. Synthetic AI smoke
  was path-skipped; no prompts, jobs or provider code changed.

The independent review in this task inspected the exact-head source, assertions
and CI logs. It found no confirmed functional or security defects, and identified
the missing final-head evidence in this record. The reference convention now
distinguishes raw worker-only cache access from the owned, D4-filtered feedback
projection required by FR-BL-10 and UX-02. GitHub reports PR #203 merged on
2026-10-24; this later review does not establish that independent re-review
occurred before that merge.

Evidence limits remain explicit: the historical Red/Green commands above are
the recorded chronology, not independently recovered execution logs. The review
did not rerun application tests because its available checkout was later than
the PR head. Mocked browser tests do not establish live-stack grading latency.
**p95 10 s remains deferred until staging — unverified under #155**; no
functional or security requirement is waived by that deferral.

This follow-up changes documentation only. Under `docs/testing.md`, artificial
Red/Green application tests are not applicable. Validation consists of checking
the recorded SHA, CI job results and counts, reviewing the wording against D4,
and checking Markdown formatting and the diff. The final-head CI above belongs
to PR #203, not to this documentation follow-up.

Follow-up checks: `git diff --check` passes; evidence references, counts and the
staging deferral were checked against the final-head CI logs. Prettier reports
formatting differences in both documents, also reproduced on their unchanged
`main` versions; a whole-file reformat is outside this focused correction.
