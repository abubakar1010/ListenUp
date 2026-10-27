"""The pure rules of a mark (#58, FR-TR-2): where it sits and what it may hold."""

import pytest

from listenup.modules.review.domain import (
    MARK_TAGS,
    MAX_MARK_WORDS,
    MAX_NOTE_LENGTH,
    MarkOutOfRange,
    MarkTooLong,
    MarkWithoutWords,
    NoteTooLong,
    TagUnknown,
    check_tag,
    clean_note,
    place_mark,
)

WORDS = ["a", "lot", "of", "people.", ""]
STARTS = [11_000, 11_200, 11_400, 12_000, 13_000]


def test_a_mark_takes_the_audio_time_and_text_of_its_words():
    place = place_mark(1, 3, WORDS, STARTS)
    assert place.at_ms == 11_200
    assert place.phrase == "lot of people."


def test_a_single_word_mark():
    assert place_mark(0, 0, WORDS, STARTS).phrase == "a"


def test_removed_words_leave_no_gaps_in_the_phrase():
    assert place_mark(3, 4, WORDS, STARTS).phrase == "people."


def test_removed_words_alone_cannot_be_marked():
    # A correction can empty a word; there is nothing left to hear as written text.
    with pytest.raises(MarkWithoutWords):
        place_mark(4, 4, WORDS, STARTS)


@pytest.mark.parametrize(("word_from", "word_to"), [(-1, 0), (2, 1), (4, 5), (5, 5)])
def test_a_range_outside_the_passage_or_backwards_is_refused(word_from, word_to):
    with pytest.raises(MarkOutOfRange):
        place_mark(word_from, word_to, WORDS, STARTS)


def test_a_mark_is_a_word_or_a_phrase_not_a_paragraph():
    words = ["w"] * (MAX_MARK_WORDS + 1)
    starts = list(range(len(words)))
    assert place_mark(0, MAX_MARK_WORDS - 1, words, starts).at_ms == 0
    with pytest.raises(MarkTooLong):
        place_mark(0, MAX_MARK_WORDS, words, starts)


@pytest.mark.parametrize(
    ("note", "cleaned"), [(None, None), ("", None), ("  ", None), (" weak ", "weak")]
)
def test_a_note_is_trimmed_and_an_empty_note_is_no_note(note, cleaned):
    assert clean_note(note) == cleaned


def test_a_note_holds_at_most_500_characters():
    assert clean_note("x" * MAX_NOTE_LENGTH) == "x" * MAX_NOTE_LENGTH
    with pytest.raises(NoteTooLong):
        clean_note("x" * (MAX_NOTE_LENGTH + 1))


# -- tags (#61, FR-TR-4) -------------------------------------------------------------------


def test_the_four_tags_match_the_database_check():
    assert MARK_TAGS == ("linking", "reduction", "weak_form", "unknown_word")


@pytest.mark.parametrize("tag", ["linking", "reduction", "weak_form", "unknown_word", None])
def test_a_known_tag_or_no_tag_is_kept(tag):
    assert check_tag(tag) == tag


@pytest.mark.parametrize("tag", ["accent", "", "Linking", "weak form", " linking"])
def test_any_other_tag_is_refused(tag):
    with pytest.raises(TagUnknown):
        check_tag(tag)
