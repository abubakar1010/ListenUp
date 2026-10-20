# ADR 0050: Shadow measures model choices and go/no-go

- Status: Proposed for owner review
- Date: 2026-10-20
- Follow-up to: [ADR 0010](0010-self-hosted-speech-pipeline-for-recordings.md)
- Related: [ADR 0034](0034-speech-models-chosen-by-spikes-b1-and-b2.md)
- Evidence: [spike #20](../spikes/20-shadow-measures.md), its per-pair tables,
  controls and pinned [prototype](../spikes/shadow20/README.md)

## Context

The MVP needs seven original-relative speech measures. Cheap self-hosted scoring
is not enough if measures mislabel intelligible speech, confuse missing audio
with missing words, or count an echo as a performance. Accent must be guidance
compared with this speaker and excluded from overall (FR-SH-15).

The stage-0 server (#16) is not available. #20 therefore runs on the managed
container's CPU for ranking evidence only. Its ten independent read-speech pairs
and synthetic degradations are a feasibility set, not a human-shadowing golden
set or a production acceptance evaluation. B2's alignment validation is still
provisional; no historical boundary agreement is promoted to human accuracy.

## Decision

**No-go for shipping this prototype as the seven calibrated self-hosted grades.
Go for further self-hosted research and retaining the isolated reproducible
harness.** Keep ADR 0010's privacy/default decision; this result does not authorize
sending recordings to a hosted service or adding production dependencies.

Candidate choices, not production configuration changes:

- English `WAV2VEC2_ASR_BASE_960H`, int8 linear layers, for word alignment; retain
  ADR 0034's independent boundary-validation gate. Pin torchaudio 2.8.0 until a
  tested replacement for its deprecated CTC aligner exists.
- `facebook/wav2vec2-lv-60-espeak-cv-ft`, pinned to
  `ae45363bf3413b374fecd9dc8bc1df0e24c3b7f4`, for canonical-phone CTC GOP. Keep
  fp32 as the research baseline. The spike separately compares int8 phoneme
  posteriors; do not assume B2's letter-boundary agreement validates GOP.
  Int8 retains the ten-pair majority ranking, but changes pronunciation scores
  by up to 15.44 points and individual phone GOP by up to 6.817 log-ratio units.
  Do not adopt it as equivalent based on this sample. Separate unchanged-setting
  Whisper reruns vary on two poor clips; cache non-GOP evidence when isolating
  precision effects, and keep that instability in the reliability assessment.
- Parselmouth 0.4.7 for voiced pitch contours. Accent remains experimental;
  pitch correlation alone does not assess vowels, consonants and stress.
- Prompted faster-whisper `small.en` int8 for diagnostic transcription only,
  not a validated filler counter or word-presence oracle. Forced alignment alone
  must never prove completeness. Articulation's word-final GOP shares the
  pronunciation model's acoustic and dictionary biases.
- Keep null/unobservable values explicit. Never turn failed alignment/ASR or
  insufficient matched words into perfect fluency. Keep per-word/per-sound raw
  evidence and model/configuration provenance; prototype thresholds are not
  contractually approved good/needs-work/missed thresholds.

## Carry forward

**#21 (B3):** Only the real stage-0 server can pass p50/p95 latency acceptance.
Use 30 actual 75 s rounds with a cached reference profile, warm models, two threads,
no queue, and no feedback generation. Benchmark VAD silence skipping and bounded
windows, one shared phoneme pass per round, and record RSS and exact settings.
This prototype deliberately runs separate word, phoneme and transcription passes;
it is a quality harness, not the one-pass target architecture. Preserve the score
regression set when optimizing or switching precision; any model/quantization
change needs quality evidence as well as speed. Do not transplant container times.

**#22 (B4):** Use 20 independently teacher-labelled recordings with genuine fillers,
compare two/three models or settings, report precision/recall and absolute count
error (AT-17 within one), including lexical “like”/“you know”, accents and pauses.
Prompting alone is not evidence of disfluency retention. Keep the measure labelled
an estimate/unavailable until the unchanged recall and count gates pass; do not
infer precision from known synthetic insertions alone.

**#80:** Keep the provider-neutral port, consent/privacy, eligibility, provenance,
configuration replacement and retry behavior. Contract fixtures must distinguish
missing/unknown from low confidence and retain per-word/per-sound evidence.
Validate boundaries independently, canonical phone inventory and unsupported
symbols, omissions/repetitions, reference-speaker variation and real articulation
errors. Calibrate scores/markers with human labels on independent recordings;
exclude accent from overall. Test clean voices, digital copies/mixes and real
loudspeaker/room echoes before treating a leakage screen as reliable. Reuse the
methods only after #21/#22 and these quality gates; do not copy notebook transforms
into application code as approved scoring policy.

## Consequences

Speech inference remains local with licence-documented public research inputs.
No `listenup` dependencies or API/web code change. A successful aggregate ranking
on synthetic poor speech does not waive individual weak/failing measures, the
natural-shadowing gap, B2's human labels, AT-17 filler accuracy, or real-server
latency. The owner can review the evidence in one unmerged PR and choose the next
research work without misrepresenting this as a production-ready assessment.
