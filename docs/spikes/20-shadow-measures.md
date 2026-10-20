# Spike #20: seven Shadow speech measures on container CPU

Issue [#20](https://github.com/abubakar1010/ListenUp/issues/20); follow-up decision:
[ADR 0050](../adr/0050-shadow-measures-model-choices-and-go-no-go.md).
Requirements: FR-SH-4, FR-SH-9, FR-SH-10, FR-SH-15, AT-17.

**This is a quality experiment on the managed container's CPU, not a stage-0
benchmark.** #16 is not provisioned; no latency, throughput, or capacity claim is
made. #21 owns speed on the real server. The experiment stayed within the issue's
three-day effort box. Tool: Codex, authorized by the owner after Claude Code was
found unavailable. Base: current main, recorded in the provenance file.

## Method and limits

Read first: issue #20, ADRs 0010 and 0034, and the B1/B2 write-ups. B2's historical
boundary figures are provisional after its tokenizer/comparator corrections;
this spike does not silently turn that evidence into validated word boundaries.

Ten triads use the same text spoken independently by three CMU ARCTIC speakers
(bdl, slt, clb), rotating original/good roles. These are natural human readings,
**not actual human shadowing sessions**. The good recording is never a copy or
filtered copy of the original. There is no learner data. Every poor recording is
synthetic: one word removed using good-reading alignment, sixth-order 900 Hz
low-pass filtering, 1.2 s late start, a 0.6 s pause, and flite “um uh” insertion.
Cut intervals, removed words, source speakers and audio hashes are in the
[manifest](shadow20/results/manifest.json). The clips are short ARCTIC utterances,
not 75 s rounds; different speaking style and ASR errors remain confounders.

Two pairs have additional late-only, low-pass-only, skipped-word-only and
filler-only controls. These reveal whether a measure responds to its intended
change. They are diagnostic examples, not a statistically independent validation
set. Synthetic low-pass speech tests loss of acoustic information; it does not
establish correctness on real mumbling, consonant substitutions, or merged sounds.
No listening/teacher labelling was supplied for these controls. Filler truth is
two intended synthesized tokens, not a teacher-verified count of natural fillers.

Alignment is the provisional ADR 0034 English wav2vec2 model with dynamic int8
linear layers. Pronunciation uses real phoneme-model CTC GOP, not letter CTC
confidence renamed as GOP. eSpeak en-us phones are Viterbi-aligned to original and
candidate; score transforms compare their GOPs. Articulation uses word-final-phone
GOP. Parselmouth supplies word pitch using actual frame timestamps. A separate
prompted `small.en` pass supplies observed text and fillers, so forced alignment
cannot automatically count missing words as present. All seven measures use the
original clip/profile as their comparator. Accent is excluded from overall; no
available-measure average is used to waive a missing measure or pass the spike.

A measure wins only on strict good > poor. Ties and missing values do not win.
Four strict wins out of all seven is the narrow issue's “most measures” criterion.
Missing accent or fluency is shown explicitly, not converted to a passing zero.
These arbitrary prototype score transforms are not calibrated learning grades.
See the [prototype README](shadow20/README.md) for formulas, exact model revisions,
licences and reproduction. [Raw fp32](shadow20/results/results-fp32.json) and
[raw int8](shadow20/results/results-int8.json) retain transcripts, word timings,
per-sound GOP, per-word markers, and failures. Raw GOP can be negative; displayed
scores are relative 0–100 transforms. The two runs differ only in phoneme-model
linear-layer quantization; the word aligner remains int8 in both.

Execution provenance: [hardware/software](shadow20/results/provenance.json),
[artifact SHA256s](shadow20/results/input-hashes.json), and the prototype's pinned
requirements. Host: Intel Xeon Platinum 8573C, 3 visible vCPUs, cgroup quota 2 CPUs,
about 9.7 GiB visible RAM, Python 3.12.14; 2 torch threads, no GPU. Date: 2026-10-20.
All scored downloads succeeded through the inherited proxy; no policy bypass.
The upstream ARCTIC host returned 502/503, so the permitted public dataset mirror
was used. Audio/weights live only in ignored scratch, never in this PR.

## Validation record

- Core score behavior was tested first: the initial focused pytest command failed
  because the `measures` interface did not exist; five tests then passed. A strict
  floating-point equality in the timing test was corrected to approximate equality.
- During the first model run, fluency's empty matched-gap case incorrectly returned
  100. Added `test_fluency_requires_observed_gaps_and_penalizes_excess_pause`, observed
  its missing-interface failure, implemented null for unobservable gaps, and got
  six passing tests. Interrupted the incomplete old run and regenerated both full
  runs with the corrected code. The abandoned partial run is not evidence here.
- The model orchestration/fetch/report scripts were assembled as notebook-quality
  research code and exercised with real inputs; they did **not** have a complete
  test-first development cycle. This limitation is disclosed, not reconstructed
  as TDD evidence. They are not production adapters.
- Named tests cover GOP competitor exclusion, reference-relative scoring, missing
  and repeated-word matching, late starts versus allowed lag, changed speech rate,
  exact delayed echo versus independent noise/silence/empty input, filler phrase
  matching, and missing fluency evidence. They detect reversed scoring direction,
  counting forced missing words, ignoring all constant lag, and an all-high echo
  classifier. Regex tests explicitly preserve the lexical “like” limitation.
- Final helper checks: **6 tests pass**, with **100% line/branch coverage of
  `measures.py` only**; Ruff lint and format checks pass for the prototype. This
  coverage figure does not cover the model orchestration/fetch/report scripts.
- App backend/web, database, migrations and generated API checks are not applicable:
  no application code, package dependencies or schemas changed. Independent
  fresh-session review and required CI remain PR/merge gates; no merge requested.

The generated per-pair tables follow. The final assessment and follow-up decision
use both combined degradation and the controls; ranking alone does not establish
that each score measures its intended property.


### Pair 01: a0001.wav (bdl → slt)

Removed word: `trail`. Strict good > poor: **4/7** (fp32), **4/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 93.9 | 0.0 | 93.9 | 0.0 |
| pronunciation | 90.4 | 0.0 | 93.2 | 0.0 |
| accent | 82.0 | missing | 82.0 | missing |
| articulation | 100.0 | 0.0 | 100.0 | 0.0 |
| fluency | 100.0 | missing | 100.0 | missing |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 87.5 | 0.0 | 87.5 | 0.0 |

### Pair 02: a0002.wav (slt → clb)

Removed word: `case`. Strict good > poor: **4/7** (fp32), **5/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 96.0 | 38.4 | 96.0 | 37.5 |
| pronunciation | 100.0 | 0.0 | 92.3 | 0.0 |
| accent | 95.8 | missing | 95.8 | 64.1 |
| articulation | 87.8 | 0.1 | 81.2 | 0.1 |
| fluency | 100.0 | 100.0 | 100.0 | 100.0 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 87.5 | 25.0 | 87.5 | 50.0 |

### Pair 03: a0003.wav (clb → bdl)

Removed word: `evening`. Strict good > poor: **5/7** (fp32), **5/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 93.8 | 12.9 | 93.8 | 12.9 |
| pronunciation | 96.8 | 0.6 | 100.0 | 0.5 |
| accent | 0.0 | 87.5 | 0.0 | 87.5 |
| articulation | 99.4 | 4.0 | 100.0 | 3.0 |
| fluency | 100.0 | 39.5 | 100.0 | 39.5 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 90.9 | 54.5 | 90.9 | 54.5 |

### Pair 04: a0004.wav (bdl → slt)

Removed word: `to`. Strict good > poor: **5/7** (fp32), **5/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 83.8 | 18.6 | 83.8 | 18.6 |
| pronunciation | 75.8 | 0.1 | 75.8 | 0.1 |
| accent | 73.3 | 87.3 | 73.3 | 87.3 |
| articulation | 59.1 | 0.2 | 52.7 | 0.2 |
| fluency | 100.0 | 33.6 | 100.0 | 33.6 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 100.0 | 55.6 | 100.0 | 55.6 |

### Pair 05: a0006.wav (slt → clb)

Removed word: `i'll`. Strict good > poor: **5/7** (fp32), **5/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 81.1 | 12.0 | 81.1 | 12.0 |
| pronunciation | 96.2 | 0.1 | 86.6 | 0.1 |
| accent | 87.8 | 94.5 | 87.8 | 94.5 |
| articulation | 100.0 | 0.0 | 93.4 | 0.0 |
| fluency | 97.0 | 30.7 | 97.0 | 30.7 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 90.9 | 54.5 | 90.9 | 54.5 |

### Pair 06: a0007.wav (clb → bdl)

Removed word: `see`. Strict good > poor: **5/7** (fp32), **5/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 97.9 | 7.8 | 97.9 | 7.8 |
| pronunciation | 100.0 | 3.9 | 100.0 | 4.6 |
| accent | 79.8 | 84.2 | 79.8 | 84.2 |
| articulation | 100.0 | 8.7 | 100.0 | 8.9 |
| fluency | 100.0 | 42.3 | 100.0 | 42.3 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 100.0 | 63.6 | 100.0 | 63.6 |

### Pair 07: a0009.wav (bdl → slt)

Removed word: `faced`. Strict good > poor: **5/7** (fp32), **5/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 84.8 | 12.1 | 84.8 | 12.1 |
| pronunciation | 100.0 | 0.1 | 97.5 | 0.1 |
| accent | 93.7 | 94.6 | 93.7 | 94.6 |
| articulation | 100.0 | 0.1 | 100.0 | 0.2 |
| fluency | 100.0 | 39.5 | 100.0 | 39.5 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 100.0 | 66.7 | 100.0 | 66.7 |

### Pair 08: a0010.wav (slt → clb)

Removed word: `what`. Strict good > poor: **5/7** (fp32), **5/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 61.3 | 8.7 | 61.3 | 8.7 |
| pronunciation | 100.0 | 0.4 | 100.0 | 0.4 |
| accent | 75.9 | 78.1 | 75.9 | 78.1 |
| articulation | 100.0 | 0.7 | 100.0 | 0.9 |
| fluency | 100.0 | 30.4 | 100.0 | 30.4 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 100.0 | 83.3 | 100.0 | 83.3 |

### Pair 09: a0011.wav (clb → bdl)

Removed word: `in`. Strict good > poor: **5/7** (fp32), **5/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 92.9 | 6.5 | 92.9 | 6.5 |
| pronunciation | 88.4 | 0.1 | 87.8 | 0.1 |
| accent | 89.2 | 49.7 | 89.2 | 49.7 |
| articulation | 73.4 | 0.1 | 71.6 | 0.1 |
| fluency | 100.0 | 94.2 | 100.0 | 94.2 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 100.0 | 100.0 | 100.0 | 100.0 |

### Pair 10: a0012.wav (bdl → slt)

Removed word: `and`. Strict good > poor: **5/7** (fp32), **4/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 91.3 | 0.0 | 91.3 | 0.0 |
| pronunciation | 100.0 | 0.1 | 89.3 | 0.1 |
| accent | 88.0 | missing | 88.0 | missing |
| articulation | 81.0 | 0.2 | 61.6 | 0.2 |
| fluency | 100.0 | missing | 100.0 | missing |
| fillers | 100.0 | 0.0 | 100.0 | 100.0 |
| completeness | 100.0 | 0.0 | 100.0 | 10.0 |

## Aggregate strict wins

| Measure | fp32 wins / ties / missing | int8 wins / ties / missing |
| --- | --- | --- |
| timing | 10 / 0 / 0 | 10 / 0 / 0 |
| pronunciation | 10 / 0 / 0 | 10 / 0 / 0 |
| accent | 1 / 0 / 3 | 2 / 0 / 2 |
| articulation | 10 / 0 / 0 | 10 / 0 / 0 |
| fluency | 7 / 1 / 2 | 7 / 1 / 2 |
| fillers | 1 / 9 / 0 | 0 / 10 / 0 |
| completeness | 9 / 1 / 0 | 9 / 1 / 0 |

## Single-degradation controls (fp32)

| Pair | Variant | Timing | GOP pronunciation | Articulation | Fluency | Fillers | Completeness |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 01 | good | 93.9 | 90.4 | 100.0 | 100.0 | 100.0 | 87.5 |
| 01 | late | 30.7 | 90.3 | 100.0 | 100.0 | 100.0 | 87.5 |
| 01 | lowpass | 98.5 | 0.6 | 0.9 | 100.0 | 100.0 | 50.0 |
| 01 | skip | 76.1 | 46.1 | 100.0 | 100.0 | 100.0 | 87.5 |
| 01 | fill | 59.1 | 87.0 | 100.0 | 51.2 | 0.0 | 75.0 |
| 01 | poor | 0.0 | 0.0 | 0.0 | missing | 100.0 | 0.0 |
| 02 | good | 96.0 | 100.0 | 87.8 | 100.0 | 100.0 | 87.5 |
| 02 | late | 41.2 | 95.5 | 70.8 | 100.0 | 100.0 | 87.5 |
| 02 | lowpass | 92.5 | 0.3 | 0.1 | 100.0 | 100.0 | 37.5 |
| 02 | skip | 86.4 | 31.5 | 61.0 | 100.0 | 100.0 | 62.5 |
| 02 | fill | 57.3 | 98.8 | 75.1 | 49.2 | 100.0 | 87.5 |
| 02 | poor | 38.4 | 0.0 | 0.1 | 100.0 | 100.0 | 25.0 |

## Echo controls (threshold 0.6)

| Pair | Independent clean reading | Exact copy | Digital mixture |
| --- | ---: | ---: | ---: |
| 01 | 0.060 | 1.000 | 0.476 |
| 02 | 0.159 | 1.000 | 0.537 |
| 03 | 0.048 | 1.000 | 0.802 |
| 04 | 0.076 | 1.000 | 0.644 |
| 05 | 0.116 | 1.000 | 0.529 |
| 06 | 0.032 | 1.000 | 0.875 |
| 07 | 0.045 | 1.000 | 0.542 |
| 08 | 0.217 | 1.000 | 0.546 |
| 09 | 0.059 | 1.000 | 0.765 |
| 10 | 0.045 | 1.000 | 0.537 |

## Filler counts (fp32; poor has 2 intended synthetic insertions)

| Pair | Original | Good | Poor |
| --- | ---: | ---: | ---: |
| 01 | 0 | 0 | 0 |
| 02 | 0 | 0 | 0 |
| 03 | 0 | 0 | 0 |
| 04 | 0 | 0 | 0 |
| 05 | 0 | 0 | 0 |
| 06 | 0 | 0 | 0 |
| 07 | 0 | 0 | 0 |
| 08 | 1 | 1 | 1 |
| 09 | 0 | 0 | 0 |
| 10 | 0 | 0 | 23 |

## Phoneme int8 sensitivity and rerun stability

Both configurations meet the narrow majority criterion in 10/10 pairs. Across
the 28 candidate/control recordings, corresponding phone GOP values change by
**0.325 log-ratio units on average**, **0.940 at p95**, and **6.817 at maximum**
(absolute differences). Reference-relative pronunciation score changes average
**2.73 points**, with a **15.44-point maximum**. Timing agreement from B2 cannot
justify treating these posterior changes as free. Keep fp32 as the research
baseline; int8 GOP needs independent human-error calibration before adoption.

The separate full runs also produced different poor-speech Whisper hypotheses
for pairs **02 and 10**, despite unchanged Whisper settings and identical waveform
hashes. Pair 10 changes from 23 regex fillers to zero. Thus changes to the
non-GOP measures in the int8 columns cannot be attributed to phoneme quantization.
The tables preserve actual run outputs; the correct next experiment caches an
independent transcript/alignment when isolating posterior precision. Reproduction
commands are supplied, but bit-for-bit transcript repeatability is not established.

## Measure verdicts (fp32 baseline)

| Measure | Rating | Evidence and practical limit |
| --- | --- | --- |
| Rhythm and timing | **works, on this synthetic test** | Good wins 10/10 combined pairs; late-only controls fall from 93.9 to 30.7 and 96.0 to 41.2. Missing ASR matches also drive this score down, so it is not independent of completeness. No real shadow-lag calibration or human boundary accuracy is established. |
| Pronunciation (phoneme GOP) | **weak** | Good wins 10/10, but low-pass-only controls collapse from 90.4 to 0.6 and 100.0 to 0.3 even with unchanged words. This demonstrates sensitivity to damaged acoustics, not calibrated phone-error detection. Pair 02's late-only score changes from 100.0 to 95.5 despite identical spoken material. |
| Accent | **fails; experimental** | Only 1/10 strict win, 3 missing comparisons, and 6 reversals. Pair 01's filler-only intonation score rises 82.0 → 89.7. Pitch correlation cannot represent the SRS's consonants, vowels and stress, and filtering changes which frames/words are observable. Keep it outside overall. |
| Articulation | **weak** | Good wins 10/10 combined, but shares the phoneme GOP's acoustic confound. Pair 01's skipped-word-only score stays 100.0; pair 02's late-only ending score falls 87.8 → 70.8 without changed endings. It cannot yet support word/sound error markers. |
| Fluency | **weak** | 7 wins, 1 tie, 2 missing. Filler-only pauses lower both controls to about 50, but pair 02's combined poor speech still scores 100 after most words are lost. Matching surviving words is insufficient to measure restarts or all hesitations. |
| Filler words | **fails** | 1 win and 9 ties. The one win is misleading: pair 10's poor hypothesis contains 23 regex fillers, not the intended 2. Pair 01's filler-only pass counts 2, pair 02's counts 0. Prompting is not reliable retention. Lexical “like” in pair 08 counts as a filler in both good and poor. No full AT-17 pass. |
| Completeness | **weak** | 9 wins, 1 tie, but pair 01's skipped-word control stays 87.5, identical to good. The unmodified good readings in pairs 01/02 score 87.5 due to transcription/text mismatch; low-pass-only changes to 50.0/37.5 without deleting words. ASR matches avoid tautological forced-alignment coverage but are not literal presence ground truth. |

The **narrow combined-ranking criterion passes in all 10 pairs** on the fp32
baseline (four or five strict wins out of seven). That is a useful feasibility
signal, not a go for all seven measures. Separate controls expose false responses,
missing evidence and correlated measures. In particular, the two GOP-based wins
are not independent confirmation of pronunciation and articulation validity.

**Echo screen: weak.** With threshold 0.6, all 10 exact copies are flagged and all
10 independent good voices are below threshold. Only 4/10 digital mixtures are
flagged; 6 leak mixtures are missed. There are no room impulse responses, speaker
playback recordings or acoustic echo-cancellation tests. Do not treat a clean
screen as proof the original is absent from a microphone recording.

For the combined poor controls, detected filler counts are 0 in eight pairs,
1 in pair 08 and 23 in pair 10. Against two intended insertions, only pair 08 is
numerically within one, and that is a lexical false-positive candidate, not
validated recall. All other errors exceed one. Original/good recordings have no
independent filler annotation, and synthesized insertions have not been listened
to by a teacher; this diagnostic cannot supply #22's precision/recall gate.

## Go/no-go and next work

**No-go for shipping these seven scores; go for continued self-hosted research.**
ADR 0010 remains the privacy/default decision. Model inference can run locally,
but this set does not establish the necessary individual score validity. ADR 0050
records candidate model choices and the detailed carry-forward for #21, #22 and
#80. Keep original-relative raw evidence, experimental accent, missingness and
provenance; validate real human shadowing, boundary accuracy, phone errors and
microphone leakage before promoting the transforms or per-word markers.
