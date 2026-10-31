"""Shadow delivery measures are pure code over assessment signals (#82, FR-SH-4/9).

Parameters are provisional and uncalibrated (ADR 0095); these tests pin the
arithmetic and the null rules, not speech accuracy, which #80/#22/#110 validate.
"""

import copy
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from listenup.modules.grading.domain.delivery import (
    PACKAGED_PARAMETERS,
    DeliveryParameters,
    Interval,
    Word,
    place_original,
    score_round,
)

# Round, explicit values so every expected score below is worked by hand.
PARAMETERS: dict[str, object] = {
    "version": "test",
    "provisional": True,
    "calibrated": False,
    "timing": {
        "min_matched_words": 2,
        "onset_full_credit_s": 0.5,
        "onset_zero_credit_s": 1.5,
        "rate_tolerance": 0.1,
        "rate_zero": 0.5,
        "break_s": 0.3,
        "weights": {"onsets": 60, "rate": 20, "phrasing": 20},
    },
    "fluency": {
        "hesitation_s": 0.25,
        "long_pause_s": 1.0,
        "event_weights": {"hesitation": 1, "long_pause": 2, "restart": 2},
        "zero_events_per_minute": 12,
    },
    "fillers": {
        "free_per_minute": 1,
        "zero_per_minute": 10,
        "count_validated": False,
    },
    "echo": {"leakage_threshold": 0.5},
}


def params(**changes: object) -> DeliveryParameters:
    data = copy.deepcopy(PARAMETERS)
    data.update(changes)
    return DeliveryParameters.from_mapping(data)


def words(onsets: list[float], *, length: float = 0.3, first: int = 0) -> list[Word]:
    return [Word(first + i, t, t + length) for i, t in enumerate(onsets)]


def original_of(n: int, step: float = 0.5) -> list[Word]:
    return words([i * step for i in range(n)])


def score(recorded: list[Word], *, n: int = 10, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs.setdefault("original", original_of(n))
    kwargs.setdefault("fillers", [])
    kwargs.setdefault("leakage", None)
    return score_round(
        params(),
        reference_word_count=n,
        recorded=recorded,
        **kwargs,  # type: ignore[arg-type]
    )


# --- Completeness ------------------------------------------------------------------


def test_completeness_is_the_share_of_reference_words_found():
    recorded = [w for w in original_of(10) if w.index not in {3, 7}]
    assert score(recorded).measures["completeness"].score == 80


def test_a_repeated_word_counts_once_and_out_of_range_indices_are_ignored():
    recorded = [*original_of(4), Word(1, 2.0, 2.2), Word(99, 2.5, 2.6)]
    assert score(recorded, n=8).measures["completeness"].score == 50


def test_completeness_rounds_halves_up():
    # 1 of 8 = 12.5 -> 13; 3 of 8 = 37.5 -> 38.
    assert score(original_of(1), n=8).measures["completeness"].score == 13
    assert score(original_of(3), n=8).measures["completeness"].score == 38


def test_no_matched_words_is_unobservable_not_zero():
    """Silence and failed alignment look alike, so neither proves omissions (ADR 0050)."""
    result = score([])
    for name in ("timing", "fluency", "fillers", "completeness"):
        assert result.measures[name].score is None
        assert result.measures[name].reason == "no_matched_words"
    assert result.overall is None


def test_an_empty_reference_is_reported_as_such():
    result = score(original_of(3), n=0)
    assert {m.reason for m in result.measures.values()} == {"no_reference_words"}
    assert result.overall is None


# --- Rhythm and timing -------------------------------------------------------------
# PARAMETERS: onsets within 0.5 s earn full credit, 1.5 s none (linear between); a
# rate ratio within 10 % earns full credit, 50 % none; weights onsets 60, rate 20,
# phrasing 20. original_of(10) has 0.2 s gaps, below the 0.3 s break, so phrasing
# is unobservable there and its weight drops out (onsets 60 : rate 20).


def test_on_time_speech_scores_higher_than_the_same_text_with_late_starts():
    """AT-17 (part), on constructed timings rather than a real sample (#80)."""
    on_time = words([0.2 + i * 0.5 for i in range(10)])
    # The second phrase starts a second late, and the learner stays behind.
    late = on_time[:5] + [Word(w.index, w.start + 1.0, w.end + 1.0) for w in on_time[5:]]
    on_time_score = score(on_time).measures["timing"].score
    late_score = score(late).measures["timing"].score
    # Words 5-9 lag 1.2 s: credit 0.3, so onsets (5 + 1.5) / 10 = 0.65. The rate ratio
    # is 5.5 / 4.5: credit 1 - (2/9 - 0.1) / 0.4 = 25/36.
    assert (on_time_score, late_score) == (100, 66)  # (60 * 0.65 + 20 * 25 / 36) / 80


def test_a_slower_speech_rate_loses_onset_and_rate_credit():
    # Lag grows 0.1 s a word; ratio 5.4 / 4.5 = 1.2 -> rate credit 0.75.
    # Onsets: six words within 0.5 s, then 0.9, 0.8, 0.7, 0.6 -> mean 0.9.
    result = score(words([i * 0.6 for i in range(10)])).measures["timing"]
    assert result.score == 86  # (60 * 0.9 + 20 * 0.75) / 80 = 86.25
    assert result.details["rate_ratio"] == pytest.approx(1.2)


def test_phrasing_credits_pausing_where_the_original_breaks():
    # A 0.7 s break after word 4 in the original.
    original = words([0, 0.5, 1.0, 1.5, 2.0, 3.0, 3.5, 4.0, 4.5, 5.0])
    kept = score(original, original=original).measures["timing"]
    # Run straight through: words 5-9 are 0.5 s early (full credit), rate ratio 0.9.
    dropped = score(original_of(10), original=original).measures["timing"]
    assert (kept.score, dropped.score) == (100, 80)
    assert (dropped.details["breaks"], dropped.details["breaks_kept"]) == (1, 0)


def test_timing_needs_two_matched_words():
    result = score(original_of(1)).measures["timing"]
    assert (result.score, result.reason) == (None, "too_few_matched_words")
    assert score(original_of(2)).measures["timing"].score == 100


def test_timing_needs_the_original_timing_of_matched_words():
    """Words the original's alignment could not place are unknown, not late."""
    result = score(original_of(10), original=original_of(1)).measures["timing"]
    assert (result.score, result.reason) == (None, "too_few_matched_words")


def test_a_restart_times_the_restarted_words_at_their_final_attempt():
    # The learner says 0 1 2, restarts at 1 and 2 a second later, then goes on late.
    # The restart replaces the first try, so words 1-9 all lag 1.0 s (credit 0.5)
    # and word 0 is on time: onsets (1 + 9 * 0.5) / 10 = 0.55. Rate 5.5 / 4.5: 25/36.
    recorded = [
        *original_of(3),
        Word(1, 1.5, 1.8),
        Word(2, 2.0, 2.3),
        *words([2.5 + i * 0.5 for i in range(7)], first=3),
    ]
    result = score(recorded).measures["timing"]
    assert result.details["matched"] == 10
    assert result.details["mean_lag_s"] == pytest.approx(0.9)
    assert result.score == 59  # (60 * 0.55 + 20 * 25 / 36) / 80 = 58.61


def test_timing_rounds_halves_up_despite_float_error():
    original = [Word(0, 0.0, 0.3), Word(1, 0.5, 0.8)]  # a 0.2 s gap: no break
    # Lags 0.4 and 0.6 s: onsets (1 + 0.9) / 2 = 0.95. Ratio 0.7 / 0.5 = 1.4: rate
    # credit (0.5 - 0.4) / 0.4 = 0.25. (60 * 0.95 + 20 * 0.25) / 80 = 0.775 exactly,
    # which binary floats put just below 77.5.
    recorded = [Word(0, 0.4, 0.5), Word(1, 1.1, 1.2)]
    assert score(recorded, n=2, original=original).measures["timing"].score == 78


def test_early_speech_is_off_time_too():
    early = words([i * 0.5 - 1.0 for i in range(10)])
    early = [Word(w.index, max(0.0, w.start), w.end) for w in early]
    assert score(early).measures["timing"].score < 100


# --- Fluency -----------------------------------------------------------------------
# Events are weighted (hesitation 1, long pause 2, restart 2) per minute of the
# original passage; 12 a minute scores 0. A pause counts by how much it exceeds the
# original's gap between the same words: 0.25 s a hesitation, 1.0 s a long pause.


def minute_original() -> list[Word]:
    """Ten words 6 s apart; the passage runs exactly one minute."""
    return [*words([i * 6.0 for i in range(9)], length=0.25), Word(9, 54.0, 60.0)]


def shifted(recorded: list[Word], after: int, by: float) -> list[Word]:
    return [Word(w.index, w.start + by, w.end + by) if w.index > after else w for w in recorded]


def fluency(recorded: list[Word], **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs.setdefault("original", minute_original())
    return score(recorded, **kwargs).measures["fluency"]


def test_speech_that_keeps_the_originals_pauses_is_fluent():
    result = fluency(minute_original())
    assert result.score == 100
    assert dict(result.details) == {
        "hesitations": 0,
        "long_pauses": 0,
        "restarts": 0,
        "judged_gaps": 9,
        "events_per_minute": 0.0,
    }


def test_a_hesitation_and_a_long_pause_cost_their_weights_per_minute():
    hesitated = fluency(shifted(minute_original(), after=4, by=0.5))
    assert (hesitated.score, hesitated.details["hesitations"]) == (92, 1)  # 1 - 1/12
    stalled = fluency(shifted(minute_original(), after=4, by=1.5))
    assert (stalled.score, stalled.details["long_pauses"]) == (83, 1)  # 1 - 2/12


def test_pause_thresholds_are_inclusive():
    assert fluency(shifted(minute_original(), after=4, by=0.25)).details["hesitations"] == 1
    assert fluency(shifted(minute_original(), after=4, by=0.125)).details["hesitations"] == 0
    assert fluency(shifted(minute_original(), after=4, by=1.0)).details["long_pauses"] == 1


def test_a_restart_is_counted_once():
    original = minute_original()
    restarted = [*original[:3], Word(1, 13.0, 13.25), *original[3:]]
    result = fluency(restarted)
    assert (result.score, result.details["restarts"]) == (83, 1)


def test_a_pause_beside_words_the_original_could_not_place_is_not_judged():
    original = [w for w in minute_original() if w.index not in {4, 5}]
    result = fluency(shifted(minute_original(), after=4, by=3.0), original=original)
    assert (result.score, result.details["long_pauses"]) == (100, 0)


def test_events_beyond_the_zero_rate_floor_at_zero():
    choppy = minute_original()
    for after in range(9):
        choppy = shifted(choppy, after=after, by=1.5)
    assert fluency(choppy).score == 0  # 9 long pauses = 18 a minute


def test_fluency_with_nothing_to_judge_is_unobservable_not_perfect():
    """ADR 0050: insufficient matched words never become perfect fluency."""
    one_word = fluency(minute_original()[:1])
    assert (one_word.score, one_word.reason) == (None, "no_judged_gaps")
    # Every gap touches a word the original's alignment could not place.
    every_other = [w for w in minute_original() if w.index % 2 == 0]
    unplaced = fluency(minute_original(), original=every_other)
    assert (unplaced.score, unplaced.reason) == (None, "no_judged_gaps")


def test_a_restart_alone_is_observed_disfluency():
    original = minute_original()
    result = fluency([original[1], Word(0, 7.0, 7.25)])
    assert (result.score, result.details["restarts"], result.details["judged_gaps"]) == (83, 1, 0)


def test_fluency_needs_the_originals_duration():
    result = score(original_of(3), original=[]).measures["fluency"]
    assert (result.score, result.reason) == (None, "no_original_timing")


# --- Filler words ------------------------------------------------------------------
# Up to 1 a minute of the original passage scores 100; 10 a minute scores 0.


def fillers_at(count: int) -> list[Interval]:
    return [Interval(1.0 + 6 * i, 1.4 + 6 * i) for i in range(count)]


def test_fillers_are_counted_and_rated_per_minute_as_an_estimate():
    result = score(minute_original(), original=minute_original(), fillers=fillers_at(4))
    measure = result.measures["fillers"]
    assert result.filler_count == 4
    # 4 a minute: 1 - (4 - 1) / (10 - 1) = 2/3.
    assert measure.score == 67
    assert dict(measure.details) == {"count": 4, "per_minute": 4.0, "estimate": True}


def test_filler_rate_boundaries():
    def filler_score(count: int) -> int | None:
        return (
            score(minute_original(), original=minute_original(), fillers=fillers_at(count))
            .measures["fillers"]
            .score
        )

    assert (filler_score(0), filler_score(1), filler_score(2)) == (100, 100, 89)
    assert (filler_score(9), filler_score(10), filler_score(11)) == (11, 0, 0)


def test_a_validated_filler_count_is_not_labelled_an_estimate():
    """B4 (#22) flips count_validated; until then every count is an estimate."""
    parameters = params(fillers={**PARAMETERS["fillers"], "count_validated": True})  # type: ignore[dict-item]
    result = score_round(
        parameters,
        reference_word_count=10,
        original=minute_original(),
        recorded=minute_original(),
        fillers=[],
        leakage=None,
    )
    assert result.measures["fillers"].details["estimate"] is False


def test_fillers_need_the_originals_duration():
    result = score(original_of(3), original=[], fillers=fillers_at(2))
    assert (result.measures["fillers"].score, result.measures["fillers"].reason) == (
        None,
        "no_original_timing",
    )
    assert result.filler_count == 2


# --- Overall -----------------------------------------------------------------------


def test_overall_is_the_equal_mean_of_the_measures_available():
    """FR-SH-9 over the four measures built so far; #83 adds the other two (ADR 0095)."""
    result = score(
        shifted(minute_original(), after=4, by=1.5),  # fluency 83
        n=12,  # completeness 10/12 = 83
        original=minute_original(),
        fillers=fillers_at(4),  # fillers 67
    )
    timing = result.measures["timing"].score
    assert timing is not None
    assert result.overall_basis == ("timing", "fluency", "fillers", "completeness")
    assert result.overall == math.floor((timing + 83 + 67 + 83) / 4 + 0.5)


def test_an_unobservable_measure_is_left_out_of_the_overall():
    # One word said: no timing (two words needed) and no gap to judge fluency on.
    result = score(original_of(1), n=4, original=minute_original())
    assert result.measures["timing"].score is None
    assert result.measures["fluency"].score is None
    assert result.overall_basis == ("fillers", "completeness")
    assert result.overall == 63  # (100 + 25) / 2 = 62.5, halves up


def test_accent_and_unbuilt_measures_never_enter_the_overall():
    assert set(score(original_of(10)).measures) == {"timing", "fluency", "fillers", "completeness"}


# --- Echo check (plumbing; the detector is #80's, ADR 0095) ------------------------


def test_no_leakage_signal_means_the_echo_check_did_not_run():
    result = score(original_of(10))
    assert (result.echo.status, result.echo.message) == ("unchecked", None)


@pytest.mark.parametrize(
    ("leakage", "status", "message"),
    [
        (0.0, "clear", None),
        (0.49, "clear", None),
        (0.5, "leak", "use_headphones"),
        (1.0, "leak", "use_headphones"),
    ],
)
def test_leakage_at_the_threshold_asks_for_headphones(leakage, status, message):
    result = score(original_of(10), leakage=leakage)
    assert (result.echo.status, result.echo.message) == (status, message)
    assert result.measures["completeness"].score == 100  # numbers are kept, flagged


@pytest.mark.parametrize("leakage", [-0.1, 1.1, float("nan")])
def test_an_invalid_leakage_signal_is_refused(leakage):
    with pytest.raises(ValueError, match="leakage"):
        score(original_of(10), leakage=leakage)


# --- Parameters --------------------------------------------------------------------


def test_the_packaged_parameters_are_provisional_and_uncalibrated():
    packaged = DeliveryParameters.load(PACKAGED_PARAMETERS)
    assert packaged.version
    assert (packaged.provisional, packaged.calibrated) == (True, False)
    assert packaged.raw["fillers"]["count_validated"] is False  # B4 (#22) not passed
    result = score_round(
        packaged,
        reference_word_count=10,
        original=minute_original(),
        recorded=minute_original(),
        fillers=[],
        leakage=None,
    )
    assert result.parameters_version == packaged.version
    assert result.overall is not None


def broken(path: str, value: object) -> dict[str, object]:
    data = copy.deepcopy(PARAMETERS)
    *parents, leaf = path.split(".")
    node = data
    for key in parents:
        node = node[key]  # type: ignore[assignment,index]
    if value is KeyError:
        del node[leaf]  # type: ignore[attr-defined]
    else:
        node[leaf] = value  # type: ignore[index]
    return data


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("version", ""),
        ("provisional", "yes"),
        ("calibrated", KeyError),
        ("timing.min_matched_words", 1),
        ("timing.min_matched_words", 2.5),
        ("timing.onset_zero_credit_s", 0.5),  # not above full credit
        ("timing.rate_tolerance", -0.1),
        ("timing.break_s", "0.3"),
        ("timing.weights", {"onsets": 60, "rate": 20}),
        ("timing.weights.rate", 0),
        ("fluency.long_pause_s", 0.25),  # not above a hesitation
        ("fluency.event_weights.restart", -1),
        ("fluency.zero_events_per_minute", 0),
        ("fillers.zero_per_minute", 1),  # not above the free rate
        ("fillers.count_validated", 1),
        ("echo.leakage_threshold", 0),
        ("echo.leakage_threshold", 1.5),
        ("echo", KeyError),
        ("timing.break_s", True),
        ("timing.break_s", float("inf")),
    ],
)
def test_invalid_parameters_are_refused(path, value):
    with pytest.raises(ValueError, match="delivery parameter"):
        DeliveryParameters.from_mapping(broken(path, value))


# --- Invariants (characterization: written after the measures above) ---------------

times = st.floats(min_value=0, max_value=120, allow_nan=False)


@st.composite
def timed_words(draw: st.DrawFn, max_index: int = 15) -> list[Word]:
    out = []
    for _ in range(draw(st.integers(0, 25))):
        start = draw(times)
        out.append(Word(draw(st.integers(0, max_index)), start, start + draw(st.floats(0, 2))))
    return out


@settings(max_examples=300, deadline=None)
@given(
    recorded=timed_words(),
    original=timed_words(),
    n=st.integers(0, 12),
    filler_count=st.integers(0, 30),
    leakage=st.none() | st.floats(0, 1),
)
def test_every_score_is_bounded_or_explicitly_unobservable(
    recorded, original, n, filler_count, leakage
):
    result = score(
        recorded, n=n, original=original, fillers=fillers_at(filler_count), leakage=leakage
    )
    for measure in result.measures.values():
        if measure.score is None:
            assert measure.reason
        else:
            assert type(measure.score) is int and 0 <= measure.score <= 100
    assert result.filler_count == filler_count
    basis = [result.measures[name].score for name in result.overall_basis]
    assert all(value is not None for value in basis)
    if basis:
        assert result.overall == math.floor(sum(basis) / len(basis) + 0.5)  # type: ignore[arg-type]
    else:
        assert result.overall is None


@settings(max_examples=200, deadline=None)
@given(lag=st.floats(0, 3), extra=st.floats(0, 3), n=st.integers(2, 12))
def test_starting_later_never_improves_timing(lag, extra, n):
    original = original_of(n)
    behind = [Word(w.index, w.start + lag, w.end + lag) for w in original]
    later = [Word(w.index, w.start + extra, w.end + extra) for w in behind]
    assert score(later, n=n).measures["timing"].score <= score(behind, n=n).measures["timing"].score  # type: ignore[operator]


@given(recorded=timed_words(max_index=9), extra=st.integers(0, 9))
def test_saying_another_word_never_lowers_completeness(recorded, extra):
    more = [*recorded, Word(extra, 200.0, 200.3)]
    before = score(recorded).measures["completeness"].score or 0
    assert score(more).measures["completeness"].score >= before  # type: ignore[operator]


# --- The recording clock (ADR 0096) -----------------------------------------------


def test_original_words_are_placed_on_the_recording_clock():
    """The browser reports when the original began in the recording (count-in or a
    later "Play now"); media times move by segment start and that offset."""
    placed = place_original(
        [(0, 60_000, 60_400), (1, 60_500, 61_000)],
        segment=(60_000, 90_000),
        playback_offset_ms=3_250,
    )
    assert placed == [Word(0, 3.25, 3.65), Word(1, 3.75, 4.25)]


def test_original_words_outside_the_segment_are_dropped():
    placed = place_original(
        [(0, 59_900, 60_200), (1, 60_200, 60_500), (2, 89_800, 90_100), (3, 89_500, 90_000)],
        segment=(60_000, 90_000),
        playback_offset_ms=0,
    )
    assert [w.index for w in placed] == [1, 3]


def test_an_unknown_playback_offset_is_refused():
    with pytest.raises(ValueError, match="playback offset"):
        place_original([(0, 60_000, 60_400)], segment=(60_000, 90_000), playback_offset_ms=-1)
