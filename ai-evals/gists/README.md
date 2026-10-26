# Gist collection kit — issue #106

**Collection pending. This is not a human golden set.** As of 2026-10-27,
no learner responses, consent evidence or teacher judgments were supplied in
issue #106 (including its empty comment list) or found in the repository.
The synthetic runner fixtures are excluded. Do not close #106 on this kit.
See [status.md](status.md) for measured coverage and work still required.

This kit supports NFR-AI-6 and AT-10–AT-13, with an AT-15 handoff to #109.
It changes no grading code, released prompt/rubric, provider or threshold.
No inference, provider evaluation or calibration was performed.

- [passages.json](passages.json): ten licensed source selections, exact source
  members, transcripts, checksums, durations and draft key points.
- [passages.md](passages.md): readable inventory and reproduction instructions.
- [learner-and-consent.md](learner-and-consent.md): participant instructions,
  separate permission choices and private consent administration.
- [teacher-guide.md](teacher-guide.md): actual v2 rubric, independent rating,
  captured/missed labels, adjudication and agreement reporting.
- [import-and-validation.md](import-and-validation.md): runner mapping,
  anonymization, release checks and validation-only command.
- [coverage.md](coverage.md): collection targets and acceptance evidence.
- [templates/](templates/): header-only intake/rating/provenance/agreement CSVs,
  a 50-slot recruitment plan, and an explicitly incomplete JSON template.

Start by assigning a collection coordinator and at least one English teacher
(two recommended). Have the teacher review audio suitability and correct/freeze
references before recruiting consenting B1–C1 adults. Collect 50 original learner
responses, approximately five per passage; retain naturally weak responses.
Collect paired transformations additionally, rather than inflating the original
response count. Rate independently, reconcile disagreements, remove identifiers,
validate, then commit only cleared manifests and anonymous annotations here.

The public repo is unsuitable for consent forms, names, contact details,
participant keys, private originals or signed media URLs. `.gitignore` is not a
privacy boundary: store those materials in an access-controlled system outside
the checkout. Blank consent wording here contains no participant records.
