# ADR 0099: Provisional Shadow pronunciation, articulation, accent and word labels

- Status: Proposed (owner review on the #83 pull request)
- Story: #83. Related: ADRs 0010, 0050, 0074, 0092, 0093; #80, #21, #22, #82, #107, #110
- Requirements: FR-SH-4, FR-SH-9, FR-SH-10, FR-SH-15, FR-SH-18; D3, D11; UX-01, UX-12, UX-33

## Context

#83 adds the last three Shadow measures (pronunciation, articulation and accent),
the overall round score over the six measures that are not accent, and a label for
every segment word. Like #82 it is built against the synthetic `fake-assessment`
provider only, under owner exception E2 (ADR 0074). Grading stays off for learners
until #21, #22, #106, #107, #109 and #110 are done. ADR 0050 forbids promoting spike
transforms to scoring policy and requires null to be explicit.

The speech assessment port gives, per matched reference word, a word accuracy and
ordered sounds with a goodness score in [0, 1], plus the learner's pitch track. The
reference profile (#76, ADR 0050 Q3) holds the original's word timings, pitch and
intensity frames, and no phone-level scores. Phone-level reference GOP is #80's.

No schema change: `grading.round_grades.word_labels` exists (migration
`20261031_82_round_grades`).

## Decision

**D1. Pure functions with a separate versioned parameter file.** The rules live in
`modules/grading/domain/speech_measures.py`. Every threshold and weight lives in
`shadow_speech.v<N>.json`, which says `"provisional": true, "calibrated": false`.
`shadow_delivery.v1.json` (ADR 0092) is unchanged. Each grade stores both versions
(`parameters_version`, `speech_parameters_version`), the speech file's calibration
flag, the overall weights and the overall basis. This answers ADR 0092's open Q3:
the overall definition is versioned with the new measures in their own file, not by
rewriting the delivery file. The loader is strict, as in ADR 0092. It refuses
unknown keys, out-of-range values and an overall weight set that is not exactly the
six scored measures, so accent can never be weighted in (D11).

**D2. Pronunciation** is the per-sound goodness averaged per word, then averaged
over the words the learner said. A missed word counts against completeness, not
pronunciation, so it is not counted twice. A word whose sounds the provider did not
return uses its word-level accuracy, and `word_accuracy_only` records how many did.
A restarted word is judged on its last attempt, as in timing.

**D3. Articulation** is `1 − weighted penalties / weighted sounds` over the sounds of
the words said:

- A sound under `dropped_below` is **dropped**.
- A sound under `unclear_below` is **merged** when it is shorter than
  `merged_max_s` (squeezed into a neighbour), otherwise **unclear**.
- Word endings weigh `position_weights.final`. A sound on a **linking** boundary
  weighs at least `linking_weight`: the last sound of a word, or the first sound of
  the next word, when the next reference word follows with less than
  `linking_gap_s` of silence. Gaps are rounded to nine places first, so a gap of
  exactly the threshold does not link.
- Penalties are the position weight times `issue_weights[issue]`.
- With no sound detail at all, articulation is null (`no_sound_evidence`), never 100.

**D4. Accent** is experimental guidance compared with this speaker, never
correctness. Its components are compared word by word, so they need no shared clock
and still work when the playback offset is unknown:

- **vowels**: each vowel's goodness against the same vowel in this speaker's word.
  Only a shortfall counts, so sounding clearer than the speaker is never marked
  down. Until the profile has phone scores (#80), it is null with the reason
  `no_reference_sounds`.
- **stress**: the Pearson correlation of the words' log durations, i.e. which
  words the speaker leans on. The contract has no syllables, so this is
  phrase-level prominence, not lexical stress inside a word.
- **pitch**: the Pearson correlation of each word's median voiced pitch (cents),
  i.e. the contour. A correlation does not depend on either speaker's register,
  range or pace.

A correlation needs `min_words` words (at least 3) in both speakers. A flat original
cannot be compared (`flat_original`). A flat learner against a varied original
gets 0. The credit is linear from `zero_r` to `full_r`. The available components
are combined with renormalized weights. With none available, accent is null
(`no_accent_evidence`). The parameter file's `experimental: true` stays until the
golden set and the fairness check pass (#110).

**D5. Word labels (FR-SH-10).** Every segment word, in order:

- **missed** when no attempt was matched (no score, no reasons);
- **needs work** when its value (as in D2) is under `labels.good_from`, or when any
  of its sounds has an issue;
- otherwise **good**.

The sound-level reasons are `{sound, position, issue, linking}`, with the issues
dropped, merged, unclear and inaccurate (at or above `unclear_below` but under
`good_from`). Articulation and the markers flag exactly the same sounds, because
they share one annotation step. Labels are stored as
`{index, text, label, score, basis, reasons}`. `basis` is `sounds` or `word`.

**D6. Overall round score.** `delivery.overall_score(measures, weights)` is the one
rule. It is the weighted mean, halves rounded up, of the weighted measures that are
observable, and it reports that basis. A null measure is left out (ADR 0092 Q2).
Version 1 weighs the six measures equally (D3, D11). The delivery-only overall in
`score_round` uses the same function with equal weights.

**D7. The learner gate stays as #82 left it.** `GET /shadow/rounds/{id}/grade` still
answers `unavailable` to every learner. The service now holds the release as the
code constant `LEARNER_GRADES_RELEASED = False`. Turning it on is a reviewed code
change, never a setting. Even when it is on, a grade is projected only when it is
`scored` or `ready`, its evidence is not synthetic, and it has all seven measures.
The OpenAPI schema describes the scored projection (`RoundFeedbackScored`), so the
web client has typed markers. Integration tests turn the constant on to prove the
projection, and they prove that synthetic evidence stays unavailable.

**D8. Web.** `RoundFeedback` reads each recorded round's grade, also after its
recording was deleted (grades and labels stay, D7 of #119). It shows "Feedback
unavailable." exactly as before when the grade is unavailable or cannot be read.
Once released, it shows:

- the six measures and the round score;
- accent in its own "Accent guidance" block marked "Experimental" and "Not in your
  score", with "Compared with this speaker" (UX-33);
- the word markers on the segment transcript.

Needs-work words have a dotted underline and are bold; missed words have a hollow
circle and muted text (UX-12). Every marked word carries a visually hidden label,
and a "words to work on" list says each reason in plain words, so no marker relies
on colour (UX-01, WCAG 1.4.1). Markers show for every round, including rounds 2 and
3, after it ends, on the round's section and on the completion screen. They hide
while any round is being shadowed, because rounds 2 and 3 are spoken without text.

### Starting values (version 1, provisional)

| Parameter | Value | Meaning |
| --- | --- | --- |
| `sounds.dropped_below` / `unclear_below` | 0.2 / 0.5 | sound goodness under which a sound is dropped / unclear |
| `sounds.merged_max_s` | 0.03 | an unclear sound shorter than this is merged |
| `sounds.linking_gap_s` | 0.05 | silence under this links two words |
| `labels.good_from` | 0.7 | a word (and each sound) at or above this is good |
| `articulation.position_weights` | initial 1, medial 1, final 2 | |
| `articulation.linking_weight` | 2 | |
| `articulation.issue_weights` | dropped 1, merged 1, unclear 0.5 | |
| `accent.weights` | vowels 40, stress 30, pitch 30 | renormalized over what is observed |
| `accent.min_words` / `zero_r` / `full_r` | 3 / 0.0 / 0.8 | |
| `accent.vowel_full_gap` / `vowel_zero_gap` | 0.1 / 0.5 | vowel shortfall for full / no credit |
| `accent.vowel_labels` | IPA English vowels | which sound labels are vowels |
| `overall.weights` | 1 each for the six measures | D3, D11 |

These are planning placeholders, not measurements, and must not be described as
validated.

## Consequences

- Synthetic output exercises the arithmetic, the storage and the projection only.
  The fake scores every sound 0.75 with the placeholder label `synthetic`, so its
  labels are all "good" and its vowels are never compared.
- Real-speech criteria stay open: the quality of the labels and measures on real
  recordings, accent fairness across speaker accents, and the vowel component, which
  needs reference phone scores (#80, #107, #110). The PR uses "Refs #83".
- A new parameter set is a new file version, so stored grades stay comparable.
- `round_grades` rows written by #82 have four measures; they are never projected.

## Open questions for the owner

These do not change version 1.

1. Should a word without sound detail be labelled from its word accuracy (today),
   or hold a fourth "not judged" state that FR-SH-10 does not have?
2. Is word-duration agreement an acceptable stand-in for stress until the contract
   carries syllables, or should stress stay null like vowels?
3. Showing round 2's markers before round 3 shows the segment text between rounds.
   The story asks for markers after rounds 2 and 3; they are hidden only while a
   round is playing. Should they instead wait until round 3 is recorded?
4. Database Design §6 should document the `word_labels` shape and the two parameter
   versions in `speech_info` (design owner).
