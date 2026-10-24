# ADR 0057: A Dictation mark is confirmed in place or deleted

- Status: Proposed in the #59 pull request (2026-10-23; Undo amended 2026-10-24 after
  review); the owner accepts it on merge
- Date: 2026-10-23
- Implements: FR-TR-3, the Transcript part of AT-4
- Builds on: ADRs 0047 and 0055

## Context

Marks added from the Dictation diff are stored with `source = 'dictation'` and
`status = 'suggested'` (ADR 0055). In Transcript the learner listens again and confirms
or removes each one (FR-TR-3). Issue #59 left open whether a removed Dictation mark is
deleted or kept with a status for analytics; `practice.marks.status` allows only
`suggested` and `confirmed`.

## Decision

- **Confirm in place.** `PUT /sessions/{id}/marks/{mark_id}/status` with
  `{"status": "confirmed"}` is one UPDATE behind the Transcript gate
  (`require_reached`), answering 200 with the mark. A second confirmation answers with
  the same mark, so no `run_once` is needed. `suggested` is refused (422): a mark never
  goes back to waiting. Refusals: 404 `session_not_found` and `mark_not_found`, 409
  `step_locked`. Manual marks are confirmed from the start, so the call does not
  change them.
- **Remove deletes.** Removing a Dictation mark is the existing
  `DELETE /sessions/{id}/marks/{mark_id}`, as for a manual mark. The row is gone; no
  `removed` status is added. Reasons:
  - A kept row would hold `UNIQUE (session_id, word_from, word_to)`, so the learner could
    not mark the same words again by hand without the removed row coming back.
  - Every reader of marks (the Transcript list and count, the Dictation "already added"
    state, Card's phrase suggestions and Shadow) would have to filter it out, and Card
    and Shadow are built in other stories. One forgotten filter would feed a word the
    learner rejected into their cards.
  - The data export would carry marks the learner removed.
  - The analytics need is already met: `ops.analytics_events` keeps each mark's
    `mark_created` event after the mark is deleted (ADR 0035), and the Dictation diff
    still holds what was missed. A removal event can be added later in analytics
    without changing marks.
- **Web.** `MarkSync` gains an `update` op that covers the note and the status, and a
  `confirm` transport call. Confirming and removing are single actions, so they are
  sent at once, not after the 2 s debounce (saved within 1 s); unsent ones stay in
  localStorage like notes. A Dictation mark shows its source in text: the word's
  description ("Marked from Dictation, to confirm" or "Marked from Dictation"), a
  label in the mark list ("From Dictation · To confirm", "From Dictation" or "Your
  mark"), and a line under the word, dashed while it waits, beside the colour fill.
- **Undo of a removal keeps the source.** Removal is sent at once, so Undo nearly always
  comes after the DELETE. Undo of a Dictation mark therefore adds its words again through
  the existing `POST /dictation/attempts/{id}/marks` (ADR 0055) with the mark's own id,
  not through `POST /sessions/{id}/marks`. The server checks the words against the scored
  diff, so the browser still cannot claim a Dictation source, and no new route is needed.
  The mark comes back `dictation` and `suggested`; its note, and a confirmation made
  before the removal, follow as an update. Words marked again since give back the mark
  they have. If the server refuses to add them again, the mark comes back as the
  learner's own (`manual`, confirmed), so Undo never loses it. Undo before the removal is
  sent cancels it. A manual mark is made again through the Transcript route as before.

## Consequences

Unconfirmed marks stay `suggested` once Transcript is finished; finishing does not
require every mark to be confirmed. Card and Shadow read `status` and decide how to
treat suggested marks. Undo never confirms a mark on the learner's behalf. The
`mark_created` event is unique per mark id, so a mark brought back by Undo is not
counted twice.
