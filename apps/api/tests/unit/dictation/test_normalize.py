"""Normalisation of Dictation text (Architecture 13.1, issue #53)."""

import pytest

from listenup.modules.dictation.domain.normalize import Token, keys_equal, tokenize, tokenize_text
from listenup.modules.dictation.domain.numbers import parse_number_words
from listenup.modules.dictation.domain.spelling_variants import BRITISH_TO_AMERICAN


def keys(text: str) -> list[str]:
    return [token.key for token in tokenize_text(text)[1]]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello, World!", ["hello", "world"]),
        ("  spaced\tout\n words ", ["spaced", "out", "words"]),
        ('"Quoted" (aside) - dash -- em—dash', ["quoted", "aside", "dash", "em", "dash"]),
        ("well-known", ["well", "known"]),
        ("and/or", ["and", "or"]),
        ("Café naïve", ["cafe", "naive"]),
        ("".join(chr(ord(c) + 0xFEE0) for c in "FULL") + " width", ["full", "width"]),
        ("U.S. e.g.", ["us", "eg"]),
        ("...", []),
        ("", []),
    ],
)
def test_case_punctuation_and_separators(text: str, expected: list[str]) -> None:
    assert keys(text) == expected


APOSTROPHE_CODE_POINTS = (0x27, 0x2019, 0x2018, 0x2BC, 0x60, 0xB4, 0xFF07, 0x201B)


@pytest.mark.parametrize("variant", [f"don{chr(c)}t" for c in APOSTROPHE_CODE_POINTS])
def test_apostrophe_variants_are_unified(variant: str) -> None:
    assert keys(variant) == ["do", "not"]


@pytest.mark.parametrize(
    ("contracted", "expanded"),
    [
        ("could've", "could have"),
        ("couldn't", "could not"),
        ("wouldn't've", "would not have"),
        ("I'm", "I am"),
        ("we're", "we are"),
        ("they'll", "they will"),
        ("won't", "will not"),
        ("can't", "can not"),
        ("cannot", "can not"),
        ("shan't", "shall not"),
        ("let's", "let us"),
        ("y'all", "you all"),
    ],
)
def test_contraction_pairs_are_equal(contracted: str, expanded: str) -> None:
    assert keys(contracted) == keys(expanded)


@pytest.mark.parametrize(
    ("contracted", "full_forms"),
    [("he'd", ("he would", "he had")), ("it's", ("it is", "it has"))],
)
def test_ambiguous_contractions_match_either_full_form(
    contracted: str, full_forms: tuple[str, str]
) -> None:
    short = keys(contracted)
    for full in full_forms:
        long = keys(full)
        assert len(short) == len(long)
        assert all(keys_equal(a, b) for a, b in zip(short, long, strict=True))


def test_possessive_s_loses_its_apostrophe() -> None:
    assert keys("John's dog's") == ["johns", "dogs"]
    assert keys("dogs'") == ["dogs"]
    assert keys("o'clock") == ["oclock"]


@pytest.mark.parametrize(
    ("british", "american"),
    [
        ("colour", "color"),
        ("Colours", "colors"),
        ("favourite", "favorite"),
        ("centre", "center"),
        ("theatres", "theaters"),
        ("organise", "organize"),
        ("organisation", "organization"),
        ("recognised", "recognized"),
        ("analyse", "analyze"),
        ("travelled", "traveled"),
        ("travelling", "traveling"),
        ("cancelled", "canceled"),
        ("defence", "defense"),
        ("catalogue", "catalog"),
        ("grey", "gray"),
        ("programme", "program"),
        ("jewellery", "jewelry"),
        ("OK", "okay"),
    ],
)
def test_british_and_american_spellings_are_equal(british: str, american: str) -> None:
    assert keys(british) == keys(american)


def test_spelling_table_leaves_shared_words_alone() -> None:
    for word in ("advise", "promise", "surprise", "exercise", "emphasis", "travel", "color"):
        assert word not in BRITISH_TO_AMERICAN
    assert all(
        " " not in british and british != american
        for british, american in BRITISH_TO_AMERICAN.items()
    )


@pytest.mark.parametrize(
    ("digits", "words"),
    [
        ("15", "fifteen"),
        ("0", "zero"),
        ("21", "twenty-one"),
        ("21", "twenty one"),
        ("105", "one hundred and five"),
        ("105", "one hundred five"),
        ("100", "a hundred"),
        ("1,000", "a thousand"),
        ("2,500", "twenty-five hundred"),
        ("1,500", "one thousand five hundred"),
        ("1000000", "one million"),
        ("3.5", "three point five"),
        ("0.5", "zero point five"),
        ("1990", "nineteen ninety"),
        ("1905", "nineteen oh five"),
        ("2025", "twenty twenty-five"),
        ("2025", "two thousand and twenty-five"),
        ("1990s", "the nineteen nineties"),
        ("'90s", "nineties"),
        ("90's", "the nineties"),
        ("1st", "first"),
        ("2nd", "second"),
        ("21st", "twenty-first"),
        ("100th", "hundredth"),
        ("15%", "fifteen percent"),
        ("15%", "fifteen per cent"),
        ("$5", "five dollars"),
        ("3pm", "three pm"),
        ("3 p.m.", "three pm"),
        ("12:30", "twelve thirty"),
    ],
)
def test_numbers_as_digits_equal_numbers_as_words(digits: str, words: str) -> None:
    def without_article(text: str) -> list[str]:
        return [key for key in keys(text) if key != "the"]

    assert without_article(digits) == without_article(words)


def test_number_words_stop_where_the_number_ends() -> None:
    assert keys("twenty five people") == ["#25", "people"]
    assert keys("one hundred and fifty and a half") == ["#150", "and", "a", "half"]
    assert keys("a cat") == ["a", "cat"]
    assert keys("hundreds of people") == ["hundreds", "of", "people"]
    assert keys("one second") == ["#1", "#2th"]


def test_parse_number_words_reports_words_used() -> None:
    assert parse_number_words(["nineteen", "ninety", "five", "dogs"], 0) == ("#1995", 3)
    assert parse_number_words(["the", "dog"], 0) is None
    assert parse_number_words(["one", "hundred", "and"], 0) == ("#100", 2)


def test_tokens_map_back_to_source_words_when_split_or_merged() -> None:
    tokens = tokenize(["I", "could've", "seen", "nineteen", "ninety", "1990s"])
    assert tokens == [
        Token("i", "i", 0, 0),
        Token("could", "could", 1, 1),
        Token("have", "have", 1, 1),
        Token("seen", "seen", 2, 2),
        Token("#1990", "nineteenninety", 3, 4, is_number=True),
        Token("#1990s", "#1990s", 5, 5, is_number=True),
    ]


def test_punctuation_only_word_gives_no_tokens() -> None:
    assert tokenize(["Hello", "—", "there"]) == [
        Token("hello", "hello", 0, 0),
        Token("there", "there", 2, 2),
    ]


def test_tokenize_text_returns_whitespace_words() -> None:
    words, tokens = tokenize_text(" Could've  been\nworse. ")
    assert words == ["Could've", "been", "worse."]
    assert [t.first_word for t in tokens] == [0, 0, 1, 2]
