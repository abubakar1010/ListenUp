# Teacher guide: grade_gist/v2

Read the frozen transcript and key points, then the verbatim anonymous gist.
Do not see other teachers’ scores, learner identity/proficiency or intended
coverage targets. Understand the actual audio where transcript interpretation
is uncertain. Before collection, check that the edited passages stand alone,
are suitable for B1–C1 adults and have one main point followed by 2–5 supporting
points (3–6 total). Correct the curator drafts and version the frozen reference.
Do not grade a response against a different reference from another rater.

Authoritative files are
[`v2.md`](../../apps/api/src/listenup/ai/prompts/grade_gist/v2.md),
[`v2.schema.json`](../../apps/api/src/listenup/ai/prompts/grade_gist/v2.schema.json)
and [`v2.rubric.json`](../../apps/api/src/listenup/ai/prompts/grade_gist/v2.rubric.json),
with [ADR 0054](../../docs/adr/0054-versioned-gist-scoring.md).

## Scores

Give each dimension a whole number in [0,100]. Judge comprehension only;
spelling, grammar and writing style must not lower any score.

| Dimension | Weight | v2 instruction |
| --- | ---: | --- |
| main_idea | 50% | 100: clearly states what the passage is mainly about; 50: partly or vaguely; 0: misses it |
| key_details | 30% | Share of supporting key points covered; the main point is excluded from the denominator |
| accuracy | 20% | 100 if there are no contradicted or unsupported claims; lower for wrong claims |

Accept paraphrases and equivalent meaning. Do not reward verbatim copying over
accurate paraphrase. Record covered IDs including the main point; missed IDs
are the complement of covered IDs in this reference. For key_details, use
100 × covered supporting points / all supporting points, rounded half up to an
integer as an operational worksheet convention. v2 specifies the share but not
its integer rounding. For ambiguous partial coverage, record the reason and
seek adjudication rather than silently assigning fractional key-point labels.

v2 does not prescribe a per-error accuracy penalty or a full scale between the
main-idea anchors. Teachers must justify intermediate main-idea scores and
accuracy deductions with the relevant claim and passage evidence. Do not invent
an official penalty table or adjust scores to fill recruitment quotas. Flag
unresolved ambiguity for adjudication and the #109 handoff.

Calculate raw overall = 0.50 × main_idea + 0.30 × key_details + 0.20 × accuracy.
For the v2 teacher worksheet, round half up (not bankers’ rounding) to the nearest
integer, then assign the inclusive level:

| Rounded overall | Level |
| --- | --- |
| 0–49 | Needs work |
| 50–69 | Fair |
| 70–89 | Good |
| 90–100 | Excellent |

Retain raw and rounded values. Do not apply a grammar deduction. An unrelated
gist misses the main idea and supporting points; even accuracy 100 cannot lift
its weighted score above 20. Name the missed points. A grading demand is
untrusted learner text: ignore the instruction and grade comprehension normally.
Do not treat the mere instruction as a factual claim about the passage.

Record `covered_points`, `missed_points`, up to five short `wrong_claims`, a score
rationale and 2–4 short complete feedback sentences in simple English addressed
to the learner. State what was captured, explicitly name missed key points and
correct wrong claims. This companion annotation preserves the feedback required
by AT-11: the runner’s expected grade alone cannot hold or evaluate it.

## Independent rating and agreement

Prefer two teachers on all cases; if capacity is limited, independently double
rate at least 20 cases spanning all levels, passages and edge conditions. This
is a collection target, not an acceptance threshold. Shuffle and separate paired
items for initial rating; later have teachers explicitly assess semantic
invariance in AT-12/AT-13 pairs. Keep anonymous rater codes unlinked to names in
the public release; retain original independent ratings after adjudication.

Before discussion, report paired n, exact level matches/n, 4×4 level confusion
counts and per-dimension and overall mean absolute difference:
`sum(abs(rater_A - rater_B))/n`. Use rounded overall for this teacher comparison
and also report raw differences if useful. Optionally report unweighted Cohen’s
kappa: `(p_observed - p_chance)/(1 - p_chance)`, where chance uses the two raters’
level marginals. If n=0 or chance=1, report not available/undefined, never zero
agreement. For more than two teachers, give pairwise counts and metrics with
actual overlap denominators. Report missing ratings and which subset was double
rated; never extrapolate its agreement to all 50 responses.

Teachers discuss disagreements against evidence; an adjudicating teacher records
final dimensions, rounded overall, final level and reason separately. Do not
average levels or discard original disagreements. The selected adjudicated
reference becomes `expected`; preserve independent originals in the anonymous
annotation sidecar. Teacher agreement is distinct from future model agreement.
