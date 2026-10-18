# ADR 0042: Transcript review lines and shared passage playback

- Status: Accepted by the owner in the #57 plan
- Date: 2026-10-18
- Implements: FR-TR-1, FR-TX-5, FR-PL-5, NFR-PERF-4, UI-3, UI-4
- Builds on: ADRs 0021, 0023, 0025 and 0038

## Decision

`review` owns the learner-facing `GET /sessions/{session_id}/transcript` and
Transcript screen. `transcript` owns cache generation and the authorized read
boundary. Review calls `transcript.service.read_passage` with the RLS request
transaction and an explicit, separately configured worker-role database. It never
queries shared cache tables or imports another module's repository. Authentication,
ownership and the step gate precede every privileged read. No database grants change.

Configure `LISTENUP_TRANSCRIPT_READ_DATABASE_URL` with the worker login in production.
The development default uses the local database with `role=listenup_worker`; Compose
sets the container hostname explicitly. Do not point this setting at the API login or
grant that login cache SELECT. This connection is pooled separately and disposed at
application shutdown; normal request transactions still run as the API role.

The response contains session_id, passage, media_url and lines. A line is a logical
sentence from sentence_starts, with a zero-based index, absolute start_ms/end_ms and
words. Each word has a passage-global zero-based index, text and absolute half-open
millisecond timing. Line ends use the latest word end. Sentence grouping survives
cache-span boundaries; visual text wrapping does not create new replay units.
media_url names the existing authenticated media route, never a signed storage URL.
The response is private/no-store. A ready silent passage returns an empty lines array.

Refusals preserve ProblemError codes: 401 not_signed_in; 404 session_not_found
(including another learner), content_not_found; 409 step_locked (with step and
open_step), transcript_not_ready, transcript_failed. Request validation uses the
existing 422 validation_failed handler. Transcript remains readable after completion.
Reading does not start a step or write entry_locked_at: the existing practice
transition sets it when Transcript opens (ADR 0021).

The correction seam is the existing authorized read_passage result. #56 must apply
learner corrections inside that service while cache-row and local-word indices
remain available, before returning the passage. Review groups that result unchanged.
No speculative correction schema, fake corrections or editing/autosave path is added.
Marks and Transcript completion remain in #58 and later review work.

The shared web passage player retains Dictation's transport and control policy.
Compatibility exports preserve its imports; Transcript supplies sentence replay.
Leading silence has no current line; replay chooses the first line. Between sentences
and after the last sentence the preceding line stays current, including at passage
end. Replay and word activation start playback. Ordinary seek preserves paused or
playing state. Positions passed to the transport are passage-relative; displayed
word times stay absolute. Existing speeds are 1x, 0.9x and 0.75x, with pitch preserved.

Transcript keyboard shortcuts match Dictation (Space/K, J, R, brackets) outside
interactive controls. Native controls retain keyboard behavior and shortcut handling
never steals focus. A visible Current line label, structural border and aria-current
accompany colour. The layout wraps at 360 px; highlight updates never move focus.

## Validation limits

Component seek tests measure application scheduling against a controlled media
boundary, including strict rejection of a 300 ms measurement. Chromium tests exercise
real WAV playback and keyboard seeking against mocked HTTP responses. These are not
measurements of deployed storage/network latency. Actual-server NFR-PERF-4 remains
**deferred until staging — unverified**, linked to launch tracker #155 and the story
validation record. No requirement or latency target is weakened.
