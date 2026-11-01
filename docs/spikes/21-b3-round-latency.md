# #21 B3: end-to-end Shadow round latency

**CI-runner evidence (E4).** [Owner exception E4](https://github.com/abubakar1010/ListenUp/issues/119#issuecomment-6559104401)
replaces #21's stage-0-host prerequisite with GitHub `ubuntu-24.04-arm` evidence.
This work never acquires the host lock and makes no host/capacity claim.

## Question and verdict

With reference profiles precomputed, all models warm, no queue, and two threads,
does one approximately 75 s recording finish analysis in **under 50 s at p95**?

**FAIL — CI-runner evidence (E4).** The worst run is [41324223275](https://github.com/abubakar1010/ListenUp/actions/runs/41324223275) with p95 **81.904 s**, exceeding the strict under-50 s target. The spike investigation is complete; the B3 performance gate is failed.

## Method

The [isolated harness](shadow21/README.md) reuses the corrected #20 `assess`
function and pinned models, transforms and evidence-eligibility rules. Its
window wrapper applies VAD and bounded acoustic inference; it neither imports
application code nor registers a real assessment provider. Phone logits are
computed once per retained window and shared by pronunciation/articulation.
Separate word alignment and Whisper transcription are included in elapsed time.
Shared-encoder optimizations remain unmeasured.

Thirty candidate recordings use ten concatenated passages from each of CMU
ARCTIC bdl/slt/clb. Whole utterances are appended in sorted common-prompt order
until at least 75 s, then the next passage starts. References use slt/clb/bdl
respectively, with identical text sequences and naturally different durations.
The manifest records source utterances, durations and waveform hashes. There
is no inserted padding, time stretching or reuse within one speaker's ten rounds.
These public read-speech proxies do not establish natural-shadowing quality.

Downloads, model loads, every reference profile and one full candidate warmup
precede the sample. The serial monotonic wall timer includes candidate ffmpeg
decode, Silero VAD, word/phone model inference, CTC alignment, phonemization,
Whisper, pitch, echo and all measure transforms. It excludes reference work,
queueing, feedback generation and artifact serialization. A failed recording
stops the run; incomplete runs cannot produce an acceptance summary.

Each GitHub job runs the work in Docker with `--cpus=2 --memory=8g
--memory-swap=8g`, OMP/BLAS threads 2, torch intra/inter-op threads 2 and Whisper
CPU threads 2 (one worker). Artifacts preserve actual cgroup settings, runner
`lscpu`, `nproc`, `free -b`, `uname -m`, image version and source SHA. The
container quota constrains the runner's four visible CPUs to two CPUs.
The 8 GiB limit sets this benchmark's memory budget; #233 owns production
`mem_limit` decisions.

## Results — CI-runner evidence (E4)

| Workflow run | p50 (s) | p95 (s) | Min–max (s) | Spread (s) | Process peak RSS (GiB) |
| --- | ---: | ---: | ---: | ---: | ---: |
| [41324111941](https://github.com/abubakar1010/ListenUp/actions/runs/41324111941) | 73.818 | 77.978 | 69.468–81.914 | 12.446 | 7.184 |
| [41324223275](https://github.com/abubakar1010/ListenUp/actions/runs/41324223275) | 75.859 | 81.904 | 71.913–91.585 | 19.673 | 7.585 |
| [41324294482](https://github.com/abubakar1010/ListenUp/actions/runs/41324294482) | 77.585 | 80.752 | 72.648–102.882 | 30.234 | 8.025 |

Each run has all 30 samples. Percentiles use nearest rank (items 15 and 29 of
30); spread is maximum minus minimum. The decision uses the **worst run's p95**,
not pooled percentiles or the best repeat. JSON artifacts retain all samples,
measure outputs, workload manifest, input/model hashes, settings and runner facts.

CI-runner evidence (E4): candidate durations are **75.001–79.025 s**; independent
references last **63.236–91.125 s** and are fully precomputed. Across the three
runs, p50 spans **73.818–77.585 s** and p95 spans **77.978–81.904 s** (p95 spread
**3.926 s**). No percentile is pooled across runs.

[Durable JSON](shadow21/results.json) preserves each recording's time, all runner
facts, settings, the common workload manifest, model/input hashes and artifact
IDs/SHA256 digests. The downloaded ZIP digests match GitHub's metadata. All three
manifests, input hashes and software/runtime settings match exactly; every
reported percentile was recomputed from the 30 raw samples.

CI-runner evidence (E4): each runner reports Neoverse-N2, four visible CPUs,
`aarch64`, image `ubuntu24-arm64` version `20261026.166.1`. The measured container
is restricted to two CPUs. Dynamic int8 uses the observed **oneDNN** engine;
this is not an int8/fp32 accuracy comparison for #232.

RSS is `getrusage(RUSAGE_SELF).ru_maxrss` for the process lifetime, including
setup and all cached references. It is not cgroup peak memory or a production
sizing result. Process RSS and cgroup charging account for shared file-backed
pages differently; the slightly higher RSS in the last run does not change its
recorded 8 GiB `memory.max` and zero `memory.swap.max`. Production `mem_limit`
and learner capacity remain in #233.

The three evidence runs were selected before seeing their measurements. Run 1
precedes the added runtime-budget assertion; its recorded cgroup/thread settings
are identical to the later runs. Run 2 adds that assertion outside the timer;
run 3 changes only the methodology README. The timed algorithm and inputs are
unchanged. Initial workflows also automatically uploaded small Buildx metadata
records, containing no runtime audio or weights; the final scaffold disables
those additional records and uploads benchmark evidence as JSON only.

## Scope and limitations

[ADR 0096](../adr/0096-b3-round-latency.md) records the decision. ADR 0050's
quality no-go and ADR 0074's fake-provider restrictions remain in force. VAD and
window seams have not been validated for measure quality; blank frames preserve
the recording clock across skipped silence, but do not validate boundaries.
No precision-equivalence, B4 filler-recall, learner calibration or grading gate
is passed by this speed experiment. No learner or golden-set data, YouTube
media, or consent-restricted recordings are used. No audio or weights are
committed or uploaded; the CMU redistribution notice is retained in shadow20.

E4 requires a single spot check on stage 0 when available, queued after #17;
that future check confirms or replaces these figures. This work neither runs
that check nor claims learner capacity, deployment readiness or launch approval.

## Validation

| Evidence | Check and outcome |
| --- | --- |
| Whole-utterance packing, insufficient/invalid input | `test_pack_uses_whole_utterances_and_never_repeats`, `test_pack_rejects_insufficient_data`, `test_pack_rejects_invalid_duration` |
| 30 matching-text references, source manifest and decode | `test_manifest_has_30_whole_75_second_rounds_and_checks_reference_text`, `test_decode_requests_mono_16khz_and_preserves_pcm` |
| Cached references, warmup and exactly 30 timed candidates | `test_reference_precompute_and_warmup_precede_all_30_timers` |
| VAD silence skipping, bounded word/phone windows, original clock | `test_windows_skip_silence_and_bound_work`, `test_vad_drives_both_models_without_compressing_the_recording_clock`, four `WindowTests` cases |
| E4 compute/no-swap guard | `test_budget_refuses_extra_cpu_swap_or_threads` |
| Complete-run p50/p95, strict threshold, invalid samples | `test_summary_requires_all_30_and_uses_nearest_rank` |
| Real ARM end-to-end integration | Three linked complete workflow runs, all public inputs, no inference fakes |

`python -m pytest docs/spikes/shadow21 -q --cov=docs/spikes/shadow21
--cov-branch --cov-report=term-missing`: **14 passed** locally. `core.py` and
`inference.py` have 100% line/branch coverage; `run.py` has 98% combined coverage
(only its CLI entry line/branch remains outside the fake-boundary unit coverage).
Real ARM runs exercise the CLI and real external boundaries. Unit fakes establish
orchestration and configuration, never model quality or benchmark latency.

Actual red/green chronology: the four initial workload/window/percentile tests
failed on the missing `core` interface, then passed. The two initial tensor
window tests failed on the missing `inference` interface after torch was installed,
then passed. The budget test failed on missing `validate_budget`, then passed.
Additional inventory/phone/failure, invalid-duration and runner-orchestration
checks are post-implementation characterization. The orchestration/fetch/workflow
did not have a complete test-first cycle; this history is disclosed rather than
retrospectively called TDD. Coverage does not establish test-first chronology.

Ruff lint/format, actionlint 1.7.7 and `git diff --check` pass. Backend/web suites
are not applicable locally: their source, configuration and dependencies are
unchanged. The existing migration head remains singular (`90_session_deletion`);
no migration is created or applied. Required repository CI and fresh-session
review are recorded in the PR; independent review remains an owner handoff
before merge, not a claim made by this builder.

Three isolated mutations were tested under `work/21/mutations/`: accepting
`p95 <= 50`, deleting the full warmup and placing all acoustic windows at time
zero. Each focused test rejects its mutation. The first clock assertion checked
only argmax and initially let the misplaced-window mutation pass; it now asserts
near-certain blank probabilities and rejects that mutation. All 14 ordinary tests
remain green. Only test assertions changed; measurement code and running jobs
were untouched.
