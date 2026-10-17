# ADR 0039: Validate deployment performance before launch

- Status: Accepted by owner; launch measurements outstanding
- Date: 2026-10-16
- Sources: owner decision; System Design §1 and §12; SRS §8.2; #16, #45, #112, #155
- Refines: validation timing in System Design §12; preserves ADR 0034 model choices and targets

## Context

Stage-0 is not provisioned. Requiring its latency measurements to complete every
feature prevents local and GitHub Actions development from finishing. A hosted CI
runner can exercise integration behavior and detect performance regressions, but
cannot establish latency or capacity of an unavailable deployment.

## Decision

Complete development with the existing applicable local/CI checks, coverage and
independent review gates. Only actual-server performance criteria may be explicitly
deferred to staging, with their original targets and missing evidence recorded in
the story and linked to the mandatory pre-launch tracker #155. Story closure means
development is complete; it does not mean a deferred criterion has passed.

Before public launch, deploy the release candidate to the designated stage-0 host,
run the applicable System Design benchmarks and end-to-end performance targets with
real configured adapters and representative load, and independently review the
results. Preserve raw measurements, failures, percentile method, sample count,
corpus, revision, hardware and worker/model settings. For #45, measure playable to
committed transcribed readiness for three-minute passages, including queue delay,
with p95 strictly below 120 seconds. Cache-hit results are reported separately.

GitHub Actions may orchestrate both stages. GitHub-hosted measurements remain
preliminary; measurements executing on the actual stage-0 deployment can qualify.
No new workflow, self-hosted runner, infrastructure or automated deployment gate is
provisioned by this documentation decision. The release owner enforces #155 before
public launch; a closed tracker without evidence does not satisfy the gate.

## Consequences

The owner can finish local development without a cloud account. Unverified server
performance still blocks public launch, and failures must be resolved before it.
Functional/security/quality checks, model-quality gates and independent review
remain required; this exception cannot conceal unrelated gaps. Historical #45
measurements stay unverified and its missing independent review is not repaired by
this decision. No runtime, schema, credentials or performance thresholds change.
