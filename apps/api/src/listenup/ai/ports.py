"""The four AI ports and their vendor-neutral types (Architecture 7.1, NFR-AI-1, ADR 0028).

Callers depend on these Protocols and types only; adapters in `ai/providers/` implement
them. Every result carries the provider, model and version that produced it, so a stored
result can be compared with one from another provider (NFR-AI-5).

Audio goes in as a path to a local file the worker has fetched from storage; adapters
decode it themselves. Times are seconds from the start of that file.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Role(StrEnum):
    TRANSCRIPTION = "transcription"
    ALIGNMENT = "alignment"
    SPEECH_ASSESSMENT = "speech_assessment"
    TEXT_AI = "text_ai"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Provenance(_Strict):
    """Who produced a result (NFR-AI-5). `version` names the library or API version and
    anything else that changes the output for the same model, such as int8 weights."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    version: str = Field(min_length=1)


class AIResult(_Strict):
    provenance: Provenance


class Span(_Strict):
    start: float = Field(ge=0)
    end: float = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError("end is before start")
        return self


# --- Transcription -----------------------------------------------------------------


class TimedWord(Span):
    text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class TranscriptSegment(Span):
    """A stretch of speech the provider returned as one unit, usually a sentence."""

    text: str
    words: tuple[TimedWord, ...]


class Transcript(AIResult):
    language: str = Field(min_length=2)
    duration_seconds: float = Field(ge=0)
    segments: tuple[TranscriptSegment, ...]

    @property
    def words(self) -> tuple[TimedWord, ...]:
        return tuple(word for segment in self.segments for word in segment.words)


@runtime_checkable
class TranscriptionPort(Protocol):
    async def transcribe(self, audio: Path, language: str = "en") -> Transcript: ...


# --- Alignment ---------------------------------------------------------------------


class AlignedUnit(Span):
    """One sound unit inside a word: a phone, or a character for character-level models."""

    label: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class AlignedWord(Span):
    """A word of the reference text with its timing. `index` is the word's position in
    the reference text split on whitespace, so callers can map it back; words the model
    cannot align (digits, symbols) are missing from the result rather than guessed."""

    index: int = Field(ge=0)
    text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    units: tuple[AlignedUnit, ...]


class Alignment(AIResult):
    unit_kind: Literal["phone", "character"]
    words: tuple[AlignedWord, ...]


@runtime_checkable
class AlignmentPort(Protocol):
    async def align(self, audio: Path, text: str) -> Alignment: ...


# --- Speech assessment -------------------------------------------------------------


class SoundScore(Span):
    label: str = Field(min_length=1)
    score: float = Field(ge=0, le=1)


class WordScore(Span):
    index: int = Field(ge=0)
    text: str = Field(min_length=1)
    accuracy: float = Field(ge=0, le=1)
    sounds: tuple[SoundScore, ...]


class Filler(Span):
    text: str = Field(min_length=1)


class PitchPoint(_Strict):
    time: float = Field(ge=0)
    hertz: float | None = Field(default=None, gt=0)  # None where the speech is unvoiced


class SpeechAssessment(AIResult):
    """Per-word and per-sound scores, timing, pauses, fillers and pitch (Architecture 7.1)."""

    words: tuple[WordScore, ...]
    pauses: tuple[Span, ...]
    fillers: tuple[Filler, ...]
    pitch: tuple[PitchPoint, ...]


@runtime_checkable
class SpeechAssessmentPort(Protocol):
    async def assess(
        self, recording: Path, reference_text: str, reference_audio: Path
    ) -> SpeechAssessment: ...


# --- Text AI -----------------------------------------------------------------------


@dataclass(frozen=True)
class TextTask:
    """A prompt in `ai/prompts/<name>/<version>.md` (Architecture 7.3, NFR-AI-4)."""

    name: str
    version: str


class TextGeneration[T: BaseModel](AIResult):
    task: str
    prompt_version: str
    value: T


@runtime_checkable
class TextAIPort(Protocol):
    async def generate[T: BaseModel](
        self, task: TextTask, input: Mapping[str, Any], output_schema: type[T]
    ) -> TextGeneration[T]: ...


@runtime_checkable
class Preloadable(Protocol):
    """An adapter that loads a model once per process; the gateway calls `load` at worker
    start so no job pays the cold start (System Design 5.2). Blocking: run it in a thread."""

    def load(self) -> None: ...
