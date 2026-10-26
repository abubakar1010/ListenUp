# ADR 0061: Shadow playback rounds before recording

- Status: Accepted
- Date: 2026-10-25
- Related: [ADR 0050](0050-shadow-measures-model-choices-and-go-no-go.md),
  [ADR 0057](0057-shadow-segment-proposals.md)
- Owner approved the #79 implementation plan before implementation.

## Context

FR-SH-2/3 require three numbered repetitions of one segment, with a short count-in
at original speed and text only in round 1. Recording, microphone readiness and
consent, upload and plan completion belong to #78, #81 and #87. Playback must not
manufacture evidence that a recording exists. Reference profiling gates grading,
not rounds (ADR 0050).

## Decision

Persist one row per numbered round in `practice.shadow_rounds`. Each row has
`playback_status` (`ready` or `ended`) independently of nullable `recorded_at`.
Only the playback field changes in #79. There is no successful recording/upload
transition, recording-completed analytics event or `complete_step` call here.
The learner can finish three playbacks while Shadow remains open; the existing
confirmed skip remains available. The UI states that no recording was saved.

The learner starts a numbered round, then activates Play for its three-second
count-in. Playback covers the saved half-open segment at 1x, stops at its end,
and reports playback ended. Advancing to the next numbered round is explicit.
Interruptions, Stop and reload restart the same unended round with a new count-in;
they do not allocate another round. A browser autoplay refusal offers a direct
Play now action after the count-in. Leaving or hiding the page stops playback.

The API locks the parent session before checking `require_step(Step.SHADOW)` and
reading/writing rounds. Round 1 locks the segment in its insert transaction;
this supersedes the older convention assigning that transaction to #78.
PostgreSQL enforces numbers 1–3, uniqueness, generated `transcript_shown`, immutable
round identities and sequential insertion after the preceding playback ended.
The insert trigger uses the same session/segment lock order. Ownership uses a
composite segment/user foreign key, `own_rows` RLS and explicit API grants.

`GET /sessions/{id}/shadow/rounds` returns the current round and text-free history.
It obtains text through `transcript.service` only when the current round is 1,
clipped to the selected segment using absolute word-start times. Round 2/3 state
responses omit `text` entirely and never read the reference transcript. Round
start/end POSTs return bodyless 204 responses, including idempotent replays, so
stored responses cannot later reveal round-1 text. Reads are private/no-store.
The client cancels outstanding round reads and drops its round transcript both
before mutations and again when they settle, before refreshing authoritative
state. It also drops the cache on unmount and hides transcript text during
refreshes and after failed reads; only a successful read can reveal it again.
This governs Shadow responses; the existing learner-owned Transcript review and
export remain available under their existing policies. It cannot revoke text already shown in round 1.

## Consequences

Shadow owns its fixed-speed controls, round status and responsive layout. Its
keyboard policy is Tab to native buttons and Enter/Space to activate them; the
general UX-07 transport shortcuts do not apply to Shadow. Round controls offer
Stop/restart instead of pause, seek or speed changes. Shared
progress, Cards, gist recovery and reference profiling remain outside #79.
Until grading ships, the round UI shows “Feedback unavailable”. Starting a round
does not inspect reference-profile readiness or invoke speech models.

#78 must add working-microphone/consent checks before recording begins. #81 can
attach recording to the count-in/playback lifecycle and add upload metadata and
successful recording state; playback-ended callbacks cannot stand in for that
state. #87 must require real recordings for completion. No prototype grades or
hosted speech provider are enabled.
