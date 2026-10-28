# Passage selection checklist: gists

Use this for the **about 10** passages (#106). Record each in `passages.json`.
Tick every box for every passage; a passage that fails one is replaced.

## Audio source and licence

- [ ] The audio is **public domain** or **licensed for this use**: a Creative Commons
  licence that allows copying, adaptation and use by a team that publishes the
  transcript, or written permission from the rights holder. Record the licence
  and a public `source_url` (https, no query string or token).
- [ ] The licence allows publishing the **transcript** and key points in a public repo.
  Where it does not, do not use the passage.
- [ ] The audio is **not** from YouTube or another site whose terms forbid downloading
  (OQ-6). Use sources that allow reuse, such as archives of freely licensed talks or
  spoken-word collections.
- [ ] Attribution is recorded exactly as the licence requires.

## Fit for the product

- [ ] Length suits Blind: a single listen of about 30 seconds to 3 minutes.
- [ ] One clear speaker, or a small number of clearly distinct ones; little music or noise.
- [ ] A transcript exists and has been checked against the audio by a person.
- [ ] Three to six key points can be written, one of them the main idea, each a complete
  sentence of 300 characters or fewer.
- [ ] Nothing in the passage is offensive, medical or legal advice, or about a private person.

## Variety across the set (see the [matrix](coverage-matrix.md))

- [ ] **Topics** (script): no two passages share a topic (for example science, health, travel, work,
  daily life, culture, technology, history, money, environment).
- [ ] **Speakers** (manual, not recorded in `passages.json`): at least three passages with a
  woman, three with a man, and a mix of ages where known.
- [ ] **Accents** (script): at least four different speaker accents across the set (for example
  North American, British, Australian or New Zealand, Indian, and any non-native English
  speaker), with no one accent in more than three passages.
- [ ] **Style:** include both a talk-style monologue and some conversational speech.
- [ ] **Difficulty:** a spread from easy to hard, so every level from Needs work to
  Excellent can occur for a real reason.

## Key points

- [ ] Written by a teacher, not by the AI under test.
- [ ] One `main`, the rest `supporting`, labelled `kp1` to `kp6` in order.
- [ ] Each point is independently checkable from the transcript.
- [ ] At least one passage has a point that is easy to miss (a number, a contrast, a
  conclusion), so the details dimension can discriminate.

## Catalogue entry (shape only)

```json
{
  "id": "p01",
  "title": "Title of the recording",
  "topic": "technology",
  "speaker_accent": "british",
  "licence": "CC BY 4.0",
  "source_url": "https://example.org/recording",
  "duration_seconds": 0
}
```
