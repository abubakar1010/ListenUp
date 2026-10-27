# ADR 0068: Shadow microphone check and voice consent

- Status: Accepted
- Related: #78, ADRs 0048, 0050, 0051 and 0063
- Owner approved the implementation plan before implementation.

## Decision

Reuse the existing numbered round-start HTTP boundary from #79. After locking
and checking the owned session's Shadow step, require the current, unwithdrawn
voice consent through `identity.service.require_voice_consent`, using the app's
settings. Do this before `run_once`, including successful idempotency replays.
Playback-ended writes remain possible after withdrawal; they prove no recording.
No new table, consent mechanism or migration is needed.

The browser asks for microphone access only after an explicit button activation.
Resume the AudioContext during button activation, before awaiting microphone
permission, so a delayed permission prompt cannot consume that activation. Its
analyser reads transient samples locally, without connecting to
speakers, saving audio, using MediaRecorder or sending audio to the server. The
short check requires three audible, non-clipped samples within ten seconds;
pauses between words are allowed. This is an input check, not speech recognition,
recording validation or an assessment of recording quality. A labelled native
meter provides levels; a polite status announces only state changes. Headphones
are advised. Missing, denied, busy, silent and unsupported inputs explain recovery
and point to the existing confirmed Skip Shadow action.

ShadowScreen owns one polite status region for segment changes, microphone
readiness and round playback (UX-22). Standalone round/readiness/player components
fall back to their own region; composed children report status to their owner.
Consent acceptance moves focus to its confirmation instead of adding a live
region. Clear the checkbox selection after a successful grant so a later
withdrawal/refusal returns to unchecked acceptance. Link to the canonical notice
through `DOCUMENTS.voice_recording.path` while embedding the exact versioned text.

Readiness lasts only for this mounted, visible page. After checking, retain the
live input track to detect disconnection or browser muting, but close the analyser's AudioContext.
Release it on retry, cancellation, timeout, page hide and unmount. A late permission
result is stopped if its originating check was cancelled. Reload and returning
from a hidden page require a fresh check. Browser readiness is not server proof
that a microphone exists.

Show the exact current voice text from the existing legal registry. Explicitly
accept its version through `/me/consents`; never preselect the checkbox. Missing
text or failed consent reads fail closed. Refusal at round start clears cached
consent and refreshes both consent records and versions. Settings retains the
existing withdrawal mechanism and the published retention/deletion wording.

## Interface for #81

- `ShadowReadiness.onReady(boolean)` gates numbered start and restored playback
  controls. It currently owns its temporary check stream; it does not expose audio
  samples, a Blob, recording completion or upload metadata.
- #81 should lift stream ownership into a shared lifecycle owner (or release the
  check stream before acquiring its recording stream), then connect recording to
  `ShadowRoundPlayer`'s count-in/playback lifecycle. It must validate a live input
  immediately before capture rather than persist this page-local readiness flag.
- Before every capture, including a restarted/restored existing round, await
  `POST /sessions/{id}/shadow/rounds/{number}/start`. Its existing bodyless 204
  authorizes that boundary, including replays; 403 `voice_consent_required`
  returns to the current notice. A previous success is not lasting authorization.
- Upload/finalization needs its own ownership and consent policy; this change
  introduces no recording, upload or replay endpoints. Playback-ended does not
  populate `recorded_at`, emit recording completion or complete the plan.
- Keep Feedback unavailable until ADR 0050's quality gates pass. Input readiness
  and current consent do not authorize grading or a hosted speech provider.
