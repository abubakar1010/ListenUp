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

ADR 0056 records selection, persistence and database locking. The owners should
verify/synchronize D8 at these existing source lines (they already contain D8
wording in current main): `docs/design/srs.md:63` (C3), `:229` (FR-SH-1), `:439`
(AT-6); `docs/design/database-design.md:438` (table), `:470` (round relationship),
`:733` (rule matrix), `:772` (lock), `:783` (span trigger). The Database Design
DDL additionally needs this migration's finite range checks, composite ownership,
API grants/RLS and immutable lock. Source line references are for this PR's base.

Fresh-session independent review and passing required CI remain owner merge gates.
Final check outcomes and changed-line coverage are recorded in the PR.
