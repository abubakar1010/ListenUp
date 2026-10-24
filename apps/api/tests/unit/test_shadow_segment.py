import pytest
from hypothesis import given
from hypothesis import strategies as st

from listenup.modules.shadow.domain.segment import propose, validate


def test_proposal_covers_90_to_150_second_cluster():
    start, end, count = propose(0, 240_000, [10_000, 90_000, 110_000, 140_000, 150_000])
    assert start <= 90_000 and end > 150_000
    assert count == 4
    assert 60_000 <= end - start <= 90_000


@pytest.mark.parametrize("duration", [30_000, 45_000, 60_000])
def test_short_passage_is_whole(duration):
    assert propose(10_000, 10_000 + duration, []) == (10_000, 10_000 + duration, 0)
    validate(10_000, 10_000 + duration, 10_000, 10_000 + duration)


@pytest.mark.parametrize("start,end", [(0, 44_999), (1, 45_000), (0, 60_000)])
def test_45_second_passage_allows_only_whole_passage(start, end):
    with pytest.raises(ValueError):
        validate(0, 45_000, start, end)


@pytest.mark.parametrize("start,end", [(-1, 60_000), (0, 59_999), (0, 90_001), (180_000, 240_001)])
def test_invalid_segment_refused(start, end):
    with pytest.raises(ValueError):
        validate(0, 240_000, start, end)


def test_no_marks_and_ties_choose_earliest_window():
    assert propose(20_000, 200_000, []) == (20_000, 110_000, 0)
    assert propose(0, 200_000, [10_000, 190_000]) == (0, 90_000, 1)


@given(st.lists(st.integers(0, 299_999), max_size=50))
def test_proposal_maximizes_half_open_mark_count(marks):
    start, end, count = propose(0, 300_000, marks)
    validate(0, 300_000, start, end)
    assert count == sum(start <= m < end for m in marks)
    for candidate in [0, 210_000, *[min(210_000, m) for m in marks]]:
        assert count >= sum(candidate <= m < candidate + 90_000 for m in marks)


def test_tied_maximum_uses_earliest_possible_start():
    assert propose(0, 240_000, [120_000, 150_000]) == (60_001, 150_001, 2)
