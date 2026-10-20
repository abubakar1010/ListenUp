# Spike #20: seven Shadow speech measures on container CPU

Issue [#20](https://github.com/abubakar1010/ListenUp/issues/20); follow-up decision:
[ADR 0050](../adr/0050-shadow-measures-model-choices-and-go-no-go.md).
Requirements: FR-SH-4, FR-SH-9, FR-SH-10, FR-SH-15, AT-17.

**This is a quality experiment on the managed container's CPU, not a stage-0
benchmark.** #16 is not provisioned; no latency, throughput, or capacity claim is
made. #21 owns speed on the real server. The experiment stayed within the issue's
three-day effort box. Tool: Codex, authorized by the owner after Claude Code was
found unavailable. Original PR base: `4efc101`, recorded in the provenance file.

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
cannot automatically count missing words as present. Timing is null with fewer
than two unambiguous matched words. Whole-passage pronunciation/articulation grades
require complete unambiguous candidate-word corroboration and valid alignment/phone
evidence. Otherwise they are null with an explicit reason; forced-phone GOP stays
in the raw diagnostics. Differing repeated-token counts make occurrence identity
unknown. Unsupported words are marked `unknown`, not confirmed `missed`.
These conservative research eligibility rules are not production scoring policy.
All seven measures use the
original clip/profile as their comparator. Accent is excluded from overall; no
available-measure average is used to waive a missing measure or pass the spike.

A measure wins only on strict good > poor. Ties and missing values do not win.
Four strict wins out of all seven is the narrow issue's “most measures” criterion.
Unavailable timing, GOP, accent and fluency are shown explicitly, never as wins.
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
was used. Audio/weights live only in uncommitted scratch, never in this PR.

## Validation record

The initial author reported an interface-missing red/green cycle for five helper
tests, then a sixth for unavailable fluency. That history is retained in the
original PR commit; this follow-up does not reconstruct or claim to prove it.
The orchestration/fetch/report scripts originally had no complete test-first cycle.
That historical gap remains disclosed; notebook-quality research is not an
exemption from `docs/testing.md`.

The review fixes have actual regression evidence from this session:

| Behavior | Focused command (Python from `work/review169/venv/bin/python`) | Observed red → green |
| --- | --- | --- |
| No timing grade/win with zero or one observed word | `-m pytest docs/spikes/shadow20/test_measures.py -q -k timing_requires -o cache_dir=work/review169/pytest-cache` | 2 failures (`0.0 is None`) before the fix; 8 helper cases pass after it |
| GOP eligibility, unknown words, finite evidence and positive durations | `-m pytest docs/spikes/shadow20/test_assess.py -q -o cache_dir=work/review169/pytest-cache` | 6 failures, including fabricated perfect grades and absent evidence metadata; 14 total cases pass after the fix |
| Ambiguous repeated-word occurrences | `-m pytest docs/spikes/shadow20/test_assess.py -q -k repeated -o cache_dir=work/review169/pytest-cache` | 2 failures before the ambiguity guard; all 16 cases pass after it |

Final command: `python -m pytest docs/spikes/shadow20 -q --cov=measures
--cov=experiment --cov=summarize --cov-branch --cov-report=term-missing`:
**16 passed**. `measures.py` has 100% line/branch coverage; `experiment.py` has
33.5% line / 10.5% branch coverage and `summarize.py` 18.0% / 5.6%. The new
orchestration tests use boundary fakes and exercise eligibility, not model quality.
Uncovered model loading/inference, pitch, build and CLI/report paths were exercised
by real runs, but are not claimed as unit-test coverage. `fetch.py` is not in this
coverage scope. The historical fetch/report TDD gap remains; no policy waiver is
inferred from this disclosure. Ruff lint/format and relative-link/diff checks pass.

Both full CPU evaluations were regenerated after the fixes using the pinned
public inputs. Re-fetch and a fresh build matched all 12 input artifact hashes
and every manifest waveform hash. No network-policy denial or proxy bypass occurred.
Per-recording `timing_evidence`, `gop_evidence` and `word_evidence` retain the
eligibility reasons next to the unchanged raw phone diagnostics. The old 10/10
claim is withdrawn: absent timing and unsupported forced-phone grades had counted
as wins. The regenerated tables below use only eligible strict comparisons.

Application backend/web, database, migrations and API checks are not applicable:
those areas and their dependencies remain untouched. The original PR CI run 297
passed, but it does not execute this isolated harness. CI on this correction and
fresh-session re-review remain merge gates. No stage-0 speed criterion is claimed.

### Pair 01: a0001.wav (bdl → slt)

Removed word: `trail`. Strict good > poor: **1/7** (fp32), **1/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 93.9 | missing | 93.9 | missing |
| pronunciation | missing | missing | missing | missing |
| accent | 82.0 | missing | 82.0 | missing |
| articulation | missing | missing | missing | missing |
| fluency | 100.0 | missing | 100.0 | missing |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 87.5 | 0.0 | 87.5 | 0.0 |

### Pair 02: a0002.wav (slt → clb)

Removed word: `case`. Strict good > poor: **3/7** (fp32), **3/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 96.0 | 37.5 | 96.0 | 37.5 |
| pronunciation | missing | missing | missing | missing |
| accent | 95.8 | 64.1 | 95.8 | 64.1 |
| articulation | missing | missing | missing | missing |
| fluency | 100.0 | 100.0 | 100.0 | 100.0 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 87.5 | 50.0 | 87.5 | 50.0 |

### Pair 03: a0003.wav (clb → bdl)

Removed word: `evening`. Strict good > poor: **3/7** (fp32), **3/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 93.8 | 12.9 | 93.8 | 12.9 |
| pronunciation | missing | missing | missing | missing |
| accent | 0.0 | 87.5 | 0.0 | 87.5 |
| articulation | missing | missing | missing | missing |
| fluency | 100.0 | 39.5 | 100.0 | 39.5 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 90.9 | 54.5 | 90.9 | 54.5 |

### Pair 04: a0004.wav (bdl → slt)

Removed word: `to`. Strict good > poor: **3/7** (fp32), **3/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 83.8 | 17.3 | 83.8 | 17.3 |
| pronunciation | 75.8 | missing | 75.8 | missing |
| accent | 73.3 | 87.8 | 73.3 | 87.8 |
| articulation | 59.1 | missing | 52.7 | missing |
| fluency | 100.0 | 33.6 | 100.0 | 33.6 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 100.0 | 55.6 | 100.0 | 55.6 |

### Pair 05: a0006.wav (slt → clb)

Removed word: `i'll`. Strict good > poor: **3/7** (fp32), **3/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 81.4 | 12.0 | 81.4 | 12.0 |
| pronunciation | missing | missing | missing | missing |
| accent | 86.9 | 94.5 | 86.9 | 94.5 |
| articulation | missing | missing | missing | missing |
| fluency | 97.0 | 30.7 | 97.0 | 30.7 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 90.9 | 54.5 | 90.9 | 54.5 |

### Pair 06: a0007.wav (clb → bdl)

Removed word: `see`. Strict good > poor: **3/7** (fp32), **3/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 97.9 | 7.8 | 97.9 | 7.8 |
| pronunciation | 100.0 | missing | 100.0 | missing |
| accent | 79.8 | 84.2 | 79.8 | 84.2 |
| articulation | 100.0 | missing | 100.0 | missing |
| fluency | 100.0 | 42.3 | 100.0 | 42.3 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 100.0 | 63.6 | 100.0 | 63.6 |

### Pair 07: a0009.wav (bdl → slt)

Removed word: `faced`. Strict good > poor: **3/7** (fp32), **3/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 84.8 | 12.1 | 84.8 | 12.1 |
| pronunciation | 100.0 | missing | 97.5 | missing |
| accent | 93.7 | 94.6 | 93.7 | 94.6 |
| articulation | 100.0 | missing | 100.0 | missing |
| fluency | 100.0 | 39.5 | 100.0 | 39.5 |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 100.0 | 66.7 | 100.0 | 66.7 |

### Pair 08: a0010.wav (slt → clb)

Removed word: `what`. Strict good > poor: **4/7** (fp32), **4/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 61.3 | 8.1 | 61.3 | 8.1 |
| pronunciation | 100.0 | missing | 100.0 | missing |
| accent | 75.9 | 75.2 | 75.9 | 75.2 |
| articulation | 100.0 | missing | 100.0 | missing |
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

Removed word: `and`. Strict good > poor: **1/7** (fp32), **1/7** (int8).

| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |
| --- | ---: | ---: | ---: | ---: |
| timing | 91.3 | missing | 91.3 | missing |
| pronunciation | 100.0 | missing | 89.3 | missing |
| accent | 88.0 | missing | 88.0 | missing |
| articulation | 81.0 | missing | 61.6 | missing |
| fluency | 100.0 | missing | 100.0 | missing |
| fillers | 100.0 | 100.0 | 100.0 | 100.0 |
| completeness | 100.0 | 0.0 | 100.0 | 0.0 |

## Aggregate strict wins

| Measure | fp32 wins / ties / missing | int8 wins / ties / missing |
| --- | --- | --- |
| timing | 8 / 0 / 2 | 8 / 0 / 2 |
| pronunciation | 1 / 0 / 9 | 1 / 0 / 9 |
| accent | 3 / 0 / 2 | 3 / 0 / 2 |
| articulation | 1 / 0 / 9 | 1 / 0 / 9 |
| fluency | 7 / 1 / 2 | 7 / 1 / 2 |
| fillers | 0 / 10 / 0 | 0 / 10 / 0 |
| completeness | 9 / 1 / 0 | 9 / 1 / 0 |

## Single-degradation controls (fp32)

| Pair | Variant | Timing | GOP pronunciation | Articulation | Fluency | Fillers | Completeness |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 01 | good | 93.9 | missing | missing | 100.0 | 100.0 | 87.5 |
| 01 | late | 30.7 | missing | missing | 100.0 | 100.0 | 87.5 |
| 01 | lowpass | 98.5 | missing | missing | 100.0 | 100.0 | 50.0 |
| 01 | skip | 76.1 | missing | missing | 100.0 | 100.0 | 87.5 |
| 01 | fill | 59.1 | missing | missing | 51.2 | 0.0 | 75.0 |
| 01 | poor | missing | missing | missing | missing | 100.0 | 0.0 |
| 02 | good | 96.0 | missing | missing | 100.0 | 100.0 | 87.5 |
| 02 | late | 41.2 | missing | missing | 100.0 | 100.0 | 87.5 |
| 02 | lowpass | 92.5 | missing | missing | 100.0 | 100.0 | 37.5 |
| 02 | skip | 86.4 | missing | missing | 100.0 | 100.0 | 62.5 |
| 02 | fill | 57.3 | missing | missing | 49.2 | 100.0 | 87.5 |
| 02 | poor | 37.5 | missing | missing | 100.0 | 100.0 | 50.0 |

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
| 10 | 0 | 0 | 0 |

## Phoneme int8 sensitivity and rerun stability

The corrected majority criterion passes in **2/10 pairs in each configuration**,
not 10/10. Nine pairs lack an eligible pronunciation/articulation comparison;
forced phones for unsupported words no longer supply ranking wins. The two
remaining majority cases are pairs 08 and 09; this is not a pass of issue #20.

The per-phone diagnostics are retained independently of grade eligibility.
Across the 28 candidate/control recordings, corresponding phone GOP values change
by **0.325 log-ratio units on average**, **0.940 at p95**, and **6.817 at maximum**.
Applying the *ungated diagnostic* transform `100 exp(min(0, Gshadow−Goriginal))`
to the raw word-mean GOPs changes it by **2.73 points on average**, with a
**15.44-point maximum**. These are not differences between validated whole-passage
grades. Most such grades are now unavailable. B2 timing agreement cannot justify
adopting int8 posterior values as equivalent; retain fp32 as the research baseline.

The corrected fp32/int8 runs produced identical Whisper hypotheses. Earlier
unchanged-setting runs on identical waveform hashes differed for poor clips
**02 and 10**: the original fp32 pair 10 output counted **23** regex fillers,
whereas this rerun counts **zero**. That earlier adverse evidence remains in the
[original raw output](https://github.com/abubakar1010/ListenUp/blob/b9d36ef477954dcbe11778dd8186673d4e0509fd/docs/spikes/shadow20/results/results-fp32.json).
The independent review also reproduced those two unstable clips before these fixes.
Do not attribute non-GOP changes to phoneme quantization or infer repeatability
from the newest matching hypotheses. Cache transcription/alignment when isolating
precision effects. Both corrected runs retain the original per-phone, boundary,
pitch and echo evidence exactly; the eligibility rules and ASR-derived fields
explain the changed grades/markers.

## Measure verdicts (corrected fp32 baseline)

| Measure | Rating | Evidence and practical limit |
| --- | --- | --- |
| Rhythm and timing | **works, where observable on this synthetic test** | 8 strict wins and 2 missing comparisons; late-only controls still fall from 93.9 to 30.7 and 96.0 to 41.2. Zero/one-word evidence is unavailable, not a zero grade. ASR support and provisional forced boundaries remain confounders; real shadow-lag calibration is absent. |
| Pronunciation (phoneme GOP) | **weak; mostly unavailable** | 1 strict win and 9 missing comparisons. Raw forced-phone diagnostics respond to filtering, but cannot establish pronunciation quality. For example, ungated diagnostic transforms on pair 01 good/lowpass are 90.4/0.6; both whole-passage grades are unavailable because word corroboration is incomplete. Human phone-error labels are still needed. |
| Accent | **fails; experimental** | 3 strict wins, 2 missing comparisons and 5 reversals after excluding ambiguous repeated-token occurrences. The changed subset itself changes pitch correlation; a few extra wins do not validate vowel/consonant/stress assessment. Keep it outside overall. |
| Articulation | **weak; mostly unavailable** | 1 strict win and 9 missing comparisons. Raw word-final GOP shares pronunciation's acoustic confounds; ungated pair 01 good/lowpass transforms are 100.0/0.9. These diagnostics are not eligible grades or independently verified word/sound markers. |
| Fluency | **weak** | 7 wins, 1 tie and 2 missing comparisons. Filler-only pauses lower both controls to about 50, but pair 02's poor speech still scores 100 despite incomplete word coverage. Surviving unambiguous gaps do not measure all hesitations/restarts. |
| Filler words | **fails** | 0 wins and 10 ties in this rerun. Pair 01's filler-only pass counts 2, pair 02's counts 0. The historical pair 10 count of 23 versus the new zero shows instability, not successful retention. Lexical “like” in pair 08 remains a false-positive candidate. No AT-17 pass. |
| Completeness | **weak** | 9 wins and 1 tie, but pair 01's skipped-word control stays 87.5, identical to good. Good readings in pairs 01/02 score 87.5 due to ASR/text mismatch; low-pass-only scores fall to 50.0/37.5 without deleting words. Pair 09's omitted word is restored by ASR and completeness stays 100; full ASR corroboration is not literal presence ground truth. |

**The narrow combined-ranking acceptance criterion does not pass.** Only two
pairs reach four strict wins out of seven. There is no available-measure average
or substitution of raw diagnostic transforms for missing grades. Pair 09's
hallucinated word and the unstable/subset-dependent measures show why even those
two majority results do not independently validate the measures. The original
10/10 result is withdrawn, not retained as an acceptance claim.

**Echo screen: weak.** At threshold 0.6, all 10 exact copies are flagged and all
10 independent good voices are below threshold. Only 4/10 digital mixtures are
flagged; 6 mixtures are missed. No loudspeaker/room echo or acoustic echo
cancellation was tested. A clean screen is not proof that a microphone recording
contains no original playback.

For the combined poor controls, this rerun detects zero fillers in nine pairs
and one in pair 08. Against two intended insertions, only pair 08 is numerically
within one, and that is a lexical false-positive candidate, not validated recall.
Original/good readings have no independent filler annotation; the synthesized
insertions have not been teacher-verified. This does not supply #22's
precision/recall or AT-17 count gate.

## Go/no-go and next work

**No-go for shipping these seven scores; go for continued self-hosted research.**
ADR 0010 remains the privacy/default decision. The corrected experiment fails
the ten-pair majority criterion as well as individual validity gates. ADR 0050
retains the candidate model choices and unchanged carry-forward for #21, #22 and
#80. Keep raw original-relative evidence, explicit missingness/reasons, experimental
accent and provenance. Validate human shadowing, boundaries, phone errors, word
presence and microphone leakage before promoting transforms or markers.
