# 0056: Persist Shadow proposals and enforce their span in PostgreSQL

Status: Accepted (story #77; D8 was approved by product).

## Context

FR-SH-1 and C3 require a segment around the densest marks. D8 allows only the
whole passage for passages from 30 to 60 seconds. The API and database must both
enforce the rule. Rounds, microphones and consent remain #78/#79.

## Decision

`shadow/domain/segment.py` owns the pure validation and densest-window search.
The proposal uses the longest allowed window, up to 90 seconds, maximizing the
number of mark start times inside its half-open span. Equal counts choose the
earliest possible start in integer milliseconds; no marks chooses the passage
start. Sorting and a sliding pointer take O(n log n) time. Timings stay absolute.
Marks are read exclusively through `review.service.list_marks`.

GET resumes the saved segment or persists a first system proposal. PUT replaces
its bounds and records `chosen_by = learner` and the mark count at selection.
Requests serialize on the learner's session row, then recheck the Shadow step,
so concurrent first entry and adjustment cannot overwrite a learner selection.
The row lock also orders selection against session transitions.

The hand-written migration creates `practice.shadow_segments` with a finite,
nonempty 30–90 second span CHECK, a composite session/learner foreign key, RLS,
and explicit API grants. `segments_span` checks passage containment and the
cross-table D8 exception: 60–90 seconds for longer passages, exactly the whole
passage for 30–60 seconds. A CHECK alone cannot read the parent passage.

`segments_lock` refuses every differing update after `locked_at` is set, including
clearing the lock or changing ownership. The API cannot delete segments; parent
session/account deletion still cascades. Future round 1 creation must set
`locked_at` in the same transaction before recording starts. This story tests that
state directly in PostgreSQL and does not create a rounds table or endpoint.

The Shadow screen reuses the passage waveform with optional mode bounds and a
label; its existing default passage behavior is unchanged. It shows no adjustable
handles for short or locked segments. Saved data joins the standard learner export.

## Consequences

The proposal may include fewer than 90 seconds when the passage is shorter, and
has millisecond boundaries when necessary to include a mark at a half-open edge.
Mark counts describe the saved selection, rather than changing while the learner
drags a handle. The future round implementation owns setting the lock, not this
segment screen. Database Design §5/§8.2 owners must synchronize the exact DDL,
grants, composite ownership and strengthened lock; D8 prose is already in main.
