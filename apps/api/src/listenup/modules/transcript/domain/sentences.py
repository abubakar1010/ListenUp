"""Sentence-ending punctuation, independent of provider and cache chunk boundaries."""

_PERSON_TITLES = frozenset({"dr.", "mr.", "mrs.", "ms.", "prof.", "rev."})


def ends_sentence(word: str) -> bool:
    word = word.rstrip("\"'\u201d\u2019)]}")
    return word.casefold() not in _PERSON_TITLES and word.endswith((".", "?", "!"))
