"""Assessment output becomes scoring input and stored provenance (#82, NFR-AI-5)."""

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
