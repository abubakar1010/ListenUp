"""Which diff words a mark added from Dictation may cover (#55, FR-DI-6).

Only wrong and missing words are mark candidates (ADR 0019). A mark from the diff covers
one candidate or a run of candidates next to each other in the passage, and takes the
audio time of its first word. How long a mark may be is the review module's rule.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from listenup.modules.dictation.domain.scoring import MarkCandidate


class NotACandidate(ValueError):
    """The range holds a word that was right, or one that is not in the passage."""


@dataclass(frozen=True)
class CandidateRange:
    at_ms: int
    phrase: str


def candidate_range(
    candidates: Sequence[MarkCandidate], word_from: int, word_to: int
) -> CandidateRange:
    """The audio time and words of `word_from` to `word_to`, if every one is a candidate."""
    by_index = {candidate.word_index: candidate for candidate in candidates}
    if word_to < word_from:
        raise NotACandidate(f"words {word_from} to {word_to} run backwards")
    covered = [by_index.get(index) for index in range(word_from, word_to + 1)]
    words = [candidate for candidate in covered if candidate is not None]
    if len(words) != len(covered):
        raise NotACandidate(f"words {word_from} to {word_to} are not all missed or wrong")
    return CandidateRange(at_ms=words[0].at_ms, phrase=" ".join(c.word for c in words))
