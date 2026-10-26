# Collection and validation status

Snapshot: **2026-10-27**. Repository base `c7975df`; issue #106 and #109 read
through GitHub. #106 had no comments or attached learner/teacher records.
Repository search found only explicitly synthetic gist fixtures and earlier
validation records stating the teacher sets are absent. No supplied human data
was available to validate; no wider private learner repository was assumed.

| Measure | Actual available | Remaining |
| --- | ---: | --- |
| Licensed source passage candidates | 10 | Teacher listening/suitability review and reference approval for all 10 |
| Distinct source corpus speakers | 10 | No accent-representativeness claim; review intended listening population |
| Original learner responses | 0 | About 50 consented B1–C1 originals, roughly 5 per passage |
| Additional AT-12/AT-13 paired partners | 0 | At least 5 meaning-preserving clean partners and 5 controls |
| Teacher-graded cases | 0 | Every collected original and retained transformation |
| Independently double-rated cases | 0 | Prefer all; proposed minimum overlap 20 |
| Needs work / Fair / Good / Excellent | 0 / 0 / 0 / 0 | All four levels, initial recruitment aims 13 / 13 / 12 / 12 |
| AT-10 verified human cases | 0 | At least 5 teacher-confirmed main-idea/most-detail cases |
| AT-11 verified human cases | 0 | At least 5 unrelated cases with explicit missed-point feedback |
| AT-12 verified pairs | 0 | At least 5 teacher-verified same-meaning pairs and same-level checks |
| AT-13 verified pairs | 0 | At least 5 injection/control pairs with normal human grading |
| Publicly cleared learner/teacher records | 0 | Private permissions and two-person anonymization/release review |
| Teacher agreement | Not available (paired n=0) | Independent ratings and pre-adjudication metrics |
| Model agreement / AT-15 consistency | Not run | #109; outside this collection-kit task |

The issue’s “about 50 gists with teacher grades committed” and demonstrated
coverage/teacher-agreement criteria remain **unmet**. Recruitment targets in the
kit are proposals, not evidence. No response, score or judgment was fabricated
or relabelled as human data. Curator-written reference points await teacher
approval; they are not teacher judgments.

## Checks performed

- Actual `GradeGistInput` model used to validate all ten source inputs (empty
  gist only as a structural probe, never a collected response).
- Ten unique passage IDs, ten distinct corpus speaker IDs, 3–6 points with exactly
  one main first, and durations 47.400–67.445 seconds checked.
- All 53 selected audio segments downloaded from the source corpus mirror;
  ffprobe confirmed durations, and SHA-256 fingerprints recorded and rechecked.
  Transcripts were joined exactly from the corresponding corpus records.
- Fifty planned slots reconcile to five per passage, broad CEFR targets
  17 B1 / 17 B2 / 16 C1 and level targets 13 / 13 / 12 / 12; all uncollected.
- Four intake/rating/provenance/agreement CSVs checked header-only, with no
  invented data rows. JSON template parses but actual `Dataset` rejects its null
  placeholders as intended.
- A disposable **synthetic-only** contract probe using an existing synthetic
  fixture reference validated the filled template shape against `Dataset`.
  Duplicate IDs, unknown expected fields, missing dimensions, out-of-range and
  NaN scores, and disallowed `synthetic_runs` were rejected on scratch copies.
  These probes are not committed datasets or model-quality evidence.
- Relative Markdown links and whitespace checked. No executable application
  behavior changed: TDD red/green and changed-code coverage are not applicable
  under `docs/testing.md`’s documentation rule. Full app suites, gateway smoke,
  live inference and calibration were not run.

Validation command used from repository root:
`PYTHONPATH=apps/api/src apps/api/.venv/bin/python /workspace/work/validate_gist_kit.py`.
This is a task-local authoring check, not a newly supported repository command.
Use the documented validation-only model command in
[import-and-validation.md](import-and-validation.md) for future supplied data.

## Next collection steps

Assign a coordinator and teacher(s); set private consent administration/contact,
retention and release arrangements; review and freeze ten suitable references;
recruit consenting learners; collect original and labelled paired responses;
obtain independent teacher ratings and adjudication; publish anonymous
pre-adjudication agreement/coverage with actual denominators; clear privacy and
rights; import and structurally validate the genuine dataset and sidecars.

Keep unresolved accuracy-scale judgments, pair mismatches and the runner versus
production rounding distinction visible in the #109 handoff. Do not tune prompts,
weights, bounds, providers, quotas or grading code under #106, or claim provider
acceptance from this kit.
