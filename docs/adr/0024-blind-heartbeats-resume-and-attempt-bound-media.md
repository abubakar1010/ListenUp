# ADR 0024: Blind heartbeats, the one resume and attempt-bound media

- Status: Accepted; navigation and whole-clip access are refined by [ADR 0033](0033-design-review-policy-resolutions.md)
- Date: 2026-10-03
- Source: issues #62, #63 and #65; [SRS FR-BL-1 to FR-BL-5, NFR-REL-3](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd); [System Design 9.2](https://claude.ai/code/artifact/98274889-96ba-4424-afad-c2cd056206e2); [Database Design 5](https://claude.ai/code/artifact/ba05f7b3-f881-41e5-86d6-dcb94a509644); ADR 0007; D13, D18; final UI D01 to D04, D07

## Context

ADR 0007 settled that the server enforces Blind with an attempt-bound media URL and 5-second heartbeats, with one automatic resume after an interruption the learner did not cause (D13, D18). The design documents left open:

- how the server checks that the position keeps in step with its clock;
- how it tells a network stall or a device pause from a pause the learner made;
- where it records the resume;
- how the 3 s rewind of the resume passes the check against going backwards;
- how the media URL is bound to the attempt;
- when the gist may be sent.

## Decision

- **The rules are one pure function.** `judge(listen, beat, now)` in `modules/blind/domain/listen.py` returns continue, resume or stop with a void reason. The service locks the attempt's row, judges and writes the result in one transaction. The time is the server's own; tests replace it through the `server_now` dependency.
- **A clock that runs from an anchor.** The anchor is the passage start, or the resume point. The position must stay within 1.5 s ahead of the anchor's clock (`too_fast`) and within 6 s behind it (`interrupted`). The 6 s is D13's 5 s limit plus 1 s for the beat's own trip. Both checks measure from the anchor rather than from the last beat, so small advances do not add up. Waiting the player reports pauses the clock (`buffering_ms`: loading, waiting for data, the resume's wait and count) by moving the anchor time later, up to 20 s per listen.
- **Interruptions are reported by the player and limited by the server.** A beat in the `interrupted` state carries the stop position and the cause:
  - `network`: the player stops after 10 s without an answered beat, then reports when a beat gets through;
  - `device`: a pause the player did not make.

  A beat with `buffering_ms` over the 20 s allowance also counts as a network stall. The first interruption gets the resume, unless it was a device pause of 5 s or more; a second interruption voids. During an unfinished listen, a hidden page (`left_page`), a backward jump or a position outside the passage (`seek`) voids. More than 15 s without a beat (`missed_heartbeat`) voids only when no eligible interruption is reported; an explicitly reported first network interruption is judged before this timeout.
- **The resume moves the anchor.** The server sets `resume_from = max(passage start, stop - 3 s)` and makes it the new anchor, with the clock starting at the grant. The rewind is therefore not a backward jump, and "Carry on now" (final UI D07) cannot run ahead. The resumed listen gets a fresh 20 s allowance. `resume_count` (0 or 1) and `resume_stop_ms` record the resume.
- **`practice.blind_attempts` gains columns** beyond the Database Design, in migration 0009:
  - `media_expires_at`;
  - `passage_start_ms` and `passage_end_ms`, copied at the start so a beat reads one row;
  - `anchor_position_ms` and `anchor_at`;
  - `resume_stop_ms`;
  - the void reason `interrupted`.

  The table keeps the design's checks, its fill factor of 70, `own_rows` and the composite foreign key `(attempt_id, user_id)` to `practice.attempts`.
- **Media bound to the attempt.** Starting an attempt returns `/api/v1/blind/attempts/{id}/media/{token}`. The server stores only the token's SHA-256. The route checks the token, that the attempt is active and that its window is still open. The window is the rest of the passage, plus the waiting still allowed, plus 60 s. The route then redirects to a storage URL signed afresh for exactly the remaining window (`signed_download(..., ttl_seconds=...)`, never cached). Another learner gets 404 `attempt_not_found`, a wrong token gets 404 `media_not_found`, and an ended attempt or window gets 410 `media_expired`.
- **Leaving is reported with `fetch(..., {keepalive: true})`**, not `navigator.sendBeacon`, because every POST needs the `X-CSRF-Token` header. The page sends it on `pagehide` and on `visibilitychange` to hidden. In-app navigation reports it on unmount. A reload finds the unfinished attempt and voids it as `reload`. Once the whole passage has played, a void changes nothing: the gist form is safe to leave.
- **The gist** is accepted only when the last accepted position is within 1 s of the end and the anchor's clock has reached it. It needs three sentences: each ends with `.`, `!` or `?` followed by a space or the end, and has at least 3 words. The same rule is in `domain/gist.py` and the web's `gist.ts`. The gist is at most 2000 characters and is submitted under `run_once`. Submitting finishes the attempt as `submitted` and completes the Blind step. Grading waits for the AI gateway: `GRADE_GIST_JOB` names the seam, and #68 queues it in the same transaction.

## Consequences

- An honest learner on a poor connection gets 20 s of buffering, then one resume, then another 20 s. A client that fakes beats can hold the position still for at most about 6 s, or run at most 1.5 s ahead. Recording the audio elsewhere still cannot be prevented (ADR 0007).
- The rest of the clip's media stays reachable through `GET /media/{id}` (ADR 0022), for example on the clip page. Limiting that while a Blind step is open is a product decision this ADR does not take.
- The step's live state is one row updated every 5 s. Only voids are logged.
- If a Blind attempt's final `ended` beat is lost, the server does not count the listen as complete, and the gist is refused with `listen_incomplete` until the attempt is restarted.
