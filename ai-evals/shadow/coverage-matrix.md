# Coverage matrix: Shadow

What the set must contain before #107 can close. `check_golden_sets.py --require-complete`
enforces every row marked **script**; rows marked **manual** are checked by the reviewer.
Tags go in each case's `tags` list in `dataset.json`: lower case, kebab-case, no repeated
tag, no empty value after a colon. The minimums are the kit's proposal for "about 50"; the owner may change them
(and the constants in the script) before collecting.

## Size

| Item | Target | Check |
| --- | --- | --- |
| Recordings | 45 to 55; ids `r01`, `r02`, ... | **script**: case count and id shape |
| Segments | 8 to 12, one topic each, none unused, at least four reference-speaker accents and no accent in more than three segments | **script**: one `passage:<id>` tag per case, id in `passages.json`, no unused or duplicate entry |
| Reference speakers | at least three women and three men | **manual**: not recorded in `passages.json` |
| Teachers | at least 1 per recording; a second teacher on as many as possible | **script**: a grade per case, no duplicate `(case, teacher)`, the seven measures and a `filler_count`; a single grade must equal `expected`. **Manual**: how many have a second teacher (`--agreement`) |
| Duration | a 60 to 90 s segment, or a whole 30 to 60 s passage (FR-SH-1) | **script**: `duration_seconds` of every segment is 30 to 90 s and `context.audio_seconds` is set on every case within 1 s of its segment. **Manual**: that a 30 to 60 s clip is the whole passage |
| Audio paths | `external/rec-<n>.wav` and `external/ref-<segment>.wav` | **script**, in every mode: no absolute path, URL, drive letter, `..` or personal file name; no audio file or `external/` folder in the suite's folder |

## Accent spread (for #111)

#111 compares system and teacher scores for each measure **per accent group**, so every
recording carries exactly one `accent:<group>` tag and one `speaker:<code>` tag.

| Requirement | Minimum |
| --- | --- |
| Accent groups with enough speakers | 4 (**script**) |
| Distinct speakers in each such group | 3 (**script**); a speaker belongs to one group; the `speaker:` tag is a code like `s12` |
| Recordings per group | aim for 8 or more, so a per-measure bias is not one person (**manual**) |

Proposed starting groups (confirm with the teacher **before** collecting; use kebab-case
labels such as `accent:south-asian`): South Asian, East Asian, Spanish or Portuguese speaking,
Arabic speaking, Slavic speaking, West African, and a reference group of speakers whose first
language is English. Groups are by the speaker's self-reported first language or region, are
coarse on purpose and are never graded. Recruit so that no group has fewer than three people
and no one speaker supplies more than about a fifth of the group's recordings (**manual**),
and so that every segment is shadowed by at least three speakers from different groups
(**manual**).

## Clear vs mumbled (AT-17)

| Tag | Rule | Minimum |
| --- | --- | --- |
| `pair:<id>` + `delivery:clear` | A speaker shadows a segment clearly and on time | 3 pairs |
| `pair:<id>` + `delivery:mumbled` | The same segment, mumbled with late starts | 3 pairs |

A pair is valid when it has exactly one clear and one mumbled case, both on the **same
segment** (`passage:`), and the mumbled version gets a **lower `overall`** (all **script**).
Ideally the same speaker does both (**manual**).

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
| Word labels | every case has one entry in `word-labels.json`, none for an unknown case; labels are `good`, `needs_work` or `missed`, and the words match `reference_text` word for word (**script**) |
| Consistency (AT-21) | evaluated by the runner, not here; needs no extra recordings |
| Agreement | `--agreement` reports it where two teachers graded |
