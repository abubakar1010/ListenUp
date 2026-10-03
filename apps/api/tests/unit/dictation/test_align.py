"""Weighted edit-distance alignment for Dictation (ADR 0008, issue #53)."""

import pytest

from listenup.modules.dictation.domain import align as align_module
from listenup.modules.dictation.domain.align import (
    AlignOp,
    OpKind,
    align,
    is_spelling_slip,
    letter_distance,
)
from listenup.modules.dictation.domain.normalize import Token, tokenize_text


def tokens(text: str) -> list[Token]:
    return tokenize_text(text)[1]


def word(key: str) -> Token:
    return Token(key, key, 0, 0)


def kinds(ref: str, typed: str) -> list[str]:
    return [op.kind.value for op in align(tokens(ref), tokens(typed))]


@pytest.mark.parametrize(
    ("a", "b", "distance"),
    [
        ("", "", 0),
        ("cat", "cat", 0),
        ("cat", "", 3),
        ("cat", "cut", 1),
        ("the", "teh", 1),
        ("kitten", "sitting", 3),
        ("receive", "recieve", 1),
    ],
)
def test_letter_distance(a: str, b: str, distance: int) -> None:
    assert letter_distance(a, b) == distance
    assert letter_distance(b, a) == distance


@pytest.mark.parametrize(
    ("ref", "typed", "slip"),
    [
        ("brown", "brwn", True),
        ("receive", "recieve", True),
        ("necessary", "neccesary", True),
        ("there", "their", True),
        ("jumps", "jump", True),
        ("word", "ward", True),
        ("word", "wired", False),  # two edits on a four-letter word
        ("the", "teh", True),  # swapped letters
        ("dog", "dogg", True),  # doubled letter
        ("in", "on", False),  # short words that differ are different words
        ("he", "she", False),
        ("cat", "cut", False),
        ("elephant", "elegance", False),  # more than two edits
        ("same", "same", False),
    ],
)
def test_spelling_slip_rule(ref: str, typed: str, slip: bool) -> None:
    assert is_spelling_slip(word(ref), word(typed)) is slip


def test_numbers_and_contraction_tokens_are_never_slips() -> None:
    assert not is_spelling_slip(
        Token("#15", "fifteen", 0, 0, True), Token("#16", "sixteen", 0, 0, True)
    )
    assert not is_spelling_slip(word("'s"), word("'d"))


@pytest.mark.parametrize(
    ("ref", "typed", "expected"),
    [
        ("the cat sat", "the cat sat", ["match", "match", "match"]),
        ("the cat sat", "", ["missing", "missing", "missing"]),
        ("", "the cat", ["extra", "extra"]),
        ("the cat sat", "the sat", ["match", "missing", "match"]),
        ("the cat sat", "the big cat sat", ["match", "extra", "match", "match"]),
        ("the cat sat", "the dog sat", ["match", "wrong", "match"]),
        ("the brown cat", "the brwn cat", ["match", "slip", "match"]),
        ("he would go", "he'd go", ["match", "match", "match"]),
        ("a lot", "alot", ["slip"]),
        ("everyone", "every one", ["slip"]),
    ],
)
def test_alignment_examples(ref: str, typed: str, expected: list[str]) -> None:
    assert kinds(ref, typed) == expected


def test_substitution_prefers_the_most_similar_word() -> None:
    ops = align(tokens("the big cat"), tokens("bog cat"))
    assert ops == [
        AlignOp(OpKind.MISSING, (0,), ()),
        AlignOp(OpKind.WRONG, (1,), (0,)),
        AlignOp(OpKind.MATCH, (2,), (1,)),
    ]


def test_repeated_words_tie_break_is_stable() -> None:
    ops = align(tokens("the the the"), tokens("the the"))
    assert [op.kind for op in ops] == [OpKind.MATCH, OpKind.MATCH, OpKind.MISSING]
    assert ops == align(tokens("the the the"), tokens("the the"))


def test_every_token_appears_once_in_order() -> None:
    ref = tokens("one fish two fish red fish blue fish and some more fish")
    typed = tokens("one fsh too fish read fish fish blue and and more fishes")
    ops = align(ref, typed)
    assert [i for op in ops for i in op.ref] == list(range(len(ref)))
    assert [j for op in ops for j in op.typed] == list(range(len(typed)))


def test_large_gaps_use_anchors_and_keep_every_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(align_module, "MAX_TABLE_CELLS", 4)
    ref = tokens("alpha beta gamma delta epsilon zeta eta theta iota kappa")
    typed = tokens("alpha betta gamma x delta epsilon zeta y theta iota kapa")
    ops = align(ref, typed)
    assert [i for op in ops for i in op.ref] == list(range(len(ref)))
    assert [j for op in ops for j in op.typed] == list(range(len(typed)))
    assert sum(op.kind is OpKind.MATCH for op in ops) == 7


def test_large_gap_without_unique_anchors_uses_common_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(align_module, "MAX_TABLE_CELLS", 1)
    ops = align(tokens("a b a b a b c"), tokens("x a b a b y"))
    assert [i for op in ops for i in op.ref] == list(range(7))
    assert [j for op in ops for j in op.typed] == list(range(6))
    assert sum(op.kind is OpKind.MATCH for op in ops) == 4


def test_large_gap_with_nothing_in_common_is_paired_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(align_module, "MAX_TABLE_CELLS", 1)
    ops = align(tokens("one two three"), tokens("cat dog"))
    assert [op.kind for op in ops] == [OpKind.WRONG, OpKind.WRONG, OpKind.MISSING]
