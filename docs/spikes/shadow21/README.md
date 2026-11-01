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
