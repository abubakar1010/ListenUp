"""Sentence-ending punctuation, independent of provider and cache chunk boundaries."""


def ends_sentence(word: str) -> bool:
    return word.rstrip("\"'\u201d\u2019)]}").endswith((".", "?", "!"))
