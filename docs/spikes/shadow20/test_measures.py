import numpy as np
import pytest
from measures import echo, filler_count, gop, matched_indices, relative, timing


def test_gop_competes_with_other_phones_not_ctc_blank():
    lp = np.log([[0.9, 0.06, 0.03, 0.01], [0.9, 0.02, 0.06, 0.02]])
    assert gop(lp, 1, [1, 2, 3]) == pytest.approx((np.log(2) + np.log(1 / 3)) / 2)
    assert relative(-2, -1) < relative(-1, -1)


def test_alignment_does_not_count_forced_missing_words():
    assert matched_indices(
        ["we", "can", "go", "home", "now"], ["we", "go", "um", "home"]
    ) == [(0, 0), (2, 1), (3, 3)]
    assert matched_indices(["go", "go"], ["go"]) == [(0, 0)]
    assert matched_indices(["go"], []) == []


def test_late_start_penalized_but_small_shadow_lag_allowed():
    o = np.array([0.2, 0.6, 1.0, 1.4])
    assert timing(o, o + 0.15) == pytest.approx(100)
    assert timing(o, o + 1.2) < timing(o, o + 0.15)
    assert timing(o, o * 1.5) < 100
    assert timing([], []) == 0


def test_echo_detects_shifted_waveform_without_flagging_other_voice():
    rng = np.random.default_rng(20)
    x = rng.normal(size=16000)
    assert echo(x, np.r_[np.zeros(1600), x]) > 0.99
    assert echo(x, rng.normal(size=16000)) < 0.1
    assert echo(x, np.zeros(16000)) == 0
    assert echo([], []) == 0


def test_fillers_counts_phrases_and_not_substrings():
    assert filler_count("Um, umbrella, uh, you know, ER.") == 4
    assert filler_count("I like this") == 1  # deliberately lexical; reported limitation


def test_fluency_requires_observed_gaps_and_penalizes_excess_pause():
    from measures import fluency

    assert fluency([], []) is None
    assert fluency([0.1], [0.1]) == 100
    assert fluency([0.1], [0.9]) < 60
