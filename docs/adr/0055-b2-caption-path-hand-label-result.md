# ADR 0055: B2 hand-label result and the caption path

- Status: Accepted (owner, 2026-10-23, taking the recommended option for each decision below)
- Date: 2026-10-22
- Follow-up to: [ADR 0034](0034-speech-models-chosen-by-spikes-b1-and-b2.md)
- Related: [ADR 0039](0039-performance-validation-before-launch.md), [ADR 0037](0037-free-ai-provider-order-and-eligibility.md), [ADR 0050](0050-shadow-measures-model-choices-and-go-no-go.md)
- Evidence: [spike #19](https://github.com/abubakar1010/ListenUp/issues/19), [`docs/spikes/19-b2-alignment.md`](../spikes/19-b2-alignment.md#hand-labels-result-of-the-2026-10-22-run), [`docs/spikes/b2-labels/`](../spikes/b2-labels/README.md); SRS FR-TX-2, FR-TR-1, NFR-PERF-4

## Context

ADR 0034 lets the caption path (force-align creator captions instead of transcribing) ship with YouTube intake, behind its flag (OQ-6), only if the hand-labelled check in `docs/spikes/b2-labels/` shows a mean word-boundary error of at most 50 ms with complete coverage. Its 2026-10-11 amendment made every earlier B2 number historical until regenerated with the corrected harness.

The corrected harness was run on the committed label set on 2026-10-22, and again on 2026-10-23 after review fixes, on the managed cloud container (Intel Xeon @ 2.80 GHz, 4 cores, 15.7 GB, no GPU). Like ADR 0050, this is container evidence only; it says nothing about the stage 0 server.

## Result

- **None of the three windows is labelled.** The TextGrids are the `spike-labelkit make` templates: the `words` tier is empty, only the reference-text `hint` tier has content, and the import writes no label file. A person must label them in Praat; labels made from any model would measure the systems against themselves.
- `spike-compare` reports 0 of 3 windows labelled, 0 words compared, no mean, and `meets_hand_label_gate: false` ([raw report](../spikes/data/b2-v2/spike-19-b2-hand-labels.json)).
- The harness counted only label files that existed, and treated a window with a single labelled word as labelled, so a partly labelled set could pass. It now requires `windows.json`, counts a window as labelled only when its words (and marked `<pause>` intervals) leave no unlabelled stretch over 3 s, and fails the gate while any window is incomplete. It also writes a failing row when there is no model output.

## Decision

1. **The caption path does not ship under ADR 0034's condition: the gate is not met, for want of evidence.** No mean word-boundary error exists. Nothing about the aligner's accuracy is concluded either way; historical system-to-system agreement is not promoted to accuracy.
2. **Keep the alignment model choice provisional and unchanged:** `WAV2VEC2_ASR_BASE_960H`, 30 s windows, int8 (`ai.yaml`), still needed for transcript-path alignment and as ADR 0050's candidate. No production configuration or dependency changes.
3. **The gate stays as written in ADR 0034** (every window labelled, every labelled word matched, mean <= 50 ms). "Labelled" now means covered: no unlabelled stretch over 3 s, with long pauses marked `<pause>`. It is re-run when the labels exist; a new ADR records that result and, if it passes, lets the caption path ship behind the YouTube flag.
4. **Core-seconds per audio-second on the stage 0 server: deferred until staging, unverified** (ADR 0039). The target (about 0.2) and its evidence (the B2 commands in the spike report, run on stage 0) are unchanged and tracked in [#155](https://github.com/abubakar1010/ListenUp/issues/155); it needs [#16](https://github.com/abubakar1010/ListenUp/issues/16). The 0.177 container figure remains historical.

## Consequences

- When YouTube intake is enabled, captioned videos take the transcription path (`small.en` then alignment), as uncaptioned ones do. That costs about 0.54 instead of about 0.18 core-s per audio-s per new passage (historical container figures), with no change in learner-visible behaviour. YouTube intake is behind its flag pending legal review (OQ-6), so this costs nothing today.
- Issue #19 stays open: its hand-label criterion has no result, and its stage 0 criterion is deferred to #155.
- The `MMS_FA` fallback in ADR 0034 is not a way around the gate: it has the same unlabelled evidence, and its noncommercial licence (ADR 0037) blocks unqualified commercial use.

## Owner decisions (2026-10-23)

The owner took the recommended option for each open point.

1. **Labelling.** The owner (or someone they assign) labels the three windows by hand in Praat, following `docs/spikes/b2-labels/README.md`: about 30 to 40 minutes per window, with the audio rebuilt from the public corpora (LibriSpeech test-clean and test-other alone are about 670 MB). The deadline is before YouTube intake's flag is turned on, not before launch of the upload-only path. Until then the caption path stays off.
2. **Sample size.** The three windows (about 450 words, one accented) stay the gate's sample, as ADR 0034 set it. The sample does not grow for this decision. Real conversational and accented speech is covered by the hand-checked clips ADR 0034 already adds to the golden set before the YouTube path ships.
3. **Caption path off, YouTube intake not blocked by it.** Until the gate passes, captioned YouTube videos take the transcription path like any other video. The cost is compute only (about 0.54 instead of about 0.18 core-s per audio-s, historical container figures), with no change for the learner. YouTube intake stays gated only by its own flag and legal review (OQ-6).
4. **No `MMS_FA` fallback.** ADR 0034's `MMS_FA` fallback is withdrawn: its noncommercial licence (ADR 0037) rules it out without a licence review, which is not worth doing for a compute saving. If the labels fail the gate, the caption path stays off, the transcription path stays in use, and any alternative aligner gets its own spike and ADR.
5. **This ADR is accepted** as the record of ADR 0034's caption-path condition. ADR 0034's status line points here.
6. **Numbering.** By the time of acceptance, `main` had 0052 and 0053 and an open branch had claimed 0054 (`feat/55-dictation-words-to-marks`), so this record takes 0055.
