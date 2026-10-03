"""Dictation scoring: a deterministic word-level diff (FR-DI-5, FR-DI-6, ADR 0008).

``score_dictation`` compares the learner's text with the reference transcript of the
passage. It normalises both texts (``normalize``), aligns them by weighted edit distance
(``align``), and classifies every reference word as correct, spelling slip, wrong or
missing, with the typed words that do not belong to any reference word listed as extra.
Each wrong or missing word becomes a mark candidate at its audio time, which the learner
may add to the mark list (FR-DI-6). No AI is involved.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Final

from listenup.modules.dictation.domain.align import AlignOp, OpKind, align
from listenup.modules.dictation.domain.normalize import Token, tokenize, tokenize_text

# The design gives accuracy as correct words / reference words and does not say where a
# spelling slip belongs (Architecture 13.1, issue #53). A slip means the learner heard
# the word, and Dictation offers no spell-check (FR-DI-3), so slips count as correct.
# Set this to False to count only exact words. See ADR 0019.
SPELLING_SLIPS_COUNT_AS_CORRECT: Final = True

DIFF_VERSION: Final = 1


class WordStatus(StrEnum):
    CORRECT = "correct"
    SPELLING_SLIP = "spelling_slip"
    WRONG = "wrong"
    MISSING = "missing"
    # A reference word with nothing to compare, such as a lone dash. Not counted.
    NOT_SCORED = "not_scored"


@dataclass(frozen=True, slots=True)
class ReferenceWord:
    """One word of the reference transcript with its audio time, in milliseconds."""

    text: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if self.start_ms < 0 or self.end_ms < self.start_ms:
            msg = f"invalid word time {self.start_ms}..{self.end_ms} for {self.text!r}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class WordResult:
    """The verdict on one reference word and what the learner typed for it."""

    index: int  # position in the passage word sequence (practice.marks.word_from)
    word: str
    status: WordStatus
    typed: str  # the learner's words aligned to this word, "" when missing

    def to_json(self) -> dict[str, str | int]:
        return {"index": self.index, "word": self.word, "status": self.status, "typed": self.typed}


@dataclass(frozen=True, slots=True)
class ExtraWord:
    """A typed word that matches no reference word."""

    typed: str
    before_index: int  # index of the reference word it comes before; one past the end at the end

    def to_json(self) -> dict[str, str | int]:
        return {"typed": self.typed, "before_index": self.before_index}


@dataclass(frozen=True, slots=True)
class MarkCandidate:
    """A wrong or missing word the learner may add to the mark list (FR-DI-6)."""

    word_index: int
    word: str
    status: WordStatus
    at_ms: int
    end_ms: int

    def to_json(self) -> dict[str, str | int]:
        return {
            "word_index": self.word_index,
            "word": self.word,
            "status": self.status,
            "at_ms": self.at_ms,
            "end_ms": self.end_ms,
        }


@dataclass(frozen=True, slots=True)
class DictationScore:
    words: tuple[WordResult, ...]
    extras: tuple[ExtraWord, ...]
    mark_candidates: tuple[MarkCandidate, ...]
    correct_count: int
    slip_count: int
    wrong_count: int
    missing_count: int
    scored_count: int  # reference words that were compared (all but NOT_SCORED)
    accuracy: Decimal  # percent with two decimals, for practice.dictation_attempts.accuracy

    @property
    def extra_count(self) -> int:
        return len(self.extras)

    def diff_json(self) -> dict[str, object]:
        """The value for practice.dictation_attempts.diff: per reference word, status and
        what was typed, plus the extra words."""
        return {
            "version": DIFF_VERSION,
            "slips_count_as_correct": SPELLING_SLIPS_COUNT_AS_CORRECT,
            "words": [word.to_json() for word in self.words],
            "extras": [extra.to_json() for extra in self.extras],
        }


def reference_from_arrays(
    words: Sequence[str], start_ms: Sequence[int], end_ms: Sequence[int]
) -> tuple[ReferenceWord, ...]:
    """Build the reference from the parallel arrays in content.passage_transcripts."""
    if not len(words) == len(start_ms) == len(end_ms):
        msg = f"word arrays differ in length: {len(words)}, {len(start_ms)}, {len(end_ms)}"
        raise ValueError(msg)
    return tuple(ReferenceWord(w, s, e) for w, s, e in zip(words, start_ms, end_ms, strict=True))


def score_dictation(
    reference: Sequence[ReferenceWord], typed: str, *, first_word_index: int = 0
) -> DictationScore:
    """Score the learner's text against the reference passage.

    ``first_word_index`` is the passage's first word's position in the whole transcript;
    it is added to every word index in the result so indexes match practice.marks.
    """
    ref_tokens = tokenize(word.text for word in reference)
    typed_words, typed_tokens = tokenize_text(typed)
    ops = align(ref_tokens, typed_tokens)

    statuses = _word_statuses(len(reference), ref_tokens, ops)
    typed_for = _typed_for_words(len(reference), ref_tokens, typed_tokens, typed_words, ops)

    results = tuple(
        WordResult(first_word_index + i, word.text, statuses[i], typed_for[i])
        for i, word in enumerate(reference)
    )
    counts = {status: 0 for status in WordStatus}
    for result in results:
        counts[result.status] += 1
    scored = len(reference) - counts[WordStatus.NOT_SCORED]
    credited = counts[WordStatus.CORRECT]
    if SPELLING_SLIPS_COUNT_AS_CORRECT:
        credited += counts[WordStatus.SPELLING_SLIP]

    marks = tuple(
        MarkCandidate(result.index, result.word, result.status, word.start_ms, word.end_ms)
        for result, word in zip(results, reference, strict=True)
        if result.status in (WordStatus.WRONG, WordStatus.MISSING)
    )
    return DictationScore(
        words=results,
        extras=_extras(
            len(reference), ref_tokens, typed_tokens, typed_words, ops, first_word_index
        ),
        mark_candidates=marks,
        correct_count=counts[WordStatus.CORRECT],
        slip_count=counts[WordStatus.SPELLING_SLIP],
        wrong_count=counts[WordStatus.WRONG],
        missing_count=counts[WordStatus.MISSING],
        scored_count=scored,
        accuracy=_percent(credited, scored),
    )


def _percent(part: int, whole: int) -> Decimal:
    if whole == 0:
        return Decimal("0.00")
    return (Decimal(part * 100) / Decimal(whole)).quantize(Decimal("0.01"), ROUND_HALF_UP)


_TOKEN_STATUS: Final = {
    OpKind.MATCH: WordStatus.CORRECT,
    OpKind.SLIP: WordStatus.SPELLING_SLIP,
    OpKind.WRONG: WordStatus.WRONG,
    OpKind.MISSING: WordStatus.MISSING,
}


def _word_statuses(
    word_count: int, ref_tokens: Sequence[Token], ops: Sequence[AlignOp]
) -> list[WordStatus]:
    """Combine token verdicts into one verdict per reference word.

    A word split into several tokens ("could've") is correct only when every token is;
    missing only when every token is; wrong when any token is wrong or missing; and a
    spelling slip otherwise. A token spanning several words ("nineteen ninety") gives
    its verdict to each of them.
    """
    per_word: list[set[WordStatus]] = [set() for _ in range(word_count)]
    for op in ops:
        if op.kind is OpKind.EXTRA:
            continue
        status = _TOKEN_STATUS[op.kind]
        for t in op.ref:
            for w in range(ref_tokens[t].first_word, ref_tokens[t].last_word + 1):
                per_word[w].add(status)
    return [_combine(found) for found in per_word]


def _combine(found: set[WordStatus]) -> WordStatus:
    if not found:
        return WordStatus.NOT_SCORED
    if len(found) == 1:
        return next(iter(found))
    if WordStatus.WRONG in found or WordStatus.MISSING in found:
        return WordStatus.WRONG
    return WordStatus.SPELLING_SLIP


def _typed_for_words(
    word_count: int,
    ref_tokens: Sequence[Token],
    typed_tokens: Sequence[Token],
    typed_words: Sequence[str],
    ops: Sequence[AlignOp],
) -> list[str]:
    typed_indexes: list[set[int]] = [set() for _ in range(word_count)]
    for op in ops:
        if not op.ref or not op.typed:
            continue
        source = {
            w
            for t in op.typed
            for w in range(typed_tokens[t].first_word, typed_tokens[t].last_word + 1)
        }
        for t in op.ref:
            for w in range(ref_tokens[t].first_word, ref_tokens[t].last_word + 1):
                typed_indexes[w].update(source)
    return [" ".join(typed_words[w] for w in sorted(found)) for found in typed_indexes]


def _extras(
    word_count: int,
    ref_tokens: Sequence[Token],
    typed_tokens: Sequence[Token],
    typed_words: Sequence[str],
    ops: Sequence[AlignOp],
    first_word_index: int,
) -> tuple[ExtraWord, ...]:
    """Extra typed words, each with the reference word it comes before.

    A typed word whose tokens are all extra is reported as typed. When only part of a
    typed word is extra ("could've" typed for "could"), the extra part is reported.
    """
    before: dict[int, int] = {}
    next_word = word_count
    for op in reversed(ops):
        if op.ref:
            next_word = ref_tokens[op.ref[0]].first_word
        elif op.kind is OpKind.EXTRA:
            for t in op.typed:
                before[t] = next_word

    tokens_of_word: defaultdict[int, list[int]] = defaultdict(list)
    for t, token in enumerate(typed_tokens):
        for w in range(token.first_word, token.last_word + 1):
            tokens_of_word[w].append(t)

    extras: list[ExtraWord] = []
    reported_parts: set[int] = set()
    for w in range(len(typed_words)):
        tokens = tokens_of_word.get(w, [])
        if tokens and all(t in before and t not in reported_parts for t in tokens):
            position = min(before[t] for t in tokens)
            extras.append(ExtraWord(typed_words[w], first_word_index + position))
            continue
        for t in tokens:
            if t in before and t not in reported_parts:
                reported_parts.add(t)
                token = typed_tokens[t]
                text = (
                    " ".join(typed_words[token.first_word : token.last_word + 1])
                    if token.is_number
                    else token.key
                )
                extras.append(ExtraWord(text, first_word_index + before[t]))
    return tuple(extras)
