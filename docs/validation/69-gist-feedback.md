# Story #69: gist feedback

Implements FR-BL-5, FR-BL-7, FR-BL-8, FR-BL-10 and FR-DI-3 under ADR 0054 and UX-02.
One story, one PR; the owner merges after passing CI and fresh-session review.
No changes to grading jobs/prompts, cards, Shadow, mark list or mark editing.
No schema migration or provider call is needed.

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

## Final checks

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
- Backend full coverage: in progress. Initial run was stopped after lint autofix
  removed imported fixtures; explicit re-export aliases fixed setup, and the run
  restarted. This was test setup, not a production regression or Red evidence.
- No migration: no database schema changed. OpenAPI exported and client regenerated;
  new GET route registered as Owned in `access_registry.py`.
- Required CI and independent fresh-session review remain before owner merge.

## Deferred performance criterion

**p95 result within 10 s after gist submission: deferred until staging — unverified.**
Track the unchanged target in [launch validation #155](https://github.com/abubakar1010/ListenUp/issues/155).
Measure submission-to-visible-result latency on the actual staging host with the
real grading adapter and a representative workload, including grade.ready delivery.
Synthetic response tests and local browser timing do not establish this target.
This remains a pre-launch gate.
