"""Property tests for Dictation scoring (issue #53 acceptance criteria, NFR-MNT-2)."""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from listenup.modules.dictation.domain import (
    DictationScore,
    ReferenceWord,
    WordStatus,
    score_dictation,
)

# Real words, including the ones normalisation rewrites: contractions, numbers in digits
# and words, British spellings and possessives.
TRICKY_WORDS = [
    "could've",
    "don't",
    "won't",
    "it's",
    "he'd",
    "I'm",
    "John's",
    "15",
    "fifteen",
    "1990",
    "1990s",
    "twenty",
    "five",
    "hundred",
    "and",
    "a",
    "first",
    "21st",
    "3.5",
    "colour",
    "color",
    "organise",
    "travelled",
    "the",
    "there",
    "their",
    "in",
    "on",
    "well-known",
    "OK",
]
plain_words = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=9)
words = st.one_of(st.sampled_from(TRICKY_WORDS), plain_words)
word_lists = st.lists(words, min_size=1, max_size=40)
punctuation = st.sampled_from(["", "", ".", ",", "!", "?", ";", ":", "...", '"', ")"])
whitespace = st.sampled_from([" ", "  ", "\n", "\t", " \n "])


def reference(texts: list[str]) -> tuple[ReferenceWord, ...]:
    return tuple(ReferenceWord(w, i * 400, i * 400 + 300) for i, w in enumerate(texts))


def verdicts(result: DictationScore) -> list[WordStatus]:
    return [word.status for word in result.words]


@given(word_lists)
def test_identical_text_scores_100(texts: list[str]) -> None:
    result = score_dictation(reference(texts), " ".join(texts))
    assert result.accuracy == Decimal("100.00")
    assert set(verdicts(result)) <= {WordStatus.CORRECT, WordStatus.NOT_SCORED}
    assert result.extras == ()
    assert result.mark_candidates == ()


@given(word_lists, st.sampled_from(["", "   ", "\n\t", "...", "!?"]))
def test_empty_input_scores_0_with_every_word_missing(texts: list[str], typed: str) -> None:
    result = score_dictation(reference(texts), typed)
    assert result.accuracy == Decimal("0.00")
    assert all(s is WordStatus.MISSING for s in verdicts(result) if s is not WordStatus.NOT_SCORED)
    assert [m.word_index for m in result.mark_candidates] == [
        w.index for w in result.words if w.status is WordStatus.MISSING
    ]


@given(word_lists, word_lists, st.data())
def test_stable_under_whitespace_case_and_punctuation(
    ref_texts: list[str], typed_texts: list[str], data: st.DataObject
) -> None:
    plain = score_dictation(reference(ref_texts), " ".join(typed_texts))
    noisy_words = [
        data.draw(punctuation)
        + (w.upper() if data.draw(st.booleans()) else w)
        + data.draw(punctuation)
        for w in typed_texts
    ]
    noisy_text = data.draw(whitespace).join(noisy_words) + data.draw(whitespace)
    noisy = score_dictation(reference(ref_texts), noisy_text)
    assert verdicts(noisy) == verdicts(plain)
    assert noisy.accuracy == plain.accuracy
    assert len(noisy.extras) == len(plain.extras)


@settings(max_examples=50)
@given(word_lists, word_lists)
def test_scoring_is_deterministic_and_consistent(
    ref_texts: list[str], typed_texts: list[str]
) -> None:
    ref = reference(ref_texts)
    typed = " ".join(typed_texts)
    result = score_dictation(ref, typed)
    assert result == score_dictation(ref, typed)

    assert [w.index for w in result.words] == list(range(len(ref)))
    assert (
        result.correct_count + result.slip_count + result.wrong_count + result.missing_count
        == result.scored_count
    )
    assert Decimal(0) <= result.accuracy <= Decimal(100)
    marked = [w.index for w in result.words if w.status in (WordStatus.WRONG, WordStatus.MISSING)]
    assert [m.word_index for m in result.mark_candidates] == marked
    for mark in result.mark_candidates:
        assert mark.at_ms == ref[mark.word_index].start_ms
    assert all(0 <= e.before_index <= len(ref) for e in result.extras)
