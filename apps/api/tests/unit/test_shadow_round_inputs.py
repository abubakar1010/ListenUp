"""Assessment output becomes scoring input and stored provenance (#82, NFR-AI-5)."""

import math

import pytest

from listenup.ai.ports import (
    Filler,
    PitchPoint,
    Provenance,
    SoundScore,
    Span,
    SpeechAssessment,
    WordScore,
)
from listenup.modules.grading.domain.delivery import DeliveryParameters, Interval, Word
from listenup.modules.grading.round_inputs import recorded_inputs, speech_info


def assessment(provider: str = "local-speech") -> SpeechAssessment:
    return SpeechAssessment(
        provenance=Provenance(provider=provider, model="m-1", version="2.0"),
        words=(
            WordScore(
                index=1,
                text="cat",
                start=3.5,
                end=3.9,
                accuracy=0.8,
                sounds=(SoundScore(label="k", start=3.5, end=3.6, score=0.8),),
            ),
            WordScore(index=0, text="the", start=3.2, end=3.4, accuracy=0.9, sounds=()),
        ),
        pauses=(Span(start=3.4, end=3.5),),
        fillers=(Filler(text="um", start=4.0, end=4.2),),
        pitch=(PitchPoint(time=3.2, hertz=110),),
    )


def test_recorded_words_and_fillers_keep_reference_indices_and_times():
    words, fillers = recorded_inputs(assessment())
    assert words == [Word(1, 3.5, 3.9), Word(0, 3.2, 3.4)]
    assert fillers == [Interval(4.0, 4.2)]


@pytest.mark.parametrize(
    ("provider", "synthetic"), [("local-speech", False), ("fake", True), ("fake-assessment", True)]
)
def test_speech_info_stores_provenance_and_marks_synthetic_output(provider, synthetic):
    """Synthetic numbers are never shown as learner results (ADR 0074)."""
    info = speech_info(assessment(provider), DeliveryParameters.load())
    assert info == {
        "provider": provider,
        "model": "m-1",
        "version": "2.0",
        "synthetic": synthetic,
        "parameters_version": "1",
        "parameters_calibrated": False,
    }


def test_missing_playback_offset_only_disables_timing():
    result = round_result_of(assessment("fake-assessment"), playback_offset_ms=None)
    assert result["measures"]["timing"] == {
        "score": None,
        "reason": "playback_offset_unknown",
        "details": {},
    }
    assert result["measures"]["completeness"]["score"] == 100
    assert result["measures"]["fluency"]["score"] is not None
    assert result["filler_count"] == 1
    assert result["speech_info"]["synthetic"] is True
    assert result["speech_info"]["overall_basis"] == [
        "pronunciation",
        "articulation",
        "fluency",
        "fillers",
        "completeness",
    ]
    assert result["speech_info"]["echo"] == {"status": "unchecked", "message": None}


def test_round_result_keeps_headphones_warning_and_scores():
    result = round_result_of(assessment("fake-assessment"), leakage=0.5)
    assert result["echo_detected"] is True
    assert result["speech_info"]["echo"] == {"status": "leak", "message": "use_headphones"}
    assert result["measures"]["timing"]["score"] is not None


# --- #83: the whole round --------------------------------------------------------


def test_reference_frames_become_per_word_prosody():
    from listenup.modules.grading.domain.speech_measures import Prosody, prosody_from_frames

    # The profile's frames are centred: frame i of a span starting at 10 000 ms sits
    # at 10 000 + 20 i + 10 ms (parselmouth_acoustics). Word 0 [10 000, 10 090)
    # holds frames 0-3; frame 4, centred at 10 090, is word 1's first frame.
    frames: list[int | None] = [6000, 6100, None, 6200, 6300, None, None, None, None, None]
    result = prosody_from_frames(
        [(0, 10_000, 10_090), (1, 10_090, 10_200)],
        frames_start_ms=10_000,
        frame_step_ms=20,
        pitch_cents=frames,
    )
    assert result == {0: Prosody(0.09, 6100.0), 1: Prosody(0.11, 6300.0)}


def round_result_of(assessment: SpeechAssessment, **changes: object) -> dict[str, object]:
    from listenup.modules.grading.domain.speech_measures import Prosody, SpeechParameters
    from listenup.modules.grading.round_inputs import round_result

    arguments: dict[str, object] = {
        "reference_words": ["the", "cat"],
        "original": [(0, 10_000, 10_200), (1, 10_300, 10_900)],
        "original_prosody": {0: Prosody(0.2, 6000), 1: Prosody(0.6, 6100)},
        "segment": (10_000, 70_000),
        "playback_offset_ms": 3_200,
    }
    arguments.update(changes)
    return round_result(
        assessment,
        DeliveryParameters.load(),
        SpeechParameters.load(),
        **arguments,  # type: ignore[arg-type]
    )


def test_round_result_stores_seven_measures_and_the_overall_over_six():
    result = round_result_of(assessment())
    measures = result["measures"]
    assert set(measures) == {  # type: ignore[arg-type]
        "timing",
        "pronunciation",
        "articulation",
        "fluency",
        "fillers",
        "completeness",
        "accent",
    }
    # "the" has no sounds (word accuracy 0.9), "cat" one sound at 0.8: mean 85.
    assert measures["pronunciation"]["score"] == 85  # type: ignore[index]
    assert measures["accent"]["details"]["experimental"] is True  # type: ignore[index]
    assert measures["accent"]["details"]["compared_with"] == "this_speaker"  # type: ignore[index]
    info = result["speech_info"]
    assert "accent" not in info["overall_basis"]  # type: ignore[index]
    assert info["overall_weights"] == {  # type: ignore[index]
        "timing": 1,
        "pronunciation": 1,
        "articulation": 1,
        "fluency": 1,
        "fillers": 1,
        "completeness": 1,
    }
    assert info["speech_parameters_version"] == "1"  # type: ignore[index]
    assert info["speech_parameters_calibrated"] is False  # type: ignore[index]
    assert info["parameters_version"] == "1"  # type: ignore[index]


def test_round_result_labels_every_segment_word_as_stored_json():
    words = (
        WordScore(
            index=0,
            text="the",
            start=3.2,
            end=3.4,
            accuracy=0.9,
            sounds=(SoundScore(label="ð", start=3.2, end=3.4, score=0.1),),
        ),
    )
    lone = assessment().model_copy(update={"words": words})
    result = round_result_of(lone)
    assert result["word_labels"] == [
        {
            "index": 0,
            "text": "the",
            "label": "needs_work",
            "score": 10,
            "basis": "sounds",
            "reasons": [{"sound": "ð", "position": "final", "issue": "dropped", "linking": False}],
        },
        {"index": 1, "text": "cat", "label": "missed", "score": None, "basis": None, "reasons": []},
    ]


def test_learner_pitch_is_compared_in_cents_word_by_word():
    from listenup.modules.grading.round_inputs import spoken_inputs

    spoken, pitch = spoken_inputs(assessment())
    assert [w.index for w in spoken] == [1, 0]
    assert spoken[0].sounds[0].label == "k"
    assert pitch == [(3.2, pytest.approx(1200 * math.log2(110)))]
