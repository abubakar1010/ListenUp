# Gist golden set (#106)

About 50 learner gists, each graded by at least one English teacher with the gist rubric
([ADR 0054](../../docs/adr/0054-versioned-gist-scoring.md), SRS 5.2.1). The set checks that
AI gist grading agrees with teachers before launch and before any provider switch
(NFR-AI-6). The runner that scores it is #108 ([format](../README.md#dataset-format-version-1)).

**Status: collection kit only. No real data is committed.** #106 stays open until the
set below exists and passes `check_golden_sets.py --require-complete`.

## What is in this folder

| File | Purpose |
| --- | --- |
| [`grading-guide.md`](grading-guide.md) | What a teacher does and scores, matching the rubric |
| [`consent-form-template.md`](consent-form-template.md) | Consent for a learner whose gist is used |
| [`passage-selection-checklist.md`](passage-selection-checklist.md) | How to choose and record the ~10 passages |
| [`coverage-matrix.md`](coverage-matrix.md) | What the 50 gists must cover; the tags that prove it |
| `dataset.template.json` | Empty runner dataset (`kind: teacher`, `suite: gist`); copy to `dataset.json` |
| `teacher-grades.template.json` | Empty per-teacher grades; copy to `teacher-grades.json` |
| `passages.template.json` | Empty passage catalogue; copy to `passages.json` |

## Source of the data

- **Passages:** public-domain or licensed audio only (see the checklist). The catalogue
  records title, topic, speaker accent, licence and a public source URL for each. The audio
  itself is not stored here.
- **Gists:** written by B1 to C1 learners who listened to a passage once, Blind-style, and
  typed what they understood. A few, marked in the matrix, are written on purpose by the
  team or a teacher (unrelated, misspelled, prompt-injection) and tagged `kind:authored`.
  The PR and the set's `source` must say that some are authored. Do not present authored
  examples as learner work.
- **Key points:** three to six per passage, labelled `kp1`, `kp2`, ... in order, with
  exactly one `main`. Write them once per passage and reuse them, with the same transcript,
  for every gist of that passage. They follow the same shape the key-point extraction
  produces (`text` up to 300 characters). The checker enforces all of this.
- **Grades:** teacher grades only. Nobody invents, estimates or model-generates a grade.
  If a grade is missing, the case is missing.

## Consent and personal data

- Every learner signs the [consent form](consent-form-template.md) **before** writing a
  gist. Signed forms and the learner-to-code register stay outside this repository, in
  team-only storage (for example the team drive). Never commit them, photos of them or a
  list that links codes to people.
- The repository is public. A committed gist must not contain a name, email, phone number,
  employer, school, address, account id or any other detail that identifies a person. Read
  each gist and remove or generalise such details **with the learner's agreement** before
  it enters `dataset.json`. Do not alter the meaning or the language errors.
- Learners appear only as a case id (`g01` to `g50`). Teachers appear only as `T1`, `T2`.
  The mapping from codes to people is kept outside the repository. The checker enforces
  both code shapes.
- `check_golden_sets.py` scans every JSON file here, templates included, for emails, phone
  numbers and signed URLs as a safety net, and fails if an audio file or an `external/`
  folder appears in the folder. It cannot find names. The reviewer of the PR reads every
  gist.
- A learner may withdraw at any time. Delete the case from `dataset.json`, its grades and
  its tags in a new commit and tell the owner that earlier history still holds the text.
  Use this promise in the consent form only if the owner accepts it, otherwise change the
  form. If the withdrawn case was one of an AT-12 pair, or took a level or tag below its
  minimum, collect a replacement before the set is declared complete.

## Files to create when collecting

1. `dataset.json`: runner format, `kind: "teacher"`, `suite: "gist"`. Each case has
   `id`, `tags` (see the matrix), `input` (`transcript`, `gist`, `key_points`) and
   `expected` (the final grade: `scores`, `overall`, `level`). Add a `context` with
   `consent`, `region` and `population` only if a candidate hosted provider's terms and
   the consent form allow it: the runner never bypasses provider eligibility, and an
   absent context makes hosted providers ineligible.
2. `teacher-grades.json`: one entry per teacher per case with that teacher's own grade and
   `covered_points`. When two teachers graded a case, `expected` in `dataset.json` is the
   agreed grade after they discuss; if they cannot agree, use the more experienced
   teacher's grade and note it in `source`. With a single teacher, `expected` must equal
   that teacher's grade (the checker enforces it).
3. `passages.json`: the catalogue, one entry per passage used.

## Check it

From `apps/api`:

```sh
uv run python scripts/check_golden_sets.py --suite gist                    # format, privacy
uv run python scripts/check_golden_sets.py --suite gist --require-complete # the matrix
uv run python scripts/check_golden_sets.py --suite gist --agreement        # two teachers
```

`--agreement` reports, for cases graded by two or more teachers, the share of pairs that
gave the same level and the mean absolute difference per dimension and overall. Every
pair counts, so a case with three teachers weighs three times a case with two. Put that
output in the PR that commits the set (#106 acceptance: "agreement is reported").
It exits 1 if `teacher-grades.json` is missing or invalid, and cannot be combined with
`--require-complete`.

## Definition of done for #106

- [ ] About 50 gists graded, committed in the runner's format with this README.
- [ ] `check_golden_sets.py --require-complete --suite gist` reports `ok`.
- [ ] Every level and AT-10 to AT-13 are covered (the matrix says how many).
- [ ] Agreement reported where two teachers graded.
- [ ] Consent forms and the code register are kept outside the repository, and the owner
  confirmed they exist.
