# ADR 0092: Deleting a practice session or one Shadow recording

- Status: Accepted (owner-approved plan, 2026-10-31)
- Related: #90; SRS FR-SH-17, AT-20, NFR-SEC-5; ADRs 0029, 0069, 0070, 0085 and 0087

## Context

Learners must be able to delete their voice recordings on request, either one at a
time or with the session they belong to (FR-SH-17, AT-20). Content deletion
(ADR 0085) already removes whole clips storage-first, with a durable manifest, and
the retention sweep (ADR 0087) already clears expired recordings. The #249 review
found that storage calls must never run while a row lock is held.

## Decision

- **Deleting a session.** `DELETE /sessions/{id}` takes `{"confirm": true}` and
  answers 202 with the `request_id`; repeating it returns the same request.
  It locks the session row (the first lock every mode request takes) and sets the
  barrier `practice.sessions.deleting_at` (migration `90_session_deletion`).
  From then on, session reads and lists, round lookups, the card and saved-mark
  lists, and card audio writers treat the session as gone (404 `session_not_found`
  or `round_not_found`). The clip and the learner's other sessions stay.
- **Storage first, rows second.** The request stores an `ops.deletion_requests` row
  (`scope = 'session'`, at most one open per session) listing the session's Shadow
  prefix `users/<user>/shadow/<session>/` and its card snippet prefixes. The
  `library.delete_session` job (background lane) commits the refreshed list, waits
  for registered card snippet writers (`Reschedule`), deletes the prefixes with no
  transaction open, and only then deletes the session row in a short transaction.
  Steps, attempts, gist grades, marks, cards, segments and rounds cascade. Cached
  idempotent replies naming the session, its attempts or cards are removed before
  and after the delete (ADR 0085). The job sets the barrier again before deleting,
  so an open request still finishes after a schema rollback and upgrade. The
  reconciler re-runs saved lists hourly, so a signed upload that lands late is
  removed too. An exhausted job marks the request `failed` for the scheduler to
  retry. Analytics events survive (ADR 0035).
- **Deleting one recording.** `DELETE /shadow/rounds/{id}/recording` answers 204.
  It reads the round without a lock, deletes the stored file, then runs one
  conditional update that clears `recording_key`, `recording_mime`,
  `recording_bytes` and `uploaded_at` while the round still holds that key. A round
  never recorded answers 409 `recording_not_ready`. A round already cleared, by
  the learner or by retention, answers 204. A failed storage call leaves the key
  for a retry. Voice consent is not required, so withdrawing it never blocks deletion.
- **Trigger rule.** No trigger change is needed. `check_shadow_round` (migration
  `93_shadow_retention`) already accepts exactly one change to a recorded round:
  clearing all four recording columns together while `recorded_at` is unchanged.
  The learner's delete and the retention sweep both make that change. A partial
  clear, a changed or cleared `recorded_at`, and setting a recording again on a
  cleared round are all refused.
- **Progress and grades stay.** The round keeps `recorded_at`, so a completed Shadow
  step stays complete and the three-recordings check still counts the round. The
  future `grading.round_grades` row (#82) is keyed by `round_id` and cascades only
  when the round row is deleted, so it survives a recording delete. Contract for
  #82: the analysis job reads `recording_key` under the round lock, treats NULL as
  "recording deleted" (an unscored grade becomes `unavailable`; it never fetches
  the file again), and never writes recording columns.
- **Withdrawn voice consent** is already enforced by #78/#81: round start
  (ADR 0069) and recording upload (ADR 0070) refuse with 403
  `voice_consent_required` until the current consent is given again, and a pending
  upload is discarded at completion.
- **Browser.** "Delete plan" in Your plans and "Delete recording" beside each replay
  open a confirmation dialog with the safe action focused. A failure keeps the
  dialog open with the error and a retry. Results are announced in a polite status
  region.

## Consequences

Learners control their recordings individually and per session. Like content
deletion, a session deletion is asynchronous, but the session is hidden at once.
Downgrading `90_session_deletion` drops the barrier, so a pending session reappears
until an upgrade, after which its open request finishes.
