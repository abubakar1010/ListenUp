# Import, anonymization and validation

## Intake and private handling

Create an access-controlled collection folder **outside the checkout**, with
separate permissions for consent/identity records and response material.
The private coordinator ledger links participants, withdrawal status and random
case IDs. Use unrelated random case IDs (`gist_` plus random alphanumeric text),
not names, account IDs, school codes or hashes of emails. Random IDs make data
pseudonymous while a private key exists; do not promise guaranteed anonymity.

The CSVs here are header-only templates. Copy them to private storage to fill.
`responses.csv` holds verbatim text and collection conditions. `teacher-grades.csv`
holds one row per case/rater; put adjudication in a separate row with a separate
rater code and retain originals. In CSV cells, encode point IDs and claim lists
as JSON arrays; use a CSV writer that quotes embedded commas and newlines.
Treat response cells as text on spreadsheet import to prevent formula execution
from entries starting `=`, `+`, `-` or `@`; never modify the canonical gist merely
to make a spreadsheet safe. None of these CSVs is directly accepted by the runner.

After rating, a coordinator and a second reviewer inspect every proposed release:

1. Check privately that learner and teacher permissions cover the proposed public
   text/ratings and any transformations. Exclude denied, unknown or withdrawn cases.
2. Remove identity/contact, school/employer, exact location, dates and personal
   anecdotes from metadata, feedback and rationales. Scan for email/phone/address,
   account IDs, URLs, usernames and signed query strings; human review must catch
   indirect identifiers. Do not publish CEFR if a small cell makes someone identifiable.
3. Preserve spelling, grammar, factual mistakes and adversarial text. If the gist
   itself identifies someone, preferably exclude/recollect. If redaction is
   necessary, keep the original only privately, mark the released text transformed,
   and have teachers regrade that exact released version. Never carry grades over
   a meaning-changing redaction. Preserve pair integrity or recollect both items.
4. Export only approved fields. No names, timestamps, consent-form IDs, withdrawal
   tokens, source filenames containing identities, signed URLs or private paths.
   The anonymous sidecar has only public case IDs and unlinked rater codes.
5. Review the staged diff, not only the current file: no raw/temporary records in
   Git history or logs. If personal data was ever committed, stop distribution and
   invoke the repository’s incident/removal process; deleting a working file alone
   does not remove history. Apply the predetermined private retention/deletion plan.

## Mapping to the current runner

`templates/dataset.json.template` is valid JSON with **null score placeholders**.
It intentionally fails `Dataset` until genuine responses and teacher grades are
inserted. Never replace nulls with invented defaults. Do not load it as a dataset
or commit a `kind: teacher` manifest without verified human judgments.

For each cleared case, copy the exact frozen `transcript` and `key_points` from
`passages.json` and insert the released gist. Use one case for each actual response
or clearly labelled transformation. Add condition/pair labels as non-identifying
`tags`; keep richer metadata in the provenance sidecar, not extra runner fields.
The runner rejects unknown keys. Keep `smoke: false` unless a later owner explicitly
selects a smoke subset. Teacher datasets cannot run with `--offline`.

| Destination | Source |
| --- | --- |
| `version`, `kind`, `suite` | `1`, `teacher`, `gist` |
| `id`, case `id` | Unique stable letters/numbers/underscore/hyphen, max 64 characters |
| `source` | Anonymous origin + grading guide/rubric/reference version |
| `input.transcript`, `input.key_points` | Exact frozen passage; one `main` first, 2–5 supporting; unique `kp1`–`kp6` labels |
| `input.gist` | Approved verbatim learner text, or explicitly tagged transformation |
| `expected.scores` | Final human `main_idea`, `key_details`, `accuracy` integers in 0–100 |
| `expected.overall`, `expected.level` | Teacher’s rounded v2 overall and corresponding reference level |
| sidecar | Independent ratings, covered/missed IDs, claims, feedback, raw overall, provenance and adjudication |

The loader permits finite fractional scores and independently annotated teacher
overall/level, but the collection guide follows the v2 integer scale. It accepts
1–6 key points and does not enforce a main point; our collection review enforces
3–6, exactly one main first, matching FR-BL-6. Empty gist strings can load but do
not count as standard product submissions. No `synthetic_runs` in teacher data.
No `rubric_version`, `covered_points`, `missed_points` or feedback inside `expected`.

Omit case `context` for collection manifests: its default has `consent: false`,
no region or population. This does not invalidate the collection or authorize AI
processing. In #109, an authorized operator must supply verified anonymous routing
context consistent with specific processing consent and gateway policy. Never
set `consent: true`, region or population just to make a provider eligible.

## Runner/production distinction — do not change under #106

Production v2 computes and rounds 50/30/20 using half-up, then uses 50/70/90.
`ai.evals.runner.gist_grade` uses unrounded 50/30/20 and operator-supplied level
bounds. Thus raw 69.5 is production Good (70 rounded) but would be runner Fair
if bounds were 50/70/90. Keep teacher scores/levels as actually judged; flag such
boundary cases rather than editing them to make evaluation agree. The loader
allows independent reference overall/level. `ai-evals/thresholds.json` still has
null gist bounds and no calibrated agreement/MAE gates. The v2 rubric values are
not permission to populate that config. Resolve/report this distinction and all
provider evaluation, thresholds and tuning in #109. AT-15 remains a future
three-run requirement (range at most 10), not measured by teacher agreement.

## Validation without inference

From `apps/api`, using the existing environment, run this against the completed,
release-cleared manifest (replace the path explicitly). It reads only the model
contract: no PostgreSQL, gateway, provider or AI config is needed.

```sh
uv run python - /absolute/path/to/cleared-dataset.json <<'PY'
import sys
from pathlib import Path
from listenup.ai.evals.models import Dataset
p = Path(sys.argv[1])
d = Dataset.model_validate_json(p.read_bytes())
assert d.kind == 'teacher' and d.suite == 'gist'
print(f'Validated {len(d.cases)} teacher cases structurally')
PY
```

Model validation checks required fields, unique IDs, suite inputs, exact score
dimensions, finite range, required levels and disallowed synthetic samples. It
cannot prove human authorship, consent, licensing, reference correctness or
anonymization. Separately reconcile case IDs across the response, ratings,
provenance and final manifest; require a final teacher grade for every case and
no orphan annotations. Check each covered/missed list partitions known key IDs,
claims/feedback follow the guide, weighted raw/rounded scores are consistent,
levels follow v2, pairs share the exact reference and intended meaning, and
source/audio hashes match. Record mismatches and adjudicate; never silently fix
teacher scores. Check full rubric/reference hashes and final dataset SHA-256.

Report actual counts by passage, level, broad CEFR, condition, independent
originals, transformations, pairs, excluded cases, raters and rating overlap.
Then calculate the pre-adjudication agreement described in the teacher guide.
An empty cell is missing data; use “not available”, not an invented zero score.
Validate failure paths on scratch copies if importing newly supplied records:
unknown fields, duplicate IDs, out-of-range/NaN scores, missing dimensions and
unknown covered labels. Do not commit those synthetic probes as teacher cases.
