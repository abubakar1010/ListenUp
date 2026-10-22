# ADR 0047: Marks are named by the browser and synced one row at a time

- Status: Accepted by the owner in the #58 pull request (2026-10-20); amends ADR 0033
  for marks (no version checks)
- Date: 2026-10-19
- Implements: FR-TR-2, AT-4 (range and audio time), NFR-PERF-3, NFR-REL-1, UI-4
- Builds on: ADRs 0014, 0021, 0025, 0033, 0035 and 0044

## Context

A mark must appear at once, be kept on the device within one second, reach the server
after the 2 s debounce of ADR 0033, and survive a reload, a closed tab and a lost
connection. System Design 3.2 budgets one INSERT per mark. A mark can be changed or
removed before its create has reached the server. The platform rule for submissions
is `run_once` with an `Idempotency-Key`, which adds a row to `ops.idempotency_keys`
for every request.

## Decision

`review` owns `practice.marks` (Architecture: `practice.marks` | review), created as
the full Database Design 5 table so tags (#61) and Dictation pre-fill (#55, #59) add
code without a migration. Rows reference `(session_id, user_id)`, have the `own_rows`
policy and explicit `listenup_api` grants, and are in the data export.

- `POST /sessions/{id}/marks` takes `{id, word_from, word_to, note}`. The browser makes
  the id (a random UUID). The server inserts with `ON CONFLICT DO NOTHING`: one INSERT
  per mark, and a resend of the same id and range answers 200 with the stored mark. The
  id is the idempotency key, so marks do not use `run_once`. Refusals: 409
  `mark_exists` (these words are already marked; carries `mark_id`), 409
  `mark_id_taken`, 422 `mark_out_of_range`, `mark_no_words` (every word in the range
  was removed by a correction), `mark_too_long` (over 20 words) and
  `note_too_long` (over 500 characters after trimming; an empty note is no note).
- The server sets `at_ms` from the start of the first word and takes the phrase from the
  passage words (`transcript.service.read_passage`, with the learner's corrections).
  The phrase reaches analytics only as its keyed pattern (`record_mark_created`, ADR
  0035) and is not stored with the mark.
- `GET`, `PATCH /{mark_id}` (note only) and `DELETE /{mark_id}` complete the set. Every
  route calls `practice.require_reached(TRANSCRIPT)` first; another learner gets 404
  `session_not_found`. A second delete answers 404 `mark_not_found`.
- In the browser, `features/review/markSync.ts` keeps an outbox of per-mark changes in
  localStorage (`listenup:marks:<session id>`), written on every change. It merges the
  changes to one mark before sending (a note travels with an unsent create; an unsent
  removed mark is never sent) and reuses `lib/autosave`'s debounce, failure
  classification, backoff and status text. Marks are per-row with no version: the last
  note saved wins. A refused new mark is taken back with the reason. A refused note
  change or removal puts back what the server holds, so a saved mark never disappears;
  a 401 keeps every change on the device and the next change tries again. A create is
  marked as attempted when it is sent, because its answer may be lost after the server
  stored it: removing such a mark still sends the DELETE (a 404 is fine), and the mark is
  dropped without a request only when no create was ever sent. A resent create answers
  with the mark as the server first stored it, so a note written since then follows as a
  note change. `mark_exists` reloads
  the list, so the other tab's marks, notes and removals show. The saved list is read
  each time Transcript opens and is not kept in the query cache.
- Keyboard (UI-4): on a word, Left and Right move, Shift with an arrow extends the
  selection, M marks it (or opens the note of the mark it already is), Esc clears it.
  Enter and Space keep jumping to the word (ADR 0044). Shift+Arrow grows from the word
  that has the focus. The 20-word limit is also held in the browser: the selection stops
  there and says so. Words can be marked before the audio is ready; only the jump waits.
  A plain click selects the word and jumps to it (#57); Shift+click only extends the
  selection and never moves the audio. While words are chosen the panel sticks below the
  practice header and raises the page's `scroll-padding-top` by its height, so a focused
  word is never hidden behind it (WCAG 2.4.11). With a note editor open it is about 380 px
  tall at 360 px, so it scrolls with the page instead.

## Consequences

A create can be resent any number of times without doubling a mark or an analytics
event, with no idempotency row. A client could choose an id that is already taken;
that is refused and costs nothing else. The primary key spans every learner while
row-level security hides other learners' rows, so an id already used in another account
is refused with `mark_id_taken` too; with random v4 ids this reveals nothing useful and
needs no further handling. Two tabs editing one note overwrite each other
silently, which is acceptable for an optional note.

Owner decisions (2026-10-20):

- M marks; Enter and Space keep jumping to the word, as shipped in #57. One key keeps
  one meaning on a word button, and #57's shortcut stays stable. The UX-07 keyboard map
  in `docs/design/ux-decisions.md` is updated to match.
- "Saved within 1 s" means the local copy within 1 s, with the server save after the
  2 s debounce (SRS NFR-PERF-3 as revised by ADR 0033). Actual-server latency is
  validated at the pre-launch gate (#155).
- A mark covers at most 20 words (`MAX_MARK_WORDS`): a word or a phrase, never a
  paragraph.

Owner decisions (2026-10-22, after the #58 review):

- "One action" (FR-TR-2) is the marking itself, once the words are chosen: M on a
  focused word, or the Mark button after choosing words by pointer. Choosing a word by
  pointer is a separate step, because a plain click keeps its #57 meaning (jump to the
  word) and a phrase has to be chosen before it can be marked.
- This ADR amends ADR 0033 for marks: ADR 0033's version checks protect whole-value
  drafts such as the Dictation draft (ADR 0025), where a stale save would overwrite
  newer text. Marks
  sync one row at a time, so they carry no version and the last note saved wins. SRS
  NFR-PERF-3 names no version check and stays as it is.
- Marks are exempt from the `run_once` rule in `CLAUDE.md`, which names the exemption:
  the browser-made id is the idempotency key.
- When another tab has already marked the same words, `mark_exists` drops this tab's
  unsent mark, including a note typed on it, and shows the other tab's mark. This needs
  two tabs marking exactly the same words before either has synced, and the note is
  optional, so it is accepted rather than merged.
