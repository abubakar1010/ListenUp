# Technical spikes (epic #5)

Benchmark harness for the spikes that decide model sizes, budgets and go/no-go calls before
public launch. Preliminary runs may inform feature work during development. This is
not application code: it has its own dependencies so the heavy speech libraries
stay out of `apps/api`.

**Launch acceptance numbers must come from the stage 0 server (#16).** Laptop,
container and GitHub-hosted CI results are preliminary and must be labelled with
their actual host. GitHub Actions may orchestrate qualifying runs on the stage-0
server. The harness records the machine's CPU, core count and memory with every
result. Actual-server performance validation is tracked before launch in #155
([ADR 0039](../docs/adr/0039-performance-validation-before-launch.md)); model-quality
requirements are not waived.

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
export PYTHONPATH=../apps/api/src        # production text, Dictation and conversion helpers
```

Run the scripts with `.venv/bin/python -m listenup_spikes.<module>` (or the `spike-*` names
with `uv run --no-sync`), so `uv run` does not remove the CPU torch wheels. B1, B2, Shadow
alignment and the NFR-PERF-2 check import the product's pure helpers through the
`PYTHONPATH` above. B2 uses exactly the production alignment text preprocessing.

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
| #94 B5 load test | `spike-b5 --out results/b5-<host>` (add `--stage0` only on the stage-0 server) | none: seeds its own learners | read p95 < 200 ms, write p95 < 300 ms, server CPU < 30% at 15 req/s plus 20 Blind learners |

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

## B5 load test (#94)

`spike-b5` needs Docker (with Compose), `uv`, and the backend dependencies (`cd apps/api && uv sync`). It:

1. starts PostgreSQL, storage, the migrations, the API and the default worker as the
   Compose project `listenup-b5` (`infra/compose/compose.yml` plus
   [`load/compose.b5.yml`](load/compose.b5.yml): pg_stat_statements preloaded, the
   API as one process without reload, the fake AI configuration, PostgreSQL on port
   55432; no media worker, ClamAV or speech models);
2. seeds `--learners` learners (default 150) with `apps/api/scripts/seed_load.py`: the
   fixture script's clip and a session at each step, an active Blind attempt, a cached
   transcript, `--history` extra clips, a login session, and fresh Blind sessions for
   the first `--blind-learners` (default 20);
3. runs [`load/b5.js`](load/b5.js) in `grafana/k6:1.3.0`: `--mixed-rps` (default 15)
   requests per second of mixed reads and writes at a constant arrival rate, plus the
   Blind learners' heartbeats every 5 s, for `--warmup` (60 s) and then `--duration`
   (600 s) measured;
4. samples `docker stats` and dumps pg_stat_statements, reset at the end of warm-up.

It writes `results.json`, `results.md` and `requests.csv.gz` (every request: phase,
kind, route, status, duration, k6 error code), then deletes the seed manifest, which
holds session tokens. p95 is nearest-rank over every measured request, failed ones
included; CPU is each container's share of all host cores, and the server is the API,
database and worker together. Sign-in is seeded, not posted: the per-IP sign-in limit
would refuse N learners from one load generator; CSRF uses the real double-submit
check with one fixed token per learner. The exit code is 1 when a target is missed.

A run without `--stage0` is labelled local and is never stage-0 evidence. On the stage-0
server, run against the deployed release candidate (#112) with `--skip-up`,
`--base-url`, `--health-url` and `--database-url` pointing at it, and the load
generator on another machine where possible; record the deployment's own CPU if
`docker stats` cannot see it. Clean up with
`docker compose -p listenup-b5 -f infra/compose/compose.yml -f spikes/load/compose.b5.yml down -v`.

`spike-summary b1|b2 <results folder>` prints the tables used in `docs/spikes/`.

`spike-compare` matches ordered text blocks before measuring timing differences; there
is no timing cutoff. Reports include unmatched words and coverage, including missing
passages and sources with zero matches. Boundary-error means describe matched words;
the within-50/100-ms shares include all compared words in the denominator. The hand-label
gate passes only with non-empty, complete label coverage and mean error <= 50 ms.
Inspect text matches for repeated/ambiguous excerpts before accepting the hand-label
result. Agreement between models cannot pass this gate.

The original B2 JSON in `docs/spikes/data/b2/` predates these corrections and remains
historical evidence only. Rebuild the audio and rerun B2 into fresh results/words folders
before using it to validate the production model; see `docs/spikes/19-b2-alignment.md`.

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
