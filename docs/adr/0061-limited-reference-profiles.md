# ADR 0061: Limited original reference profiles

- Status: Accepted (owner approved story #76's implementation plan on 2026-10-25)
- Date: 2026-10-25
- Implements: #76, FR-SH-4 (basis), FR-SH-9, NFR-AI-5
- Preserves: [ADR 0034](0034-speech-models-chosen-by-spikes-b1-and-b2.md), [ADR 0050](0050-shadow-measures-model-choices-and-go-no-go.md)

## Context

#45 caches original transcripts as non-overlapping, padded media spans. One selected
passage can use several cache rows. The old proposed profile DDL contained phones
and scoring statistics; ADR 0050 instead authorizes word alignment, pitch and
intensity only. Original profiles must be shared without sharing learner corrections
or notifications, and must never gate round playback, recording or completion.

## Decision

Use `content.reference_profiles`, keyed by `(passage_transcript_id, fingerprint)`.
The FK cascades with the original cached span. A passage composes its contributing
rows rather than repeating inference for a different learner or overlapping selection.
Original cache words are immutable through application services. Corrections remain
private overlays and do not change this input or its identity.

The SHA-256 fingerprint covers canonical JSON containing format version 1,
trusted alignment deployment provider/model/version, alignment options, pinned
Parselmouth version and acoustic settings, and decoded audio format. The trusted
version resolver runs before inference; response provenance must match it. Runtime
version changes invalidate reuse. A changed format needs its own schema/format
migration. Existing versioned cache rows remain available to their subscriptions.

Alignment uses the existing gateway and its eligibility, quota and output validation:
`WAV2VEC2_ASR_BASE_960H`, 30-second emission windows and dynamic int8 linear layers.
There is no alignment-policy change, phone pass, GOP, learner analysis or calibrated
score. Missing aligned words stay missing; alignment is not proof of completeness.
ADR 0034's independent boundary-validation gate remains outstanding and unchanged.

Parselmouth 0.4.7 provides deterministic local acoustic extraction inside
`ai/providers/`; this is not a new speech-assessment provider. It is installed in
the media worker's speech extra and in development for real acoustic contract tests.
Persist its actual version, bundled Praat version, settings and format alongside
actual alignment provenance. Its upstream GPLv3 licence remains applicable.

Store only packed word indices, absolute media start/end milliseconds, and confidence
scaled to 0–1000. Store pitch as integer cents relative to 1 Hz and intensity as
integer centidecibels. These are raw Praat measurements, not calibrated speech scores.
Both tracks use centres at `span.lower + 10 + 20*i` ms. SQL NULL explicitly means
unvoiced/unobservable, including window margins and windows too short for analysis;
no zero/perfect score is substituted. Do not raise the pitch floor to analyse a tiny
cache gap. Character and phone units, repeated text and scoring statistics are omitted.

An authorized transcript-ready hook transaction registers a learner-owned
`profile_subscriptions` row and queues missing spans on the intake lane. The queue
key includes transcript id and fingerprint. A session advisory lock additionally
protects inference/cache rechecks against direct concurrent execution. A separate
per-media transaction lock serializes subscriptions and result settlement. Inference
holds no idle database transaction. Successful spans commit independently and survive
other spans' failures/retries.

Store results and update subscribers in one transaction. Publish `profile.ready`
with each affected learner's session id only after all of its padded spans are ready;
`profiled` is passage readiness, never the media conversion stage. Publish
`profile.failed` on permanent/exhausted failure. Notifications roll back with results.
An already-ready shared passage registers readiness without a processing job.
Transient failures use the existing lane retries; operators can retry exhausted jobs.
No partial profile is served as ready. Deleted parents are not recreated, disabled
owners receive no notifications, and remaining active owners can retain shared work.

`transcript.service.reference_profile` checks ownership and reached Shadow before
using the worker-role database. It returns pending/ready/failed, progressive stage
and ready original evidence. The API has no profile-cache grant; subscriptions have
`own_rows`, a same-learner session FK, export inclusion and deletion cascades.
Playback and plan transitions never call this optional grading boundary. Browser
profile events invalidate session queries; future grading UI belongs to its story.

## Consequences and evidence limits

A real configured model/Parselmouth run on a 180-second selected fixture with five
seconds of trailing padding stored 479 words and 9,250 acoustic frames in 35,776
PostgreSQL composite bytes. This is fixture-specific storage evidence, not a hard
size promise for longer passages or arbitrary speech. The fixture concatenates
successive full LibriSpeech utterances from one speaker/chapter and pads silence;
its input cache uses human words with synthetic transcription timings. Alignment,
acoustics, ffmpeg, S3, worker-role persistence and readiness are real in that run.

Mocked boundary tests prove orchestration separately. Neither those tests nor the
real processing run validates human-labelled boundary accuracy or calibrated grades.
Stage-0 performance is **deferred until staging — unverified** under ADR 0039 and
[#155](https://github.com/abubakar1010/ListenUp/issues/155). ADR 0050's launch gates
and the deferred #80 phone-level work remain unchanged.
