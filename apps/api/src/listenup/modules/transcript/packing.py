"""Validate and pack provider-relative seconds as media-absolute milliseconds."""

import math
from dataclasses import dataclass

from listenup.ai.ports import Transcript
from listenup.modules.transcript.domain.sentences import ends_sentence
from listenup.modules.transcript.domain.spans import Span


@dataclass(frozen=True)
class Packed:
    words: list[str]
    start_ms: list[int]
    end_ms: list[int]
    confidence: list[int]
    sentence_starts: list[int]
    provider_info: dict[str, str]


def pack(result: Transcript, span: Span) -> Packed:
    left, right = span
    words: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    confidence: list[int] = []
    sentences: list[int] = []
    for word in result.words:
        if not math.isfinite(word.start) or not math.isfinite(word.end):
            raise ValueError("non-finite word timing")
        if word.end <= word.start:
            raise ValueError("empty word timing")
        start, end = left + round(word.start * 1000), left + round(word.end * 1000)
        if not left <= start <= end <= right or (starts and start < starts[-1]):
            raise ValueError("word timing outside window or unordered")
        # Provider segments are acoustic chunks, not necessarily sentences. Preserve
        # continuations across chunks and detect sentence endings within a chunk.
        if not words or ends_sentence(words[-1]):
            sentences.append(len(words))
        words.append(word.text)
        starts.append(start)
        ends.append(end)
        confidence.append(round(word.confidence * 1000))
    return Packed(words, starts, ends, confidence, sentences, result.provenance.model_dump())
