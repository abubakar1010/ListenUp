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
uv sync --extra youtube --extra transcribe --extra datasets
# torch and torchaudio from the CPU index: the PyPI wheels bundle CUDA libraries a CPU
# server never uses (as in the worker-media image, ADR 0028)
uv pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.8.*" "torchaudio==2.8.*"
uv pip install praat-parselmouth soundfile
export OMP_NUM_THREADS=2                # 2 threads per worker process (System Design 5.2)
```

Run the scripts with `.venv/bin/python -m listenup_spikes.<module>` (or the `spike-*` names
with `uv run --no-sync`), so `uv run` does not remove the CPU torch wheels. B1 and the
NFR-PERF-2 check use the product's own Dictation rules and conversion command, and B2 and
the Shadow prototype align through the product's wav2vec2 adapter, so they run with
`PYTHONPATH=../apps/api/src`.

Models download from Hugging Face on first use (MMS_FA from dl.fbaipublicfiles.com, the
English wav2vec2 model from download.pytorch.org). Results are written as `.md` and `.json`;
the results documents in `docs/spikes/` quote them and keep the JSON next to them.

## The spikes

| Issue | Command | Data you supply | Pass if |
| --- | --- | --- | --- |
| #17 YouTube intake | `spike-youtube urls.txt` | 20 public test videos (one URL per line, optional label); include a private, an age-restricted, a live and an over-length video to test rejections | p95 link-to-playable for 8-12 min clips <= 45 s; rejections detected from metadata |
| #18 B1 transcription | `spike-b1 data/passages --model small.en --beam-size 5 --processes 2 --threads 2` (one run per setting), then `spike-perf2` | 20 x 3-min passages built with `spike-passages` (below) | p95 <= 1.0 core-s per audio-s at an acceptable WER |
| #19 B2 alignment | `spike-b2 data/passages --model MMS_FA --window-s 0` (one run per setting), then `spike-compare` | the same passages; hand labels for 3 windows (`docs/spikes/b2-labels/`) | <= 0.2 core-s per audio-s; boundary error small enough for Transcript sync |
| #20 Shadow measures | `spike-shadow data/shadow --fillers-model small.en` | 10 folders, each with `original.<audio>`, `original.txt`, `good.<audio>` and `poor.<audio>` (mumbled, late) recorded by consenting team members, not learners | good beats poor on most measures; each measure rated works / weak / fails |
| #21 B3 round latency | same command, 30 learner recordings | as #20 | p95 analysis <= 50 s per round |
| #22 B4 fillers | `spike-b4 data/fillers --model small.en` | 20 recordings, each with `NAME.fillers` holding the teacher-marked filler count | recall >= 80% for the chosen setting |

Build the B1/B2 passages (licence-safe: LibriSpeech is LibriVox public-domain audio with
CC BY 4.0 text, VoxPopuli is CC0). Each is about 3 minutes plus 5 s of real neighbouring
speech on each side, as the product transcribes it (System Design 5.1):

```sh
mkdir -p data/raw && cd data/raw
curl -LO https://www.openslr.org/resources/12/test-clean.tar.gz && tar xzf test-clean.tar.gz
curl -LO https://www.openslr.org/resources/12/test-other.tar.gz && tar xzf test-other.tar.gz
curl -L -o vp_en_test.parquet https://huggingface.co/api/datasets/facebook/voxpopuli/parquet/en/test/0.parquet
curl -L -o vp_acc_test_0.parquet https://huggingface.co/api/datasets/facebook/voxpopuli/parquet/en_accented/test/0.parquet
curl -L -o vp_acc_test_1.parquet https://huggingface.co/api/datasets/facebook/voxpopuli/parquet/en_accented/test/1.parquet
cd ../..
spike-passages librispeech data/raw/LibriSpeech/test-clean data/passages --count 8
spike-passages librispeech data/raw/LibriSpeech/test-other data/passages --count 6
spike-passages voxpopuli data/raw/vp_en_test.parquet data/passages --set vp-en --count 3
spike-passages voxpopuli data/raw/vp_acc_test_0.parquet data/raw/vp_acc_test_1.parquet \
    data/passages --set vp-accented --count 3
```

`spike-summary b1|b2 <results folder>` prints the tables used in `docs/spikes/`.

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
