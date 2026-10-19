"""Range/structure checks independent of the adapter's Pydantic construction."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from listenup.ai.ports import Usage
from listenup.ai.validation import validate_alignment, validate_transcript

PROVENANCE = {"provider": "p", "model": "m", "version": "1"}
TRANSCRIPT = {
    "provenance": PROVENANCE,
    "language": "en",
    "duration_seconds": 1,
    "segments": [
        {
            "start": 0,
            "end": 1,
            "text": "Hello",
            "words": [{"start": 0, "end": 1, "text": "Hello", "confidence": 1}],
        }
    ],
}
ALIGNMENT = {
    "provenance": PROVENANCE,
    "unit_kind": "character",
    "words": [
        {
            "index": 0,
            "text": "Hello",
            "start": 0,
            "end": 1,
            "confidence": 1,
            "units": [{"label": "h", "start": 0, "end": 1, "confidence": 1}],
        }
    ],
}


@pytest.mark.parametrize(
    "change", ["duration", "segment_start", "word_end", "word_start", "confidence"]
)
def test_transcript_invalid_boundaries(change):
    data = deepcopy(TRANSCRIPT)
    if change == "duration":
        data["duration_seconds"] = 0.5
    elif change == "segment_start":
        data["segments"][0]["start"] = 0.5
    elif change == "word_end":
        data["segments"][0]["words"][0]["end"] = 1.1
    elif change == "word_start":
        data["segments"][0]["words"][0]["start"] = -0.1
    else:
        data["segments"][0]["words"][0]["confidence"] = 1.01
    with pytest.raises(ValueError):
        validate_transcript(data)


def test_valid_transcript_and_alignment_keep_provenance():
    assert validate_transcript(TRANSCRIPT).words[0].confidence == 1
    assert validate_alignment(ALIGNMENT, "Hello").provenance.version == "1"


@pytest.mark.parametrize("change", ["index", "duplicate", "unit_end", "unit_start", "text"])
def test_alignment_invalid_boundaries(change):
    data = deepcopy(ALIGNMENT)
    if change == "index":
        data["words"][0]["index"] = 1
    elif change == "duplicate":
        data["words"].append(deepcopy(data["words"][0]))
    elif change == "unit_end":
        data["words"][0]["units"][0]["end"] = 2
    elif change == "unit_start":
        data["words"][0]["start"] = 0.5
    else:
        data["words"][0]["text"] = "unrelated"
    with pytest.raises(ValueError):
        validate_alignment(data, "Hello")


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": 1, "cache_tokens": 2},
        {"output_tokens": 1, "reasoning_tokens": 2},
        {"audio_seconds": float("inf")},
        {"input_tokens": True},
    ],
)
def test_usage_rejects_invalid_subsets_and_values(usage):
    with pytest.raises(ValidationError):
        Usage(**usage)


def test_schema_coercion_cannot_introduce_nonfinite_values():
    from pydantic import BaseModel

    from listenup.ai.validation import revalidate

    class Number(BaseModel):
        value: float

    with pytest.raises(ValueError):
        revalidate(Number, {"value": "NaN"})


def test_end_before_start_is_rejected_even_in_constructed_results():
    data = deepcopy(TRANSCRIPT)
    data["segments"][0]["words"][0].update(start=0.8, end=0.2)
    with pytest.raises(ValueError, match="end is before start"):
        validate_transcript(data)
