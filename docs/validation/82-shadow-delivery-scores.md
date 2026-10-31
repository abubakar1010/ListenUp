# #82 — Shadow round delivery scores

## Scope and status

E2 implementation against `fake-assessment` only. The five existing commits are
preserved; ADR 0095 and 0096 were renamed to the assigned 0092 and 0093 in a new
commit. No additional ADR was added. The migration token belongs to this session
per #119; the old #90 wait is superseded.

Built: the four provisional scoring rules, assessment conversion, lane-1 round job,
`grading.round_grades`, transactional queue/event delivery, 120-second availability
deadline and owned retry. Synthetic scores are stored for contract testing but are
never exposed as learner assessments. Existing recording and three-round plan
completion behavior stays independent of grading.

The browser offset/design update remains with its owners (ADR 0093). With no
stored offset, timing is null with `playback_offset_unknown`; other measures remain
observable. Echo plumbing stores `unchecked` without a detector and can represent
`use_headphones` when a signal is supplied. There is no real leakage detector.

**Not met:** AT-17 on a real known sample, B4 filler recall/count accuracy, and the
p95 50 s budget. Synthetic timings/fillers establish none of these. Real leakage
reliability is also unverified. #80/#21/#22 and quality/calibration gates remain;
#155 tracks the eventual host measurement. Use **Refs #82**, never an issue-closing
reference. No stage-0 host or real speech model was used.

## Acceptance criteria

Tests are in `apps/api/tests/unit/test_shadow_delivery_scoring.py` unless a row
names another file.

| Criterion | Evidence | State |
| --- | --- | --- |
| AT-17 (part): on-time speech scores higher than the same text with late starts | `test_on_time_speech_scores_higher_than_the_same_text_with_late_starts` (100 vs 66, hand-worked), `test_a_slower_speech_rate_loses_onset_and_rate_credit`, `test_starting_later_never_improves_timing` (Hypothesis) | Met on constructed timings only; a real known sample needs a real provider (#80) |
| AT-17: fillers within one of the true count, or labelled estimate | `test_fillers_are_counted_and_rated_per_minute_as_an_estimate`, `test_a_validated_filler_count_is_not_labelled_an_estimate`, `test_the_packaged_parameters_are_provisional_and_uncalibrated` | Labelled estimate; the count accuracy is B4 (#22) |
| Scores within the p95 50 s budget | — | Deferred until staging — unverified (#21, tracker #155). Scoring itself takes about 37 ms for 300 words on the dev container (not a budget measurement) |
| Leaking original flagged with a headphones message | `test_leakage_at_the_threshold_asks_for_headphones`, `test_no_leakage_signal_means_the_echo_check_did_not_run`, `test_an_invalid_leakage_signal_is_refused` | Rule only (Q3 c); the detector and its reliability are #80 |
| Measures and provider info stored per round (FR-SH-18) | `test_round_job_persists_measures_provenance_and_one_event` | Met for synthetic contract evidence; not learner/model quality |
| Each measure 0 to 100, overall the equal mean without accent (FR-SH-9, FR-SH-15) | `test_overall_is_the_equal_mean_of_the_measures_available`, `test_an_unobservable_measure_is_left_out_of_the_overall`, `test_accent_and_unbuilt_measures_never_enter_the_overall`, `test_every_score_is_bounded_or_explicitly_unobservable` | Met for the four measures (Q2) |
| Original words on the recording clock (ADR 0093) | `test_original_words_are_placed_on_the_recording_clock`, `test_original_words_outside_the_segment_are_dropped`, `test_an_unknown_playback_offset_is_refused` | Met for the rule; browser capture and offset persistence remain outside this continuation |
| Provider, model and version per result; synthetic output marked (NFR-AI-5, ADR 0074) | `tests/unit/test_shadow_round_inputs.py`: `test_speech_info_stores_provenance_and_marks_synthetic_output`, `test_recorded_words_and_fillers_keep_reference_indices_and_times`; `tests/unit/ai/test_assessment_contract.py`: `test_callers_tell_synthetic_output_from_the_gateway` | Built and persisted by the round job |
| Null never becomes 0 or 100 (ADR 0050) | `test_no_matched_words_is_unobservable_not_zero`, `test_an_empty_reference_is_reported_as_such`, `test_timing_needs_two_matched_words`, `test_timing_needs_the_original_timing_of_matched_words`, `test_a_pause_beside_words_the_original_could_not_place_is_not_judged`, `test_fluency_needs_the_originals_duration`, `test_fillers_need_the_originals_duration`, `test_fluency_with_nothing_to_judge_is_unobservable_not_perfect`, `test_an_unobservable_measure_is_left_out_of_the_overall` | Met |

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
| 6 Recording clock | `ImportError: cannot import name 'place_original'` | 61 passed |
| 7 Assessment inputs (`uv run pytest tests/unit/test_shadow_round_inputs.py -q`) | `ModuleNotFoundError: listenup.modules.grading.round_inputs` | 4 passed; with the scoring tests, 65 |

The three Hypothesis invariants were added after the measures, as
characterization; they passed at once.

### Fixes from the fresh-session review

The review of `a83cffe` is posted on PR #261. Its findings were fixed test-first:

| Cycle | Red (observed) | Green (observed) |
| --- | --- | --- |
| 8 Fluency with nothing to judge (ADR 0050) | 3 failed: `assert (100, None) == (None, 'no_judged_gaps')`, the missing `judged_gaps` detail, and the overall still counting fluency 100 for one word said | 63 passed, with `test_a_restart_alone_is_observed_disfluency` |
| 9 Halves up despite float error | `assert 77 == 78` (lags 0.4 and 0.6 s give exactly 77.5, held as 77.4999...) | 64 passed. A brute-force grid of two-word timings against exact fractions then found no mismatch |
| 10 Boundaries (characterization) | Passed at once; red is the mutants below, each of which failed these tests | 68 passed |
| 11 Strict parameter file | 7 failed: unknown keys (`brake_s`, `notes`), all-zero event weights and non-mapping files accepted, and the loaded values still mutable | 75 passed |
| 12 Synthetic check from the gateway (`uv run pytest tests/unit/ai/test_assessment_contract.py -q`) | `ImportError: cannot import name 'is_synthetic'` | 30 passed with `test_shadow_round_inputs.py` and `tests/architecture` |

Cycle 10's tests: `test_early_speech_is_off_time_too` (now pinned at 63 for leading
and lagging by 1.0 s, with valid word times),
`test_a_break_is_a_gap_of_break_s_or_more_on_both_sides`,
`test_a_repeated_word_is_not_a_restart_and_its_gap_is_not_judged`,
`test_overlapping_original_words_expect_no_gap`, the `timing.rate_zero` validation
case, and `test_overall_is_the_equal_mean_of_the_measures_available` (now pinned at
76 by hand).

ADR 0093 gained the measurement rules for the offset (recorder `start` event,
`currentTime` correction, null after a stall or before the recorder started). The
review's four policy questions are recorded as open in ADR 0092; they do not
change version 1.

## Mutation check

Temporary mutants, each restored afterwards; every one was caught:
long-pause and hesitation boundaries made exclusive, the DTW tie-break preferring a
repeated original word (the first attempt was a list reorder, which `min` over
`(cost, tag)` ignores, so it was equivalent; the tag swap was caught), gaps beside
unplaced words judged, the echo threshold made exclusive, unobservable measures
counted in the overall, timing on one word, restarts dropped, the estimate label
dropped, the original's gap ignored, phrasing always credited.

Review mutants, all caught after the fixes: round-half-to-even and half-up
without the float correction, the expected-gap clamp removed, the
`rate_zero > rate_tolerance` check removed, the break threshold made exclusive for
the original and for the learner, a repeated word counted as a restart, early speech
given full onset credit, and the no-judged-gap rule removed.

## Checks

From `apps/api`: `uv run ruff format --check .`, `uv run ruff check .`,
`uv run mypy`, `uv run lint-imports` (6 contracts kept). Coverage of
`grading/domain/delivery.py` and `grading/round_inputs.py`: 100 % of lines and
branches. `tests/architecture`: 4 passed.

## Continuation acceptance and safety mapping

Tests below are in `tests/integration/test_shadow_delivery_jobs.py` unless stated.

| Requirement | Named evidence |
| --- | --- |
| Lane 1, transactional admission | `test_recording_queues_one_lane_one_job_and_private_pending_grade`, `test_queue_and_grade_roll_back_together` |
| FR-SH-18 and id-only grade.ready, no duplicates | `test_round_job_persists_measures_provenance_and_one_event`, `test_event_failure_rolls_back_scores` |
| FR-SH-16 failure, retry, deadline, late success | `test_provider_failure_keeps_recording_and_retry_can_score`, `test_retry_coalesces_live_work_and_resets_only_admitted_cycle`, `test_due_deadline_marks_unavailable_without_changing_recording`, `test_finished_round_deadline_is_a_noop` |
| No stale callback or cross-learner writes | `test_stale_generation_cannot_assess_or_change_new_cycle`, `test_round_grade_rls_and_owner_constraint`, `test_assessment_source_authorizes_round_and_uses_original_words` |
| E2 projection and provider restriction | `test_synthetic_grade_is_unavailable_and_retry_is_owned`, `test_e2_refuses_other_provider_before_any_audio` |
| Consent, deletion, missing source/profile | `test_withdrawn_voice_consent_prevents_assessment`, `test_disabled_account_does_not_assess`, `test_session_deleted_during_assessment_is_not_recreated`, `test_missing_audio_keeps_data_and_never_assesses`, `test_profile_state_never_calls_assessment` |
| Missing offset and headphones evidence | `tests/unit/test_shadow_round_inputs.py::test_missing_playback_offset_only_disables_timing`, `test_delivery_result_keeps_headphones_warning_and_scores` |
| Recording/plan remains independent | `tests/integration/test_shadow_recording.py::test_three_rounds_produce_three_replayable_recordings` |
| Migration/metadata | `tests/integration/test_migrations.py::test_upgrade_downgrade_one_and_upgrade_again`, `test_full_downgrade_leaves_an_empty_database`, `test_history_is_linear` |

## Continuation red/green evidence

Commands run from `apps/api`, using the local PostgreSQL/S3 test services.

| Cycle | Command / actual red | Actual green |
| --- | --- | --- |
| Baseline | Existing two unit files | 65 passed |
| Result serialization | `uv run pytest tests/unit/test_shadow_round_inputs.py -q`: 2 failed / 4 passed, missing `delivery_result` | Both unit files: 67 passed |
| Storage/enqueue | `uv run pytest tests/integration/test_shadow_delivery_jobs.py -xq`: missing `grading.round_grades` | Initial three integration tests plus migration tests: 7 passed |
| Service input | `...::test_assessment_source_authorizes_round_and_uses_original_words`: missing assessment-source boundary | Included in the 7 passing tests above |
| Assessment job | `...::test_round_job_persists_measures_provenance_and_one_event`: pending instead of scored | Four integration tests passed after implementation and correcting fixture playback-key setup |
| Owned API | `...::test_synthetic_grade_is_unavailable_and_retry_is_owned`: 404 instead of 200 | Integration plus recording regressions: 27 passed |
| Finished deadline regression | `...::test_finished_round_deadline_is_a_noop`: incorrectly raised Reschedule | Pending-only callback guard fixed it |

The first integration attempt failed because PostgreSQL was stopped; it is **not**
red evidence. Services were started and the missing-table failure observed before
schema implementation. The first provider-outage assertion expected OSError;
the gateway correctly wraps it as AIUnavailable, and the test was corrected. A
consent test initially used a nonexistent DELETE endpoint; it was corrected to the
existing POST withdrawal API. Neither setup/assertion correction is claimed as
production-behavior red evidence.

Recovery, consent and deletion branches were initially implemented together with
the job before their focused tests. Those subsequent tests are characterization,
not test-first evidence. The finished-deadline defect was observed before its fix.
The earlier five commits' evidence above is retained as recorded by that session;
this continuation does not reconstruct their chronology.

ADR renumbering and generated API artifacts have no executable behavior and need
no artificial red test. OpenAPI was exported and the TypeScript client regenerated.

## Final continuation checks

Pending completion of the current full checks; actual outcomes follow below.
Fresh-session independent review and green required CI remain merge gates. No PR
is opened until the owner requests it; no merge is authorized.
