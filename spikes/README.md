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
| #22 B4 fillers | `spike-ami fetch data/fillers`, then `spike-b4 data/fillers --model small.en` (on the Arm runner: the speech-benchmarks workflow, below) | none: 20 AMI windows (CC BY 4.0) fetched from [`b4/ami-windows.json`](b4/ami-windows.json); or your own `NAME.<audio>` with `NAME.fillers` (count) and optional `NAME.marks.json` (timed marks) | recall >= 80% for the chosen setting |
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

## Speech benchmarks on the GitHub Arm runner (exception E4)

The owner's exception E4 ([#119](https://github.com/abubakar1010/ListenUp/issues/119#issuecomment-6559104401))
moves B1 to B4 to GitHub's `ubuntu-24.04-arm` runner. The `Speech benchmarks` workflow
([`.github/workflows/speech-benchmarks.yml`](../.github/workflows/speech-benchmarks.yml)) is
started by hand (Actions, "Run workflow"). It:

1. records the runner facts E4 asks for ([`ci/runner-facts.sh`](ci/runner-facts.sh): `lscpu`,
   `nproc`, `free -b`, `uname -m`, the runner image and the commit);
2. runs [`ci/run-benchmark.sh`](ci/run-benchmark.sh) in `python:3.12-slim-bookworm` with
   `--cpus=2`, `OMP_NUM_THREADS=2` and no swap (memory 12 GB, the runner's limit);
3. refuses to upload any audio, then uploads `results/` (numbers, text, runner facts).

**The repository is public, so its workflow logs and artifacts are public.** Use only
openly licensed audio that may be redistributed, fetched at run time. Never commit audio,
and never use learner, golden-set (#106, #107), YouTube or voice-consent recordings.

A result counts only from **at least three separate runs**: report p50, p95 and the
spread, judge each pass criterion by the worst run, and label it "CI-runner evidence
(E4)" in `docs/spikes/` and the ADR. B3 (#21) and the #233 rerun add their own
`benchmark` choices to the workflow and to `run-benchmark.sh`.

### B4 data: AMI windows

B4's reference is the AMI Meeting Corpus (CC BY 4.0;
[licence](https://groups.inf.ed.ac.uk/ami/corpus/license.shtml)), chosen in
[`docs/spikes/22-filler-corpus-options.md`](../docs/spikes/22-filler-corpus-options.md).
Its manual annotations tag hesitations and discourse markers on time-stamped words, so
`spike-b4` matches each transcribed filler to a marked one (0.5 s tolerance; uh, um and er
are one kind, "like" and "you know" the other) and reports recall and precision per kind.
Every transcribed "like" counts, as a counter that cannot tell the verb apart would.

`ami.py` picks one 75 s window per speaker by a fixed rule, before any model is run:
windows starting at a word onset where the speaker talks at least 60% of the time and at
least five B4 fillers fall inside; the least crosstalk (in steps of 1% of the window), then
the most own speech, then the earliest start; one window per speaker, at most four TNO
(Dutch) speakers, 20 windows. Filler counts are a floor, never maximised.

1. Run the workflow with `b4-ami-manifest`. It downloads the annotation zip (SHA-256 pinned
   in `ami.py`), applies the rule and records each window's audio SHA-256. Commit the
   artifact's `ami-windows.json` as `spikes/b4/ami-windows.json` in a pull request.
2. Run the workflow with `b4` three or more times. Each run fetches the 20 windows by HTTP
   range request (about 48 MB, a 2 s pause between requests), checks every checksum, and
   runs `spike-b4`. The audio stays in the container's `/tmp`.

Attribution: AMI Consortium, AMI Meeting Corpus, CC BY 4.0; the runs use 75 s excerpts of
the headset audio and the manual word and disfluency annotations. AMI's host refuses
Python's built-in HTTP client, so requests go through curl, a command-line download like the
wget command AMI's download page recommends for its large video files. curl keeps its own
identity, and an HTTP error stops the run: no retries or workarounds.

## B5 load test (#94)

`spike-b5` needs Docker (with Compose), `uv`, the `load` extra (`uv sync --extra load`), and the backend dependencies (`cd apps/api && uv sync`). It:

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
4. starts k6 at a wall-clock time it picks (`--start-lead`, default 20 s, after the
   image is pulled), samples `docker stats`, resets pg_stat_statements at the end of
   warm-up and dumps it at the end, and counts the Blind attempts by outcome;
5. deletes the seeded learners (unless `--keep-data`) and the seed manifest.

It writes `results.json`, `results.md` and `requests.csv.gz` (every request: phase,
kind, route, status, duration, k6 error code). The seed manifest holds session tokens:
it lives only in a private temporary folder outside `--out` and is removed however the
run ends. p95 is nearest-rank over every measured request, failed ones included, with a
second p95 over the answered requests; CPU is each container's share of all host cores,
and the server is the API, database and worker together. Sign-in is seeded, not posted:
the per-IP sign-in limit would refuse N learners from one load generator; CSRF uses the
real double-submit check with one fixed token per learner. The exit code is 1 when a
target is missed, more than 1% of reads or writes fail, or less than 95% of the planned
load is delivered (ADR 0065).

A run without `--stage0` is labelled local and is never stage-0 evidence. `--stage0`
needs `--skip-up` and the deployment's `--base-url`. On the stage-0 server, run against
the deployed release candidate (#112) with `--health-url` and `--database-url` (the
database owner: seeding, statements and attempt outcomes) pointing at it too, and the
load generator on another machine where possible (`--k6-network` picks k6's Docker
network). Record the deployment's own CPU if `docker stats` cannot see it. Clean up with
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
