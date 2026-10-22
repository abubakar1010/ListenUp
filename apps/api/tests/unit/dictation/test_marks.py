"""Which diff words a Dictation mark may cover (#55, FR-DI-6).

Only wrong or missing words are mark candidates (ADR 0019): a mark added from the diff
covers one of them, or a run of them next to each other in the passage.
"""

import pytest

from listenup.modules.dictation.domain import (
    MarkCandidate,
    NotACandidate,
    WordStatus,
    candidate_range,
)

# Passage words 2, 3 and 4 were missed or wrong, then word 7; words 5 and 6 were right.
CANDIDATES = (
    MarkCandidate(2, "kind", WordStatus.MISSING, 2_000, 2_300),
    MarkCandidate(3, "of", WordStatus.MISSING, 2_300, 2_400),
    MarkCandidate(4, "gonna", WordStatus.WRONG, 2_400, 2_900),
    MarkCandidate(7, "there", WordStatus.WRONG, 4_000, 4_400),
)


def test_one_candidate_word_takes_its_audio_time_and_word():
    place = candidate_range(CANDIDATES, 7, 7)
    assert (place.at_ms, place.phrase) == (4_000, "there")


def test_a_run_of_candidates_starts_at_its_first_word():
    place = candidate_range(CANDIDATES, 2, 4)
    assert (place.at_ms, place.phrase) == (2_000, "kind of gonna")


def test_part_of_a_run_is_a_range_of_its_own():
    place = candidate_range(CANDIDATES, 3, 4)
    assert (place.at_ms, place.phrase) == (2_300, "of gonna")


@pytest.mark.parametrize(
    ("word_from", "word_to"),
    [
        (5, 5),  # a correct word
        (4, 7),  # a run with correct words inside it
        (1, 2),  # starts before the first candidate
        (7, 8),  # ends after the last one
        (4, 3),  # backwards
        (-1, 2),
    ],
)
def test_a_range_with_any_other_word_is_refused(word_from: int, word_to: int):
    with pytest.raises(NotACandidate):
        candidate_range(CANDIDATES, word_from, word_to)


def test_a_diff_without_candidates_refuses_every_range():
    with pytest.raises(NotACandidate):
        candidate_range((), 0, 0)
