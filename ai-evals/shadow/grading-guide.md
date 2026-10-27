# Teacher grading guide: Shadow recordings

For the English teacher grading Shadow recordings for #107. Read the
[README](README.md) first. About 50 recordings take roughly four to five hours: plan breaks,
and grade in several sessions with the same headphones.

## What you get for each recording

- The **reference audio** and its **text** (the original speaker).
- The learner's **recording** of shadowing that segment.
- A list of the segment's words in order, to label.

You do not see who the speaker is, their accent group or any system grade. Do not look at
system output while grading.

## Judge the speaker against the original, not against a native accent

Pronunciation and accent are **guidance relative to the original clip, not a verdict on the
learner** (FR-SH-15). Do not mark a speaker down for being a non-native speaker or for an
accent that is clear and easy to understand. Mark what differs from the original in a way
that would make a listener hesitate or mishear. Accent is graded but **excluded from
`overall`**.

## The seven measures (each 0 to 100)

| Measure | Listen for | Low means |
| --- | --- | --- |
| `timing` | Speech rate and word timing against the original; pause length and placement | Much faster or slower, late starts, pauses in odd places |
| `pronunciation` | Accuracy of each word and sound | Many words or sounds wrong or hard to recognise |
| `accent` | Vowels, consonants, stress and intonation compared with the original speaker | Stress and intonation far from the original (guidance only) |
| `articulation` | Clarity: dropped, merged or unclear sounds and word endings | Mumbled, swallowed endings, hard to make out |
| `fluency` | Smoothness: hesitations, restarts, long pauses | Frequent stops, restarts and long gaps |
| `fillers` | Rate of fillers (um, uh, er, like, you know) | Many fillers per minute; **100 = none** |
| `completeness` | Share of the reference words actually spoken | Words or whole phrases skipped |

Use the whole range. Anchor your scale once at the start: listen to two recordings you think
are the best and worst you will hear, set 90+ and 20 or below for those, and keep that scale
for all 50.

`overall` is your impression of the round **without accent**. It is not an average you must
compute.

## Count the fillers

Record `filler_count`: the number of filler words (um, uh, er, and lexical fillers like
"like" or "you know" that are used as fillers, not as part of the sentence) the speaker adds
that are **not in the reference text**. Count what you hear, not what is likely. This count is
checked within one of the system's count (AT-17), so be exact; if unsure, listen twice and
note the case.

## Label every word (`word-labels.json`)

For each word of the reference text, in order:

- `good`: said clearly and correctly enough.
- `needs_work`: said, but mispronounced, unclear or stressed wrongly.
- `missed`: not said at all (skipped or inaudible).

A word said twice is `good` if the best attempt is clear. A word you cannot decide on:
choose `needs_work`, never `missed`, unless it is clearly absent.

## Clear and mumbled versions (AT-17)

Some recordings are the **same speaker and segment**, once clearly and once mumbled with late
starts. Grade each on its own merits. The mumbled one should score lower overall for real
reasons, not because you know it is the mumbled one. You will not be told which is which.

## Working rules

1. Use good headphones in a quiet room. Listen to the reference first, then the recording.
2. Grade each recording once on its own; do not compare it with the previous one.
3. Write grades under your code (`T1`, `T2`). Never write your name. Never edit another
   teacher's entry.
4. If two teachers grade, grade **independently first**, then discuss. Keep both original
   entries; `dataset.json` takes the agreed grade.
5. Do not copy or share audio outside the team's private storage. Do not write anything
   about a speaker's identity, health or background in a grade or note.
6. If a recording has leaked reference audio in the background (echo), or is cut short or
   silent, flag it rather than grading it.

## Example entry (shape only; the values are not real grades)

```json
{
  "case": "r01",
  "teacher": "T1",
  "grade": {
    "scores": {
      "timing": 0, "pronunciation": 0, "accent": 0, "articulation": 0,
      "fluency": 0, "fillers": 0, "completeness": 0
    },
    "overall": 0,
    "filler_count": 0
  }
}
```

And the word labels (`word-labels.json`, shape only):

```json
{"case": "r01", "words": [{"word": "word", "label": "good"}]}
```
