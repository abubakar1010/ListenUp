"""faster-whisper TranscriptionPort adapter: self-hosted, CPU, int8 (Architecture 7.5).

The model name comes from `ai.yaml` (spike #18 picks the size). The model is loaded
once per process, on first use or when the media worker preloads it, and the library is
imported only then, so the API and CI never need it (install the `speech` extra).

The adapter is split at the engine: `FasterWhisperEngine` is the only code that touches
the library and returns its output as plain `RawTranscription` data; `to_transcript` maps
that to the port's schema. Contract tests replay recorded `RawTranscription`s through the
whole adapter without the model (tests/contract).
"""

import asyncio
import threading
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from listenup.ai.config import ProviderEntry
from listenup.ai.ports import Provenance, TimedWord, Transcript, TranscriptSegment

PROVIDER = "faster-whisper"


class RawWord(BaseModel):
    start: float
    end: float
    word: str
    probability: float


class RawSegment(BaseModel):
    start: float
    end: float
    text: str
    words: list[RawWord]


class RawTranscription(BaseModel):
    """faster-whisper's output as data: `TranscriptionInfo` and the `Segment`s."""

    language: str
    duration: float
    segments: list[RawSegment]


class WhisperEngine(Protocol):
    @property
    def version(self) -> str: ...

    def run(self, audio: Path, language: str) -> RawTranscription: ...


class FasterWhisperEngine:
    def __init__(self, entry: ProviderEntry) -> None:
        import faster_whisper  # lazy: only the media worker installs it

        options = entry.options
        self._compute_type = str(options.get("compute_type", "int8"))
        self._beam_size = int(options.get("beam_size", 5))
        self._vad_filter = bool(options.get("vad_filter", True))
        download_root = options.get("download_root")
        self._model = faster_whisper.WhisperModel(
            entry.model,
            device="cpu",
            compute_type=self._compute_type,
            cpu_threads=int(options.get("cpu_threads", 2)),
            download_root=str(download_root) if download_root else None,
        )

    @property
    def version(self) -> str:
        return (
            f"faster-whisper {metadata.version('faster-whisper')}"
            f"; ctranslate2 {metadata.version('ctranslate2')}; {self._compute_type}"
        )

    def run(self, audio: Path, language: str) -> RawTranscription:
        segments, info = self._model.transcribe(
            str(audio),
            language=language,
            beam_size=self._beam_size,
            vad_filter=self._vad_filter,
            word_timestamps=True,
        )
        return RawTranscription(
            language=info.language,
            duration=info.duration,
            segments=[  # the generator does the work here
                RawSegment(
                    start=s.start,
                    end=s.end,
                    text=s.text,
                    words=[
                        RawWord(start=w.start, end=w.end, word=w.word, probability=w.probability)
                        for w in (s.words or [])
                    ],
                )
                for s in segments
            ],
        )


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(value, low), high)


def to_transcript(raw: RawTranscription, provenance: Provenance) -> Transcript:
    """Map the engine's output to the port's schema. Whisper's word times can overlap a
    segment edge or run backwards by a few milliseconds; they are clamped, never dropped."""
    segments = []
    for seg in raw.segments:
        words = []
        for w in seg.words:
            text = w.word.strip()
            if not text:
                continue
            start = max(w.start, 0.0)
            words.append(
                TimedWord(
                    text=text,
                    start=start,
                    end=max(w.end, start),
                    confidence=_clamp(w.probability),
                )
            )
        start = max(seg.start, 0.0)
        segments.append(
            TranscriptSegment(
                text=seg.text.strip(), start=start, end=max(seg.end, start), words=tuple(words)
            )
        )
    return Transcript(
        provenance=provenance,
        language=raw.language,
        duration_seconds=max(raw.duration, 0.0),
        segments=tuple(segments),
    )


class FasterWhisperTranscription:
    def __init__(
        self,
        entry: ProviderEntry,
        engine_factory: Callable[[ProviderEntry], WhisperEngine] = FasterWhisperEngine,
    ) -> None:
        self._entry = entry
        self._engine_factory = engine_factory
        self._engine: WhisperEngine | None = None
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load the model once per process; later calls return at once."""
        with self._lock:
            if self._engine is None:
                self._engine = self._engine_factory(self._entry)

    def _run(self, audio: Path, language: str) -> Transcript:
        self.load()
        assert self._engine is not None
        raw = self._engine.run(audio, language)
        provenance = Provenance(
            provider=PROVIDER, model=self._entry.model, version=self._engine.version
        )
        return to_transcript(raw, provenance)

    async def transcribe(self, audio: Path, language: str = "en") -> Transcript:
        # CPU-bound: keep the worker's event loop free for heartbeats and other jobs.
        return await asyncio.to_thread(self._run, audio, language)
