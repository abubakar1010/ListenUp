import pytest
from listenup.ai.providers.alignment_text import alignable_words as production_words

from listenup_spikes.align import alignable_words


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Café isn’t open", ["cafe", "isn't", "open"]),
        ("I can't say it's done", ["i", "can't", "say", "it's", "done"]),
        ("twenty-one 2009 $500 — 'really'!", ["twentyone", "really"]),
    ],
)
def test_benchmark_targets_match_production(text: str, expected: list[str]) -> None:
    assert alignable_words(text) == [w.tokens for w in production_words(text)] == expected
