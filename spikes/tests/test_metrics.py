import pytest

from listenup_spikes.metrics import (
    FillerMark,
    count_fillers,
    filler_recall_precision,
    hypothesis_fillers,
    match_fillers,
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


def hes(start: float, text: str = "uh") -> FillerMark:
    return FillerMark(start, start + 0.2, "hesitation", text)


def dm(start: float, text: str = "like") -> FillerMark:
    return FillerMark(start, start + 0.2, "discourse", text)


def test_hypothesis_fillers_reads_whisper_words_with_their_times() -> None:
    words = [
        (" Um,", 0.0, 0.3),
        (" I", 0.3, 0.4),
        (" like", 0.4, 0.6),
        (" you", 0.6, 0.7),
        (" know,", 0.7, 0.9),
        (" hmm", 1.0, 1.2),
        (" er", 1.2, 1.3),
        (" Like.", 1.3, 1.5),
    ]
    assert hypothesis_fillers(words) == [
        FillerMark(0.0, 0.3, "hesitation", "um"),
        FillerMark(0.4, 0.6, "discourse", "like"),
        FillerMark(0.6, 0.9, "discourse", "you know"),
        FillerMark(1.2, 1.3, "hesitation", "er"),  # "hmm" is not a B4 filler: ignored
        FillerMark(1.3, 1.5, "discourse", "like"),
    ]


def test_match_fillers_counts_hits_misses_and_extras_per_kind() -> None:
    reference = [hes(1.0), hes(5.0), dm(3.0)]
    hypothesis = [hes(1.4, "um"), hes(2.0), dm(3.1), dm(8.0)]
    result = match_fillers(reference, hypothesis)
    # uh against um 0.4 s later: a hit, spellings are interchangeable within a kind.
    assert (result["hesitation"].hits, result["hesitation"].missed, result["hesitation"].extra) == (
        1,
        1,
        1,
    )
    assert (result["discourse"].hits, result["discourse"].missed, result["discourse"].extra) == (
        1,
        0,
        1,
    )
    assert (result["all"].hits, result["all"].missed, result["all"].extra) == (2, 1, 2)
    assert result["all"].recall == pytest.approx(2 / 3)
    assert result["all"].precision == pytest.approx(2 / 4)


def test_match_fillers_uses_each_hypothesis_once_and_only_near_its_mark() -> None:
    one = match_fillers([hes(1.0), hes(1.3)], [hes(1.1)])["hesitation"]
    assert (one.hits, one.missed, one.extra) == (1, 1, 0)
    # The tolerance is 0.5 s beyond each end of the mark: 1.7 s is just inside, 1.71 s is not.
    assert match_fillers([hes(1.0)], [hes(1.7)])["hesitation"].hits == 1
    assert match_fillers([hes(1.0)], [hes(1.71)])["hesitation"].hits == 0


def test_match_fillers_never_matches_across_kinds() -> None:
    result = match_fillers([hes(1.0)], [dm(1.0)])
    assert (result["hesitation"].missed, result["discourse"].extra) == (1, 1)


def test_match_fillers_reports_no_rate_without_any_fillers() -> None:
    result = match_fillers([], [])["discourse"]
    assert (result.recall, result.precision) == (None, None)


def test_match_fillers_pairs_as_many_as_possible() -> None:
    # The mark at 1.0 s could take either; taking the farther one would leave 2.1 s unmatched.
    result = match_fillers([hes(1.0), hes(2.1)], [hes(1.0), hes(1.6)])["hesitation"]
    assert (result.hits, result.missed, result.extra) == (2, 0, 0)
    # Nearest-first would give the 1.45 s filler to the first mark and strand the second
    # (review of #280): clustered hesitations must still all pair up.
    marks = [FillerMark(1.0, 1.1, "hesitation", "uh"), FillerMark(1.9, 2.0, "hesitation", "uh")]
    found = [FillerMark(0.55, 0.6, "hesitation", "uh"), FillerMark(1.45, 1.5, "hesitation", "um")]
    result = match_fillers(marks, found)["hesitation"]
    assert (result.hits, result.missed, result.extra) == (2, 0, 0)


def test_match_fillers_does_not_depend_on_the_order_fillers_are_listed() -> None:
    marks = [FillerMark(1.0, 1.1, "hesitation", "uh"), FillerMark(1.9, 2.0, "hesitation", "uh")]
    found = [FillerMark(1.45, 1.5, "hesitation", "um"), FillerMark(0.55, 0.6, "hesitation", "uh")]
    assert match_fillers(marks, found)["hesitation"].hits == 2
    assert match_fillers(marks[::-1], found)["hesitation"].hits == 2
