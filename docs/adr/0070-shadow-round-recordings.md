# ADR 0070: Shadow round recordings, private upload and replay

- Status: Accepted
- Related: #81, ADRs 0005, 0010, 0050, 0063 and 0069
- Owner approved the implementation plan before implementation.

## Decision

Each Shadow round is recorded in the browser from the count-in to the end of the
segment (FR-SH-5), uploaded straight to private storage and replayed beside the
original (FR-SH-8). Per ADR 0050 option a there is no grading yet: completing a
recording marks the round recorded and uploaded, enqueues no analysis and calls no
speech provider (ADR 0010), and the learner sees "Feedback unavailable". Wiring the
analysis job on lane 1 belongs to #80/#82; completing the Shadow plan step is #87.

- **Schema.** `practice.shadow_rounds` gains `recording_key`, `recording_mime`,
  `recording_bytes` and `uploaded_at` (migration `81_shadow_recordings`). Checks
  require the key to sit under `users/<user_id>/shadow/`, the type to be
  `audio/webm` or `audio/mp4`, and the size to be 1 byte to 5 MB. The three recording
  columns are all set or all null. `shadow_rounds_expiry_idx` serves the 90-day
  retention sweep (#93); this story deletes nothing. The `shadow_round_order`
  trigger allows a recording only after playback ended and makes it write-once.
- **Storage keys.** `users/<user>/shadow/<session>/round-<n>-<round id>.<webm|m4a>`.
  The browser only ever receives signed URLs: a PUT bound to the exact type and
  length, and a GET of at most 120 s behind an ownership-checked 307.
- **API.** `POST /sessions/{id}/shadow/rounds/{number}/recording` (type and size
  validated, voice consent re-checked, playback must have ended, repeatable to
  re-sign the same key); `POST /shadow/rounds/{id}/complete` (Idempotency-Key; checks
  the stored object's size and type, deleting a mismatching object);
  `GET /shadow/rounds/{id}/recording`. Another learner gets 404 `round_not_found`.
- **Never blocks the learner.** Playback-ended is independent of the upload, so a
  failed upload or an unsupported browser does not hold the rounds. The browser keeps
  the blob in memory and offers "Retry upload" without recording again; reloading
  loses it, and the round stays played but unrecorded.
- **Browser.** MediaRecorder prefers Opus in WebM and falls back to AAC in MP4
  (Safari). A stopped or interrupted round discards its recording.
- **Replay.** Two labelled native audio controls: the original segment (media
  fragment) and the learner's recording.

## Consequences

Recordings are personal data held for 90 days (retention sweep #93). Grading, the
three-round comparison and plan completion plug into `recorded_at`/`uploaded_at`
later without schema change.
