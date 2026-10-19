# ADR 0041: Durable AI admission, validation and fallback

- Status: Accepted implementation of the approved #64 plan; oversized-input handling amended by ADR 0045
- Date: 2026-10-17
- Implements: #64; ADRs 0028 and 0037; NFR-AI-1, NFR-AI-2, NFR-AI-4, NFR-AI-5, NFR-AI-7, NFR-AI-8, NFR-AI-9; FR-BL-13

## Decision

All four existing gateway methods and port signatures remain available. Gateway
methods accept an optional keyword-only `CallContext`: approved population/region,
consent, audio duration, Shadow round and queue delay, never learner identity.
Results may add optional `Usage`; existing speech adapters need no changes.

Role lists remain ordered. `tasks` overrides text task order using provider IDs
from the role list. Duplicate IDs in a role and conflicting limits for the same
provider across roles are configuration errors: counters are shared by provider,
not separated by model, task, process or role. Adapters remain cached per role and
configuration. No hosted adapter, prompt, new model or paid route is activated.

Unknown training policy is denied. Local declarations mean inference in our
runtime without cloud routing or training/prompt logging. Existing transcription
and alignment choices retain ADR 0034's validation gates; new local text and speech
assessment require `accepted: true`. Hosted routing additionally requires verified
retention controls (including required ZDR), accepted evaluation, explicit approved
regions/populations, consent and known day/month free limits. An operator must
verify these declarations against the endpoint and deployment; they are not
self-reported learner claims. Unknown eligibility routes locally or raises
`AIUnavailable`. New model-quality evidence cannot be waived by ADR 0039.

## Admission and accounting

`ai.quota_usage` contains durable minute/day/month UTC buckets: calls, tokens and
audio seconds. `limits` selects capped dimensions; absent dimensions are uncapped,
zero means no allowance. Fixed minute windows implement configured rate limits.
All dimensions and periods are admitted atomically under a provider-scoped PostgreSQL
transaction advisory lock, then committed **before** calling the provider. No
transaction stays open during inference. Every retry requires a fresh admission.
A denied admission increments no counters. There is no paid auto-upgrade.

`ai.calls` is also the reservation ledger. Admission writes a `pending` row and
charges the maximum reserved usage. Success with validated reported usage settles
once; timeout, cancellation, invalid output, unknown usage and process death keep
the reservation charged. A crashed attempt can remain `pending` until retention;
this deliberately trades capacity for never refunding a call that might have run.
Settlement uses the admission's original buckets across midnight/month changes.
Accounting failure stops provider calls and becomes content-free `AIUnavailable`.

Text admission reserves `input_token_limit + output_token_limit`;
`task_budgets` may override these caps and prompt overhead per task, and the
effective caps are passed to the adapter factory in its `ProviderEntry`; serialized input
UTF-8 bytes plus `prompt_token_budget` must fit the input limit. Refuse oversized
input instead of silently changing learner material. Adapter implementations (#66)
must honor these caps, including prompt/schema overhead and reasoning tokens, and
supply usage when available. Missing usage remains conservatively reserved. Audio
limits require a caller-supplied duration; existing uncapped local transcription
can omit it and meters the returned duration. Reported cache tokens are a subset
of input tokens; reasoning tokens are a subset of output tokens, counted once.

Speech roles reserve audio duration and calls, not tokens. Configuring a `tokens`
cap for transcription, alignment or speech assessment is therefore a configuration
error, including a zero cap. Reject it before creating adapters or making calls;
token-metered speech requires a bounded reservation contract before enablement.
This also applies when the provider ID is shared with a text role. Existing
call/audio-limited speech routes and token-limited text routes remain supported.

## Validation and privacy

Revalidate even preconstructed models through the requested schema. Reject non-finite
numbers, invalid score/time ranges, inconsistent transcript containment, invalid
alignment indexes/text/timing and mismatched provider/model/task/prompt provenance.
Speech assessment also validates reference word indexes/text, ordering and sound
containment. The Whisper adapter normalizes boundary jitter by at most 100 ms per
timestamp before strict gateway validation, preserving every nonblank word and
the audio duration. Larger corrections are refused rather than inventing timing.
Invalid output advances to the next provider; transient errors/timeouts use bounded
exponential backoff first. Exhausting candidates raises `AIUnavailable` with a
fixed reason, without the provider exception or its cause.

Logs contain configured role/task/provider/model, trusted deployment version, prompt version,
latency, input/output/reasoning/cache units, audio seconds, fallback depth, queue delay,
projected cost and outcome. Unknown version on a failed call is NULL, never invented.
`Registry.versions` resolves versions from trusted adapter code, installed package
metadata and deployment configuration, before inference and without learner inputs.
Registered versions must match the result's provenance; mismatches fall back.
An adapter without a registered resolver logs NULL even on success, never the
response's version string: a character allowlist cannot distinguish prose from
metadata. The result still carries its port-required provenance. Built-in adapters
all register a resolver; new adapters must register one to provide operational
version provenance. No inference response or exception supplies a log version.
No learner, job, request or trace ID, path, payload or exception message is stored.
`input_units`/`output_units` are token totals; audio seconds are separate. Unknown
usage in failed/pending calls is the reservation, not claimed actual consumption.
Projected cost uses configured hypothetical rates; zero by default, it never
selects a paid plan. `usage_estimated` distinguishes conservative reservations from reported actual
usage even when an adapter succeeds without reporting usage.

`0064_ai_gateway` follows current main's `32_google_oidc`, which follows #45's `0017`; it has a distinct revision ID. Monthly call
partitions are created three months ahead. The background `ai.maintain` job runs
every five minutes, refreshes quota gauges and drops complete partitions whose
upper bound is older than 90 days (individual rows can live up to one extra month).
It removes old quota buckets too. The restricted owner function grants workers
only that maintenance operation. API/read-only roles can read, but cannot write,
these identity-free tables. A missing current partition fails closed; operators
can run the maintenance function after an extended outage.

## Saving mode and integration boundary

Saving mode starts on. `quota_saving()` also signals saving at 75% consumption of
any capped day/month dimension. Rounds 1/2 (or an unspecified round) of
`shadow_feedback` refuse AI with reason `template_feedback`; grading owns the
actual deterministic templates. Round 3 and suggestions keep AI. Routine hosted
tasks must leave the configured `grading_reserve` fraction (default 25%) for
`extract_key_points` and `grade_gist`; local tasks do not consume hosted headroom.
The alert now fires at <=25% remaining for two minutes, refining ADR 0031's old
20% alert; routing/saving decisions do not wait for the alert timer.

Retaining key points (0.5 cached average), one gist grade, round 3 and suggestions
means **3.5**, not 2.5, estimated text calls/session in saving mode, or 525 at 150
sessions/day. Standard mode remains 5.5 (825/day). Retries and fallbacks are extra;
per-task call logs measure the actual workload. Caller-owned passage caching and
job coalescing remain intact. The gateway never queues learner payloads or supplies
fabricated feedback; grading/transcript jobs retain data and translate unavailable
results into retry/delayed states. #45's existing passage job remains compatible.

Hosted adapters/prompts and their golden-set acceptance are #66 work. This story
proves deterministic gateway behavior with boundary fakes and recorded speech
responses; it makes no claim about new model quality or deployment-host latency.
