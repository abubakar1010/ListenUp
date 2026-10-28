# ADR 0074: Speech assessment contract split (owner exception E2)

- Status: Accepted
- Owner exception approved: 2026-10-28
- Related: #80, #21, #22, #82–#86; ADRs 0028 and 0041

## Decision

Split #80 into contract plumbing and real-model implementation. The existing
`SpeechAssessmentPort.assess(recording, reference_text, reference_audio)` and
`SpeechAssessment` schema remain the vendor-neutral contract: reference-indexed
word/sound scores, recording-relative timing, pauses, fillers, pitch and provenance.
No database migration, scoring formula, public API or grading job is added.

The port, output schema, `ai.yaml` registration and a fake second provider for
AT-22 may be built without #21 or #22. `fake-assessment` is a second deterministic
adapter alongside `fake`. It emits synthetic imperfect scores, placeholder sound
labels, pauses, a filler and voiced/unvoiced pitch without reading either audio
file. Empty reference text returns empty observations. These samples test the
contract and caller plumbing only, never speech accuracy or model acceptance.

The packaged `ai.yaml` registers the second fake disabled. Non-production callers
may enable it or select either fake through `LISTENUP_AI_CONFIG`; they keep the
ordinary gateway eligibility, validation, quota and provenance checks. Production
rejects every `fake` entry, enabled or not, and any enabled `fake-assessment` entry,
at gateway construction, even if ineligible for another reason. The packaged disabled
`fake-assessment` entry is the only synthetic registration production accepts. A
disabled entry cannot receive calls, and `AIGateway.entry` and
`deployment_provenance` skip disabled entries, so production reports no assessment
provider. The evaluation runner treats every synthetic provider (`fake`,
`fake-assessment`) as non-evidence. `accepted: true`
on a synthetic entry permits contract testing only. The existing `ai.fake.yaml`
remains compatible with the offline evaluation CLI's exclusively `fake` policy.

The local provider on real models and the B3 budget criterion still wait for both
#21 and #22. No real-model or B3 pass is claimed. This exception does not close #80
or waive its other dependencies. #82–#86 may be built against the fake provider
only after this port change is merged; their remaining dependencies still apply.

## Consequences

Downstream development can use a merged, tested interface without selecting or
loading a real model. Synthetic labels and numbers must never be presented as
learner assessments. The owner merges the contract PR; #80 remains open for its
real-model provider and unchanged B3 target. Evidence lives in
[the validation record](../validation/80-speech-assessment-contract.md).
