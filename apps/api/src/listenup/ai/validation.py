"""Revalidate even preconstructed Pydantic results at the untrusted adapter boundary."""

import math
from typing import Any

from pydantic import BaseModel

from listenup.ai.ports import Alignment, SpeechAssessment, Transcript


def revalidate[T: BaseModel](schema: type[T], raw: Any) -> T:
    data = raw.model_dump() if isinstance(raw, BaseModel) else raw
    _finite(data)
    result = schema.model_validate(data)
    _finite(result.model_dump())
    return result


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite output")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    if isinstance(value, (list, tuple)):
        for item in value:
            _finite(item)


def validate_transcript(raw: Any) -> Transcript:
    result = revalidate(Transcript, raw)
    last = 0.0
    for segment in result.segments:
        if segment.start < last or segment.end > result.duration_seconds:
            raise ValueError("segment outside transcript")
        last = segment.end
        word_end = segment.start
        for word in segment.words:
            if word.start < word_end or word.end > segment.end:
                raise ValueError("word outside segment")
            word_end = word.end
    return result


def validate_alignment(raw: Any, text: str) -> Alignment:
    result = revalidate(Alignment, raw)
    words = text.split()
    index, end = -1, 0.0
    for word in result.words:
        if (
            word.index <= index
            or word.index >= len(words)
            or word.start < end
            or word.text != words[word.index]
        ):
            raise ValueError("invalid word index or timing")
        index, end = word.index, word.end
        unit_end = word.start
        for unit in word.units:
            if unit.start < unit_end or unit.end > word.end:
                raise ValueError("unit outside word")
            unit_end = unit.end
    return result


def validate_assessment(raw: Any, text: str) -> SpeechAssessment:
    result = revalidate(SpeechAssessment, raw)
    words = text.split()
    index, end = -1, 0.0
    for word in result.words:
        if (
            word.index <= index
            or word.index >= len(words)
            or word.text != words[word.index]
            or word.start < end
        ):
            raise ValueError("invalid assessment word index or timing")
        index, end = word.index, word.end
        sound_end = word.start
        for sound in word.sounds:
            if sound.start < sound_end or sound.end > word.end:
                raise ValueError("sound outside assessment word")
            sound_end = sound.end
    return result
