# ADR 0033: Speech models chosen by spikes B1 and B2

- Status: Accepted (numbers indicative until rerun on the stage 0 server, #16)
- Date: 2026-10-05
- Source: spikes [#18](https://github.com/abubakar1010/ListenUp/issues/18) (B1) and [#19](https://github.com/abubakar1010/ListenUp/issues/19) (B2); results in [`docs/spikes/18-b1-transcription.md`](../spikes/18-b1-transcription.md) and [`docs/spikes/19-b2-alignment.md`](../spikes/19-b2-alignment.md); [SRS FR-TX-1, FR-TX-2, FR-TR-1, NFR-PERF-2, NFR-PERF-4, NFR-AI-3, OI-2, OI-3](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd); [System Design 2.2, 3.2, 5, 12.1](https://claude.ai/code/artifact/98274889-96ba-4424-afad-c2cd056206e2); ADR 0028

## Context

ADR 0028 shipped the transcription and alignment adapters with placeholder models (`base.en`, `MMS_FA`) until B1 and B2 measured speed and accuracy, and with hand-made contract recordings because the model hosts were unreachable where it was written. System Design 12.1 asks B1 for the Whisper size that meets about 1 core-second per audio-second at an acceptable word error rate, B2 for whether forced alignment of creator captions runs at about 0.2 core-seconds per audio-second with usable word boundaries, and SRS OI-2 for the WER that is "good enough" to score Dictation.

The stage 0 server (#16) does not exist yet. Both spikes ran on a cloud container: Intel Xeon @ 2.80 GHz, 4 cores (1 thread each), 15.7 GB, no GPU, as 2 processes x 2 threads. The test clips are 20 three-minute passages with 5 s of padding: 14 from LibriSpeech test-clean and test-other (public-domain audio, human-verified text) and 6 from VoxPopuli (CC0 European Parliament speeches, native and accented, with imperfect reference text).

## Decision

**Transcription: faster-whisper `small.en`, int8, beam 5, VAD on** (`ai.yaml`).

| Size, beam 5 | Core-s per audio-s, mean / p95 | Dictation WER, LibriSpeech | False marks per 100 words | Peak memory |
| --- | --- | --- | --- | --- |
| tiny.en | 0.10 / 0.12 | 7.7% | 4.4 | 0.5 GB |
| base.en | 0.19 / 0.23 | 5.4% | 2.9 | 0.6 GB |
| **small.en** | **0.54 / 0.66** | **3.9%** | **1.4** | **1.4 GB** |

Every size meets the speed target; `small.en` is the only one that meets the accuracy threshold below, and it costs about half the transcription compute System Design 2.2 assumed. `distil-small.en` was rejected: with faster-whisper's default `condition_on_previous_text` it drops stretches of 20 s or more (54 to 57% WER), and with the setting its model card asks for it is still worse than `base.en` (9.4%). Beam 1 cuts `small.en`'s compute by 32% for +0.1 points of WER; it is the first lever if peak CPU stays high, a one-line change in `ai.yaml`.

**OI-2, the accuracy gate for a transcription model** (part of the golden-set regression, NFR-AI-6), measured with the product's own Dictation normalisation and `score_dictation` on the golden set's human-verified read speech:

- Dictation WER at most 5% pooled, no passage above 10%, and
- at most 2 false marks per 100 words (marks a learner who typed every word right would get).

Real conversational and accented speech is not yet covered by a verified reference (VoxPopuli's text is not verbatim); the golden set gains about five hand-checked real clips before the YouTube path ships.

**NFR-PERF-2 (OI-3): a 10-minute upload is playable within 30 s (p95) of the upload completing**; upload transfer depends on the learner's network and is excluded. The product's own conversion of a 10-minute upload (playback MP4 and peaks in one decode) took 13.2 s for an AAC file and 15.6 s for an MP3 (median of 5), on one core. The transcript of a 3-minute passage keeps System Design 3.2's budget of 2 minutes from playable (measured 54 s mean, 79 s worst, with the other worker busy).

**Alignment: torchaudio `WAV2VEC2_ASR_BASE_960H` (English wav2vec2 base), emissions in 30 s windows, dynamic int8 linear layers** (`ai.yaml`: `window_seconds: 30`, `int8: true`).

| Aligner and setting | Core-s per audio-s, mean / max | Peak memory |
| --- | --- | --- |
| MMS_FA, whole passage (ADR 0028's default) | 1.19 / 1.25 | 5.9 GB |
| MMS_FA, 30 s windows | 0.58 / 0.60 | 2.7 GB |
| English base, whole passage | 0.47 / 0.51 | 4.1 GB |
| **English base, 30 s windows, int8** | **0.177 / 0.182** | **1.5 GB** |

Running a 3-minute passage through the model in one pass is what made alignment expensive (self-attention grows with the square of the length); windows and int8 do not move the boundaries (99.2% within 50 ms of the whole-passage, full-precision run). The two independently trained aligners agree to a median of 20 ms (one frame) and a p90 of 40 ms, 95.6% within 50 ms, a little less on parliamentary speech outside the English model's training domain (93%). The adapter now supports both kinds of torchaudio bundle (the MMS aligner and the English ASR models) through `forced_align`, with optional windows and int8.

**The caption path ships with YouTube intake, behind its feature flag (OQ-6, ADR 0011).** When a video has creator captions, the captions covering the passage are force-aligned instead of transcribed: 0.18 core-s per audio-s against 0.54 for `small.en` (a third, not System Design 5.1's estimated fifth). Condition: the hand-labelled check prepared in `docs/spikes/b2-labels/` must show a mean word-boundary error of at most 50 ms before the flag is turned on; if it does not, `MMS_FA` in 30 s windows (0.58) is the fallback and the path still saves compute.

**Decoding.** Both speech adapters decode audio with ffmpeg (`listenup/ai/providers/audio.py`) and hand samples to the library. faster-whisper 1.2.1's own decoder calls PyAV with an argument PyAV 19 removed, and the lock pairs exactly those versions, so the adapter as written by ADR 0028 failed on every file.

**Contract recordings.** The hand-made `fox` recordings are replaced by real ones made with `scripts/record_ai_contract.py` from a LibriSpeech test-clean utterance (public-domain audio), using the models and options in `ai.yaml`; the script now reads them from there.

## Consequences

- Transcription is the largest per-session compute cost; at about 102 core-s per padded 3-minute passage instead of 180, the System Design 2.2 estimate moves from about 160 to about 175 daily learners per 4-core server, before B2 to B4 refine the rest.
- A media worker process holds both models: at most about 2.8 GB at its peak (1.4 GB for `small.en` plus 1.5 GB for the aligner, measured separately), about 5.6 GB for two processes, within 16 GB. The models download about 0.85 GB on first start, less than the 1.35 GB of ADR 0028's pair. Cold model loads take up to 50 s, which the preload before the ready file already hides.
- Caption words with no letters (numbers written in digits, 0.13% of words in the test set) get no times; Transcript sync gives them the gap between their aligned neighbours.
- `torchaudio.functional.forced_align` is deprecated and removed in torchaudio 2.9. The worker image already pins torchaudio below 2.9; a standalone CTC forced-alignment function replaces it before any upgrade.
- int8 quantisation may change the per-letter posteriors that Shadow's measures read; spike #20 checks them with this setting.
- The Dictation tokenizer does not equate title abbreviations ("Mr" and "mister", "Dr", "St"), which Whisper writes abbreviated; a follow-up in the dictation module removes these false marks.
- Every number is from a cloud container and is rerun on stage 0 with the same harness (`spikes/`) before it becomes a commitment; the ADR is amended if the choice changes.
- Until the three hand-labelled windows are done, the boundary figures are agreement between systems, not accuracy; the labels are added to `docs/spikes/19-b2-alignment.md` and to this ADR.
