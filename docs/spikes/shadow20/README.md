# #20 CPU quality prototype

This is a research harness, not the speech-assessment provider. It imports no
`listenup` code and has an independent environment. The three CMU ARCTIC speakers
read matching prompts independently: these are read-speech proxies for a good
shadow, **not people recorded while following playback**. Poor recordings are
synthetic modifications of those independent readings. No learner recordings,
YouTube media, hosted speech inference, or committed audio/weights.

## Reproduce

Run from repository root; requires Python 3.12, `uv` and ffmpeg with `flite`.
Use the inherited proxy and TLS configuration. If any model download is denied,
stop and report the destination host; do not change routing or TLS verification.
All paths below are scratch paths, not application dependencies.

```sh
uv venv work/shadow20/venv
uv pip install --python work/shadow20/venv/bin/python -r docs/spikes/shadow20/requirements.txt
uv pip install --python work/shadow20/venv/bin/python \
  --index-url https://download.pytorch.org/whl/cpu -r docs/spikes/shadow20/cpu-requirements.txt
work/shadow20/venv/bin/python docs/spikes/shadow20/fetch.py work/shadow20 \
  --whisper-revision d1d751a5f8271d482d14ca55d9e2deeebbae577f
uv pip install --python work/shadow20/venv/bin/python -r docs/spikes/shadow20/dev-requirements.txt
work/shadow20/venv/bin/python -m pytest docs/spikes/shadow20 -q --cov=measures --cov-branch --cov-report=term-missing
work/shadow20/venv/bin/ruff check docs/spikes/shadow20
work/shadow20/venv/bin/ruff format --check docs/spikes/shadow20
OMP_NUM_THREADS=2 work/shadow20/venv/bin/python docs/spikes/shadow20/experiment.py build --data work/shadow20
OMP_NUM_THREADS=2 work/shadow20/venv/bin/python docs/spikes/shadow20/experiment.py run \
  --data work/shadow20 --out work/shadow20/results-fp32.json
OMP_NUM_THREADS=2 work/shadow20/venv/bin/python docs/spikes/shadow20/experiment.py run \
  --data work/shadow20 --phone-int8 --out work/shadow20/results-int8.json
work/shadow20/venv/bin/python docs/spikes/shadow20/summarize.py \
  work/shadow20/results-fp32.json work/shadow20/results-int8.json
```

`fetch.py` pins source/model revisions, checks SHA256 for the corpus shards and
weights, and writes hashes for all downloaded artifacts. It needs
`huggingface.co`, the CDN hosts returned by its signed redirects (this run:
`us.aws.cdn.hf.co`), and `download.pytorch.org`. The Hugging Face client may also
use `cas-server.xethub.hf.co`/`cas-bridge.xethub.hf.co`; any policy denial is a stop,
not permission to try another route. This run's required downloads succeeded.

`build` chooses the first ten common filenames with at least eight words in
all three speakers. Original/good speaker roles rotate bdl/slt/clb. It uses the
same reference text for every comparison, keeps original and good audio intact,
and makes poor audio by deleting one aligned middle word, filtering at 900 Hz
(sixth-order zero-phase Butterworth), starting 1.2 s late, adding a 0.6 s pause
and inserting flite's synthetic “um uh”. The first two pairs also retain each
single-degradation control. Filler truth is **two intended synthetic tokens**;
there is no teacher-labelled natural filler truth. Inspect the generated filler
WAV before treating it as human ground truth. The manifest records cut intervals,
removed words, source speakers and waveform hashes. The report records failures
rather than adjusting the data or thresholds to make the measures pass.

## Models, measures and provenance

- Word alignment: `WAV2VEC2_ASR_BASE_960H`, dynamic int8 linear layers, CPU,
  torchaudio 2.8.0. These short clips use one window; **not a B2 rerun**.
  Text uses lowercase ASCII letters/apostrophes in whitespace words without
  expanding contractions, matching ADR 0034 on this selected ASCII material.
- Pronunciation: `facebook/wav2vec2-lv-60-espeak-cv-ft`, revision in `fetch.py`,
  CPU fp32 and a separate dynamic-int8 run. eSpeak-NG supplies canonical en-us
  phones. Viterbi CTC aligns those phones to each audio file. Each phone's GOP is
  mean log P(expected) minus log P(strongest competing phone) over its assigned
  frames; blank and special tokens are excluded from competitors. This is a
  CTC GOP approximation, not a validated clinical/teacher pronunciation score.
  Word/sound values are retained. Relative score = 100 exp(min(0, Gshadow−Goriginal)).
  Independent speaker and dictionary mismatch can affect that value.
- Articulation: the same relative GOP calculation on word-final phones. It shares
  errors with pronunciation and does not independently detect every merged sound.
- Timing: matched-word onset lag (first 250 ms allowed), residual timing deviation
  and rate difference. Constant late starts beyond 250 ms are penalized. This
  differs deliberately from the older harness, which removed arbitrary lag.
- Fluency: excess inter-word gaps over the original, with 150 ms tolerance,
  scored exponentially. Restarts are not separately classified.
- Completeness: ordered exact text matches from a separate Whisper hypothesis,
  divided by reference word count. Forced alignment alone cannot prove a word
  was spoken. Ambiguous repeated phrases and ASR errors remain risks.
- Fillers: prompted `small.en`, int8, beam 5, VAD off, conditioning off; regex
  counts um/uh/er/erm/like/you know. Score penalizes rate above the original.
  Lexical “like”/“you know” are not disambiguated; false positives remain visible.
- Accent: experimental word-pitch correlation with the original using Parselmouth
  0.4.7 and actual pitch frame times (60–500 Hz). Fewer than four jointly voiced
  matched words, or constant contours, gives null, never a fabricated zero.
  This is an intonation proxy, not a measure of vowel/consonant accent. Exclude
  it from overall. No overall ship gate is inferred from available-score means.
- Echo: absolute waveform normalized cross-correlation, decimated to 4 kHz,
  within ±1.5 s, screening threshold 0.6. Tests cover copy, clean independent
  voice and digital mixing. This cannot validate loudspeaker/room echo rejection.

Scores are prototype transforms, not calibrated 0–100 learning grades. A missing
measure is missing evidence. No cutoff or formula was tuned against the ten-pair
outcomes. `torchaudio.functional.forced_align` is deprecated and removed in 2.9;
retain the pin until a replacement has independent boundary validation.

## Sources and licences

Audio/text: [CMU ARCTIC](http://www.festvox.org/cmu_arctic/), Kominek and Black,
2003, speakers bdl, slt and clb; distributed by the
[MikhailT mirror](https://huggingface.co/datasets/MikhailT/cmu-arctic/tree/b88ad416e092c4dfdffc6071f4b8e2d057a160f9).
The mirror identifies MIT. Retain the more specific Carnegie Mellon 2003
permission notice in [CMU-NOTICE.txt](CMU-NOTICE.txt), also preserved by
[larynx](https://github.com/rhasspy/larynx/blob/master/licenses/cmuarctic.txt):
use/copy/modify for any purpose without fee, with notice and modification marking.
The upstream server returned 502/503 during this run; the public mirror was used
for audio, through the same proxy. Only these permitted research inputs were used.
All synthetic modifications are identified above and in the manifest.

Phoneme weights: [model card](https://huggingface.co/facebook/wav2vec2-lv-60-espeak-cv-ft),
Apache-2.0; Xu, Baevski and Auli. Word-aligner weights:
[torchaudio bundle documentation](https://docs.pytorch.org/audio/2.8.0/generated/torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.html),
MIT. [faster-whisper small.en](https://huggingface.co/Systran/faster-whisper-small.en),
MIT; conversion of OpenAI Whisper. Parselmouth is GPL-3.0; eSpeak-NG is GPL-3.0;
ffmpeg/flite supplies only the synthetic filler control. No binaries are vendored.

Speechocean762 (SLR101, CC BY 4.0 per OpenSLR, though its HF card says Apache-2.0)
and LibriSpeech were explored/downloaded in scratch while finding matching texts;
**neither contributes to the scored set**. No claim about either corpus's
pronunciation scores is made here.
