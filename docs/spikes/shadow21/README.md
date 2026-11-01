# B3 ARM CI benchmark

CI-runner evidence (E4), authorized by [owner exception E4](https://github.com/abubakar1010/ListenUp/issues/119#issuecomment-6559104401).

The reusable `benchmarks.yml` accepts `benchmark: b3` through dispatch or
`workflow_call`. Extend the selector/entrypoint for #22, #232 and #233 rather than
silently running B3 for unknown names. No other benchmark is implemented here.
The path-filtered pull-request trigger permits running this new workflow before
it exists on main. Each synchronize event is a separate workflow run, not a
matrix replicate. It runs the PR head SHA and records it in the artifact.

Public data/model revisions and hashes come from `../shadow20/fetch.py`.
The CMU notice in `../shadow20/CMU-NOTICE.txt` applies. Audio is modified by
concatenation only; none is committed or uploaded. Artifacts contain JSON only.
The benchmark container has 2 CPUs, 8 GiB memory, equal memory-swap (no swap),
OMP/BLAS threads 2, torch intra/inter-op threads 2, Whisper CPU threads 2 and
one worker. This is one media process, with no competing worker or queue.
It is not a measurement of stage 0 capacity or a choice of production mem_limit.

Models and measure transforms remain the pinned #20 research baseline: int8
word model, fp32 phone model, small.en int8 beam 5. Each recording makes one
shared phoneme traversal, with bounded windows, used by both GOP measures.
Separate word-alignment and Whisper traversals are included in the timer.
No real provider, learner grading, calibration or B4 quality pass is implied.

## Workload and timing boundaries

For each of bdl, slt and clb, take the lexicographically sorted common prompts
and append whole utterances, without new silence, until duration reaches 75 s.
Start the next round at the next utterance; stop after ten rounds per speaker.
References use slt, clb and bdl respectively and the exact same prompt sequence.
Utterances are neither repeated within a speaker's ten rounds nor time-stretched.
Final utterances remain intact, so round lengths exceed 75 s slightly. The
artifact manifest records all source names, texts, durations and waveform hashes.
These are independent read-speech proxies, not natural learner shadows.

All reference decode/alignment/GOP/pitch/transcript work finishes before timing;
references remain in memory. A complete candidate round warms every model and
transform. Thirty candidates then run serially with a monotonic wall timer.
The timer starts before ffmpeg decode and ends after the complete `assess` result,
including VAD, phonemization, CTC alignment, ASR, pitch, echo and measure transforms.
JSON artifact writing, model loading, downloads and feedback generation are outside
that boundary. No failed or missing recording is dropped from the percentile.

Silero VAD selects speech with 400 ms padding, splitting retained intervals into
at most 30 s acoustic windows. Both word and phone models traverse those windows
once each; GOP pronunciation and articulation share the phone logits. Inference
outputs are placed on the recording's 20 ms grid; skipped gaps contain blank-only
logits. The window's final incomplete convolution frame is also blank. This
preserves the clock for the existing CTC/pitch measures, but window seams and VAD
are unvalidated quality changes. Whisper uses its own default VAD padding and is
included in full. There is no per-utterance oracle alignment in the timed path.
The experiment does not demonstrate a single common encoder for all model roles.

Percentiles use nearest rank: p50 is sorted item 15 and p95 item 29 of 30.
Spread is maximum minus minimum; the full range is retained. The verdict compares
the largest per-run p95 with the strict `< 50 s` threshold, without pooling runs.

A successful workflow means that all 30 measurements completed and evidence was
uploaded. The B3 budget verdict lives in `summary.json` (`pass`) and ADR 0096;
a completed experiment can report a failed latency target without failing CI.
