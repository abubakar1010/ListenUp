# #82 — Shadow round delivery scores

## Scope and status

Partial. Owner decisions of 2026-10-31 (plan review): Q1 provisional versioned
parameters, Q2 overall over the available measures, Q3 echo plumbing only; the
version 1 starting values were confirmed the same day as placeholders, not evidence
([ADR 0095](../adr/0095-provisional-shadow-delivery-scores.md)). Built against the
synthetic assessment provider under E2 ([ADR 0074](../adr/0074-speech-assessment-contract-split.md)).

Done: the pure scoring for timing, fluency, filler words and completeness, the
version 1 parameter file and its validation, and the echo flag rule.

Not yet built: the `grading.round_grades` migration, the lane-1 round job, its
storage of measures and provider info, and the `grade.ready` event. They wait for
#90 to merge; this session does not own migrations until then.

## Acceptance criteria

All tests are in `apps/api/tests/unit/test_shadow_delivery_scoring.py`.

| Criterion | Evidence | State |
| --- | --- | --- |
| AT-17 (part): on-time speech scores higher than the same text with late starts | `test_on_time_speech_scores_higher_than_the_same_text_with_late_starts` (100 vs 66, hand-worked), `test_a_slower_speech_rate_loses_onset_and_rate_credit`, `test_starting_later_never_improves_timing` (Hypothesis) | Met on constructed timings only; a real known sample needs a real provider (#80) |
| AT-17: fillers within one of the true count, or labelled estimate | `test_fillers_are_counted_and_rated_per_minute_as_an_estimate`, `test_a_validated_filler_count_is_not_labelled_an_estimate`, `test_the_packaged_parameters_are_provisional_and_uncalibrated` | Labelled estimate; the count accuracy is B4 (#22) |
| Scores within the p95 50 s budget | — | Deferred until staging — unverified (#21, tracker #155). Scoring itself takes about 37 ms for 300 words on the dev container (not a budget measurement) |
| Leaking original flagged with a headphones message | `test_leakage_at_the_threshold_asks_for_headphones`, `test_no_leakage_signal_means_the_echo_check_did_not_run`, `test_an_invalid_leakage_signal_is_refused` | Rule only (Q3 c); the detector and its reliability are #80 |
| Measures and provider info stored per round (FR-SH-18) | — | Not built: waits for #90 and the migration |
| Each measure 0 to 100, overall the equal mean without accent (FR-SH-9, FR-SH-15) | `test_overall_is_the_equal_mean_of_the_measures_available`, `test_an_unobservable_measure_is_left_out_of_the_overall`, `test_accent_and_unbuilt_measures_never_enter_the_overall`, `test_every_score_is_bounded_or_explicitly_unobservable` | Met for the four measures (Q2) |
| Null never becomes 0 or 100 (ADR 0050) | `test_no_matched_words_is_unobservable_not_zero`, `test_an_empty_reference_is_reported_as_such`, `test_timing_needs_two_matched_words`, `test_timing_needs_the_original_timing_of_matched_words`, `test_a_pause_beside_words_the_original_could_not_place_is_not_judged`, `test_fluency_needs_the_originals_duration`, `test_fillers_need_the_originals_duration` | Met |

## Red and green

Command for every cycle, from `apps/api`:
`uv run pytest tests/unit/test_shadow_delivery_scoring.py -q`.

| Cycle | Red (observed) | Green (observed) |
| --- | --- | --- |
| 1 Completeness and no matched words | Collection error: `ModuleNotFoundError: listenup.modules.grading.domain.delivery` | 4 passed |
| 2 Timing | 7 failed: timing score `None` (not built) | First run: 2 failed. The restart test's hand value (62) was wrong: DTW has two equal-cost alignments, and the diagonal tie-break pairs the restart with its final attempt, the intended rule. Recomputed by hand: 59. The late-start fixture shifted single words past their neighbours (unrealistic, so DTW skipped them); it was rebuilt as a late second phrase, recomputed by hand: 66. Then 11 passed |
| 3 Fluency | 7 failed: fluency `None` | 18 passed |
| 4 Fillers, overall, echo, parameters | 32 failed (missing `filler_count`, `echo`, overall, validation); 3 validation cases already passed through the cycle-1 loader | 53 passed, then the packaged file was missing (`FileNotFoundError`); after adding it, 54 passed |
| 5 Empty reference | `{'no_matched_words'} == {'no_reference_words'}` (the branch was dead, found by coverage) | 58 passed |

The three Hypothesis invariants were added after the measures, as
characterization; they passed at once.

## Mutation check

Temporary mutants, each restored afterwards; every one was caught:
long-pause and hesitation boundaries made exclusive, the DTW tie-break preferring a
repeated original word (the first attempt was a list reorder, which `min` over
`(cost, tag)` ignores, so it was equivalent; the tag swap was caught), gaps beside
unplaced words judged, the echo threshold made exclusive, unobservable measures
counted in the overall, timing on one word, restarts dropped, the estimate label
dropped, the original's gap ignored, phrasing always credited.

## Checks

From `apps/api`: `uv run ruff format --check .`, `uv run ruff check .`,
`uv run mypy`, `uv run lint-imports` (6 contracts kept). Coverage of
`grading/domain/delivery.py`: 100 % of lines and branches.
