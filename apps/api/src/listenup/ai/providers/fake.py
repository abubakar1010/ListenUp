"""Deterministic fake providers for every port, for tests and local runs (ADR 0028).

Select one in `ai.yaml` with `provider: fake`. They need no model and no network, so
switching a role to `fake` is how a test proves the provider is chosen by configuration
alone (AT-22). The gateway refuses them in production.
"""

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from listenup.ai.config import ProviderEntry
from listenup.ai.ports import (
    AlignedUnit,
    AlignedWord,
    Alignment,
    Provenance,
    SpeechAssessment,
    TextGeneration,
    TextTask,
    TimedWord,
    Transcript,
    TranscriptSegment,
    WordScore,
)

PROVIDER = "fake"
VERSION = "1"
WORD_SECONDS = 0.4
DEFAULT_TEXT = "this is a fake transcript"

# Canned Text AI outputs by task name; tests register what a task should return.
_text_responses: dict[str, dict[str, Any]] = {}


def register_text_response(task: str, payload: Mapping[str, Any]) -> None:
    _text_responses[task] = dict(payload)


def clear_text_responses() -> None:
    _text_responses.clear()


def _provenance(entry: ProviderEntry) -> Provenance:
    return Provenance(provider=PROVIDER, model=entry.model, version=VERSION)


def _span(i: int) -> tuple[float, float]:
    return round(i * WORD_SECONDS, 3), round((i + 1) * WORD_SECONDS, 3)


class FakeTranscription:
    """Returns the text in `<audio>.txt` next to the file, else `options.text`, one word
    every 0.4 s."""

    def __init__(self, entry: ProviderEntry) -> None:
        self._entry = entry

    async def transcribe(self, audio: Path, language: str = "en") -> Transcript:
        await asyncio.sleep(0)
        sidecar = audio.with_suffix(".txt")
        text = (
            sidecar.read_text()
            if sidecar.exists()
            else str(self._entry.options.get("text", DEFAULT_TEXT))
        )
        tokens = text.split()
        words = tuple(
            TimedWord(text=t, start=_span(i)[0], end=_span(i)[1], confidence=1.0)
            for i, t in enumerate(tokens)
        )
        end = words[-1].end if words else 0.0
        segment = TranscriptSegment(text=" ".join(tokens), start=0.0, end=end, words=words)
        return Transcript(
            provenance=_provenance(self._entry),
            language=language,
            duration_seconds=end,
            segments=(segment,) if words else (),
        )


class FakeAlignment:
    """Aligns each word of the text to the next 0.4 s, with characters as units."""

    def __init__(self, entry: ProviderEntry) -> None:
        self._entry = entry

    async def align(self, audio: Path, text: str) -> Alignment:
        await asyncio.sleep(0)
        words = []
        for i, token in enumerate(text.split()):
            start, end = _span(i)
            step = (end - start) / len(token)
            units = tuple(
                AlignedUnit(
                    label=ch,
                    start=round(start + k * step, 3),
                    end=round(start + (k + 1) * step, 3),
                    confidence=1.0,
                )
                for k, ch in enumerate(token)
            )
            words.append(
                AlignedWord(index=i, text=token, start=start, end=end, confidence=1.0, units=units)
            )
        return Alignment(
            provenance=_provenance(self._entry), unit_kind="character", words=tuple(words)
        )


class FakeSpeechAssessment:
    """Scores every reference word as perfectly spoken, with no pauses or fillers."""

    def __init__(self, entry: ProviderEntry) -> None:
        self._entry = entry

    async def assess(
        self, recording: Path, reference_text: str, reference_audio: Path
    ) -> SpeechAssessment:
        await asyncio.sleep(0)
        words = tuple(
            WordScore(index=i, text=t, start=_span(i)[0], end=_span(i)[1], accuracy=1.0, sounds=())
            for i, t in enumerate(reference_text.split())
        )
        return SpeechAssessment(
            provenance=_provenance(self._entry), words=words, pauses=(), fillers=(), pitch=()
        )


class FakeTextAI:
    """Returns the response registered for the task, or the schema's defaults."""

    def __init__(self, entry: ProviderEntry) -> None:
        self._entry = entry

    async def generate[T: BaseModel](
        self, task: TextTask, input: Mapping[str, Any], output_schema: type[T]
    ) -> TextGeneration[T]:
        await asyncio.sleep(0)
        try:
            value = output_schema.model_validate(_text_responses.get(task.name, {}))
        except ValidationError as exc:
            raise ValueError(
                f"fake text AI has no valid response for task {task.name!r}; "
                "register one with register_text_response"
            ) from exc
        result: type[TextGeneration[T]] = TextGeneration[output_schema]  # type: ignore[valid-type]
        return result(
            provenance=_provenance(self._entry),
            task=task.name,
            prompt_version=task.version,
            value=value,
        )
