# ADR 0019: Dictation scoring rules

- Status: Accepted
- Date: 2026-10-03
- Source: issue #53; [SRS FR-DI-3, FR-DI-5, FR-DI-6](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd); [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13)

## Context

ADR 0008 makes Dictation scoring a pure function: normalise, align by weighted edit distance, classify each reference word as correct, spelling slip, wrong or missing. The design gives accuracy as correct words / reference words but does not say whether a spelling slip counts as correct, how many letters make a slip for short words, or how numbers and contractions compare. Passages run up to 15 minutes (FR-DI-1), about 2,500 words.

## Decision

- **Spelling slips count as correct** for accuracy. A slip means the learner heard the word, Dictation offers no spell-check (FR-DI-3), and the product scores listening, not spelling. Slips are still reported separately and are not mark candidates. The rule is one constant, `SPELLING_SLIPS_COUNT_AS_CORRECT` in `modules/dictation/domain/scoring.py`, and the stored diff records which rule applied.
- **A slip is scaled by word length.** Words of three letters or fewer allow only a swapped or doubled letter ("teh", "dogg"); four letters allow one edit; five or more allow two. This keeps "in" and "on" or "he" and "she" as wrong words. A word typed joined or split ("alot", "every one", "dont") is a slip.
- **Normalisation** lower-cases, strips punctuation, unifies apostrophes, expands contractions ("'d" and "'s" after a pronoun match either full form), maps British spellings to American ones from a curated table, and reduces numbers in digits or words to one key ("15" and "fifteen", "1990s" and "the nineteen nineties", "21st" and "twenty-first"). Punctuation never changes a score.
- **Words, not tokens, are scored.** A reference word split into several tokens is correct only when all of them are; a token made of several words gives its verdict to each word. Mark candidates are per reference word, with the word's start time as `at_ms`.
- **Long passages** are aligned by anchoring on common start and end and on tokens unique to both texts (patience diff), with the weighted table only between anchors. A 2,500-word passage scores in well under 200 ms.

## Consequences

Scores forgive spelling but not listening errors, and the rule can be flipped in one place. The British spelling table needs words added over time. Homophones within the slip limit ("there" and "their") are slips, while different words within it ("these" and "those") are slips too; a dictionary could tell them apart later.
