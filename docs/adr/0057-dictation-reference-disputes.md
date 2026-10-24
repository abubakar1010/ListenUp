# ADR 0057: Learner reference disputes and existing marks

- Status: Accepted
- Date: 2026-10-23
- Source: #56; FR-TX-3, FR-TX-4; ADRs 0008, 0019, 0044, 0047, 0055

## Context

Generated references can be wrong. Learners need to correct a word from the scored
Dictation diff without changing the shared cache, revealing the reference before
submission, or losing marks they already chose to save (#55).

## Decision

- `POST /dictation/attempts/{id}/disputes` accepts a passage-global `word_index`
  and `corrected_text` (0–60 characters). Only an owned, scored Dictation attempt
  may be disputed. The transcript service authorizes the session and maps that
  index to the immutable cache-row/local-word identity; clients cannot name cache
  rows. Empty and multiword replacements keep the original word slot and timings.
- FR-TX-4 follows issue #56's scored-diff correction flow: a dispute happens after
  initial scoring and re-scores that attempt; saved overlays also apply before
  future attempts' initial scoring. The owner approved synchronizing FR-TX-4 with
  this flow on 2026-10-24; no pre-submit editor is introduced.
- Write only the learner's existing `content.transcript_corrections` overlay.
  Migration `56_dictation_disputes` grants API writes under existing own-row RLS;
  the API still cannot read or mutate the shared cache. Cache reads use the existing
  worker connection after ownership and step checks. Shared key-point references
  continue to use original words.
- Re-score the disputed attempt synchronously with pure `score_dictation` using
  the learner's overlays and original submission. Correction, score and the id-only
  `dictation.scored` event commit in the request transaction. A learner-scoped
  transaction advisory lock serializes disputes and initial scoring, including
  different attempts sharing words. Concurrent edits to one word commit in order;
  the last committed replacement wins. Submission keys use `run_once`, so retrying
  an earlier request cannot undo a later correction. The browser retains the key
  after a lost/failed response and starts a new key when the input changes.
  After success it refetches the authoritative result as well: a replayed response
  can predate a newer correction committed in another tab.
- Initial scoring of future attempts uses that learner's overlays. Other already
  scored attempts retain their historical result until explicitly disputed; this
  route re-scores only the named attempt. Transcript reads show current overlays.
- **Preserve existing marks**, including their IDs, source, status, phrase snapshot,
  notes and audio positions. A learner explicitly saved these practice choices;
  correction must not silently remove or rewrite them. Re-scoring replaces the
  attempt's candidates, so newly correct words cannot create new marks. Learners
  can remove saved marks through the existing controls. This decision changes no
  mark status or styling, and does not touch Card or Shadow behavior.
- A content-delete trigger removes only that learner's corrections for that media,
  even while another learner retains its shared cache. Its fixed-search-path,
  non-public security-definer function exposes no cache data and can only run as
  a trigger. Disputes hold a key-share lock on the owned content row through commit,
  so deletion cannot race past an in-flight write and leave an orphan overlay.
  Account deletion retains its existing cascade. Existing export integration
  includes only the requesting learner's correction rows.
- Reuse the existing Transcript `edited` flag and accessible Edited marker.
  Saving invalidates Transcript queries, and `dictation.scored` also refreshes
  them in other tabs; events carry no words or correction text.

## Consequences

Shared transcripts and original grading references remain stable. Corrections
have the same lifetime as the learner's content, including shared-media content.
No correction table duplication, AI call, mark reconciliation or downstream
Card/Shadow rewrite is introduced. A learner's concurrent scoring is serialized
for the short database/scoring transaction. Documentation and generated clients
describe the new route; access-registry, lifecycle and UI tests pin its boundaries.
