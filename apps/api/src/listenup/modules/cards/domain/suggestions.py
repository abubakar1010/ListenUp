"""Which marks the Card step offers first (FR-CA-4, PRD CA-5).

A suggestion is a nudge toward likely connected speech; the learner still chooses
every card. A mark is suggested when its phrase has several words, it is tagged
linking, reduction or weak form, or the learner marked the same phrase in an
earlier session. Suggested marks come first; each group keeps audio order.
"""

import re
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal

Reason = Literal["multi_word", "linking", "reduction", "weak_form", "earlier_session"]

_TAG_REASONS: tuple[Reason, ...] = ("linking", "reduction", "weak_form")
_EDGE_PUNCTUATION = re.compile(r"^[^\w]+|[^\w]+$")


@dataclass(frozen=True)
class Candidate:
    mark_id: uuid.UUID
    phrase: str
    tag: str | None


@dataclass(frozen=True)
class Suggestion:
    mark_id: uuid.UUID
    reasons: tuple[Reason, ...]

    @property
    def suggested(self) -> bool:
        return bool(self.reasons)


def normalize(phrase: str) -> str:
    """The phrase compared across sessions: lower case, one space, no edge punctuation.

    A curly apostrophe counts as a straight one, as in analytics' mark patterns.
    """
    folded = phrase.lower().replace("\u2019", "'")
    words = (_EDGE_PUNCTUATION.sub("", word) for word in folded.split())
    return " ".join(word for word in words if word)


def rank(candidates: Sequence[Candidate], earlier: Collection[str]) -> list[Suggestion]:
    """The candidates in display order, each with why it is suggested.

    `candidates` arrive in audio order and `earlier` holds `normalize`d phrases the
    learner marked in other sessions.
    """
    ranked = [_suggestion(candidate, earlier) for candidate in candidates]
    return sorted(ranked, key=lambda suggestion: not suggestion.suggested)


def _suggestion(candidate: Candidate, earlier: Collection[str]) -> Suggestion:
    phrase = normalize(candidate.phrase)
    reasons: list[Reason] = []
    if len(phrase.split()) > 1:
        reasons.append("multi_word")
    for tag in _TAG_REASONS:
        if candidate.tag == tag:
            reasons.append(tag)
    if phrase and phrase in earlier:
        reasons.append("earlier_session")
    return Suggestion(candidate.mark_id, tuple(reasons))
