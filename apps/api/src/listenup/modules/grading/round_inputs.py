"""Turn an assessment into delivery-scoring input and stored provenance (#82).

The round job calls these; the domain stays free of `listenup.ai`.
"""

from dataclasses import asdict
from typing import Any

from listenup.ai.gateway import is_synthetic
from listenup.ai.ports import SpeechAssessment
from listenup.modules.grading.domain.delivery import (
    DeliveryParameters,
    Interval,
    Word,
    place_original,
    score_round,
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


def delivery_result(
    assessment: SpeechAssessment,
    parameters: DeliveryParameters,
    *,
    reference_word_count: int,
    original: list[tuple[int, int, int]],
    segment: tuple[int, int],
    playback_offset_ms: int | None,
    leakage: float | None = None,
) -> dict[str, Any]:
    """Persistable evidence, including explicit unknown clock and leakage states."""
    words, fillers = recorded_inputs(assessment)
    scores = score_round(
        parameters,
        reference_word_count=reference_word_count,
        original=place_original(
            original, segment=segment, playback_offset_ms=playback_offset_ms or 0
        ),
        recorded=words,
        fillers=fillers,
        leakage=leakage,
        clock_known=playback_offset_ms is not None,
    )
    return {
        "measures": {name: asdict(value) for name, value in scores.measures.items()},
        "overall": scores.overall,
        "filler_count": scores.filler_count,
        "echo_detected": scores.echo.status == "leak",
        "speech_info": {
            **speech_info(assessment, parameters),
            "overall_basis": list(scores.overall_basis),
            "echo": asdict(scores.echo),
        },
    }
