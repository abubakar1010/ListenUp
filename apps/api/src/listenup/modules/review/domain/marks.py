"""The pure rules of a mark (#58, FR-TR-2, ADR 0047).

A mark covers the passage words `word_from` to `word_to` (inclusive, indices in the
passage word sequence) and keeps the audio time of its first word, so the mark list
(#60), Card and Shadow can play it back. The server derives the time and the phrase
from the passage words; the browser sends only the range.
"""

from collections.abc import Sequence
from dataclasses import dataclass

MAX_NOTE_LENGTH = 500  # practice.marks.note CHECK
MAX_MARK_WORDS = 20
"""A mark is a word or a phrase, never a paragraph: a longer range is refused."""


class MarkRuleError(ValueError):
    """A mark the rules refuse; the service maps each kind to a problem code."""


class MarkOutOfRange(MarkRuleError):
    pass


class MarkTooLong(MarkRuleError):
    pass


class NoteTooLong(MarkRuleError):
    pass


@dataclass(frozen=True)
class MarkPlace:
    at_ms: int
    phrase: str


def place_mark(
    word_from: int, word_to: int, words: Sequence[str], starts_ms: Sequence[int]
) -> MarkPlace:
    """Where the mark sits in the audio and the words it covers."""
    if not 0 <= word_from <= word_to < len(words):
        raise MarkOutOfRange(f"words {word_from} to {word_to} are not in the passage")
    if word_to - word_from + 1 > MAX_MARK_WORDS:
        raise MarkTooLong(f"a mark covers at most {MAX_MARK_WORDS} words")
    phrase = " ".join(word for word in words[word_from : word_to + 1] if word)
    return MarkPlace(at_ms=starts_ms[word_from], phrase=phrase)


def clean_note(note: str | None) -> str | None:
    """The note as stored: trimmed, and None when nothing is left."""
    if note is None or not note.strip():
        return None
    note = note.strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise NoteTooLong(f"a note holds at most {MAX_NOTE_LENGTH} characters")
    return note
