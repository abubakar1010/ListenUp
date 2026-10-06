# Spike #19 (B2): forced alignment of creator captions

- Issue: [#19](https://github.com/abubakar1010/ListenUp/issues/19). Requirements: FR-TX-2, FR-TR-1, NFR-PERF-4. Sources: System Design 5.1, 12.1 (B2); Architecture 5.1, 7.5.
- Decision: [ADR 0033](../adr/0033-speech-models-chosen-by-spikes-b1-and-b2.md).
- Raw results: [`data/b2/`](data/b2/), produced by `spikes/` (`spike-b2`, `spike-compare`, `spike-summary`). Hand-label kit: [`b2-labels/`](b2-labels/README.md).

> **Indicative numbers.** The stage 0 server (#16) does not exist yet. Every number here was measured on the cloud container below and must be rerun on stage 0 before it becomes a commitment. **The hand-labelled boundary check is pending** (see below): the boundary figures here are agreement between systems, not accuracy against a person.

**Machine:** Intel Xeon Processor @ 2.80 GHz, 4 cores, 1 thread per core, 15.7 GB RAM, no GPU, Linux x86_64, Python 3.12.3; one process with 2 threads (`torch.set_num_threads(2)`, `OMP_NUM_THREADS=2`). Run date: 2026-10-05.
**Software:** torch 2.8.0 and torchaudio 2.8.0 (CPU wheels), `torchaudio.functional.forced_align`. Models: torchaudio's `MMS_FA` bundle (multilingual MMS aligner, about 300M parameters, 1.2 GB) and `WAV2VEC2_ASR_BASE_960H` (English wav2vec2 base fine-tuned on LibriSpeech 960 h, 95M parameters, 360 MB).

## Questions and answers

| Question (issue #19) | Answer |
| --- | --- |
| Does wav2vec2 CTC forced alignment run at about 0.2 core-seconds per audio-second or better? | **Yes, with the English base model in 30 s windows and int8 linear layers: 0.177 core-s per audio-s on average, 0.182 at worst**, a third of `small.en` transcription (0.54). Not with `MMS_FA`, the aligner ADR 0028 shipped: 1.19 over a whole passage (5.9 GB peak memory) and 0.58 in windows. |
| Are its word boundaries accurate enough for Transcript sync and Shadow timing? | **Very likely, to be confirmed by the hand labels.** Two independently trained aligners (the English base model and `MMS_FA`) put a word's start and end within one 20 ms frame of each other at the median and within 40 ms at the 90th percentile; 95.6% of boundaries agree within 50 ms. Transcript sync needs about 100 ms (FR-TR-1 highlights the current line; NFR-PERF-4 asks for frame-accurate seeking to a segment). Agreement is not accuracy, so the gate is the hand-labelled check below; phone-level timing for Shadow is spike #20's question. |
| Which alignment model, and does the caption path ship? | **`WAV2VEC2_ASR_BASE_960H`, 30 s windows, int8 (ADR 0033). The caption path ships with YouTube intake, behind its flag (OQ-6)**, on the condition that the hand-labelled mean boundary error is at most 50 ms; if it is not, `MMS_FA` in 30 s windows (0.58 core-s per audio-s) is the fallback, still cheaper than transcribing. |

## Method

**Test clips.** The same 20 passages as B1 ([method](18-b1-transcription.md#method)): 8 LibriSpeech test-clean, 6 test-other, 3 VoxPopuli native and 3 VoxPopuli accented, about 3 minutes each, licence-safe, no YouTube audio. The issue asks for 10 captioned passages; all 20 were aligned, which costs little and doubles the sample. Their reference text stands in for creator captions: written by people, punctuated, and for VoxPopuli not quite verbatim (it skips some false starts, uses digits, and has errors), which is what creator captions are like. Auto-generated captions are out of scope (Architecture 5.1).

**What is aligned.** Each passage's text is aligned to the passage's own audio (the 5 s padding is cut off): creator captions are timed cues, so the product aligns the cues that cover the passage rather than text missing from the audio. Words are folded to the aligner's alphabet (a to z and apostrophe); words with no letters, such as "2009" or "500", cannot be aligned and get no times.

**Settings.** Each model ran over the whole passage in one pass, and in 30 s windows (each window run with 1 s of extra audio on both sides, only the window's own frames kept; `align.py`, `window_bounds`). The English model was also run in 15 s windows and with dynamic int8 quantisation of its linear layers. Every setting ran in its own process so its peak memory is its own.

**Metrics.**
- *Core-s per audio-s*: the process's CPU time across its threads for decoding the emissions and aligning, divided by the passage length. The target is about 0.2 or better (System Design 5.1: about a fifth of transcription).
- *RTF*: wall time divided by audio length.
- *Peak memory*: maximum resident set size of the process (model plus the largest passage).
- *Boundary difference*: for each word, the absolute difference of its start time and of its end time between two sources, matched by text and time (`metrics.boundary_errors_ms`), reported as mean, median, 90th percentile and the share within 50 ms and 100 ms. Against hand labels this is the boundary error; between two systems it is agreement only.

## Results

| Model | Emission | Core-s per audio-s (mean / max) | RTF (mean) | Peak memory | Load | Passages aligned | Words not aligned (digits, symbols) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MMS_FA | whole passage | 1.191 / 1.245 | 0.613 | 5944 MB | 112.9 s | 20 of 20 | 12 of 9444 |
| MMS_FA | 30 s windows | 0.576 / 0.600 | 0.295 | 2654 MB | 3.4 s | 20 of 20 | 12 of 9444 |
| WAV2VEC2_ASR_BASE_960H | whole passage | 0.468 / 0.508 | 0.244 | 4055 MB | 31.9 s | 20 of 20 | 12 of 9444 |
| WAV2VEC2_ASR_BASE_960H | 30 s windows | 0.229 / 0.238 | 0.120 | 1363 MB | 1.2 s | 20 of 20 | 12 of 9444 |
| WAV2VEC2_ASR_BASE_960H | 15 s windows | 0.216 / 0.225 | 0.112 | 1112 MB | 1.0 s | 20 of 20 | 12 of 9444 |
| **WAV2VEC2_ASR_BASE_960H** | **30 s windows, int8** | **0.177 / 0.182** | **0.093** | **1474 MB** | **2.2 s** | **20 of 20** | **12 of 9444** |

Load times over 30 s are first loads from a cold disk cache (each model's first run); later loads take 1 to 3 s. In the JSON of the first three runs (`MMS_FA-whole`, `WAV2VEC2_ASR_BASE_960H-whole`, `WAV2VEC2_ASR_BASE_960H-w30s`) the per-passage `unaligned` field used an earlier, wrong definition (it compared the raw word count with the count after contractions were expanded, giving negative numbers); the table counts words with no letters from the passage texts (`spike-summary`), which is what the aligner skips.

**Boundary agreement** (all 20 passages; each word's start and end; agreement between systems, not accuracy):

| Comparison | Words | Mean | Median | p90 | Within 50 ms | Within 100 ms |
| --- | --- | --- | --- | --- | --- | --- |
| English base: 30 s windows, int8 vs whole passage, full precision | 9466 | 8 ms | 0 ms | 20 ms | 99.2% | 99.4% |
| English base: 30 s windows vs whole passage | 9469 | 6 ms | 0 ms | 20 ms | 99.3% | 99.5% |
| MMS_FA: 30 s windows vs whole passage | 9463 | 3 ms | 0 ms | 0 ms | 99.6% | 99.8% |
| English base (chosen setting) vs MMS_FA (whole passage) | 9466 | 18 ms | 20 ms | 40 ms | 95.6% | 98.8% |
| English base (chosen setting) vs small.en word timestamps | 8838 | 89 ms | 56 ms | 188 ms | 47.0% | 70.6% |
| MMS_FA vs small.en word timestamps | 8839 | 88 ms | 57 ms | 184 ms | 46.1% | 70.8% |

Per set:

| Set | English base (chosen) vs MMS_FA: median / p90 / within 50 ms | English base (chosen) vs small.en: median / p90 / within 100 ms |
| --- | --- | --- |
| test-clean | 20 / 40 ms / 96.4% | 52 / 167 ms / 72.9% |
| test-other | 20 / 40 ms / 96.8% | 53 / 172 ms / 72.7% |
| vp-en | 20 / 40 ms / 93.1% | 65 / 264 ms / 63.6% |
| vp-accented | 20 / 40 ms / 92.9% | 67 / 292 ms / 64.1% |

## Findings

1. **Whole-passage emissions are the cost.** Self-attention grows with the square of the input length, so a 3-minute passage in one pass costs twice the CPU and three times the memory of 30 s windows, and the boundaries do not move (99.3% within 50 ms; 99.6% for `MMS_FA`). 15 s windows save only 6% more, so 30 s is kept.
2. **int8 is free accuracy-wise.** Dynamic int8 quantisation of the linear layers cuts another 23% of CPU and leaves 99.2% of boundaries within 50 ms of the full-precision whole-passage run. Its effect on the per-letter posteriors that Shadow's measures use is for spike #20 to check.
3. **The English model is in domain for LibriSpeech.** `WAV2VEC2_ASR_BASE_960H` was fine-tuned on LibriSpeech's training set (not the test sets used here). On VoxPopuli, out of its domain, its agreement with `MMS_FA` drops from about 96.5% to 93% within 50 ms: a small loss, and one of the hand-labelled windows is accented VoxPopuli speech to measure it.
4. **Whisper's own word times are coarser** (median 56 ms from either aligner, p90 about 190 ms, worse on VoxPopuli), so the transcription path keeps aligning its transcript for the reference profile (System Design 5.1) rather than relying on Whisper's timestamps where precise boundaries matter.
5. **Numbers written in digits get no times.** 12 of 9,444 caption words (0.13%, all in VoxPopuli: "2009", "500") contain no letters, so the aligner leaves them out (ADR 0028's port already reports them as missing). Transcript sync should give such words the gap between their aligned neighbours; a follow-up for the transcript story.
6. **`torchaudio.functional.forced_align` is deprecated and removed in torchaudio 2.9.** The worker image already pins torchaudio below 2.9, and the `MMS_FA` path used the same function, so nothing changes now; moving to a standalone CTC forced-alignment implementation is a prerequisite for upgrading torchaudio.

## Capacity

Alignment of a 3-minute passage costs about 0.18 x 185 = 33 core-s. System Design 2.2 budgets about 0.5 core-s per audio-s (90 core-s) for the whole reference profile (alignment, sounds, pitch); alignment now takes about a third of that budget, leaving the rest to the sound and pitch analysis spike #20 measures. A captioned YouTube passage needs this alignment instead of transcription plus alignment, saving about 100 core-s per new passage.

## Hand labels (pending)

The issue's spot-check against hand labels needs a person to listen. Three 60 s windows are prepared in [`b2-labels/`](b2-labels/README.md): one test-clean (female reader), one test-other (male reader), one VoxPopuli accented (Spanish accent), about 450 words in all. Each has a Praat TextGrid whose hint tier carries only the reference text of the utterances in the window, with no times from any system, so the labels are independent of every system they measure. Labelling takes about 30 to 40 minutes per window; the README has the steps and the commands that import the labels and add the "vs hand labels" rows here and to ADR 0033.

## Reproduce

```sh
cd spikes   # setup and passage building: README.md
for model in WAV2VEC2_ASR_BASE_960H MMS_FA; do for window in 0 30; do
  .venv/bin/python -m listenup_spikes.b2_align data/passages --model $model --window-s $window \
    --threads 2 --out data/results/b2 --words-out data/results/words
done; done
.venv/bin/python -m listenup_spikes.b2_align data/passages --model WAV2VEC2_ASR_BASE_960H \
  --window-s 30 --int8 --threads 2 --out data/results/b2 --words-out data/results/words
.venv/bin/python -m listenup_spikes.compare data/results/words --labels ../docs/spikes/b2-labels \
  --out data/results/b2
.venv/bin/python -m listenup_spikes.summary b2 data/results/b2
```
