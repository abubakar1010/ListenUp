"""Turn an assessment into delivery-scoring input and stored provenance (#82).

The round job (after #90) calls these; the domain stays free of `listenup.ai`.
"""

from typing import Any

from listenup.ai.gateway import is_synthetic
from listenup.ai.ports import SpeechAssessment
from listenup.modules.grading.domain.delivery import DeliveryParameters, Interval, Word


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
