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

Migration `57_transcript_corrections` creates the correction table already specified
in Database Design §4. Each row is keyed by learner, cache-row ID and local word
index, with own_rows RLS, bounded text and cascading account/cache deletion. The
API receives SELECT only; the worker can persist corrections. The editor, dispute
endpoint and re-scoring remain #56, which will supply the write boundary.

After the existing ownership/step gate and complete cache coverage check,
read_passage reads overlays through the learner's request transaction, with an
explicit learner filter as well as RLS. Corrections never modify the shared cache.
Composition preserves passage-global word indices, audio times and original
sentence boundaries even when a replacement removes punctuation or is empty.
The response marks corrected words with `edited`; the screen labels them Edited.
An empty replacement retains an accessible removed-word jump target. Corrections
are included in the learner's export. Review consumes the service result without
querying corrections itself. Marks and completion remain in #58 and later work.

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

Component seek tests assert immediate target assignment, fractional-second precision
and preservation of paused/playing state. They do not measure media resume latency;
injecting a timed media event would only test the injected clock. Chromium tests exercise
real WAV playback and keyboard seeking against mocked HTTP responses. These are not
measurements of deployed storage/network latency. Actual-server NFR-PERF-4 remains
**deferred until staging — unverified**, linked to launch tracker #155 and the story
validation record. No requirement or latency target is weakened.
