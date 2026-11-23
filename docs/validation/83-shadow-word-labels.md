# #83 — Pronunciation, articulation, accent and word labels

## Scope and status

E2 implementation against `fake-assessment` only (owner exception E2, #119,
ADR 0074). There is no migration: `grading.round_grades.word_labels` comes from
`20261031_82_round_grades`. Decisions are in
[ADR 0099](../adr/0099-provisional-shadow-speech-measures-and-word-labels.md).

What was built:

- three provisional measures, as pure functions over the port's signals;
- the overall round score over the six measures that are not accent, with the
  weights in versioned config stored with each grade;
- a label for every segment word, with sound-level reasons, written by the round job;
- the scored projection of `GET /shadow/rounds/{id}/grade`, behind the unchanged
  learner gate;
- web feedback with word markers.

Learners still get `unavailable` for every round, as #82 left it.

**Not met:**

- label and measure quality on real recordings;
- accent fairness across speaker accents and the golden set (#107, #110);
- the vowel part of accent, which needs reference phone scores (#80);
- every real-model criterion of #80, #21 and #22.

The synthetic provider scores every sound 0.75 with the placeholder label
`synthetic`, so it proves the arithmetic, storage and projection, never speech
accuracy. The PR uses **Refs #83**.

## Acceptance criteria

Unit tests are in `apps/api/tests/unit/test_shadow_speech_measures.py` unless a row
names another file. Integration tests are in
`apps/api/tests/integration/test_shadow_delivery_jobs.py`. Web tests are in
`apps/web/src/features/shadow/`.

| Criterion | Evidence | State |
| --- | --- | --- |
| FR-SH-9: all seven measures (0 to 100) and an overall | `test_a_round_has_all_seven_measures_word_labels_and_both_versions`, `test_round_job_stores_seven_measures_and_labels_every_word` (integration), `test_round_result_stores_seven_measures_and_the_overall_over_six` (`test_shadow_round_inputs.py`) | Met on synthetic evidence; a measure that cannot be observed is null with a reason (ADR 0050) |
| D11: two rounds that differ only in accent have equal overall scores | `test_two_rounds_that_differ_only_in_accent_have_equal_overall_scores` (whole round, only the pitch contour differs), `test_accent_never_changes_the_overall` (Hypothesis) | Met |
| Overall = mean of the six non-accent measures, as configured | `test_overall_is_the_equal_mean_of_the_six_measures` (75, by hand), `test_overall_halves_round_up`, `test_overall_uses_the_configured_weights` (530/7 → 76), `test_an_unobservable_measure_is_left_out_of_the_overall`, `test_no_observable_measure_gives_no_overall`, `test_the_packaged_speech_parameters_are_provisional_uncalibrated_and_equal`, `test_invalid_speech_parameters_are_refused` (`overall.weights` with accent or missing a measure) | Met |
| Pronunciation: per-sound goodness averaged per word | `test_pronunciation_averages_sound_scores_per_word_then_over_words` (70), `test_a_word_without_sound_detail_uses_its_word_accuracy`, `test_a_restarted_word_is_judged_on_its_final_attempt`, `test_pronunciation_with_no_word_said_is_unobservable_not_zero` | Met (formula) |
| Articulation: dropped, merged or unclear sounds, endings and linking | `test_articulation_weighs_dropped_and_unclear_sounds_and_word_endings` (64), `test_sounds_at_a_linking_boundary_weigh_more` (63), `test_a_gap_of_linking_gap_s_or_more_does_not_link`, `test_a_very_short_unclear_sound_is_merged_but_a_short_clear_one_is_not` (86), `test_sound_issue_boundaries`, `test_articulation_without_sound_detail_is_unobservable_not_perfect` | Met (formula) |
| Accent: vowel quality, stress and pitch contour compared with the original speaker | `test_accent_follows_the_speakers_contour_not_their_voice_or_pace`, `test_an_opposite_pitch_contour_earns_no_pitch_credit`, `test_partial_contour_agreement_earns_linear_credit` (81), `test_vowel_quality_compares_each_vowel_with_the_speakers_own` (90), `test_a_flat_original_contour_cannot_be_compared`, `test_accent_needs_min_words_said_by_both`, `test_reference_frames_become_per_word_prosody` (`test_shadow_round_inputs.py`) | Formula met; vowels are null in production until #80 adds reference phone scores |
| FR-SH-10: each word is good, needs work or missed | `test_every_segment_word_is_labelled_good_needs_work_or_missed`, `test_needs_work_carries_sound_level_reasons_with_position_and_linking`, `test_a_good_average_with_one_unclear_sound_still_needs_work`, `test_a_word_at_good_from_is_good`, `test_round_result_labels_every_segment_word_as_stored_json`, `test_round_job_stores_seven_measures_and_labels_every_word` (integration) | Met on synthetic evidence |
| Markers on the transcript after the round, rounds 2 and 3 included | `ShadowRounds.test.tsx`: "shows the markers of every recorded round once it ends, round 2 included", "hides every marker while the next round is shadowed without text"; `ShadowCompletion.test.tsx`: "round 3 word markers show on the completion screen…" | Met, behind the learner gate |
| Markers not colour-only (DoD, UX-01, WCAG 1.4.1) | `RoundFeedback.test.tsx`: "every word carries its marker in words, not colour alone", "words to work on list their sound-level reasons in plain words"; axe state `shadow word markers` at 360 px, 1280 px and dark | Met |
| Accent apart from the overall, "experimental", "compared with this speaker", never correctness | `RoundFeedback.test.tsx`: "accent stands apart as experimental guidance compared with this speaker", "a scored round shows the six measures and the overall without accent"; integration `test_a_released_grade_shows_word_labels_and_accent_apart_from_the_score` (`in_overall: false`) | Met |
| Learner grading stays as gated as #82 | `test_learner_grades_stay_unreleased_under_e2`, `test_synthetic_labels_are_never_shown_even_once_released`, `test_a_released_grade_without_all_seven_measures_is_unavailable`, `test_synthetic_grade_is_unavailable_and_retry_is_owned` (from #82); `RoundFeedback.test.tsx` "an unavailable grade says so…", "a failed read also reads as unavailable…"; e2e `shadow.spec.ts` | Met |
| FR-SH-18 / NFR-AI-5: versions with each grade | `test_round_result_stores_seven_measures_and_the_overall_over_six` (`speech_parameters_version`, `overall_weights`), integration job test | Met |
| Grades and labels survive recording deletion (D7) | `ShadowRounds.test.tsx` "keeps a round's feedback after its recording is deleted (D7)", completion test round 1 | Met (web) |

## Red and green

Commands from `apps/api` unless stated. In the table, "speech" stands for
`uv run pytest tests/unit/test_shadow_speech_measures.py -q`.

| Cycle | Red (observed) | Green (observed) |
| --- | --- | --- |
| 1 Pronunciation, articulation, labels (speech) | Collection error: `ModuleNotFoundError: listenup.modules.grading.domain.speech_measures` | First run 1 failed: `test_a_gap_of_linking_gap_s_or_more_does_not_link` got 63, not 64. 0.35 − 0.30000000000000004 = 0.0499… linked at the exact threshold. Gaps are now rounded to nine places, as in `delivery.py`. Then 22 passed (98 with the #82 scoring tests) |
| 2 Accent (speech) | `ImportError` (Prosody, accent, word_pitch, hertz_to_cents) | 33 passed |
| 3 Overall and whole round (speech) | `ImportError: cannot import name 'overall_score'` | 120 passed with the #82 scoring tests, so the shared `overall_score` refactor kept #82's overall |
| 3b Empty reference | `assert {'no_matched_...erence_words'} == {'no_reference_words'}` | 45 passed |
| 4 Strict parameter file (speech) | 38 failed: the packaged file was missing and 37 invalid values were accepted. The unknown-key, missing-section and non-mapping cases already passed through the cycle-1 key check | 90 passed |
| 5 Round result (`uv run pytest tests/unit/test_shadow_round_inputs.py -q`) | 4 failed: missing `prosody_from_frames`, `round_result`, `spoken_inputs` | First run 1 failed: reasons were stored as a tuple, not a JSON list. Fixed, then 176 passed across the three unit files |
| 6 Round job (`uv run pytest tests/integration/test_shadow_delivery_jobs.py -k "seven_measures or persists_measures"`) | The first failure was an `ImportError` from the job importing the removed `delivery_result`, which is **not** behavioral evidence. With the old `round_inputs.py` restored temporarily: `assert {'completenes...cy', 'timing'} == {'accent', …}` (only four measures stored) | 38 passed (integration and inputs) |
| 7 Gated projection (`-k "unreleased or never_shown or released_grade"`) | 3 failed: `service` has no `LEARNER_GRADES_RELEASED` | 31 passed (all job integration tests) |
| Web 1 `pnpm vitest run src/features/shadow/RoundFeedback.test.tsx` (from `apps/web`) | `Failed to resolve import "./RoundFeedback"` | 12 passed |
| Web 2 `pnpm vitest run src/app/eventKeys.test.ts` | `expected [['sessions','gist-grade']] to deeply equal [… , ['sessions','round-grade']]` | 6 passed |
| Web 3 `pnpm vitest run src/features/shadow/ShadowRounds.test.tsx` | 3 failed: no "Round 2 word markers" or "Round 1 word markers" region. The fourth case ("asks for no grade before a round is recorded") passed at once and is characterization | 82 shadow tests passed |
| Web 4 `pnpm vitest run src/features/shadow/ShadowCompletion.test.tsx` | 1 failed: no "Round 3 word markers" region | Two older assertions expected one page-level "Feedback unavailable." paragraph. They now expect one notice per recorded round (3), with the grade routes mocked. 194 passed (shadow, session, app) |

Not test-first:

- `test_a_released_grade_without_all_seven_measures_is_unavailable` was written just
  after its guard. The gate mutants below show it detects removing the guard.
- `test_the_scored_measures_are_the_six_without_accent` and
  `test_learner_pitch_is_compared_in_cents_word_by_word` were written in their
  cycles' red batch.

## Mutation check

Temporary mutants, each restored afterwards (scripts in the session scratchpad).
Every one was caught by the three unit files.

- The overall iterates the measures (so it counts accent).
- The linking, dropped, unclear and `good_from` boundaries are changed between
  inclusive and exclusive.
- A good word ignores its sound issues.
- The vowel gap is absolute (it penalises sounding clearer than the speaker).
- Merged is never detected.
- The linking and final position weights are ignored.
- A flat learner contour counts as unobserved.
- A restart keeps the first try.
- `min_words` 2 is accepted.
- An accent overall weight is accepted.
- Accent weights are not renormalized.

Gate mutants, caught by the integration tests:

- the synthetic check is removed;
- the seven-measure check is removed;
- `LEARNER_GRADES_RELEASED` is set to `True`.

## Review fixes (#279 review, 2026-11-02)

A fresh-session review found the issues below; the owner asked for them to be fixed
and for the open questions to be settled with the reviewer's recommendations (ADR
0099, "Owner decisions"). Commands are from `apps/api`.

| Finding | Red (observed) | Green (observed) |
| --- | --- | --- |
| The merged check had no rounding: a 30 ms unclear sound was merged or unclear depending on where it sat | `test_an_unclear_sound_of_exactly_merged_max_s_is_unclear_wherever_it_sits`: 1 failed (`['merged'] == ['unclear']` at 0.33 s; 0.30 s and 1.27 s passed) | length rounded to nine places; 93 passed (speech) |
| Reference pitch frames were placed at their start, not their centre | `test_reference_frames_become_per_word_prosody`, rewritten so frame 4 (centre 10 090 ms) belongs to word 1: 1 failed (word 1 pitch `None`, not 6300) | frames placed at `(i + 1/2) × step`; 103 passed (two unit files) |
| The release gate ignored calibration | `test_a_grade_from_uncalibrated_parameters_is_never_shown_even_once_released[parameters_calibrated]` and `[speech_parameters_calibrated]`: 2 failed (`status: scored` projected) | both flags required; 34 passed (job integration) |
| The accent assertion compared values with themselves; needs-work and missed words never went through the job | Characterization: the pinned accent (0, reason null) and `test_needs_work_and_missed_words_are_stored_and_projected_with_their_reasons` passed at once, because the behavior already existed | 35 passed (job integration) |

Tests that need the projection now also mark the row calibrated
(`_pretend_calibrated`), as they mark it non-synthetic.

## Checks

Backend, from `apps/api`:

- `uv run ruff format --check .` and `uv run ruff check .`: clean.
- `uv run mypy`: clean (218 files).
- `uv run lint-imports`: 6 contracts kept.
- `uv run python scripts/export_openapi.py`, then `pnpm api:generate`: committed.

Web, from `apps/web`:

- `pnpm lint`, `pnpm typecheck` and `pnpm format:check`: clean.
- `pnpm test:coverage`: 72 files, 777 tests passed.
- `pnpm build`, then `pnpm size`: 127.4 kB of initial JavaScript gzip (budget 200 kB).
- `pnpm e2e e2e/shadow.spec.ts e2e/keyboard-paths.spec.ts` (Chromium): 13 passed.
- `pnpm e2e:a11y -g "plan finished|shadow word markers"`: 6 passed (360 px, 1280 px
  and dark).

Full runs:

- Backend, with PostgreSQL required:
  `LISTENUP_REQUIRE_DB=1 uv run pytest -m 'not performance' --cov --cov-report=xml`
  gave **2,911 passed, 13 skipped**. The skips are the S3 tests: there is no S3
  server in the cloud container, and CI runs them. `uv run pytest -m performance
  --no-cov`: 1 passed.
- Changed-line coverage against `main` (`diff-cover`): backend **366 lines, 100 %**;
  web **32 lines, 100 %**. `check-coverage.py` resolves every runtime file for both
  applications.
- `uv run alembic heads`: one head (`90_session_deletion`). No migration was added.

One unrelated test, `test_media_sandbox.py::test_cpu_budget_retains_auto_reaped_and_orphaned_children[False]`,
failed once in a parallel unit run under load. It passed 3 times out of 3 on its own
and in the full run.
