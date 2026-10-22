# ADR 0053: Dictation words are added to the mark list from the stored diff

- Status: Accepted by the owner in the #55 pull request (2026-10-22)
- Date: 2026-10-22
- Implements: FR-DI-6, FR-TR-2 (data), and the data side of FR-TR-3 and AT-4
- Builds on: ADRs 0019, 0021, 0042, 0044 and 0047

## Context

After scoring, the learner adds missed or wrong words to the mark list, one at a time,
a run of words in one action, or all at once, and sees which are already added (#55).
Marks belong to `review` (ADR 0047); `dictation` may reach them only through
`review/service.py` (Architecture 4.3). Every Transcript mark route calls
`require_reached(TRANSCRIPT)` and reads the passage words through `read_passage` to set
`at_ms`. A learner looking at the Dictation result may not have reached Transcript, and
the API has no worker-role read of the cache outside the Transcript routes (ADR 0042,
ADR 0044). Until now the stored diff held word indices but no audio times.

## Decision

- **The diff stores its mark candidates.** `DictationScore.diff_json` adds
  `mark_candidates` (`word_index`, `word`, `status`, `at_ms`, `end_ms`) and the diff
  version becomes 2. Scoring already derived these from the passage word timings (ADR
  0019), so a Dictation mark takes its audio time from the server's own scoring, with no
  second transcript read and no Transcript gate. The candidates are not in any response
  (ADR 0042: the reference text appears only in `result.items`). A version 1 diff has no
  candidates, so its words cannot be added; there are no production rows before launch.
- **Routes.** `POST /dictation/attempts/{id}/marks` takes `{marks: [{id, word_from,
  word_to}]}`, 1 to 2,500 entries (more than the words of a 15-minute passage, so "add
  all" is one request). Each entry is one candidate word, or a run of candidates next to
  each other in the passage (`domain/marks.candidate_range`), at most 20 words (review's
  `check_length`, the same rule as Transcript). The answer is 200 with one mark per entry,
  in order. `GET` on the same path lists the session's marks in audio order. Refusals:
  404 `attempt_not_found` (another learner's attempt, or not Dictation), 409
  `attempt_not_scored` and `mark_id_taken`, 422 `not_a_mark_candidate` and
  `mark_too_long`. One refused entry refuses the request.
- **Through review.** `dictation.service.add_marks` checks the attempt and the candidates,
  then calls `review.service.add_dictation_marks`, which inserts each mark with `source =
  'dictation'` and `status = 'suggested'` (FR-TR-3: the learner confirms or removes it in
  Transcript), with `INSERT ... ON CONFLICT DO NOTHING` and `record_mark_created` for a
  new row only. `review.service.session_marks` lists marks for a caller that has
  authorized the session. Transcript's own routes keep the Transcript gate.
- **No duplicates.** As in ADR 0047, the browser-made id is the idempotency key: a resend
  gives back the same mark. Unlike a Transcript create, words already marked by either
  path give back the mark they have instead of 409 `mark_exists`, because "add all" after
  adding some words, or after marking in Transcript, is the normal case and not a
  conflict. Overlapping ranges are different marks, as in Transcript.
- **Web.** `features/dictation/DictationMarks.tsx`, under the diff in
  `DictationResultPanel`, lists each run (split at 20 words) with an Add button for the run
  and, for runs of two or more words, one for each word; "Add all" adds each run not yet
  added, or only the words of a run that are not added alone (`marks.ts`). Each range
  keeps its id until it is added, so a retry is the same mark. Buttons are native and stay
  focusable once added (`aria-disabled`), and a polite status announces each add (UI-4).

## Consequences

Dictation marks reach Transcript, cards and Shadow as ordinary rows of `practice.marks`.
Transcript shows them through its existing list, and #59 and #60 decide how a suggested
mark is confirmed or removed. A learner who corrects a transcript word (#56) later sees
the phrase of a Dictation mark from the diff, not the correction; the mark keeps its range
and time, which do not change. Adding marks needs no worker-role connection in the
request.
