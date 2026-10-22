# ADR 0051: AI evaluation runner and versioned reports

- Status: Accepted for implementation by the owner in story #108
- Date: 2026-10-22
- Requirements: NFR-AI-6, AT-15, AT-17, AT-21, AT-22
- Related: ADRs 0028, 0041, 0046, 0050; Architecture 7.4 and 12.4

## Context

Provider changes need a repeatable regression command. Teacher sets #106/#107
and calibrated agreement limits do not exist yet. Production Shadow scoring is
also absent: the gateway returns raw speech evidence and ADR 0050 forbids treating
the research prototype as approved grades. This story must build useful tooling
without presenting invented fixtures as evidence of model quality.

The owner approved implementing with Codex and explicitly approved exposing live
Shadow grading as unavailable while exercising its report contract synthetically.
PR #173 owns changes to text adapters, prompt files and the task convenience helper;
this story starts from current main and edits none of those files or the gateway.

## Decision

1. Put the typed runner and CLI in `listenup.ai.evals`; expose `ai-evals` as an
   installed command. Keep manifests, threshold configuration and synthetic examples
   in `ai-evals/`. No schema migration, product endpoint or application UI is needed.
2. Use the gateway's public constructor, configuration, prompt loader, fitting and
   generate interfaces available on main. All gist inference, including fake CI
   inference, uses the same eligibility and persistent accounting path. No vendor
   calls, implicit provider enabling or quota bypass is allowed. A later rebase on
   #173 should adopt its public task convenience helper when available.
3. Use dataset version 1: explicit kind/suite/source, unique case IDs, typed inputs,
   reference numeric grades and explicit smoke membership. Teacher assets remain
   externally provisioned. Permit three synthetic grade samples only for synthetic
   Shadow report checks; never call them speech inference or provider evaluation.
4. Live Shadow invocation returns unavailable before inference until a public scoring
   service exists. Do not copy research transforms or derive seven grades from raw
   gateway word scores. This limitation is retained in documentation and validation.
5. Always evaluate three attempts per selected case. Measure agreement over every
   attempt, MAE per dimension/measure, worst per-case score range, and mean/worst
   filler-count error. Missing attempts fail and cannot shrink denominators.
6. Threshold configuration contains inclusive named min/max rules and optional
   operator-supplied gist level boundaries. Production config preserves approved
   SRS consistency/filler limits and leaves calibration-dependent values absent.
   Missing required rules fail closed as unconfigured. Synthetic configuration is
   isolated by scope and tests deterministic fixture invariants only.
7. Report version 1 is JSON, with a Markdown summary. Store input/config fingerprints,
   revision, case/run counts, provenance, numeric observations, metrics, limits and
   explicit failure reasons. Exclude input text, asset paths, feedback, credentials
   and exception prose. Breaking report/metric changes require a version bump.
8. Distinguish gate PASS from model-quality evidence and provider acceptance. Fake,
   synthetic, smoke, partial or fallback-only success cannot accept the requested
   provider. Reports never change live provider configuration.
9. Add a conditional CI smoke job with exact prompt/provider/ai.yaml path selection,
   including renamed/deleted paths. Use fake AI only, real PostgreSQL accounting,
   failure exit codes, and upload both reports even when the gate fails.

## Consequences

The teacher sets can adopt the documented format without changing the runner's
report/threshold contract. Gist evaluation can run against any configured eligible
text provider; synthetic smoke validates mechanics only. Changing a role's provider
configuration and rerunning exposes the actual provider and regression verdict.

PostgreSQL is required even for the standalone gist fake command. Unit tests inject
the accounting boundary; an integration test covers persistent admission and logs.
Synthetic Shadow report checks deliberately perform no gateway or AI call because
they are pure numeric report tests. They cannot satisfy live Shadow model-quality
acceptance, which remains explicitly unavailable pending the production service.

Calibration stories own new quality thresholds/level boundaries, and the golden
sets, fairness checks and review remain provider-activation requirements. A passing
CI fixture report is never permission to enable a model.
