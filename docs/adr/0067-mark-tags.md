# ADR 0067: A mark's tag is a whole value set by its own route and synced like a note

- Status: Proposed in the #61 pull request (2026-10-25). The owner chose the recommended
  options in the plan review (2026-10-25); the ADR is accepted on merge
- Date: 2026-10-25
- Implements: FR-TR-4 (PRD TR-4), UI-4
- Builds on: ADRs 0047 and 0058

## Context

A mark may carry one optional tag: linking, reduction, weak form or unknown word
(FR-TR-4). `practice.marks.tag` and its CHECK of the four values were created with the
table in #58 (ADR 0047), so tags need no migration. The learner sets, changes and clears
the tag from the mark and from the mark list, by mouse and keyboard. ADR 0047 syncs marks
one row at a time with no version, and ADR 0058 added a separate route for the status.
Three choices were open: the route, how the browser sends a change, and the control.

## Decision

- **Its own route.** `PUT /sessions/{id}/marks/{mark_id}/tag` takes `{"tag": <one of the
  four> | null}`; null clears the tag. It is one UPDATE behind the Transcript gate
  (`require_reached`), answering 200 with the mark. The whole tag is sent, so a resend
  answers with the same mark and needs no `run_once`, like the status route. The note
  `PATCH` keeps its contract (`note` required, null clears it) instead of becoming a
  partial update where a missing field and null would mean different things.
- **A create may carry the tag.** `POST /sessions/{id}/marks` takes an optional `tag`, so
  a tag chosen before the first save travels with the create, as a note does. Marks added
  from Dictation start untagged.
- **One refusal code, two layers.** The service checks the value
  (`review/domain/marks.check_tag`) and refuses anything else with 422
  `mark_tag_invalid`; the body field is a plain string so the refusal has its own code
  rather than the generic validation error. A wrong type (a number, a list) is still the
  generic 422. The database CHECK refuses the same values below the API.
- **Synced like a note.** In `MarkSync` the tag is part of the `update` op, sent after
  the 2 s debounce (ADR 0033): a native select changes its value on each arrow key, so
  sending at once would send every choice the learner moves through. A changed tag goes
  after the note and before a confirmation, and each answer becomes the server's version,
  so a failure between them resends only what is left. A refused tag puts back the
  server's tag; offline and signed-out changes stay in localStorage. A copy kept before
  tags has no `tag`, which means no tag change. Changing the tag back before the save
  sends nothing. The last tag saved wins across tabs, as for notes.
- **A native select.** The mark panel has "Tag (optional)" and each list row has "Tag for
  mark {phrase}" (the hidden words name the mark; the visible label starts the name,
  WCAG 2.5.3). The options are No tag, Linking, Reduction, Weak form and Unknown word. The
  browser's own control gives mouse, touch and keyboard operation and reports the chosen
  tag as its state. The list shows the tag in words after the mark's origin ("Your mark ·
  Weak form"), and a tagged word's description names it ("Marked Tag: Weak form"), so the
  tag never rests on the list control alone.

## Consequences

A mark with a note, a tag and a confirmation waiting can take three requests in one
flush; marks are few per session, so this is accepted rather than merging the routes.
Card and Shadow can read `tag` from `review.service`; neither uses it yet, and no tag is
set automatically (out of #61's scope).
