# ADR 0096: B3 round latency on ARM CI runners

- Status: Proposed (measured verdict; GPU evaluation proposal needs owner review)
- Date: 2026-11-01
- Story: [#21](https://github.com/abubakar1010/ListenUp/issues/21)
- Requirements: FR-SH-9, NFR-PERF; [System Design 12.1 B3](../design/system-design.md#121-benchmarks-to-run)
- Authority: [owner exception E4](https://github.com/abubakar1010/ListenUp/issues/119#issuecomment-6559104401)
- Evidence: [spike note](../spikes/21-b3-round-latency.md), [durable JSON](../spikes/shadow21/results.json), [harness](../spikes/shadow21/README.md)
- Related: [ADR 0034](0034-speech-models-chosen-by-spikes-b1-and-b2.md), [ADR 0050](0050-shadow-measures-model-choices-and-go-no-go.md), [ADR 0073](0073-stage-0-host-oracle-always-free-arm.md), [ADR 0074](0074-speech-assessment-contract-split.md)

## Context

B3 asks whether one approximately 75 s recording can finish analysis in under
50 s at p95, with its reference precomputed, models warm, no queue and two threads.
E4 authorizes `ubuntu-24.04-arm` runner evidence in place of the stage-0-host
prerequisite, without the host lock. It requires separate workflow runs, recorded
runner facts, a two-CPU/no-swap container and the worst run's p95 as the decision.
The older host-only language in ADR 0050 is subject to this explicit exception.

The corrected #20 prototype remains a research baseline: int8 word alignment,
fp32 phoneme CTC GOP, prompted `small.en` int8 beam 5, and Parselmouth. B3 bounds
acoustic windows and applies VAD. One shared phoneme traversal supplies both GOP
measures; the separate word model and Whisper pass are included in the timer.
Reference preparation and a complete candidate warmup finish before sampling.
No application provider, production model setting or scoring policy changes.

## Decision — CI-runner evidence (E4)

**B3 fails for this CPU prototype.** The worst run's p95 is **81.904 s**, against the strict under-50 s target.

| Workflow run | p50 (s) | p95 (s) | Min–max (s) | Spread (s) | Process peak RSS (GiB) |
| --- | ---: | ---: | ---: | ---: | ---: |
| [41324111941](https://github.com/abubakar1010/ListenUp/actions/runs/41324111941) | 73.818 | 77.978 | 69.468–81.914 | 12.446 | 7.184 |
| [41324223275](https://github.com/abubakar1010/ListenUp/actions/runs/41324223275) | 75.859 | 81.904 | 71.913–91.585 | 19.673 | 7.585 |
| [41324294482](https://github.com/abubakar1010/ListenUp/actions/runs/41324294482) | 77.585 | 80.752 | 72.648–102.882 | 30.234 | 8.025 |

CI-runner evidence (E4): all three runs use the same public, pinned CMU ARCTIC
waveforms and model hashes. The 30 candidates last **75.001–79.025 s** after
whole-utterance concatenation. The container has two CPUs, two torch intra/inter-op
threads, Whisper CPU threads two, 8 GiB memory and zero swap. Each run records
actual cgroup limits, hardware/image facts and its source SHA. Full settings,
per-recording times and the nearest-rank percentile rule are in the evidence.
The observed dynamic-int8 engine is **oneDNN**; no Arm int8/fp32 equivalence is
inferred. The reported RSS is process peak including setup and cached references.

**Proposed change on failure: trigger a GPU evaluation when warm, no-queue
scoring p95 is at least 50 s.** Keep the approximately 75 s segment and the
fp32 phoneme baseline for that comparison. Measure the same end-to-end path and
review the applicable quality regressions before selecting a GPU implementation.
System Design 5.2's feedback p95 threshold is 60 s; B3's separate scoring budget
needs this earlier evaluation trigger. GPU evaluation remains a proposal for
separate work under the existing cost and privacy decisions. GPU provisioning and any associated cost remain outside
this spike.

This measurement does not establish a CPU lower bound: encoder reuse, canonical
phone caching and other CPU optimizations remain unmeasured. The proposal makes
no claim that a GPU or a smaller model has passed B3. No smaller model,
quantization change or shorter learner segment is adopted by this ADR.

## Consequences

- The benchmark investigation can close #21 once its measurements and this ADR
  are recorded; the **B3 performance gate remains failed**. Closing a research
  issue does not enable real assessment or learner grading.
- ADR 0050's quality no-go, #22's filler gate, independent boundary/phone evidence,
  calibration and the remaining learner-grading prerequisites remain in force.
  VAD/window seams and public independent read speech provide no quality waiver.
- The reusable workflow exposes a benchmark selector through dispatch and
  `workflow_call`. Its benchmark-path pull-request trigger supplies pre-merge
  runs while dispatch is unavailable before the file reaches main. Only B3 is
  implemented here; #22/#232/#233 can extend the registry in their own work.
- Public audio and model weights are fetched at runtime and never committed.
  Benchmark result artifacts are JSON; initial runs also contain automatic
  Buildx metadata records, disabled in the final workflow. Those records contain
  no runtime audio or model weights.
- E4 requires one future stage-0 spot check, queued after #17, to confirm or
  replace these figures. No host lock, migration, learner-capacity figure,
  production `mem_limit`, application code or learner enablement is included.
