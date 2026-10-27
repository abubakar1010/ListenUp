# AI evaluation sets

Golden sets and the evaluation runner for the AI adapter layer (Architecture 7.4, NFR-AI-6): about 50 teacher-graded gists and about 50 teacher-graded Shadow recordings. A provider goes live only after it passes them.

Learner recordings are personal data. This repository is public, so store recordings outside it and keep only manifests and grades here.

## Run the synthetic smoke subsets

From `apps/api`, after `uv sync` and `uv run alembic upgrade head`, with PostgreSQL
running (the same `LISTENUP_DATABASE_URL` as the API):

```sh
uv run ai-evals --offline --smoke \
  --dataset ../../ai-evals/fixtures/gist.json \
  --thresholds ../../ai-evals/smoke.thresholds.json \
  --ai-config src/listenup/ai/ai.fake.yaml \
  --report ../../work/ai-evals/gist.json
```

Use `fixtures/shadow.json` and a different report name for Shadow. The equivalent
module command is `uv run python -m listenup.ai.evals`. Omit `--smoke` to select
every case. `--revision <git-sha>` records the source revision; otherwise it is
`unknown`. Each case has three attempts. Exit codes: **0** all configured checks
pass, **1** failed/unconfigured/unavailable evaluation, **2** invalid configuration
or unexpected execution error. JSON and a Markdown summary are written even when
evaluation fails; an unwritable report destination remains an OS error.

**These invented fixtures are harness validation, not model-quality evidence.**
The fake gist response is constant, so different inputs receiving the same grade
is intentional. No inference quality follows from the resulting PASS. Synthetic
Shadow runs exercise stored numeric report samples only: no audio is opened and
no AI provider is called. Their execution is `synthetic_report_contract` and
their provider acceptance is always false.

Offline gist inference uses the real gateway and its production PostgreSQL
accounting with the existing fake provider. Eligibility, input budgets and quotas
still apply; PostgreSQL is required. `--offline` refuses every configured provider
other than `fake`, including fallback roles, and refuses teacher datasets. The
CI smoke command contains no AI network call, paid provider, model download or
API credential. Unit tests additionally refuse socket connections at the AI boundary.

## Dataset format (version 1)

The loader is `listenup.ai.evals.models.Dataset`; `fixtures/*.json` are complete
examples. The same format accepts the teacher-graded sets from #106 and #107.

| Field | Meaning |
| --- | --- |
| `version` | Exactly `1` |
| `id` | Stable dataset identifier; letters, numbers, `_`, `-`, up to 64 characters |
| `kind` | `synthetic` or `teacher`; never relabel synthetic examples as teacher grades |
| `suite` | `gist` or `shadow`; determines input and score validation |
| `source` | Human-readable origin/grading guide reference, without consent records or personal identifiers |
| `cases` | Nonempty list with unique stable `id` values |
| case `smoke` | Optional boolean, default false; explicit subset membership |
| case `tags` | Optional labels for authoring/analysis; not a selection expression |
| case `context` | Optional public `CallContext`: consent, region, population, audio duration, round, queue delay; no learner identifiers |
| case `input` | The suite-specific input below |
| case `expected` | Reference grade below |
| case `synthetic_runs` | Exactly three reference-shaped samples; allowed only for synthetic Shadow report checks |

Gist input is the public `GradeGistInput`: `transcript`, `gist`, and `key_points`
with `id` (`kp1`–`kp6`), `text`, and `kind` (`main` or `supporting`). Its task is
`text_ai/grade_gist`. Version and output schema come from the public prompt
loader, never from a manifest-supplied prompt. Reference text may be fitted to
the gateway budget; learner text is never trimmed. Trimmed field names are reported.

Shadow input contains `recording`, `reference_audio` and `reference_text`.
Audio strings identify locally provisioned external assets; the runner never
downloads them. Teacher audio and consent records must stay outside this public
repository; manifests must not contain signed URLs or account identifiers.

Every reference grade has:

```json
{
  "scores": {"main_idea": 80, "key_details": 60, "accuracy": 100},
  "overall": 78,
  "level": "Good"
}
```

Gist requires exactly those three dimensions and one of `Needs work`, `Fair`,
`Good`, `Excellent`. Generated overall uses the existing SRS 50/30/20 weights,
without rounding; level cutoffs come from evaluation configuration. A teacher's
`overall` and `level` are independent reference annotations.

Shadow requires exactly `timing`, `pronunciation`, `accent`, `articulation`,
`fluency`, `fillers`, `completeness`, plus `overall` and integer `filler_count`.
`level` may be omitted. All scores must be finite and between 0 and 100. Unknown
fields, missing measures, invalid scores and duplicate case IDs fail validation.
Synthetic samples cannot appear in teacher manifests.

**Live Shadow grading is unavailable.** The gateway currently exposes raw speech
evidence, not seven calibrated grades, and ADR 0050 rejects promoting the speech
prototype into production scoring. A live Shadow invocation writes status
`unavailable`, reason `shadow_scoring_service_unavailable`, and exits 1 before
inference. Later work must integrate a public scoring service that calls the
gateway; this runner does not invent acoustic-to-grade mappings. Teacher Shadow
manifests can be authored/validated now, but cannot produce live quality results.

## Thresholds and provider configuration

`thresholds.json` preserves existing SRS requirements: gist overall range at most
10 (AT-15), Shadow measure ranges at most 10 (AT-21), and filler absolute count
error at most 1 (AT-17). Agreement/MAE limits and gist level boundaries are
deliberately uncalibrated. Production evaluation returns `unconfigured` until the
calibration stories supply them. This story chooses no production quality limits.

`smoke.thresholds.json` has `scope: synthetic`: its exact agreement/zero-error
checks and invented level boundaries describe deterministic fixtures only.
Teacher evaluation refuses these synthetic limits. Each named rule has one
inclusive bound, `{"min": number}` or `{"max": number}`. NaN, infinity, conflicting
bounds and unknown metric names are rejected or produce `unconfigured`.

Required calibrated gates for gist: `level_agreement`, `mae.main_idea`,
`mae.key_details`, `mae.accuracy`, `max_range.overall`, plus three strictly increasing
`gist_level_bounds` (lower bounds of Fair, Good and Excellent). Required Shadow
gates: `mae.<measure>` and `max_range.<measure>` for all seven measures, and
`filler_count_max_error`. Other reported numeric metrics may have optional rules.
Missing gates cannot silently produce PASS.

For a provider comparison, provision the teacher manifest and calibrated threshold
file, then run with `--ai-config path/to/candidate.yaml`, without `--offline`.
Alternatively set `LISTENUP_AI_CONFIG`; an explicit argument takes precedence.
The usual packaged `ai.yaml` is the default. Change a role's ordered provider
entries or its text-task override, then rerun the identical dataset and limits
(AT-22). Existing gateway eligibility applies, including enabled/accepted flags,
consent, retention and quotas; the runner never bypasses it or enables a provider.

Reports distinguish the role primary, effective task provider and actual result
providers. A text-task override is the requested provider when present. A fallback
can pass the regression set while leaving `provider_acceptance` false for the
requested provider. Synthetic, fake-provider, smoke, failed, unavailable and
uncalibrated runs cannot establish provider acceptance. Acceptance here is a
report indication, not a configuration update or a substitute for calibration,
human review, fairness testing and the real golden sets.

## Metrics and report format

JSON report version 1 is the machine-readable artifact. It records dataset ID/kind,
suite, role/task, execution mode, selected case count, total/successful attempts,
requested/role/actual providers, source revision, hashes of the exact dataset/threshold
bytes evaluated and canonical
parsed AI-config hash. Per-case rows contain only case ID, reference scores and
three observations (numeric grade, provider/model/version provenance, prompt
version, trimmed field names or a fixed error code). Inputs, audio paths, feedback,
teacher source text, credentials and provider exception text are not copied.

- `mae.<dimension/measure/overall>`: mean absolute error over all cases × three attempts.
- `level_agreement`: number of exact reference-level matches divided by all attempts.
- `max_range.<dimension/measure/overall>`: worst within-case max-minus-min across three runs.
- `filler_count_mae`: mean absolute filler-count error across all attempts.
- `filler_count_max_error`: worst absolute filler-count error.

Any missing attempt fails the run; aggregate metrics remain empty instead of
dropping failures from denominators. Every threshold decision records its bound,
actual value and pass flag. The Markdown companion summarizes those decisions;
the JSON carries the per-run evidence. Use numeric JSON values for comparisons,
not rounded Markdown display values. Bump the report version for incompatible
field or metric-definition changes (ADR 0052).

## CI

`.github/scripts/ai-evals-changes.sh` compares the PR merge-base/head or push range,
using both sides of file renames and deletions. A new-branch push compares with
the merge base of the default branch. Only changes under
`apps/api/src/listenup/ai/prompts/`, `apps/api/src/listenup/ai/providers/`, or the
exact `apps/api/src/listenup/ai/ai.yaml` enable `ai-evals-smoke`. Existing CI jobs
keep their normal triggers. The smoke job runs both synthetic subsets against
fake AI, fails any unsuccessful gate, and uploads JSON/Markdown with `always()`.
Its PostgreSQL service is for gateway quota/accounting, not networked AI.

## Collection kits for the teacher-graded sets (#106, #107)

[`gists/`](gists/README.md) and [`shadow/`](shadow/README.md) hold the kit for collecting the
two golden sets: README, teacher grading guide, consent form template, selection checklist,
coverage matrix and empty templates in the format above. **They hold no data yet.** Check
them from `apps/api` with `uv run python scripts/check_golden_sets.py` (add
`--require-complete` to enforce the matrix once real data exists).
