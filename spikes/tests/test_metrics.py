import pytest

from listenup_spikes.metrics import (
    count_fillers,
    filler_recall_precision,
    mean_boundary_error_ms,
    normalize_words,
    percentile,
    word_error_rate,
)


def test_normalize_expands_contractions_and_curly_apostrophes() -> None:
    assert normalize_words("I could’ve gone, OK?") == ["i", "could", "have", "gone", "ok"]


def test_wer_counts_each_error_type() -> None:
    result = word_error_rate("the cat sat on the mat", "the cat sit on mat today")
    assert (result.substitutions, result.deletions, result.insertions) == (1, 1, 1)
    assert result.wer == pytest.approx(3 / 6)


def test_wer_is_zero_for_identical_text_after_normalization() -> None:
    assert word_error_rate("It's fine.", "it is fine").wer == 0


def test_count_fillers_includes_two_word_fillers() -> None:
    assert count_fillers("Um, I was, like, you know, uh going") == 4


def test_filler_recall_and_precision() -> None:
    rp = filler_recall_precision([4, 2], [3, 3])
    assert rp.recall == pytest.approx(5 / 6)
    assert rp.precision == pytest.approx(5 / 6)


def test_percentile_nearest_rank() -> None:
    values = list(range(1, 21))
    assert percentile(values, 50) == 10
    assert percentile(values, 95) == 19
    assert percentile(values, 100) == 20


def test_boundary_error_matches_words_in_order() -> None:
    predicted = [("hello", 0.10, 0.50), ("big", 0.55, 0.80), ("world", 0.90, 1.30)]
    labelled = [("hello", 0.12, 0.48), ("world", 0.90, 1.32)]
    assert mean_boundary_error_ms(predicted, labelled) == pytest.approx(15.0)
