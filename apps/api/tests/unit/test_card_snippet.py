"""Snippet windows contain the entire phrase (FR-CA-2)."""

import pytest

from listenup.modules.cards.domain.snippet import snippet_window


@pytest.mark.parametrize(
    "start,end,duration,expected",
    [
        (11000, 12500, 60000, (10250, 13250)),
        (0, 500, 60000, (0, 3000)),
        (59000, 60000, 60000, (57000, 60000)),
        (10000, 15000, 60000, (9500, 15500)),
        (10000, 16000, 60000, (10000, 16000)),
    ],
)
def test_window_contains_phrase(start, end, duration, expected):
    assert snippet_window(start, end, duration) == expected


@pytest.mark.parametrize(
    "start,end,duration", [(0, 6001, 60000), (-1, 1000, 60000), (1, 1, 60000), (0, 2000, 1000)]
)
def test_invalid_or_long_phrase(start, end, duration):
    with pytest.raises(ValueError):
        snippet_window(start, end, duration)
