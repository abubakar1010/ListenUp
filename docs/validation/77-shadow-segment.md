# Story #77 — Shadow segment proposal

Implements FR-SH-1/C3 and AT-6 (segment portion); D8 is the approved short-passage
exception. No rounds, recording, microphone or consent implementation is included.
Branch: `feat/77-shadow-segment-proposal`, created from main after #188 merged #60.

## Acceptance criteria and tests

| Criterion | Named evidence |
| --- | --- |
| API/database enforce 60–90 seconds | `test_api_refuses_invalid_segment_length`, `test_database_enforces_segment_length`, `test_invalid_segment_refused`; empty/unbounded spans and passage containment included |
| 45-second passage permits only its whole span | `test_45_second_passage_allows_only_whole_passage` (domain/API), `test_database_short_passage_must_be_whole`, `whole 45 second passage has no adjustable handles` |
| Marks at 1:30–2:30 are covered | `test_proposal_covers_90_to_150_second_cluster`, `test_proposal_maximizes_half_open_mark_count`, `test_marks_are_counted_in_proposed_and_adjusted_segment` |
| Segment locked after round 1 starts | `test_locked_segment_refuses_changes`: database sets `locked_at`, rejects span changes and lock clearing; API returns `segment_locked` |
| Keyboard handles | `keyboard handles enforce 60 to 90 seconds and save absolute times`; `e2e/shadow.spec.ts` covers keyboard selection, persistence after reload and 360px layout |
| Related boundaries | `test_shadow_requires_open_step`, cross-learner registry tests, proposal persistence, shortest passages, tie breaking, no marks, save refusal and in-flight save race |

## Actual development evidence

Commands below run in `apps/api` unless prefixed with `apps/web`.

- `uv run pytest tests/unit/test_shadow_segment.py -q`: RED with missing public
  `shadow.domain.segment` interface; GREEN: 13 passed after the pure implementation.
- `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_shadow_segment.py -q`:
  after starting PostgreSQL and correcting the client factory fixture, RED:
  14 failed (missing routes/table). GREEN with schema/API: 14 passed, combined
  with domain tests: 27 passed. Infrastructure/setup failures were not Red evidence.
- `uv run pytest tests/unit/test_shadow_segment.py -q`: new earliest-tie example
  RED: 1 failed, 13 passed (120000 instead of 60001); GREEN: 14 passed after adding
  half-open entry-boundary candidates.
- `apps/web: pnpm vitest run src/features/shadow/ShadowScreen.test.tsx`: initial
  RED was the missing `ShadowScreen` public interface. The first Green attempt
  exposed an unavailable user-event import; tests now use this repository's
  Testing Library `fireEvent`, without a new dependency. A retry-button test
  initially used the wrong existing accessible name and was corrected to “Try again”.
- `apps/web: pnpm vitest run src/features/shadow/ShadowScreen.test.tsx -t 'holds the selected'`:
  RED: handle moved to 1 while saving; GREEN: all six component tests passed after
  guarding edits during an in-flight save.
- Existing passage-picker regression suite plus Shadow component suite: 36 passed
  before the additional race example. Browser tests are additional validation,
  not evidence of a live API/database stack (Playwright mocks the API).

- Audio preview regression: after correcting asynchronous test setup, the replay
  test failed (60 seconds instead of the 10-second segment start). Moving preview
  setup into its own mounted component and replaying from the selection start
  made all seven then-current component tests pass. A peaks rendering example
  adds waveform-load coverage.

## Review and document ownership

ADR 0057 records selection, persistence and database locking. The owners should
verify/synchronize D8 at these existing source lines (they already contain D8
wording in current main): `docs/design/srs.md:63` (C3), `:229` (FR-SH-1), `:439`
(AT-6); `docs/design/database-design.md:438` (table), `:470` (round relationship),
`:733` (rule matrix), `:772` (lock), `:783` (span trigger). The Database Design
DDL additionally needs this migration's finite range checks, composite ownership,
API grants/RLS and immutable lock. Source line references are for this PR's base.

Fresh-session independent review and passing required CI remain owner merge gates.
Final check outcomes and changed-line coverage are recorded in the PR.

## Final verification

- Synced main through `8dd1a67` (#55); no new migration was introduced, so the
  revision remains based on `68_gist_grades`. OpenAPI export and client generation
  after that sync produced no additional diff.
- Post-sync focused backend checks: **230 passed** (Dictation marks/domain,
  Shadow domain/API/database, cross-learner access).
- Backend Ruff format/check, mypy (**187 files**) and all **6** import contracts
  passed. Alembic upgrade/check and downgrade/upgrade passed; the post-sync drift
  check again reported no new operations and one head, `77_shadow_segments`.
- Current-main web suite: **516 passed in 51 files**. Coverage: **95.74% lines**,
  **88.52% branches** overall; **93% changed executable lines** (40/43).
  Coverage completeness resolves every runtime source file. The three uncovered
  changed lines are the existing waveform's pointer dispatch and retry callbacks
  for segment/content loading; keyboard bounds, persistence, refusal and races
  have direct tests. Pointer behavior also runs in the existing picker browser suite.
- Current-main Playwright suite: **42 passed**. Shadow tests additionally use a
  generated WAV with range requests to check replay from the segment start and
  stopping at the segment end. Short-passage checks distinguish segment handles
  from the audio seek slider.
- Web lint, Prettier, TypeScript, production build and size check passed; initial
  JavaScript is **124.7 kB gzip**, below the **200 kB** budget.
- `uv run pytest -m performance --no-cov -q`: **1 passed**, 1,995 deselected.
- The earlier focused boundary/export combination had one export-expiry failure
  (`test_early_expiry_keeps_a_future_job`); its isolated rerun passed. The full
  backend run passed that check; no export expiry code changed.

- Full required-service backend coverage command: **1,964 passed**, 1 deselected,
  no skips, in 837.31 seconds. It started on the #60 baseline before the #55 sync;
  the **230** post-sync focused tests independently covered the newly merged
  Dictation behavior and Shadow/access boundaries. CI reruns the full final tree.
  Changed backend coverage: **100% (122/122 executable lines)**; completeness
  check passes. No changed Shadow executable line is uncovered.

## Review remediation

- Synced current main `58ac0c3`; it adds no migration. Renumbered the Shadow
  decision to ADR 0057 because main now owns ADR 0056 for the B2 caption path.
- Moved session locking into `practice.repository` behind
  `practice.service.lock_session`. Shadow no longer reads practice tables.
  This preserves behavior, so the concurrency examples are characterization,
  not fabricated test-first Red evidence.
- Added `test_concurrent_segment_operations_serialize`, using separate restricted
  API-role transactions and observing PostgreSQL lock waits. Four cases cover
  proposal/proposal, choice/proposal, proposal/choice and skip/choice. Assertions
  check persisted bounds, one row, learner choice preservation and the existing
  `session_closed` refusal after Shadow is skipped.
- Characterization initially passed three cases; the fourth used the wrong
  expected code (`step_locked` rather than `session_closed`). Correcting that
  expectation is test setup correction, not behavioral Red. After the boundary
  refactor, the focused Shadow/session/architecture command passed **57 tests**.
- Mutation validation in an isolated archived copy: removing the original session
  lock made all **four** concurrency cases fail (duplicate insertion or bypassing
  the session transition). The production checkout was not mutated.
- Populated both learners' Shadow segments in
  `test_export_holds_every_learner_table_and_only_the_learners_data`; its focused
  run passed and verifies actual bounds, metadata and exclusion of the other
  learner's segment. This characterizes existing export behavior.
- Synchronized Database Design §5/§8.2 with the accepted migration: finite ranges,
  containment, composite ownership, explicit API grants/RLS and the immutable
  lock, including refusal to clear it. SRS C3/FR-SH-1/AT-6 and UX D8 already agree.
  Documentation renumbering/synchronization changes no behavior and needs no Red.
- Ruff format/check, mypy (187 files) and all six import contracts passed.
  Full final-tree required-service coverage and CI are in progress; their final
  outcomes will be recorded before handoff. Web runtime code is unchanged by this
  remediation; the review's 52 component and five browser checks remain applicable.

## Merge validation refresh (2026-10-24)

- Synced main through `757b19d` (#207, cross-browser resume tests); no production
  code or migration was added by that sync.
- The refreshed dependency scan failed on newly reported high advisories in
  development tooling: Zod `GHSA-mrhx-c7xc-m3w5` and Undici
  `GHSA-xjj6-f33q-929c`. `pnpm audit --audit-level=high` reproduced the failure.
  Updated only the compatible transitive lockfile resolutions: Zod 4.6.5 to
  4.6.7 and Undici 8.11.2 to 8.12.3. The same audit then reported no known
  vulnerabilities. No advisory suppression or threshold change was added.
- The actual audit failure/pass is the regression evidence for this dependency
  maintenance; no artificial application-behavior Red is claimed.
- With those resolutions: web lint, format, types, all **516** coverage tests,
  production build and size passed. Coverage is **95.74% lines / 88.48% branches**;
  initial JavaScript remains **124.7 kB gzip**. All **43** browser tests passed, including the inherited cross-browser resume
  test. Changed web coverage is **93% (40/43)**; final CI outcomes follow on the PR.
- The completed final-tree backend run after review remediation passed **1,999**
  tests with PostgreSQL/S3 required and no skips; performance separately passed.
  Coverage completeness passed and changed backend coverage was **124/124 (100%)**.
  The latest CI additionally checks the cross-browser tests inherited from main.
