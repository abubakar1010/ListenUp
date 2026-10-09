# Spike #18 (B1): CPU transcription speed and word accuracy

- Issue: [#18](https://github.com/abubakar1010/ListenUp/issues/18). Requirements: FR-TX-1, NFR-PERF-2, NFR-AI-3, OI-2, OI-3. Sources: System Design 2.2, 3.2, 5, 12.1 (B1).
- Decision: [ADR 0033](../adr/0033-speech-models-chosen-by-spikes-b1-and-b2.md).
- Raw results: [`data/b1/`](data/b1/) (one JSON per setting, every passage), produced by `spikes/` (`spike-b1`, `spike-perf2`, `spike-summary`).

> **Indicative numbers.** The stage 0 server (#16) does not exist yet. Every number here was measured on the cloud container below and must be rerun on stage 0 before it becomes a commitment (System Design 12). The harness records the machine with every result.

**Machine:** Intel Xeon Processor @ 2.80 GHz (model name as reported; no turbo or cache details exposed), 4 cores, 1 thread per core, 15.7 GB RAM, no GPU, Linux x86_64, Python 3.12.3. Run date: 2026-10-05.
**Software:** faster-whisper 1.2.1, CTranslate2 4.8.2, PyAV 19.0.1 (unused, see finding 1), ffmpeg from the distribution. Models: Systran `faster-whisper-{tiny,base,small}.en` and `faster-distil-whisper-small.en` from Hugging Face.

## Questions and answers

| Question (issue #18) | Answer |
| --- | --- |
| Which faster-whisper English size (int8, silence skipped) meets about 1 core-second per audio-second with an acceptable word error rate? | **`small.en`, int8, beam 5, VAD on.** 0.54 core-s per audio-s on average and 0.66 at p95: every size meets the speed target, and `small.en` is clearly the most accurate (3.9% Dictation WER on human-verified read speech against 5.4% for `base.en`). It costs about half the transcription budget System Design 2.2 assumed. |
| What WER is "good enough" for Dictation scoring (OI-2)? | **A transcription model is good enough when, on the golden set's human-verified read speech, its Dictation WER is at most 5% and it produces at most 2 false marks per 100 words** (marks a learner who typed every word right would get). `small.en` passes (3.9%, 1.4); `base.en` fails (5.4%, 2.9). See [the threshold](#oi-2-the-wer-threshold) for why, and its limits on real speech. |
| NFR-PERF-2: content added to playback-ready for a 10-minute clip | **Proposal: playable within 30 s of the upload finishing (p95)**, and the transcript of a 3-minute passage within 2 minutes of playable. Measured: the product's conversion of a 10-minute upload takes 13 to 16 s; a 3-minute passage transcribes in 54 s on average (79 s at worst) while the other worker process is busy. See [NFR-PERF-2](#nfr-perf-2). |
| Word-level timestamp quality | `small.en`'s word boundaries are a median 56 ms from the forced aligners' (p90 about 190 ms; 47% within 50 ms, 71% within 100 ms), worse on parliamentary speech. Good enough to cut a passage and to highlight a line, not a substitute for forced alignment where exact boundaries matter; see [timestamps](#word-timestamps). |

## Method

**Test clips.** 20 passages of about 3 minutes (180 to 197 s), each with 5 s of real neighbouring speech on both sides (System Design 5.1: the product transcribes the passage plus 5 s padding). All are licence-safe; no YouTube audio was used.

| Set | Passages | Source and licence | Reference text |
| --- | --- | --- | --- |
| test-clean | 8 (4 female, 4 male readers) | LibriSpeech test-clean: LibriVox public-domain audio, text CC BY 4.0 | human-verified |
| test-other | 6 (3 female, 3 male) | LibriSpeech test-other: harder speakers and recordings, same licence | human-verified |
| vp-en | 3 | VoxPopuli `en` test (European Parliament speeches), CC0 | official record, lightly edited |
| vp-accented | 3 (Spanish; Dutch and Slovak; Czech and Finnish accents) | VoxPopuli `en_accented` test, CC0 | transcribed, not verbatim and with errors |

A LibriSpeech passage joins one chapter's utterances in order. No single VoxPopuli test speech runs 3 minutes, so a VoxPopuli passage joins whole consecutive speeches of one debate (agenda item); in both corpora the gaps between segments are removed. `spike-passages` builds the set deterministically from the public downloads (`spikes/README.md`).

**Reference quality matters for reading the table.** LibriSpeech text was checked by people and is the basis for the threshold. VoxPopuli's text is not verbatim: in `vp-accented` the reference itself contains errors (for example it reads "in the libo treat were" where `small.en` hears "if the Lisbon treaty were", which fits the debate, and `tiny.en` and `base.en` hear "if there is one treaty where"), so its WER mixes model and reference errors and penalises the better model as much as the worse. Use the VoxPopuli columns to compare models with each other, not as absolute accuracy.

**Run layout** (as on the server, System Design 5.2): 2 worker processes at once, each with 2 threads (`cpu_threads=2`, `OMP_NUM_THREADS=2`), taking passages from a shared queue, so the timing includes contention for the 4 cores and memory bandwidth. Each process loads the model once; ffmpeg decodes each file to 16 kHz float samples (finding 1), then `transcribe(language="en", beam_size, vad_filter=True, word_timestamps=True)` runs. Every setting ran once over all 20 passages; tiny.en was also measured before a container restart and reproduced within 3% (0.106 and 0.103 core-s per audio-s, identical WER).

**Metrics.**
- *Core-s per audio-s*: the worker's CPU time across its threads plus ffmpeg's decode, divided by the file's length (passage plus padding). This is the System Design 2.2 cost unit; the target is about 1.0 or better.
- *RTF* (real-time factor): wall time divided by audio length, for one passage while the other process is also working.
- *Throughput*: audio seconds transcribed per wall second by the whole server (both processes), model loading included.
- *Peak memory*: maximum resident set size of one worker process.
- *Load*: time to load the model; first loads read from a cold disk cache and are slower (beam 5 ran first).
- *Dictation WER*: word error rate after the product's own Dictation normalisation (`listenup.modules.dictation.domain`: numbers in digits or words, British and American spellings and contractions compare equal), on the words whose midpoint falls inside the passage. Plain WER (lower-case, punctuation removed) is in the JSON; its mean differs from the Dictation WER by at most 0.4 points.
- *False marks per 100 words*: the true text scored with the product's `score_dictation` against the model's transcript as if a learner had typed every word right. Each mark candidate is a transcript error the learner would be blamed for (PRD 8.4).

## Results

Machine as above, 2 processes x 2 threads.

| Model | Beam | Core-s per audio-s (mean / p95) | RTF (mean) | Throughput, audio-s per s | Peak memory per process | Load | Dictation WER, all | False marks per 100 words |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tiny.en | 5 | 0.103 / 0.121 | 0.063 | 26.6 | 527 MB | 11.9 s | 9.6% | 5.5 |
| base.en | 5 | 0.193 / 0.227 | 0.102 | 17.6 | 601 MB | 15.4 s | 7.3% | 3.9 |
| small.en | 5 | **0.536 / 0.655** | 0.280 | 6.4 | 1363 MB | 50.2 s | **6.0%** | **2.6** |
| distil-small.en | 5 | 0.518 / 0.775 | 0.272 | 6.9 | 874 MB | 30.9 s | 56.6% | 5.3 |
| distil-small.en, `condition_on_previous_text=False` | 5 | 0.250 / 0.322 | 0.135 | 14.4 | 716 MB | 1.7 s | 10.4% | 4.9 |
| tiny.en | 1 | 0.064 / 0.070 | 0.036 | 54.0 | 545 MB | 0.9 s | 10.7% | 6.1 |
| base.en | 1 | 0.121 / 0.134 | 0.065 | 29.7 | 601 MB | 1.3 s | 7.6% | 4.2 |
| small.en | 1 | 0.366 / 0.466 | 0.192 | 9.9 | 1411 MB | 2.1 s | 6.2% | 2.9 |
| distil-small.en | 1 | 0.550 / 0.804 | 0.289 | 6.8 | 852 MB | 1.6 s | 54.2% | 8.0 |

Dictation WER per set, pooled over the set's passages (false marks per 100 words in brackets):

| Model | Beam | test-clean | test-other | LibriSpeech pooled | vp-en | vp-accented |
| --- | --- | --- | --- | --- | --- | --- |
| tiny.en | 5 | 4.9% (2.8) | 11.6% (6.7) | 7.7% (4.4) | 8.7% (5.6) | 21.4% (11.4) |
| base.en | 5 | 4.1% (2.1) | 7.3% (4.1) | 5.4% (2.9) | 7.3% (4.3) | 18.0% (9.0) |
| small.en | 5 | **3.2% (1.0)** | **5.0% (2.1)** | **3.9% (1.4)** | 6.3% (4.0) | 17.8% (8.1) |
| distil-small.en, no conditioning | 5 | 8.4% (4.6) | 10.9% (3.3) | 9.4% (4.0) | 9.5% (5.9) | 17.0% (8.9) |
| tiny.en | 1 | 6.3% (3.0) | 11.7% (7.1) | 8.5% (4.7) | 10.1% (6.7) | 23.6% (13.2) |
| base.en | 1 | 4.0% (2.2) | 8.0% (4.7) | 5.7% (3.2) | 7.7% (4.5) | 18.2% (9.5) |
| small.en | 1 | 3.1% (1.2) | 5.2% (2.3) | 4.0% (1.6) | 6.5% (4.0) | 18.3% (9.0) |

Worst single passage on LibriSpeech: `small.en` beam 5 6.7%, `base.en` beam 5 11.3%, `tiny.en` beam 5 16.9%. A learner who typed every word of a LibriSpeech passage right would score at least 96.6% with `small.en` and at least 94.3% with `base.en`.

**What the remaining `small.en` errors are** (LibriSpeech, beam 5): mostly rare names from the books (brahman heard as brahmin 13 times; montfichet, margolotte, gillikins, mombi), writing conventions (mister written "Mr", missus "Mrs", tis "it is", spider webs "spiderwebs"), and three dropped phrases of 7 to 12 words. Ordinary words are rarely wrong.

## Findings

1. **The product adapter could not transcribe as locked.** faster-whisper 1.2.1 decodes a file path through PyAV with an argument (`metadata_errors`) that PyAV 19 removed, and `apps/api/uv.lock` pairs exactly those versions, so every `transcribe(path)` raised `TypeError`. There is no newer faster-whisper. The fix (in this change) decodes with ffmpeg, as the alignment adapter already did, and hands the samples to faster-whisper; the spike measures that path, decode included.
2. **distil-small.en drops speech with the default settings.** With `condition_on_previous_text=True` (faster-whisper's default, and the product adapter's) it skips whole stretches of 20 s or more, giving 54 to 57% WER. With the setting its model card asks for it is 2x cheaper than `small.en` but 2.4x less accurate on LibriSpeech (9.4%) and worse than `base.en`, so it is not a candidate.
3. **Beam 1 is the cost lever.** It cuts `small.en`'s CPU by 32% (0.37 core-s per audio-s) for +0.1 to +0.2 points of WER. Keep beam 5 while compute is plentiful; switching to beam 1 is a configuration change in `ai.yaml` if peak CPU stays high (System Design 5.2's GPU switch point comes later).
4. **Memory is not a constraint.** Two `small.en` processes take about 2.7 GB of the 15.7 GB.
5. **Model loading takes up to 50 s from a cold disk.** The media worker already preloads models before reporting ready (ADR 0028), so no job pays it.
6. **The Dictation tokenizer treats abbreviations as different words.** "Mr" and "mister", "Mrs" and "missus", "Dr" and "doctor", "St" and "saint" do not match, and Whisper writes the abbreviations, so a learner who types the full word gets a false mark. Suggested follow-up (dictation module, not this spike): add these title abbreviations to the normalisation.

## OI-2: the WER threshold

What matters for Dictation is not WER as such but how often the learner is marked wrong for the transcript's mistake. Each false mark is a word the learner is told they missed or mistyped when they did not; it also becomes a mark that Card and Shadow build on. A false mark rate of about 1 to 2 per 100 words is a small share of what a learner at the target level actually gets wrong (a learner at 80 to 90% accuracy has 10 to 20 real marks per 100 words), so it does not change their score materially or swamp their real marks. At about 3 per 100 words or more (`base.en`, `tiny.en`), every 3-minute passage of about 450 words carries a dozen or more false marks, which is enough to make the feedback untrustworthy.

The threshold, applied as the transcription gate of the golden-set regression (NFR-AI-6):

- Dictation WER at most **5%** pooled over the golden set's human-verified read speech, and
- at most **2 false marks per 100 words** on the same passages, and
- no single passage above **10%**.

`small.en` meets all three (3.9%, 1.4, worst 6.7%); `base.en` fails all three (5.4%, 2.9, worst 11.3%).

**Limits.** Real speech is harder: on VoxPopuli's speeches `small.en` scores 6.3% (native) and 17.8% (accented), though part of the accented figure is reference error. The threshold therefore rests on verified read speech only. Before the YouTube path ships, the golden set needs about five real, conversational clips with hand-checked text (our own recordings, as the spikes README asks) so the gate also covers the speech learners will actually bring; until then accented and spontaneous speech is a known accuracy risk, eased by the learner seeing and correcting the transcript in the Transcript step.

## NFR-PERF-2

"Content added to playback-ready, for a clip of 10 minutes" means reaching the *playable* stage (System Design 3.1): the playback file is in storage. Transcription is a later stage (*transcribed*), needed only when Dictation is scored or Transcript opens.

`spike-perf2` built two 10-minute uploads from LibriSpeech audio, an MP3 (128 kbit/s stereo, 44.1 kHz) and an AAC `.m4a` (the same), and ran the product's own conversion command (`listenup.modules.content.ffmpeg.convert_args`: the AAC-LC mono 64 kbit/s faststart MP4 plus the waveform peaks, in one decode) five times each, alone on the machine:

| Upload | Wall time, median (max) of 5 | CPU time |
| --- | --- | --- |
| MP3, 10 minutes | 15.6 s (16.0 s) | about 16 core-s |
| AAC `.m4a`, 10 minutes | 13.2 s (13.3 s) | about 13.5 core-s |

Conversion is single-threaded (ffmpeg's AAC encoder), so it uses one core whatever else runs, and costs about 1.35 to 1.6 core-s per audio-minute; System Design 2.2's estimate of about 15 core-s for downloading and converting a 10-minute clip is about right for conversion alone (13.5 to 16 core-s), so a download adds to it.

Proposal for NFR-PERF-2 (replacing "to confirm after benchmarking"): **a 10-minute upload is playable within 30 s (p95) of the upload completing**: queue wait under 10 s, conversion about 16 s, and the storage write; upload transfer time depends on the learner's connection and is excluded. For the transcript, keep System Design 3.2's budget, now measured: **a 3-minute passage is transcribed within 2 minutes of playable** (measured 54 s mean, 79 s worst, per passage with the other worker busy). YouTube links keep their own budget (45 s link to playable, spike #17).

## Word timestamps

`small.en`'s word times (beam 5, inside the passage) were compared with the two forced aligners from spike #19 on all 20 passages, word by word (start and end, matched by text and time). These are differences between systems; the hand-labelled check of #19 will put an absolute figure on them.

| Compared with | Median | p90 | Within 50 ms | Within 100 ms |
| --- | --- | --- | --- | --- |
| English wav2vec2 aligner (ADR 0033's choice) | 56 ms | 188 ms | 47.0% | 70.6% |
| MMS_FA aligner | 57 ms | 184 ms | 46.1% | 70.8% |

The two aligners agree with each other far more closely (median 20 ms, 95.6% within 50 ms), so most of the difference is Whisper's. On LibriSpeech the median is 52 to 53 ms; on VoxPopuli 65 to 67 ms with a p90 near 280 ms. Whisper's times are good enough to cut a passage to its words and to highlight the current line; where exact boundaries matter (Shadow timing, word-level seeking), the transcript is force-aligned as System Design 5.1 already plans.

## Capacity (System Design 2.2)

System Design assumed transcription costs about 1.0 core-s per audio-s, about 180 core-s per session. Measured with `small.en` beam 5, a 190 s padded passage costs about 102 core-s, so a new-passage session drops from about 555 to about 477 core-s, and the average with 50% reuse from about 420 to about 381 core-s (6.4 core-minutes). At 168 usable core-minutes in the busiest hour that is about 175 learners a day on one 4-core server rather than 160; the other inputs (alignment profile, Shadow rounds) remain estimates until spikes #19 to #21 report.

## Reproduce

```sh
cd spikes   # setup and passage building: README.md
for beam in 5 1; do for model in tiny.en base.en small.en distil-small.en; do
  PYTHONPATH=../apps/api/src .venv/bin/python -m listenup_spikes.b1_transcribe data/passages \
    --model $model --beam-size $beam --processes 2 --threads 2 \
    --out data/results/b1 --words-out data/results/words
done; done
PYTHONPATH=../apps/api/src .venv/bin/python -m listenup_spikes.perf2 data/raw/LibriSpeech/test-clean --out data/results/perf2
.venv/bin/python -m listenup_spikes.summary b1 data/results/b1
```
