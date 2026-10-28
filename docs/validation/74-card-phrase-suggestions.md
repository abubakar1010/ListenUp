# #74 Suggest candidate card phrases from the session's marks

Implements FR-CA-4 (PRD CA-5). Depends on #72 and #61, both merged. No AI is
involved and no migration is needed.

## Behaviour

`GET /api/v1/sessions/{id}/cards/suggestions` returns the session's marks in the
order the Card step offers them. The ordering rule is the pure function
`rank` in `modules/cards/domain/suggestions.py`. A mark is **suggested** when any of:

| Reason | Rule |
| --- | --- |
| `multi_word` | the phrase has two or more words |
| `linking`, `reduction`, `weak_form` | the mark carries that tag (`unknown_word` is not a reason) |
| `earlier_session` | the learner marked the same phrase in a session started before this one (compared lower case, without edge punctuation, with a curly apostrophe read as straight) |

Suggested marks come first, then the rest; each group keeps audio order. Earlier
phrases come from the learner's newest 100 marks in sessions started before this one
(filtered on `user_id` as well as row-level security), read from at most 5 sessions
whose passage could be read (`review.service.earlier_phrases`). A session that cannot
be read, for any reason, is skipped in a savepoint, logged when unexpected, and does
not use up one of the 5 slots, so it never fails the request. The endpoint is read-only and gated like the card list
(`practice.require_reached(CARD)`).

In the Card step the mark list shows a "Suggested phrases" group before "Other marks",
a line saying suggestions are only a nudge, and, for a chosen suggestion, why it was
suggested. Nothing is preselected and only **Save card** (`POST .../cards`) creates a
card. Options use the phrase the endpoint returns. The mark options wait until the
suggestions request settles, so they never regroup while open; if it fails, the marks
are listed as before. "Other marks" is omitted when every mark is suggested.

## Acceptance criteria to tests

| Criterion | Test |
| --- | --- |
| A tagged reduction "a lot of" is shown among the suggestions | `tests/unit/cards/test_suggestions.py::test_tagged_reduction_a_lot_of_is_suggested`; `tests/integration/test_card_suggestions_api.py::test_tagged_reduction_is_among_the_suggestions_and_first`; `CardScreen.test.tsx` "shows a tagged reduction among labelled suggestions, ahead of other marks (FR-CA-4)" |
| No card is created without the learner choosing it | `test_card_suggestions_api.py::test_reading_suggestions_creates_no_card`; `CardScreen.test.tsx` "suggestions choose nothing: no card is created until the learner saves (FR-CA-4)" |

Other cases: each reason alone, plain and `unknown_word` marks, stable audio order,
normalised earlier-phrase match, blank phrase and empty input (`test_suggestions.py`);
`linking`/`weak_form` tags, earlier-session phrase, locked step (409), another learner
(404) and unknown session (404) in `test_card_suggestions_api.py`; the route is
registered in `access_registry.py`. UI: reason text and `aria-describedby`, no group
when nothing is suggested, and fallback to the plain list when suggestions fail.

## TDD evidence

| Cycle | Red (before implementation) | Green |
| --- | --- | --- |
| Ordering rule | `uv run pytest tests/unit/cards` failed: `ModuleNotFoundError: ...cards.domain.suggestions` | 7 passed |
| Endpoint | `uv run pytest tests/integration/test_card_suggestions_api.py -x` failed: `KeyError: 'suggestions'` (route missing, 404) | 8 passed |
| Card step UI | `pnpm vitest run src/features/cards/CardScreen.test.tsx`: 4 new tests failed (no groups, no note, no reason); the fallback test already passed, so it is characterization | 35 passed in `src/features/cards` |

### Review fixes (PR #236 review)

| Finding | Red | Green |
| --- | --- | --- |
| 1 curly apostrophe | `test_earlier_phrase_match_treats_a_curly_apostrophe_as_straight` failed: `['cat', 'don’t'] == ['don’t', 'cat']` | passed |
| 2 later sessions | `test_phrase_marked_only_in_a_later_session_is_not_called_earlier` failed (later session's phrase labelled earlier) | passed |
| 3, 4, 6 limits, skips, learner filter | `tests/unit/review/test_earlier_phrases.py` failed: `other_session_ranges() missing ... 'limit'` | passed: failed sessions skipped without using a slot, sixth readable session never read, `EARLIER_MARKS` passed as the limit |
| 5, 7 one phrase helper, one passage read | `tests/unit/review/test_marks.py` failed: `cannot import name 'mark_phrase'` | passed; existing suggestions tests unchanged and green |
| 7, 8, 9 Card step | 3 new `CardScreen.test.tsx` tests failed (empty "Other marks" group, options before suggestions settle, phrase lost when the transcript fails) | 38 passed in `src/features/cards` |

## Accessibility

- Groups use native `<optgroup label>` inside the existing labelled `select`; the
  reason is a text line linked with `aria-describedby`, so it is not colour-only.
- New axe state `card suggested phrases` (a suggestion chosen) is scanned in all three
  projects (`pnpm e2e:a11y`); the allowlist stays empty.

## Not covered

- Which heuristic suits learners best is a product judgement; the design does not
  specify it, so this keeps the three simple signals above.
- Earlier-phrase matching is exact after normalising, and limited to recent sessions
  to bound transcript reads; it does not match inflections.

## Final checks

| Check | Result |
| --- | --- |
| `uv run pytest -m 'not performance' --cov` (`LISTENUP_REQUIRE_DB=1`) | 2343 passed, 12 skipped (S3 storage was not reachable locally, so S3 integration tests skip; CI runs them with `LISTENUP_REQUIRE_S3=1`) |
| `ruff check`, `ruff format --check`, `mypy`, `lint-imports` | clean |
| `pnpm lint`, `format:check`, `typecheck`, `test:coverage` | clean; 718 tests passed |
| `pnpm build`, `pnpm size` | 126.2 kB gzip of 200 kB |
| `pnpm e2e --project=chromium` | 60 passed |
| `pnpm e2e:a11y` | 190 passed, 2 skipped by design; allowlist empty |
| After review fixes: `pnpm lint`, `format:check`, `typecheck`, `test`, `build`, `size`, `e2e` (all projects) | clean; 721 tests; 126.2 kB; 250 passed, 2 skipped |
| After review fixes: `ruff check`, `ruff format --check`, `mypy`, `lint-imports`, `tests/architecture` | clean |
| After review fixes: `uv run pytest -m 'not performance'` | 2345 passed, 12 skipped (S3 not reachable locally), 2 failed: CPU-budget timing tests in `tests/unit/test_media_sandbox.py`, untouched here, which also fail intermittently on `main` in this container; CI is the judge |

Not run locally: `uv run pytest -m performance --no-cov` and `alembic check` (no schema
change; the local database was not migrated). The existing `card` and `skip card dialog`
axe states and the Transcript keyboard e2e test failed once because their mocks did not
answer the new request; their mocks now do.
