# Technical spikes (epic #5)

Benchmark harness for the spikes that decide model sizes, budgets and go/no-go calls before
feature work starts. This is not application code: it has its own dependencies so the heavy
speech libraries stay out of `apps/api`.

**Numbers must come from the stage 0 server (#16), not a laptop or CI.** The harness records
the machine's CPU, core count and memory with every result.

## Setup on the benchmark server

```sh
sudo apt-get install -y ffmpeg          # or the distribution's equivalent
curl -LsSf https://astral.sh/uv/install.sh | sh
cd spikes
uv sync --extra youtube --extra transcribe --extra speech
export OMP_NUM_THREADS=2                # 2 threads per worker process (System Design 5.2)
```

Models download from Hugging Face on first use. Results are written to `results/<spike>.md`
and `.json`; commit the `.md` files and cite them in the spike's ADR.

## The spikes

| Issue | Command | Data you supply | Pass if |
| --- | --- | --- | --- |
| #17 YouTube intake | `spike-youtube urls.txt` | 20 public test videos (one URL per line, optional label); include a private, an age-restricted, a live and an over-length video to test rejections | p95 link-to-playable for 8-12 min clips <= 45 s; rejections detected from metadata |
| #18 B1 transcription | `spike-b1 data/passages --models tiny.en base.en small.en` | 20 x 3-min passages with exact text: build with `spike-librispeech` (below), plus ~5 real clips with hand-checked text | p95 <= 1.0 core-s per audio-s at an acceptable WER |
| #19 B2 alignment | `spike-b2 data/captioned` | 10 passages with caption text; for 3 of them, `NAME.labels.csv` (`word,start_s,end_s`) | <= 0.2 core-s per audio-s; boundary error small enough for Transcript sync |
| #20 Shadow measures | `spike-shadow data/shadow --fillers-model small.en` | 10 folders, each with `original.<audio>`, `original.txt`, `good.<audio>` and `poor.<audio>` (mumbled, late) recorded by consenting team members, not learners | good beats poor on most measures; each measure rated works / weak / fails |
| #21 B3 round latency | same command, 30 learner recordings | as #20 | p95 analysis <= 50 s per round |
| #22 B4 fillers | `spike-b4 data/fillers --model small.en` | 20 recordings, each with `NAME.fillers` holding the teacher-marked filler count | recall >= 80% for the chosen setting |

Build LibriSpeech passages for B1 (public domain read speech):

```sh
curl -LO https://www.openslr.org/resources/12/test-clean.tar.gz && tar xzf test-clean.tar.gz
spike-librispeech LibriSpeech/test-clean data/passages --count 20 --seconds 180
```

#16 (choose the server) and #23 (B6, free AI providers) are desk research: they compare
current provider terms and limits and are recorded as ADRs, not run with this harness.

## What each measure is (prototype)

`shadow_measures.py` holds the seven measures as pure, unit-tested functions over the forced
alignment of the learner and the original:

- **timing**: word-onset deviation after removing the constant shadowing lag, times the speech-rate ratio
- **pronunciation**: mean CTC posterior of spoken words (a proxy; goodness-of-pronunciation replaces it if the spike shows promise)
- **articulation**: confidence of word endings
- **fluency**: pauses longer than the original's at the same place
- **fillers**: fillers per minute from the disfluency-keeping transcription pass
- **completeness**: share of segment words actually spoken
- **accent** (experimental): correlation of the word-level intonation contour with the original's; excluded from the overall score (D11)

An echo check flags recordings where the original leaked from speakers into the microphone.

## Tests

```sh
uv sync && uv run pytest     # metrics, media conversion, rejection rules, measures; no models needed
```
