# Shadow golden set (#107)

About 50 Shadow recordings from speakers with varied first languages and accents, each
graded by at least one English teacher on the seven measures, with word labels and a
filler count. It checks that Shadow scores agree with teachers (NFR-AI-6, AT-17, AT-21) and,
through #111, that they do not favour or punish an accent (FR-SH-15). Segments follow
FR-SH-1 (60 to 90 seconds, or a whole 30 to 60 second passage). The grading measures are the
seven in SRS 5.5.1 and [ADR 0050](../../docs/adr/0050-shadow-measures-model-choices-and-go-no-go.md).

**Status: collection kit only. No real data and no audio are committed.** #107 stays open
until the set exists and passes `check_golden_sets.py --require-complete --suite shadow`.
Live Shadow grading is unavailable in the runner (ADR 0050, #108); this set is the
reference that #110 (calibration) and #111 (fairness) need.

## What is in this folder

| File | Purpose |
| --- | --- |
| [`grading-guide.md`](grading-guide.md) | What a teacher listens for and scores, per measure |
| [`consent-form-template.md`](consent-form-template.md) | Written consent for a speaker's recordings |
| [`passage-selection-checklist.md`](passage-selection-checklist.md) | How to choose and record the ~10 segments |
| [`coverage-matrix.md`](coverage-matrix.md) | What the 50 recordings must cover; the tags that prove it |
| `dataset.template.json` | Empty runner dataset (`kind: teacher`, `suite: shadow`); copy to `dataset.json` |
| `teacher-grades.template.json` | Empty per-teacher grades; copy to `teacher-grades.json` |
| `passages.template.json` | Empty segment catalogue; copy to `passages.json` |
| `word-labels.template.json` | Empty per-word labels; copy to `word-labels.json` |

## Source of the data

- **Segments:** public-domain or licensed audio, 60 to 90 seconds (or a whole 30 to 60 second
  clip), chosen with the [checklist](passage-selection-checklist.md). The reference audio and
  its text are stored outside the repository; the catalogue records their licence and public
  source.
- **Recordings:** each speaker shadows a segment in the app's Shadow format (three rounds are
  not required here; one attempt per recording is one case), with headphones, in a quiet
  room. Speakers have varied first languages and accents and give written consent.
- **Grades, word labels and filler counts:** teachers only. Nobody invents, estimates or
  model-generates them. A missing grade means a missing case.

## Recordings are personal data: audio never enters this repository

The repository is public. A voice recording identifies a person and so is personal data.

- **Audio** (learner recordings **and** reference audio) lives in private, team-only
  storage, for example a restricted object-storage bucket or drive folder. Access is limited
  to the people named on the consent form. It is never committed, attached to an issue or PR
  or sent to an AI service that trains on inputs (NFR-AI-7).
- **The repository holds only manifests:** `dataset.json` refers to audio by a relative name
  such as `external/rec-07.wav`, which the runner resolves from a locally provisioned folder.
  No absolute paths, URLs, signed links, account ids or names.
- **Consent records** (signed forms, the register linking speaker codes to people, contact
  details) are kept outside the repository in the same private storage and are never
  committed or photographed into the repo.
- Speakers appear only as `speaker:<code>` tags, teachers only as `T1`, `T2`. The mapping
  stays outside.
- `check_golden_sets.py` rejects absolute or URL audio paths and scans for emails, phone
  numbers and signed URLs. It cannot read audio. Before the PR, confirm that no audio file
  or consent record is in the diff.
- Delete a speaker's recordings, labels and grades when they withdraw. The consent form says
  what can and cannot be undone in a public repository.

## Accent groups (for #111)

Each speaker has an `accent:<group>` tag. The group is the speaker's **self-reported** first
language or region on the consent form, mapped by the owner to a coarse label agreed with the
teacher **before** collection (a proposed starting list is in the
[matrix](coverage-matrix.md)). Teachers do not assign it, and it is never graded: it
exists only so #111 can compare system and teacher scores per group. At least four groups
need several speakers each.

## Files to create when collecting

1. `dataset.json`: runner format, `kind: "teacher"`, `suite: "shadow"`. Each case has `id`,
   `tags`, `context.audio_seconds`, `input` (`recording`, `reference_audio`, `reference_text`)
   and `expected` (`scores` for the seven measures, `overall`, `filler_count`). `overall` is
   the teacher's own impression; the production overall excludes accent (FR-SH-9), so grade
   it the same way.
2. `teacher-grades.json`: each teacher's own grade per case. When two teachers graded,
   `expected` is the agreed grade after discussion; keep both originals.
3. `word-labels.json`: for every case, each word of the segment as `good`, `needs_work` or
   `missed`, in order.
4. `passages.json`: the segment catalogue.

## Check it

From `apps/api`:

```sh
uv run python scripts/check_golden_sets.py --suite shadow                    # format, privacy
uv run python scripts/check_golden_sets.py --suite shadow --require-complete # the matrix
uv run python scripts/check_golden_sets.py --suite shadow --agreement        # two teachers
```

## Definition of done for #107

- [ ] About 50 recordings graded, with word labels and filler counts, stored with this README.
- [ ] At least four accent groups with several speakers each.
- [ ] Clear and mumbled versions of the same segment (AT-17).
- [ ] `check_golden_sets.py --require-complete --suite shadow` reports `ok`.
- [ ] Audio and consent records are in private storage, access limited to the team, and the
  owner confirmed it. Nothing personal is in the repository.
