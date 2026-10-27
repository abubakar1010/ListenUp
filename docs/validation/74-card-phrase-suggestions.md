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
| `earlier_session` | the learner marked the same phrase in another session (compared lower case, without edge punctuation) |

Suggested marks come first, then the rest; each group keeps audio order. Earlier
phrases come from the learner's newest 100 marks in other sessions, read from at most
5 of those sessions (`review.service.earlier_phrases`); a session whose passage cannot
be read adds nothing. The endpoint is read-only and gated like the card list
(`practice.require_reached(CARD)`).

In the Card step the mark list shows a "Suggested phrases" group before "Other marks",
a line saying suggestions are only a nudge, and, for a chosen suggestion, why it was
suggested. Nothing is preselected and only **Save card** (`POST .../cards`) creates a
card. If suggestions fail to load, the marks are listed as before.

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

See the pull request for the final command results.
