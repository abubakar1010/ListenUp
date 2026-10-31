# ADR 0095: Provisional Shadow delivery scores

- Status: Accepted (Q1–Q3, owner, 2026-10-31); starting parameter values proposed
- Story: #82. Related: ADRs 0010, 0050, 0074; #80, #21, #22, #83, #107, #110
- Requirements: FR-SH-4, FR-SH-9, FR-SH-15, FR-SH-18, AT-17

## Context

#82 scores each Shadow round on rhythm and timing, fluency, filler words and
completeness. The SRS defines what each measure grades (5.5.1) and that each is
0 to 100, with an overall score that is the equal mean of every measure except
accent (FR-SH-9, FR-SH-15). It does not say how a lag in seconds or a pause count
becomes 0 to 100; D3 (#4) fixed only the gist rubric, the gist time limit and the
AT-15/AT-21 thresholds. The issue leaves the mapping to golden-set calibration
(#107, #110), and ADR 0050 forbids promoting the spike prototype's transforms to
approved scoring policy. Grading is built against the synthetic assessment
provider only (E2, ADR 0074), and production has no assessment provider.

## Decision

**Q1 — Provisional, versioned parameters.** The transforms are pure code in
`modules/grading/domain/delivery.py`; every threshold and weight lives in
`modules/grading/domain/shadow_delivery.v<N>.json`, which states
`"provisional": true, "calibrated": false`. The loader refuses malformed or
inconsistent values. Each stored result records the parameter version, so #110
can replace the values with evidence and rescore. Until calibration these numbers
are placeholders, not a verdict on the learner.

**Q2 — Overall over the measures available.** Until #83 adds pronunciation and
articulation, the overall score is the equal mean, halves rounded up, of the
measures that are observable, and the result lists that basis. Accent is never
included. A measure that cannot be observed is left out, never counted as 0 or
100; if none is observable there is no overall score.

**Q3 — Echo check plumbing only.** The assessment contract carries no leakage
signal and ADR 0050 requires real loudspeaker and room echoes before a leakage
screen is trusted. The domain takes an optional leakage signal in [0, 1]: absent
means `unchecked` (never "clean"), at or above the threshold means `leak` with the
`use_headphones` message, and the round keeps its numbers. The detector and its
reliability belong to #80.

### Rules the code applies

All times are on the recording's clock; the caller places the original's words on it.

- **Completeness** = reference words found / reference words (SRS 5.5.1), each
  word counted once. Out-of-range indices are ignored.
- **Rhythm and timing.** Dynamic time warping pairs the learner's words, in spoken
  order, with the original's, in reference order, at cost 0 for the same word and
  1 otherwise, so timing cannot hide a late start. Ties prefer the diagonal, which
  times a restarted word at its final attempt. Components: onset credit per paired
  word from |lag|; speech-rate ratio over the paired span; phrasing, the share of
  the original's breaks the learner also paused at. A component with nothing to
  observe drops out and the weights renormalize. At least two paired words are
  required (ADR 0050).
- **Fluency.** A pause counts by how much it exceeds the original's gap between
  the same two words (a hesitation or a long pause), and a step back in the text
  is a restart. A gap next to a word the original's alignment could not place is
  not judged. Weighted events are rated per minute of the original passage.
- **Filler words.** Count and rate per minute of the original passage, labelled an
  estimate until B4 (#22) passes and `count_validated` becomes true.
- **Per minute of the original passage**, so rounds 1–3 on one segment compare
  like for like (FR-SH-12) and a learner's own pauses cannot dilute a rate.
- **Null is explicit.** No reference words, no matched words, too few paired words
  or no original timing each give a null score with a reason (ADR 0050).

### Starting values (version 1, proposed for owner confirmation)

| Parameter | Value | Meaning |
| --- | --- | --- |
| `timing.onset_full_credit_s` / `onset_zero_credit_s` | 0.5 / 1.5 | full credit within 0.5 s of the original's onset, none from 1.5 s, linear between |
| `timing.rate_tolerance` / `rate_zero` | 0.1 / 0.5 | full credit within 10 % of the original's rate, none from 50 % |
| `timing.break_s` | 0.3 | a gap of 0.3 s or more is a break |
| `timing.weights` | onsets 60, rate 20, phrasing 20 | |
| `fluency.hesitation_s` / `long_pause_s` | 0.3 / 1.0 | excess pause thresholds, inclusive |
| `fluency.event_weights` | hesitation 1, long pause 2, restart 2 | |
| `fluency.zero_events_per_minute` | 12 | weighted events a minute that score 0 |
| `fillers.free_per_minute` / `zero_per_minute` | 1 / 10 | |
| `fillers.count_validated` | false | B4 (#22) has not passed |
| `echo.leakage_threshold` | 0.5 | applies once #80 supplies a detector |

These values are planning placeholders chosen to be plausible for shadowing, not
measured, and they must not be described as validated.

## Consequences

- Synthetic assessment output exercises the arithmetic and persistence only;
  synthetic numbers are never shown as learner results.
- AT-17 is met in part on constructed timings (on-time speech above late starts).
  The real-sample part, the filler count within one, and the leakage detector stay
  with #80, #22 and #110. The p95 50 s budget is deferred to #21 and tracker #155.
- A new parameter set is a new file version, so stored scores stay comparable.
- The round job, `grading.round_grades` migration and `grade.ready` event follow
  after #90 merges.
