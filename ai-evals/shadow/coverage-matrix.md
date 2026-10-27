# Coverage matrix: Shadow

What the set must contain before #107 can close. `check_golden_sets.py --require-complete`
enforces every row with a tag or a count. Tags go in each case's `tags` list in
`dataset.json`. The minimums are the kit's proposal for "about 50"; the owner may change them
(and the constants in the script) before collecting.

## Size

| Item | Target | Check |
| --- | --- | --- |
| Recordings | 45 to 55 | case count |
| Segments | 8 to 12 | one `passage:<id>` tag per case, id in `passages.json` |
| Teachers | at least 1 per recording; a second teacher on as many as possible | `teacher-grades.json` |
| Duration | 30 to 90 s | `context.audio_seconds` set on every case |
| Audio paths | relative, under `external/` | no absolute path, URL or `..` |

## Accent spread (for #111)

#111 compares system and teacher scores for each measure **per accent group**, so every
recording carries exactly one `accent:<group>` tag and one `speaker:<code>` tag.

| Requirement | Minimum |
| --- | --- |
| Accent groups with enough speakers | 4 |
| Distinct speakers in each such group | 3 |
| Recordings per group | aim for 8 or more, so a per-measure bias is not one person |

Proposed starting groups (confirm with the teacher **before** collecting; use kebab-case
labels such as `accent:south-asian`): South Asian, East Asian, Spanish or Portuguese speaking,
Arabic speaking, Slavic speaking, West African, and a reference group of speakers whose first
language is English. Groups are by the speaker's self-reported first language or region, are
coarse on purpose and are never graded. Recruit so that no group has fewer than three people
and no one speaker supplies more than about a fifth of the group's recordings.

## Clear vs mumbled (AT-17)

| Tag | Rule | Minimum |
| --- | --- | --- |
| `pair:<id>` + `delivery:clear` | A speaker shadows a segment clearly and on time | 3 pairs |
| `pair:<id>` + `delivery:mumbled` | The same segment, mumbled with late starts | 3 pairs |

A pair is valid when both versions use the **same segment** (`passage:`) and the mumbled
version gets a **lower teacher `overall`**. Ideally the same speaker does both.

## Fillers (AT-17: count within one)

| Item | Minimum |
| --- | --- |
| Recordings with `filler_count` of 1 or more | 10 |
| Recordings with `filler_count` of 0 | 10 |

Include lexical fillers ("like", "you know") as well as "um" and "uh", across accents and
pauses (ADR 0050, #22).

## Grading data

| Item | Rule |
| --- | --- |
| Seven measures | all seven present on every case (loader enforces) |
| Word labels | every case has an entry in `word-labels.json`; labels are `good`, `needs_work` or `missed` |
| Consistency (AT-21) | evaluated by the runner, not here; needs no extra recordings |
| Agreement | `--agreement` reports it where two teachers graded |
