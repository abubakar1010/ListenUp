# ADR 0061: Recoverable gist feedback availability

Status: Accepted (owner approved the #70 plan on 2026-10-25).

## Context

FR-BL-11, AT-14 and AT-23 require saved submissions and uninterrupted practice when
AI fails, is slow, or has exhausted its free quota. Feedback availability and the
queue lifecycle are different: a result can arrive after the UI deadline.

## Decision

Submission still commits the gist, Blind completion and grading job together.
`grading.gist_grades.feedback_deadline` stores the current cycle's deadline.
`LISTENUP_GIST_FEEDBACK_TIMEOUT_SECONDS` defaults to 30. A background deadline job
and learner-scoped API reads conditionally change expired `pending` feedback to
`unavailable`. The browser uses the server's remaining `wait_ms`, avoiding clock
skew, and ends its spinner even if later reads stall. These transitions never
change practice progress.

`delayed` means the gateway exhausted eligible fallbacks with at least one quota
admission denial. It takes precedence over the deadline. It does not mean an
ineligible or disabled provider was called. Gist and key-point quota waits use
`Reschedule` with `LISTENUP_GIST_QUOTA_RETRY_SECONDS` (default 60), preserving the
failure budget. Missing key points also postpone grading; manual grading retry
requeues reference preparation through the existing passage service boundary.
`grading.key_point_delays` records quota waiting for the exact shared media,
passage and prompt version, with no reference text. Only workers can access it;
media deletion cascades it away and successful extraction clears it. A gist
waiting for that reference reports delayed when its worker observes the marker.
Other failures retain the existing bounded lane retry policy, then become
`unavailable`; permanent input failures settle immediately.
Exhausted or permanent reference-preparation failure clears its quota marker,
including timeout and stalled-worker settlement. A gist still missing that
reference leaves `delayed` on its next run and applies its original deadline:
`pending` before the boundary, `unavailable` at or after it. The learner can then
retry reference preparation while the waiting grading job is reused. Clearing a
delay never changes a ready grade or extends the feedback deadline.

`POST /grades/{attempt_id}/retry` uses the existing grade primary key. It requires
an owned, submitted Blind attempt, normal consent and CSRF checks. A grade row
lock and the existing per-attempt queue key/lock protect concurrent requests.
Waiting/running work is reused, ready work is unchanged, and settled unsuccessful
work starts one new cycle. The response is always 202 `{ "status": "accepted" }`
after authorization; it contains no learner text. A failed enqueue rolls back
both the new job and cycle state. Old deadline jobs cannot expire a newer cycle.

Workers can save a validated late success from pending, delayed or unavailable.
The conditional ready update and `grade.ready` event stay atomic and idempotent.
The event refreshes grade queries only; it never resets the learner's active step,
Dictation draft or Transcript marks. Existing D4 disclosure stays server-derived.

## Consequences

Unavailable is recoverable feedback state, not cancellation. Retry may be a no-op
while automatic work is already queued or executing. Quota postponement can
continue indefinitely until admission succeeds or the resource is deleted.
No scoring weights, thresholds, prompt versions, provider acceptance rules or
provider enablement change. Fake/offline tests prove recovery mechanics, not
live-model quality or deployment latency.
