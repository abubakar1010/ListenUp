import numpy as np
import pytest

from listenup_spikes.align import AlignedWord, alignable_words
from listenup_spikes.shadow_measures import (
    RoundMeasures,
    accent,
    articulation,
    completeness,
    echo_score,
    extra_pauses,
    fillers_score,
    fluency,
    pronunciation,
    timing,
)


def words(starts: list[float], score: float = 0.9, dur: float = 0.3) -> list[AlignedWord]:
    return [AlignedWord(f"w{i}", s, s + dur, score, score) for i, s in enumerate(starts)]


ORIGINAL = words([0.0, 0.5, 1.0, 1.5, 2.0, 2.5])


def test_alignable_words_drop_digits_and_punctuation() -> None:
    assert alignable_words("I could've seen 3 cats!") == ["i", "could", "have", "seen", "cats"]


def test_constant_shadowing_lag_is_not_penalised() -> None:
    learner = words([0.4, 0.9, 1.4, 1.9, 2.4, 2.9])
    assert timing(ORIGINAL, learner) == pytest.approx(100)


def test_late_irregular_speech_scores_lower_on_timing() -> None:
    clear = words([0.4, 0.9, 1.4, 1.9, 2.4, 2.9])
    poor = words([0.4, 1.3, 1.6, 2.9, 3.0, 4.2])
    assert timing(ORIGINAL, poor) < timing(ORIGINAL, clear)


def test_mumbled_words_lower_completeness_pronunciation_and_articulation() -> None:
    clear = words([0, 0.5, 1, 1.5, 2, 2.5], score=0.9)
    mumbled = [*words([0, 0.5, 1], score=0.5), *words([1.5, 2, 2.5], score=0.1)]
    assert completeness(mumbled) == pytest.approx(50)
    assert pronunciation(mumbled) < pronunciation(clear)
    assert articulation(mumbled) < articulation(clear)


def test_extra_pauses_and_fluency() -> None:
    hesitant = words([0.0, 0.5, 1.6, 2.1, 3.2, 3.7])
    assert extra_pauses(ORIGINAL, hesitant) == 2
    assert fluency(ORIGINAL, hesitant) < fluency(ORIGINAL, ORIGINAL)


def test_fillers_score_per_minute() -> None:
    assert fillers_score(0, 60) == 100
    assert fillers_score(6, 60) == 0
    assert fillers_score(None, 60) is None


def test_accent_correlates_intonation_contours() -> None:
    contour = [0.0, 2.0, 4.0, 1.0, -1.0, 3.0]
    assert accent(contour, [c + 5 for c in contour]) == pytest.approx(100)
    assert accent(contour, contour[::-1]) == 0
    assert accent(contour[:3], contour[:3]) is None


def test_overall_excludes_accent() -> None:
    m = RoundMeasures({"timing": 80, "accent": 0, "completeness": 60, "fillers": None})
    assert m.overall == pytest.approx(70)


def test_echo_detected_when_original_leaks_into_recording() -> None:
    rng = np.random.default_rng(0)
    original = rng.normal(size=16000 * 5) * np.repeat(rng.uniform(0, 1, 500), 160)
    leaked = np.concatenate([np.zeros(1600), original[:-1600]]) + rng.normal(
        scale=0.1, size=original.size
    )
    unrelated = rng.normal(size=original.size) * np.repeat(rng.uniform(0, 1, 500), 160)
    assert echo_score(original, leaked) > 0.6
    assert echo_score(original, unrelated) < 0.3
