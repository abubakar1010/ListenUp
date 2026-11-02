"""Turn an assessment into round-grading input and stored provenance (#82, #83).

The round job calls these; the domain stays free of `listenup.ai`.
"""

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from listenup.ai.gateway import is_synthetic
from listenup.ai.ports import SpeechAssessment
from listenup.modules.grading.domain.delivery import (
    DeliveryParameters,
    Interval,
    Word,
    place_original,
)
from listenup.modules.grading.domain.speech_measures import (
    Prosody,
    Sound,
    SpeechParameters,
    SpokenWord,
    grade_round,
    hertz_to_cents,
)


def recorded_inputs(assessment: SpeechAssessment) -> tuple[list[Word], list[Interval]]:
    """Reference-indexed words and fillers, recording-relative seconds (ADR 0074)."""
    words = [Word(w.index, w.start, w.end) for w in assessment.words]
    return words, [Interval(f.start, f.end) for f in assessment.fillers]


def speech_info(assessment: SpeechAssessment, parameters: DeliveryParameters) -> dict[str, Any]:
    """Provider, model and version for every result (NFR-AI-5, FR-SH-18).

    `synthetic` marks fake output so no reader presents it as a learner's result.
    """
    provenance = assessment.provenance
    return {
        "provider": provenance.provider,
        "model": provenance.model,
        "version": provenance.version,
        "synthetic": is_synthetic(provenance),
        "parameters_version": parameters.version,
        "parameters_calibrated": parameters.calibrated,
    }


def spoken_inputs(
    assessment: SpeechAssessment,
) -> tuple[list[SpokenWord], list[tuple[float, float | None]]]:
    """Words with their sounds, and the learner's pitch in cents (#83)."""
    spoken = [
        SpokenWord(
            w.index,
            w.start,
            w.end,
            w.accuracy,
            tuple(Sound(s.label, s.start, s.end, s.score) for s in w.sounds),
        )
        for w in assessment.words
    ]
    return spoken, [(p.time, hertz_to_cents(p.hertz)) for p in assessment.pitch]


def round_result(
    assessment: SpeechAssessment,
    delivery: DeliveryParameters,
    parameters: SpeechParameters,
    *,
    reference_words: list[str],
    original: list[tuple[int, int, int]],
    original_prosody: Mapping[int, Prosody],
    segment: tuple[int, int],
    playback_offset_ms: int | None,
    leakage: float | None = None,
) -> dict[str, Any]:
    """Persistable evidence: seven measures, word labels and the versions and
    weights behind the overall, with explicit unknown clock and leakage states."""
    spoken, pitch = spoken_inputs(assessment)
    _, fillers = recorded_inputs(assessment)
    grade = grade_round(
        delivery,
        parameters,
        reference_words=reference_words,
        original=place_original(
            original, segment=segment, playback_offset_ms=playback_offset_ms or 0
        ),
        spoken=spoken,
        fillers=fillers,
        leakage=leakage,
        clock_known=playback_offset_ms is not None,
        learner_pitch=pitch,
        original_prosody=original_prosody,
    )
    return {
        "measures": {name: asdict(value) for name, value in grade.measures.items()},
        "overall": grade.overall,
        "word_labels": [
            {**asdict(label), "reasons": [asdict(reason) for reason in label.reasons]}
            for label in grade.word_labels
        ],
        "filler_count": grade.filler_count,
        "echo_detected": grade.echo.status == "leak",
        "speech_info": {
            **speech_info(assessment, delivery),
            "speech_parameters_version": parameters.version,
            "speech_parameters_calibrated": parameters.calibrated,
            "overall_basis": list(grade.overall_basis),
            "overall_weights": dict(grade.overall_weights),
            "echo": asdict(grade.echo),
        },
    }
