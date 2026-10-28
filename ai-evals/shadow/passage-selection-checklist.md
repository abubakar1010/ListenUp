# Segment selection checklist: Shadow

Use this for the **about 10** segments (#107). Record each in `passages.json`. Tick every box
for every segment; a segment that fails one is replaced. The speakers you recruit to shadow
these segments are covered by the [matrix](coverage-matrix.md) and the
[consent form](consent-form-template.md).

## Audio source and licence

- [ ] The reference audio is **public domain** or **licensed for this use**: a Creative Commons
  licence that allows copying and use for evaluation, or written permission from the
  rights holder. Record the licence and a public `source_url` (https, no query or token).
- [ ] The licence allows publishing the segment's **text** in a public repo (the
  reference text is in `dataset.json`). The reference **audio** stays in private storage
  even if the licence would allow publishing it.
- [ ] The audio is **not** from YouTube or another site whose terms forbid downloading (OQ-6).
- [ ] Attribution is recorded exactly as the licence requires.

## Fit for Shadow (FR-SH-1)

- [ ] The segment is **60 to 90 seconds**, or a whole passage of **30 to 60 seconds**.
  Record `duration_seconds`; each recording case sets `context.audio_seconds` the same
  (within one second, enforced). That a 30 to 60 s clip is the whole passage is checked by
  hand.
- [ ] One clear speaker, at natural speed, with little music or noise; no leakage-prone
  effects.
- [ ] The text is checked against the audio by a person and has normal punctuation.
- [ ] It is natural, connected speech with some hard words, linking and sentence stress, so
  speakers can go wrong in different ways.
- [ ] Nothing offensive, private or sensitive.

## Variety across the set

- [ ] **Topics** (script): no two segments share a topic.
- [ ] **Reference speakers:** at least three women and three men (manual), at least four
  different accents, and no one accent in more than three segments (script).
- [ ] **Difficulty:** a mix of slow and fast, simple and dense, so scores spread out.
- [ ] **Speaker use** (manual): every segment is shadowed by at least three different speakers, in
  different accent groups, so a score difference is not just a segment effect.
- [ ] Two segments are reserved for the **clear vs mumbled** pairs (AT-17); more if
  possible.

## Recording conditions

- [ ] Headphones, a quiet room, the same kind of microphone if possible (laptop or phone).
- [ ] Each speaker has signed the [consent form](consent-form-template.md) **before** being
  recorded.
- [ ] Files are named `rec-<n>.wav` (and `ref-<segment id>.wav`; the checker enforces both
  shapes) and stored in private storage.
  Nothing is stored in this repository.

## Catalogue entry (shape only)

```json
{
  "id": "s01",
  "title": "Title of the recording",
  "topic": "technology",
  "speaker_accent": "british",
  "licence": "CC BY 4.0",
  "source_url": "https://example.org/recording",
  "duration_seconds": 0
}
```
