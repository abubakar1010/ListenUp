# ADR 0053: B2 hand-label result and the caption path

- Status: Proposed for owner review
- Date: 2026-10-22
- Follow-up to: [ADR 0034](0034-speech-models-chosen-by-spikes-b1-and-b2.md)
- Related: [ADR 0039](0039-performance-validation-before-launch.md), [ADR 0037](0037-free-ai-provider-order-and-eligibility.md), [ADR 0050](0050-shadow-measures-model-choices-and-go-no-go.md)
- Evidence: [spike #19](https://github.com/abubakar1010/ListenUp/issues/19), [`docs/spikes/19-b2-alignment.md`](../spikes/19-b2-alignment.md#hand-labels-result-of-the-2026-10-22-run), [`docs/spikes/b2-labels/`](../spikes/b2-labels/README.md); SRS FR-TX-2, FR-TR-1, NFR-PERF-4

## Context

ADR 0034 lets the caption path (force-align creator captions instead of transcribing) ship with YouTube intake, behind its flag (OQ-6), only if the hand-labelled check in `docs/spikes/b2-labels/` shows a mean word-boundary error of at most 50 ms with complete coverage. Its 2026-10-11 amendment made every earlier B2 number historical until regenerated with the corrected harness.

The corrected harness was run on the committed label set on 2026-10-22, on the managed cloud container (Intel Xeon @ 2.80 GHz, 4 cores, 15.7 GB, no GPU). Like ADR 0050, this is container evidence only; it says nothing about the stage 0 server.

## Result

- **None of the three windows is labelled.** The TextGrids are the `spike-labelkit make` templates: the `words` tier is empty, only the reference-text `hint` tier has content, and the import writes no label file. A person must label them in Praat; labels made from any model would measure the systems against themselves.
- `spike-compare` reports 0 of 3 windows labelled, 0 words compared, no mean, and `meets_hand_label_gate: false`.
- The harness counted only label files that existed, so a partly labelled set could have passed on a subset. It now reads `windows.json`, lists unlabelled windows and fails the gate while any remain.

## Decision

1. **The caption path does not ship under ADR 0034's condition: the gate is not met, for want of evidence.** No mean word-boundary error exists. Nothing about the aligner's accuracy is concluded either way; historical system-to-system agreement is not promoted to accuracy.
2. **Keep the alignment model choice provisional and unchanged:** `WAV2VEC2_ASR_BASE_960H`, 30 s windows, int8 (`ai.yaml`), still needed for transcript-path alignment and as ADR 0050's candidate. No production configuration or dependency changes.
3. **The gate stays as written in ADR 0034** (every window labelled, every labelled word matched, mean <= 50 ms), now enforced for partial labelling too. It is re-run when the labels exist; a new ADR records that result and, if it passes, lets the caption path ship behind the YouTube flag.
4. **Core-seconds per audio-second on the stage 0 server: deferred until staging, unverified** (ADR 0039). The target (about 0.2) and its evidence (the B2 commands in the spike report, run on stage 0) are unchanged and tracked in [#155](https://github.com/abubakar1010/ListenUp/issues/155); it needs [#16](https://github.com/abubakar1010/ListenUp/issues/16). The 0.177 container figure remains historical.

## Consequences

- When YouTube intake is enabled, captioned videos take the transcription path (`small.en` then alignment), as uncaptioned ones do. That costs about 0.54 instead of about 0.18 core-s per audio-s per new passage (historical container figures), with no change in learner-visible behaviour. YouTube intake is behind its flag pending legal review (OQ-6), so this costs nothing today.
- Issue #19 stays open: its hand-label criterion has no result, and its stage 0 criterion is deferred to #155.
- The `MMS_FA` fallback in ADR 0034 is not a way around the gate: it has the same unlabelled evidence, and its noncommercial licence (ADR 0037) blocks unqualified commercial use.

## Owner decision points

1. **Who labels the three windows, and when?** About 30 to 40 minutes each in Praat, following `docs/spikes/b2-labels/README.md`. The audio is rebuilt from the public corpora (LibriSpeech test-clean and test-other alone are about 670 MB). Until this happens the caption path cannot ship.
2. **Is three windows (about 450 words, one accented) enough** for the ship decision, or should the sample grow, for example with real YouTube-style conversational speech?
3. **Accept that the caption path is off** until the labels pass, so YouTube intake (when OQ-6 clears) uses transcription for captioned videos too, or **block YouTube intake** until the caption path is validated.
4. **Fallback if the labels fail the gate:** `MMS_FA` is noncommercial (ADR 0037). Choose between another aligner spike, dropping the caption path, or a licence review.
5. **Accept this ADR** (Proposed) as the record of the caption-path condition, and the ADR 0034 status pointer.
6. **ADR number.** 0052 is already used by three open branches (#108, #55, #67), so this record takes 0053; renumber at merge if those land differently.
