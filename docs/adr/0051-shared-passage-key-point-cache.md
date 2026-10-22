# ADR 0051: Shared passage key points prefetched after transcription

- Status: Accepted
- Date: 2026-10-22
- Implements: #67; FR-BL-6 (reference extraction only), NFR-AI-4, NFR-AI-5
- Related: ADR 0036, ADR 0038, ADR 0046
- Sources: SRS 5.2.1, Architecture 5.4, System Design 7.1 and 7.3, Database Design 6

## Decision

`grading.jobs` registers a transcript-ready hook and is loaded through worker
`JOB_MODULES`, including in isolated media job processes. After transcription commits
its ready event, the hook verifies the originating session's owner and content item
and enqueues `grading.extract_key_points` on the AI lane in its own transaction.
This includes a transcript already present in the shared cache. No gist submission
or completion of Blind is needed. There is no new route or browser event.

Queue arguments contain only the media id and the exact, absolute, half-open
passage bounds. Both the queue unique key and the execution lock identify that
passage. Deduplication covers concurrent producers and running jobs; the execution
lock covers the cache lookup, inference and committed insert. The second job
rechecks the cache before inference even if it was queued without deduplication.
Work does not belong to the first learner: their deletion must not cancel another
learner's shared reference. Queue ids are trusted worker arguments, not a public
read-by-media API.

`transcript.service.key_points_reference` is a worker-only boundary that reads the
original cached words inside the selected span, excluding padding, words starting
at the end boundary and learner correction overlays. Missing transcript coverage
is retryable; deleted media ends the job, checked through the worker-only
`content.service.media_exists_for_worker` boundary. An empty reference fails permanently
without asking the model to invent points. Request connections retain no cache
grant and no early transcript read is added to Blind.

`grading.key_points` follows Database Design 6: uniqueness is media/span/prompt
version, media deletion cascades, and no learner id or RLS policy is attached to
this shared cache. The worker receives explicit CRUD grants, the read-only role
SELECT, and the API no table grants. Database constraints require a finite,
nonempty, nonnegative span, a nonempty prompt version, nonempty string
provider/model/deployment-version provenance, and 3–6 points with exactly one main
idea first. The immutable SQL validator also checks ordered `kp1`–`kp6` labels,
text lengths and supporting kinds. These labels identify points within a cache
entry; they are not learner identifiers.

The handler reads the active version for cache lookup and uses ADR 0046's
`text_tasks.run_task` for fitting reference input and inference. It stores the
returned prompt version and provider/model/version provenance rather than
inventing them. The existing released extraction prompt/schema and manifest need
no change. A new active prompt version creates a separate cache entry; results
are never overwritten by another learner or version. The idempotent insert is a
final safety net, not a replacement for the job lock.

Only complete, validated results are stored. Invalid model output and temporary
unavailability consume the existing AI lane's bounded retry policy; exhaustion
leaves a failed job for operations without blocking Blind. A foreign-key refusal
caused by media deletion during inference is treated as completed cleanup; other
persistence errors propagate. A worker death after inference but before commit
can require inference again: the lock does not promise exactly-once execution
across an external provider and PostgreSQL.

## Consequences and validation

No gist grading, unavailable-grade UI, manual retry route or changes to review/admin
belong to this story. Provider acceptance and quality gates from ADR 0046 remain
in force; this story enables no provider and claims no new model-quality evidence.
Tests exercise the real gateway/adapter with deterministic HTTP replies and real
PostgreSQL accounting, persistence and Procrastinate locks.

The migration follows `104_consents` while PR #171 is open; if that PR merges
first, change the parent to `58_marks` before this story merges. See the validation
record for the final checked head and the actual-server latency deferral to #155.
