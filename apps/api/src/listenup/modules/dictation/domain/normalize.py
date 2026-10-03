"""Normalisation of reference and typed text into comparable tokens (Architecture 13.1).

Each source word (a reference transcript word, or a whitespace-separated typed word) is
turned into zero or more tokens:

- Unicode is folded (accents dropped, full-width forms narrowed) and text is lower-cased.
- Every apostrophe variant becomes ``'``; punctuation is dropped; hyphens, slashes and
  other separators split words ("well-known" is "well known").
- Contractions expand: "could've" is "could have", "don't" is "do not", "can't" and
  "cannot" are "can not". "'d" and "'s" after a pronoun stay as tokens that match either
  full form ("he'd" matches "he would" and "he had"; "it's" matches "it is" and "it has").
  Any other apostrophe is removed, so a possessive "dog's" is compared as "dogs".
- British spellings become American (``spelling_variants``).
- Numbers become one key whether written in digits or words (``numbers``); "%" adds
  "percent" and a leading "$", "£" or "€" adds "dollars", "pounds" or "euros".

Every token keeps the range of source words it came from, so a result can be mapped
back to the original words even when normalisation splits one word into several tokens
("could've") or merges several words into one ("nineteen ninety").
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from listenup.modules.dictation.domain.numbers import NUMBER_STARTS, digit_keys, parse_number_words
from listenup.modules.dictation.domain.spelling_variants import BRITISH_TO_AMERICAN


@dataclass(frozen=True, slots=True)
class Token:
    """One normalised unit of comparison.

    ``key`` is what is compared. ``surface`` is the normalised spelling without
    apostrophes, used to detect words typed joined or split ("alot", "every one").
    ``first_word`` and ``last_word`` are the source word indexes it came from, inclusive.
    """

    key: str
    surface: str
    first_word: int
    last_word: int
    is_number: bool = False


# A "'d" token matches "would" or "had"; an "'s" token matches "is" or "has".
CONTRACTION_ALIASES: Final = {
    "'d": frozenset({"would", "had"}),
    "'s": frozenset({"is", "has"}),
}

_APOSTROPHES: Final = str.maketrans(
    dict.fromkeys("\u2019\u2018\u02bc\u02bb\u0060\u00b4\u2032\uff07\u201b", "'")
)
_PIECE_RE: Final = re.compile(
    r"(?P<currency>[$£€]?)(?P<body>[^\W_]+(?:['.,][^\W_]+)*)(?P<percent>%?)"
)
_CURRENCIES: Final = {"$": "dollars", "£": "pounds", "€": "euros"}

_WHOLE_CONTRACTIONS: Final = {
    "won't": ("will", "not"),
    "can't": ("can", "not"),
    "cannot": ("can", "not"),
    "shan't": ("shall", "not"),
    "let's": ("let", "us"),
    "y'all": ("you", "all"),
    "ain't": ("aint",),
}
_SUFFIX_CONTRACTIONS: Final = (
    ("n't", "not"),
    ("'ve", "have"),
    ("'re", "are"),
    ("'ll", "will"),
    ("'m", "am"),
    ("'d", "'d"),
)
# Words whose "'s" is a contraction of "is" or "has" rather than a possessive.
_S_CONTRACTION_STEMS: Final = frozenset(
    {
        "he",
        "she",
        "it",
        "that",
        "this",
        "there",
        "here",
        "what",
        "where",
        "when",
        "why",
        "how",
        "who",
        "everyone",
        "everybody",
        "everything",
        "someone",
        "somebody",
        "something",
        "nobody",
        "nothing",
    }
)


def tokenize(words: Iterable[str]) -> list[Token]:
    """Normalise a sequence of source words into tokens that map back to word indexes."""
    tokens: list[Token] = []
    for index, word in enumerate(words):
        for key, is_number in _word_keys(word):
            tokens.append(Token(key, _surface(key), index, index, is_number))
    return _merge_words(tokens)


def tokenize_text(text: str) -> tuple[list[str], list[Token]]:
    """Split typed text on whitespace and tokenise it; returns the words and the tokens."""
    words = text.split()
    return words, tokenize(words)


def keys_equal(a: str, b: str) -> bool:
    """Whether two token keys mean the same word, counting contraction aliases."""
    if a == b:
        return True
    return b in CONTRACTION_ALIASES.get(a, ()) or a in CONTRACTION_ALIASES.get(b, ())


def _surface(key: str) -> str:
    return key.replace("'", "")


def _fold(text: str) -> str:
    # Apostrophes first: NFKD would split the acute accent into a space and a mark.
    decomposed = unicodedata.normalize("NFKD", text.translate(_APOSTROPHES))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _word_keys(word: str) -> list[tuple[str, bool]]:
    keys: list[tuple[str, bool]] = []
    for match in _PIECE_RE.finditer(_fold(word)):
        body = match["body"]
        numeric = digit_keys(body)
        if numeric is not None:
            keys.extend((key, key.startswith("#")) for key in numeric)
        else:
            for part in body.split(","):
                part_numeric = digit_keys(part)
                if part_numeric is not None:
                    keys.extend((key, key.startswith("#")) for key in part_numeric)
                else:
                    keys.extend((key, False) for key in _word_parts(part.replace(".", "")))
        if match["currency"]:
            keys.append((_CURRENCIES[match["currency"]], False))
        if match["percent"]:
            keys.append(("percent", False))
    return keys


def _word_parts(word: str) -> list[str]:
    return [BRITISH_TO_AMERICAN.get(part, part) for part in _expand(word) if part]


def _expand(word: str) -> list[str]:
    if word in _WHOLE_CONTRACTIONS:
        return list(_WHOLE_CONTRACTIONS[word])
    if "'" not in word:
        return [word]
    for suffix, expansion in _SUFFIX_CONTRACTIONS:
        if word.endswith(suffix) and len(word) > len(suffix):
            return [*_expand(word[: -len(suffix)]), expansion]
    if word.endswith("'s") and word[:-2] in _S_CONTRACTION_STEMS:
        return [word[:-2], "'s"]
    return [word.replace("'", "")]


def _merge_words(tokens: Sequence[Token]) -> list[Token]:
    """Join tokens that one meaning spans: number words, and "per cent"."""
    keys = [token.key if not token.is_number else "" for token in tokens]
    merged: list[Token] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not token.is_number and token.key in NUMBER_STARTS:
            parsed = parse_number_words(keys, i)
            if parsed is not None:
                key, used = parsed
                span = tokens[i : i + used]
                surface = "".join(t.surface for t in span)
                merged.append(Token(key, surface, span[0].first_word, span[-1].last_word, True))
                i += used
                continue
        if token.key == "per" and i + 1 < len(tokens) and tokens[i + 1].key == "cent":
            merged.append(Token("percent", "percent", token.first_word, tokens[i + 1].last_word))
            i += 2
            continue
        merged.append(token)
        i += 1
    return merged
