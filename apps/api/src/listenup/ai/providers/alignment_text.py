"""Model-independent alignment text, shared with the B2 benchmark (ADR 0033).

Keep this module free of speech and application dependencies so the spike can use
exactly the production targets without installing the API or loading a model.
"""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class AlignableWord:
    index: int  # position in the reference text split on whitespace
    text: str  # the word as written in the reference
    tokens: str  # what the model aligns: lower-case a-z and apostrophes


def alignable_words(text: str) -> list[AlignableWord]:
    """Fold accents and strip punctuation without expanding contractions or splitting
    words. Words with no letters (numbers, symbols) are left out."""
    found = []
    for index, word in enumerate(text.split()):
        folded = unicodedata.normalize("NFKD", word.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'"))
        tokens = re.sub(r"[^a-z']", "", folded.lower()).strip("'")
        if tokens:
            found.append(AlignableWord(index=index, text=word, tokens=tokens))
    return found
