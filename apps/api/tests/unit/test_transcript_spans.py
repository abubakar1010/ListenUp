"""Passage-only cache arithmetic (System Design 5.1, issue #45)."""

import pytest

from listenup.modules.transcript.domain.spans import missing_spans, padded_span


@pytest.mark.parametrize(
    ("start", "end", "duration", "expected"),
    [
        (10000, 190000, 300000, (5000, 195000)),
        (0, 30000, 30000, (0, 30000)),
        (2000, 32000, 34000, (0, 34000)),
    ],
)
def test_padding_clamped(start, end, duration, expected):
    assert padded_span(start, end, duration) == expected


@pytest.mark.parametrize(
    ("cached", "expected"),
    [
        ([], [(5000, 195000)]),
        ([(0, 200000)], []),
        ([(0, 50000), (100000, 120000)], [(50000, 100000), (120000, 195000)]),
        ([(100000, 200000), (0, 100000)], []),
        ([(0, 5000), (195000, 200000)], [(5000, 195000)]),
    ],
)
def test_overlap_processes_only_gaps(cached, expected):
    assert missing_spans((5000, 195000), cached) == expected


def test_invalid_passage_rejected():
    with pytest.raises(ValueError):
        padded_span(100, 40000, 30000)
