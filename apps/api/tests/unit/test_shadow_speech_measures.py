"""Pronunciation, articulation, accent, word labels and the overall round score (#83).

FR-SH-9, FR-SH-10, FR-SH-15, D3, D11. Parameters are provisional and uncalibrated
(ADR 0099); these tests pin the arithmetic and the null rules worked by hand, not
speech accuracy, which #80/#110 validate on real recordings.
"""

import copy

import pytest
from hypothesis import given
from hypothesis import strategies as st

from listenup.modules.grading.domain.delivery import (
    DeliveryParameters,
    Interval,
    Measure,
    Word,
    overall_score,
)
from listenup.modules.grading.domain.speech_measures import (
    PACKAGED_SPEECH_PARAMETERS,
    SCORED_MEASURES,
    Prosody,
    Sound,
    SpeechParameters,
    SpokenWord,
    accent,
    articulation,
    grade_round,
    hertz_to_cents,
    label_words,
    pronunciation,
    word_pitch,
)

# Round, explicit values so every expected score below is worked by hand.
SPEECH: dict[str, object] = {
    "version": "test",
    "provisional": True,
    "calibrated": False,
    "sounds": {
        "dropped_below": 0.2,
        "unclear_below": 0.5,
        "merged_max_s": 0.03,
        "linking_gap_s": 0.05,
    },
    "labels": {"good_from": 0.7},
    "articulation": {
        "position_weights": {"initial": 1, "medial": 1, "final": 2},
        "linking_weight": 2,
        "issue_weights": {"dropped": 1.0, "merged": 1.0, "unclear": 0.5},
    },
    "accent": {
        "experimental": True,
        "weights": {"vowels": 40, "stress": 30, "pitch": 30},
        "min_words": 3,
        "zero_r": 0.0,
        "full_r": 0.8,
        "vowel_labels": ["a", "e", "i", "o", "u"],
        "vowel_full_gap": 0.1,
        "vowel_zero_gap": 0.5,
    },
    "overall": {
        "weights": {
            "timing": 1,
            "pronunciation": 1,
            "articulation": 1,
            "fluency": 1,
            "fillers": 1,
            "completeness": 1,
        }
    },
}


def speech(**changes: object) -> SpeechParameters:
    data = copy.deepcopy(SPEECH)
    data.update(changes)
    return SpeechParameters.from_mapping(data)


def sound(label: str, start: float, score: float, length: float = 0.1) -> Sound:
    return Sound(label, start, start + length, score)


def word(index: int, sounds: list[Sound], accuracy: float = 0.5) -> SpokenWord:
    return SpokenWord(index, sounds[0].start, sounds[-1].end, accuracy, tuple(sounds))


# --- Pronunciation -----------------------------------------------------------------


def test_pronunciation_averages_sound_scores_per_word_then_over_words():
    """GOP per sound, averaged per word (0.8 and 0.6), then over the words said."""
    spoken = [
        word(0, [sound("t", 0.0, 0.9), sound("e", 0.1, 0.7)]),
        word(1, [sound("k", 0.5, 0.6)]),
    ]
    result = pronunciation(speech(), spoken, reference_word_count=3)
    assert result.score == 70  # the missed third word is completeness, not pronunciation
    assert result.details["judged_words"] == 2


def test_a_word_without_sound_detail_uses_its_word_accuracy():
    spoken = [
        word(0, [sound("t", 0.0, 0.9)]),
        SpokenWord(1, 0.5, 0.9, 0.6, ()),
    ]
    result = pronunciation(speech(), spoken, reference_word_count=2)
    assert result.score == 75
    assert result.details["word_accuracy_only"] == 1


def test_pronunciation_with_no_word_said_is_unobservable_not_zero():
    result = pronunciation(speech(), [], reference_word_count=4)
    assert (result.score, result.reason) == (None, "no_matched_words")


def test_a_restarted_word_is_judged_on_its_final_attempt():
    spoken = [
        word(0, [sound("t", 0.0, 0.2)]),
        word(0, [sound("t", 1.0, 0.9)]),
    ]
    assert pronunciation(speech(), spoken, reference_word_count=1).score == 90


def test_indices_outside_the_segment_are_ignored():
    spoken = [word(0, [sound("t", 0.0, 0.8)]), word(5, [sound("k", 1.0, 0.1)])]
    assert pronunciation(speech(), spoken, reference_word_count=2).score == 80


# --- Articulation ------------------------------------------------------------------


def unlinked() -> list[SpokenWord]:
    """Word 0 drops its ending; word 1, 0.7 s later, starts unclearly."""
    return [
        word(0, [sound("a", 0.0, 0.9), sound("b", 0.1, 0.9), sound("c", 0.2, 0.1)]),
        word(1, [sound("d", 1.0, 0.4), sound("e", 1.1, 0.9)]),
    ]


def test_articulation_weighs_dropped_and_unclear_sounds_and_word_endings():
    # Weights 1+1+2 (final) + 1+2 (final) = 7; penalties 2x1 (dropped ending)
    # + 1x0.5 (unclear start) = 2.5; 1 - 2.5/7 = 0.6428... -> 64.
    result = articulation(speech(), unlinked(), reference_word_count=2)
    assert result.score == 64
    assert result.details == {"sounds": 5, "dropped": 1, "merged": 0, "unclear": 1, "linked": 0}


def test_sounds_at_a_linking_boundary_weigh_more():
    linked = unlinked()
    linked[1] = word(1, [sound("d", 0.32, 0.4), sound("e", 0.42, 0.9)])
    # The 0.02 s gap links the words: word 1's start weighs 2. 8 in all; 2 + 1 = 3
    # penalised; 1 - 3/8 = 0.625, half up -> 63.
    result = articulation(speech(), linked, reference_word_count=2)
    assert result.score == 63
    assert result.details["linked"] == 1


def test_a_gap_of_linking_gap_s_or_more_does_not_link():
    spaced = unlinked()
    spaced[1] = word(1, [sound("d", 0.35, 0.4), sound("e", 0.45, 0.9)])
    assert articulation(speech(), spaced, reference_word_count=2).score == 64


def test_a_very_short_unclear_sound_is_merged_but_a_short_clear_one_is_not():
    spoken = [
        word(
            0,
            [sound("a", 0.0, 0.9), sound("b", 0.1, 0.4, length=0.02), sound("c", 0.12, 0.9)],
        ),
        word(1, [sound("d", 1.0, 0.9, length=0.02), sound("e", 1.02, 0.9)]),
    ]
    # Weights 1+1+2 + 1+2 = 7; one merged medial sound: 1 - 1/7 = 0.857... -> 86.
    result = articulation(speech(), spoken, reference_word_count=2)
    assert result.score == 86
    assert (result.details["merged"], result.details["unclear"]) == (1, 0)


@pytest.mark.parametrize("start", [0.30, 0.33, 1.27])
def test_an_unclear_sound_of_exactly_merged_max_s_is_unclear_wherever_it_sits(start):
    """30 ms in decimals is never merged, whatever binary error the subtraction has
    (0.36 - 0.33 is 0.0299...): the boundary is rounded as the linking gap is."""
    unclear = Sound("t", start, round(start + 0.03, 2), 0.4)
    labels = label_words(speech(), ["cat"], [word(0, [unclear])])
    assert [reason.issue for reason in labels[0].reasons] == ["unclear"]


@pytest.mark.parametrize(
    ("score", "issue"), [(0.19, "dropped"), (0.2, "unclear"), (0.49, "unclear"), (0.5, None)]
)
def test_sound_issue_boundaries(score, issue):
    labels = label_words(speech(), ["cat"], [word(0, [sound("t", 0.0, score)])])
    issues = [reason.issue for reason in labels[0].reasons]
    assert issues == ([issue] if issue else ["inaccurate"])


def test_articulation_without_sound_detail_is_unobservable_not_perfect():
    spoken = [SpokenWord(0, 0.0, 0.4, 0.9, ())]
    result = articulation(speech(), spoken, reference_word_count=1)
    assert (result.score, result.reason) == (None, "no_sound_evidence")


def test_articulation_with_no_word_said_is_unobservable():
    result = articulation(speech(), [], reference_word_count=3)
    assert (result.score, result.reason) == (None, "no_matched_words")


# --- Word labels (FR-SH-10) --------------------------------------------------------


def test_every_segment_word_is_labelled_good_needs_work_or_missed():
    spoken = [
        word(0, [sound("t", 0.0, 0.9), sound("e", 0.1, 0.7)]),
        word(1, [sound("k", 0.5, 0.6)]),
    ]
    labels = label_words(speech(), ["the", "cat", "sat"], spoken)
    assert [(w.index, w.text, w.label, w.score) for w in labels] == [
        (0, "the", "good", 80),
        (1, "cat", "needs_work", 60),
        (2, "sat", "missed", None),
    ]
    assert labels[0].reasons == ()
    assert labels[2].reasons == ()


def test_needs_work_carries_sound_level_reasons_with_position_and_linking():
    spoken = [
        word(0, [sound("a", 0.0, 0.9), sound("b", 0.1, 0.9), sound("c", 0.2, 0.1)]),
        word(1, [sound("d", 0.32, 0.4), sound("e", 0.42, 0.9)]),
    ]
    labels = label_words(speech(), ["abc", "de"], spoken)
    assert [w.label for w in labels] == ["needs_work", "needs_work"]
    first, second = ([(r.sound, r.position, r.issue, r.linking) for r in w.reasons] for w in labels)
    assert first == [("c", "final", "dropped", True)]
    assert second == [("d", "initial", "unclear", True)]


def test_a_good_average_with_one_unclear_sound_still_needs_work():
    spoken = [word(0, [sound("a", 0.0, 1.0), sound("b", 0.1, 1.0), sound("c", 0.2, 0.45)])]
    (label,) = label_words(speech(), ["abc"], spoken)
    assert label.score == 82
    assert label.label == "needs_work"
    assert [r.issue for r in label.reasons] == ["unclear"]


def test_a_word_at_good_from_is_good():
    (label,) = label_words(speech(), ["at"], [word(0, [sound("a", 0.0, 0.7)])])
    assert (label.label, label.score) == ("good", 70)


def test_a_word_without_sound_detail_is_labelled_from_its_accuracy():
    (low,) = label_words(speech(), ["at"], [SpokenWord(0, 0.0, 0.3, 0.6, ())])
    (high,) = label_words(speech(), ["at"], [SpokenWord(0, 0.0, 0.3, 0.9, ())])
    assert (low.label, low.basis, low.reasons) == ("needs_work", "word", ())
    assert (high.label, high.basis) == ("good", "word")


def test_a_single_sound_word_is_its_own_ending():
    (label,) = label_words(speech(), ["a"], [word(0, [sound("a", 0.0, 0.1)])])
    assert [(r.position, r.issue) for r in label.reasons] == [("final", "dropped")]


def test_nothing_said_labels_every_word_missed():
    labels = label_words(speech(), ["one", "two"], [])
    assert [w.label for w in labels] == ["missed", "missed"]


# --- Accent (FR-SH-15): guidance compared with this speaker ------------------------


def prosody(durations: list[float], pitches: list[float | None]) -> dict[int, Prosody]:
    return {i: Prosody(d, p) for i, (d, p) in enumerate(zip(durations, pitches, strict=True))}


ORIGINAL = prosody([0.2, 0.4, 0.3, 0.5], [6000, 6200, 6100, 6400])


def test_accent_follows_the_speakers_contour_not_their_voice_or_pace():
    """An octave higher and twice as slow, with the same shape, matches this speaker."""
    learner = prosody([0.4, 0.8, 0.6, 1.0], [7200, 7400, 7300, 7600])
    result = accent(speech(), learner, ORIGINAL)
    assert result.score == 100
    assert result.details["experimental"] is True
    assert result.details["compared_with"] == "this_speaker"
    assert result.details["components"] == {"vowels": None, "stress": 1.0, "pitch": 1.0}
    assert result.details["unobserved"] == {"vowels": "no_reference_sounds"}


def test_an_opposite_pitch_contour_earns_no_pitch_credit():
    # r = -82500 / 87500 = -0.94, at or below zero_r: 0. Stress still matches: 50.
    learner = prosody([0.2, 0.4, 0.3, 0.5], [7600, 7300, 7400, 7200])
    result = accent(speech(), learner, ORIGINAL)
    assert result.score == 50
    assert result.details["components"]["pitch"] == 0.0


def test_partial_contour_agreement_earns_linear_credit():
    # Pitch r = 0.5 -> 0.5 / 0.8 = 0.625; stress r = 1. (30 x 0.625 + 30) / 60 = 81.25.
    original = prosody([0.2, 0.3, 0.4], [6000, 6100, 6200])
    learner = prosody([0.2, 0.3, 0.4], [6000, 6200, 6100])
    result = accent(speech(), learner, original)
    assert result.score == 81
    assert result.details["components"]["pitch"] == pytest.approx(0.625)


def test_a_flat_learner_contour_against_a_varied_original_earns_no_pitch_credit():
    learner = prosody([0.2, 0.4, 0.3, 0.5], [7000, 7000, 7000, 7000])
    assert accent(speech(), learner, ORIGINAL).details["components"]["pitch"] == 0.0


def test_a_flat_original_contour_cannot_be_compared():
    original = prosody([0.2, 0.4, 0.3, 0.5], [6000, 6000, 6000, 6000])
    result = accent(speech(), ORIGINAL, original)
    assert result.details["components"]["pitch"] is None
    assert result.details["unobserved"]["pitch"] == "flat_original"
    assert result.score == 100  # stress alone, renormalized


def test_pitch_needs_min_words_voiced_in_both():
    learner = prosody([0.2, 0.4, 0.3, 0.5], [7200, None, 7300, None])
    result = accent(speech(), learner, ORIGINAL)
    assert result.details["unobserved"]["pitch"] == "too_few_voiced_words"


def test_accent_needs_min_words_said_by_both():
    learner = {0: Prosody(0.2, 6000), 1: Prosody(0.4, 6200), 9: Prosody(0.3, 6100)}
    result = accent(speech(), learner, ORIGINAL)
    assert (result.score, result.reason) == (None, "no_accent_evidence")
    assert result.details["unobserved"] == {
        "vowels": "no_reference_sounds",
        "stress": "too_few_words",
        "pitch": "too_few_voiced_words",
    }


def test_vowel_quality_compares_each_vowel_with_the_speakers_own():
    """Shortfall 0.3 on "a" earns (0.5 - 0.3) / 0.4 = 0.5; "e" at or above the
    speaker earns 1; consonants are not compared. (40 x 0.75 + 30 + 30) / 100 = 90."""
    spoken = [
        word(0, [sound("t", 0.0, 0.9), sound("a", 0.1, 0.5)]),
        word(1, [sound("e", 0.5, 0.9)]),
    ]
    reference = {
        0: (sound("t", 0.0, 0.2), sound("a", 0.1, 0.8)),
        1: (sound("e", 0.5, 0.7),),
    }
    learner = prosody([0.4, 0.8, 0.6, 1.0], [7200, 7400, 7300, 7600])
    result = accent(speech(), learner, ORIGINAL, spoken=spoken, reference_sounds=reference)
    assert result.details["components"]["vowels"] == pytest.approx(0.75)
    assert result.score == 90


def test_vowels_with_different_labels_are_not_compared():
    spoken = [word(0, [sound("a", 0.0, 0.1)])]
    reference = {0: (sound("o", 0.0, 0.9),)}
    result = accent(speech(), ORIGINAL, ORIGINAL, spoken=spoken, reference_sounds=reference)
    assert result.details["unobserved"]["vowels"] == "no_vowels_compared"


def test_word_pitch_is_the_median_of_voiced_points_inside_the_word():
    points = [(0.0, 100.0), (0.1, None), (0.2, 300.0), (0.3, 200.0), (0.4, 900.0)]
    assert word_pitch(points, 0.0, 0.4) == 200.0  # 0.4 is the next word's
    assert word_pitch(points, 0.1, 0.2) is None


def test_hertz_become_cents_and_unvoiced_stays_unvoiced():
    assert hertz_to_cents(440.0) == pytest.approx(1200 * 8.78135971, abs=1e-3)
    assert hertz_to_cents(None) is None


# --- Overall round score (FR-SH-9, D3, D11) ----------------------------------------

EQUAL = dict.fromkeys(SCORED_MEASURES, 1)


def measures(**scores: int | None) -> dict[str, Measure]:
    return {name: Measure(value) for name, value in scores.items()}


SIX = {
    "timing": 80,
    "pronunciation": 70,
    "articulation": 60,
    "fluency": 90,
    "fillers": 100,
    "completeness": 50,
}


def test_the_scored_measures_are_the_six_without_accent():
    assert set(SCORED_MEASURES) == set(SIX)
    assert "accent" not in SCORED_MEASURES


def test_overall_is_the_equal_mean_of_the_six_measures():
    assert overall_score(measures(**SIX), EQUAL) == (75, tuple(SCORED_MEASURES))


def test_overall_halves_round_up():
    # 453 / 6 = 75.5 -> 76.
    assert overall_score(measures(**{**SIX, "completeness": 53}), EQUAL)[0] == 76
    # 452 / 6 = 75.33 -> 75.
    assert overall_score(measures(**{**SIX, "completeness": 52}), EQUAL)[0] == 75


def test_overall_uses_the_configured_weights():
    # (2 x 80 + 70 + 60 + 90 + 100 + 50) / 7 = 530 / 7 = 75.71 -> 76.
    weights = {**EQUAL, "timing": 2}
    assert overall_score(measures(**SIX), weights)[0] == 76


def test_an_unobservable_measure_is_left_out_of_the_overall():
    scores = measures(**{**SIX, "timing": None})
    # (70 + 60 + 90 + 100 + 50) / 5 = 74.
    overall, basis = overall_score(scores, EQUAL)
    assert overall == 74
    assert "timing" not in basis


def test_no_observable_measure_gives_no_overall():
    assert overall_score(measures(**dict.fromkeys(SIX)), EQUAL) == (None, ())


@given(st.integers(0, 100), st.integers(0, 100))
def test_accent_never_changes_the_overall(first, second):
    """D11: two rounds that differ only in accent have equal overall scores."""
    one = overall_score({**measures(**SIX), "accent": Measure(first)}, EQUAL)
    two = overall_score({**measures(**SIX), "accent": Measure(second)}, EQUAL)
    assert one == two == (75, tuple(SCORED_MEASURES))


DELIVERY = DeliveryParameters.load()


def round_of(pitch_hz: list[float]) -> dict[str, object]:
    """Four words a second apart, matched on time, voiced at the given pitch."""
    spoken = [
        SpokenWord(i, float(i), i + 0.4, 0.8, (Sound("a", float(i), i + 0.4, 0.8),))
        for i in range(4)
    ]
    return {
        "reference_words": ["one", "two", "three", "four"],
        "original": [Word(i, float(i), i + 0.4) for i in range(4)],
        "spoken": spoken,
        "fillers": [Interval(4.5, 4.7)],
        "leakage": None,
        "clock_known": True,
        "learner_pitch": [(i + 0.1, hz) for i, hz in enumerate(pitch_hz)],
        "original_prosody": {i: Prosody(0.4 + 0.1 * i, 6000 + 100 * i) for i in range(4)},
    }


def test_two_rounds_that_differ_only_in_accent_have_equal_overall_scores():
    """D11 on the whole round: only the pitch contour differs between the two."""
    rising = grade_round(DELIVERY, speech(), **round_of([100, 110, 120, 130]))
    falling = grade_round(DELIVERY, speech(), **round_of([130, 120, 110, 100]))
    assert rising.measures["accent"].score != falling.measures["accent"].score
    for name in SCORED_MEASURES:
        assert rising.measures[name] == falling.measures[name]
    assert rising.overall == falling.overall is not None


def test_a_round_has_all_seven_measures_word_labels_and_both_versions():
    result = grade_round(DELIVERY, speech(), **round_of([100, 110, 120, 130]))
    assert set(result.measures) == {*SCORED_MEASURES, "accent"}
    assert all(m.score is None or 0 <= m.score <= 100 for m in result.measures.values())
    assert result.overall_basis == tuple(
        name for name in SCORED_MEASURES if result.measures[name].score is not None
    )
    assert dict(result.overall_weights) == EQUAL
    assert [w.label for w in result.word_labels] == ["good"] * 4
    assert (result.delivery_version, result.speech_version) == (DELIVERY.version, "test")
    assert result.filler_count == 1
    assert result.echo.status == "unchecked"


def test_nothing_said_leaves_every_measure_unobservable_and_every_word_missed():
    inputs = {**round_of([100, 110, 120, 130]), "spoken": [], "learner_pitch": []}
    result = grade_round(DELIVERY, speech(), **inputs)
    assert result.overall is None
    assert {m.reason for m in result.measures.values()} == {"no_matched_words"}
    assert [w.label for w in result.word_labels] == ["missed"] * 4


def test_an_unknown_clock_disables_timing_only():
    inputs = {**round_of([100, 110, 120, 130]), "clock_known": False}
    result = grade_round(DELIVERY, speech(), **inputs)
    assert result.measures["timing"].reason == "playback_offset_unknown"
    assert result.measures["pronunciation"].score == 80
    assert "timing" not in result.overall_basis


def test_an_empty_reference_is_reported_as_such_on_every_measure():
    inputs = {**round_of([100, 110, 120, 130]), "reference_words": []}
    result = grade_round(DELIVERY, speech(), **inputs)
    assert {m.reason for m in result.measures.values()} == {"no_reference_words"}
    assert result.word_labels == []


# --- Parameters (ADR 0099) ---------------------------------------------------------


def test_the_packaged_speech_parameters_are_provisional_uncalibrated_and_equal():
    packaged = SpeechParameters.load(PACKAGED_SPEECH_PARAMETERS)
    assert packaged.version == "1"
    assert (packaged.provisional, packaged.calibrated) == (True, False)
    assert packaged.raw["accent"]["experimental"] is True
    # D3/D11: the equal-weighted mean of the six measures, accent excluded.
    assert dict(packaged.raw["overall"]["weights"]) == EQUAL
    result = grade_round(DELIVERY, packaged, **round_of([100, 110, 120, 130]))
    assert result.speech_version == "1"
    assert result.overall is not None


def broken(path: str, value: object) -> dict[str, object]:
    data = copy.deepcopy(SPEECH)
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
        ("version", 1),
        ("provisional", "yes"),
        ("calibrated", KeyError),
        ("notes", "x"),  # an unknown key is a typo, not an extra
        ("sounds.dropped_below", 0.5),  # not below unclear_below
        ("sounds.dropped_below", -0.1),
        ("sounds.unclear_below", 1.5),
        ("sounds.merged_max_s", 0),
        ("sounds.linking_gap_s", -1),
        ("sounds.linking_gap_s", True),
        ("sounds.linking_gap_s", float("nan")),
        ("sounds.gap", 0.1),
        ("labels.good_from", 0.4),  # below unclear_below
        ("labels.good_from", 1.1),
        ("articulation.position_weights", {"initial": 1, "final": 2}),
        ("articulation.position_weights.final", 0),
        ("articulation.position_weights.final", 1.5),
        ("articulation.linking_weight", 0),
        ("articulation.issue_weights.unclear", 0),
        ("articulation.issue_weights.unclear", 1.5),
        ("articulation.issue_weights", {"dropped": 1, "merged": 1}),
        ("accent.experimental", "yes"),
        ("accent.weights", {"stress": 50, "pitch": 50}),
        ("accent.weights.pitch", -1),
        ("accent.min_words", 2),  # two points always correlate perfectly
        ("accent.min_words", 3.5),
        ("accent.zero_r", -1.5),
        ("accent.full_r", 0.0),  # not above zero_r
        ("accent.full_r", 1.2),
        ("accent.vowel_labels", []),
        ("accent.vowel_labels", ["a", ""]),
        ("accent.vowel_labels", "aeiou"),
        ("accent.vowel_zero_gap", 0.1),  # not above the full-credit gap
        ("accent.vowel_zero_gap", 1.5),
        ("overall.weights", {**EQUAL, "accent": 1}),  # D11
        ("overall.weights", {k: v for k, v in EQUAL.items() if k != "fillers"}),
        ("overall.weights.timing", 0),
        ("overall.weights.timing", True),
        ("overall", KeyError),
    ],
)
def test_invalid_speech_parameters_are_refused(path, value):
    with pytest.raises(ValueError, match="speech parameter"):
        SpeechParameters.from_mapping(broken(path, value))


@pytest.mark.parametrize("data", [[], "parameters", None])
def test_speech_parameters_that_are_not_a_mapping_are_refused(data):
    with pytest.raises(ValueError, match="speech parameter"):
        SpeechParameters.from_mapping(data)  # type: ignore[arg-type]


def test_loaded_speech_parameters_are_a_frozen_copy():
    data = copy.deepcopy(SPEECH)
    loaded = SpeechParameters.from_mapping(data)
    data["labels"]["good_from"] = 0.99  # type: ignore[index]
    assert loaded.raw["labels"]["good_from"] == 0.7
    with pytest.raises(TypeError):
        loaded.raw["overall"]["weights"]["timing"] = 5  # type: ignore[index]
