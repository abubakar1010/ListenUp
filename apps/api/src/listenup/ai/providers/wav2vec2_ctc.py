"""wav2vec2 CTC forced-alignment AlignmentPort adapter: self-hosted, CPU (Architecture 7.5).

Uses a torchaudio pipeline bundle named by `model` in `ai.yaml` (default `MMS_FA`, the
multilingual wav2vec2 aligner the spike #19 harness measures). Its units are characters,
so results say `unit_kind: character`. torch and torchaudio are imported only when the
model loads, once per process, in the media worker (install the CPU wheels there).

As in the faster-whisper adapter, `TorchaudioCtcEngine` is the only code touching the
library; it returns `RawAlignment` data (frame spans per word) that `to_alignment` maps
to the port's schema, so contract tests replay recordings without the model.
"""

import asyncio
import re
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from listenup.ai.config import ProviderEntry
from listenup.ai.ports import AlignedUnit, AlignedWord, Alignment, Provenance
from listenup.ai.providers.audio import decode_pcm

PROVIDER = "wav2vec2-ctc"


class RawSpan(BaseModel):
    """One token's span in emission frames, with its mean posterior (torchaudio TokenSpan)."""

    start: int
    end: int
    score: float


class RawAlignment(BaseModel):
    sample_rate: int
    num_samples: int
    num_frames: int
    spans: list[list[RawSpan]]  # one list per alignable word, one span per character


class CtcEngine(Protocol):
    @property
    def version(self) -> str: ...

    def run(self, audio: Path, words: list[str]) -> RawAlignment: ...


@dataclass(frozen=True)
class AlignableWord:
    index: int  # position in the reference text split on whitespace
    text: str  # the word as written in the reference
    tokens: str  # what the model aligns: lower-case a-z and apostrophes


def alignable_words(text: str) -> list[AlignableWord]:
    """Words in the aligner's alphabet. Accents are folded (cafe for café); words with no
    letters (numbers, symbols) are left out, so spell numbers out in reference texts."""
    found = []
    for index, word in enumerate(text.split()):
        folded = unicodedata.normalize("NFKD", word.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'"))
        tokens = re.sub(r"[^a-z']", "", folded.lower()).strip("'")
        if tokens:
            found.append(AlignableWord(index=index, text=word, tokens=tokens))
    return found


class TorchaudioCtcEngine:
    def __init__(self, entry: ProviderEntry) -> None:
        import torch  # lazy: only the media worker installs it
        import torchaudio

        torch.set_num_threads(int(entry.options.get("threads", 2)))
        bundle = getattr(torchaudio.pipelines, entry.model)
        self._torch = torch
        self._model = bundle.get_model(with_star=False)
        self._tokenizer = bundle.get_tokenizer()
        self._aligner = bundle.get_aligner()
        self._sample_rate = int(bundle.sample_rate)

    @property
    def version(self) -> str:
        return f"torchaudio {metadata.version('torchaudio')}; torch {metadata.version('torch')}"

    def run(self, audio: Path, words: list[str]) -> RawAlignment:
        torch = self._torch
        pcm = decode_pcm(audio, self._sample_rate)
        waveform = torch.frombuffer(bytearray(pcm), dtype=torch.float32).unsqueeze(0)
        with torch.inference_mode():
            emission, _ = self._model(waveform)
        spans = self._aligner(emission[0], self._tokenizer(words))
        return RawAlignment(
            sample_rate=self._sample_rate,
            num_samples=int(waveform.size(1)),
            num_frames=int(emission.size(1)),
            spans=[
                [RawSpan(start=int(s.start), end=int(s.end), score=float(s.score)) for s in word]
                for word in spans
            ],
        )


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def to_alignment(
    words: list[AlignableWord], raw: RawAlignment, provenance: Provenance
) -> Alignment:
    if len(raw.spans) != len(words):
        raise ValueError(f"aligner returned {len(raw.spans)} words for {len(words)}")
    seconds_per_frame = (
        raw.num_samples / raw.num_frames / raw.sample_rate if raw.num_frames else 0.0
    )
    out = []
    for word, spans in zip(words, raw.spans, strict=True):
        if not spans:
            continue
        units = tuple(
            AlignedUnit(
                label=word.tokens[i] if i < len(word.tokens) else "?",
                start=span.start * seconds_per_frame,
                end=max(span.end, span.start) * seconds_per_frame,
                confidence=_clamp(span.score),
            )
            for i, span in enumerate(spans)
        )
        out.append(
            AlignedWord(
                index=word.index,
                text=word.text,
                start=units[0].start,
                end=max(units[-1].end, units[0].start),
                confidence=_clamp(sum(s.score for s in spans) / len(spans)),
                units=units,
            )
        )
    return Alignment(provenance=provenance, unit_kind="character", words=tuple(out))


class Wav2Vec2CtcAlignment:
    def __init__(
        self,
        entry: ProviderEntry,
        engine_factory: Callable[[ProviderEntry], CtcEngine] = TorchaudioCtcEngine,
    ) -> None:
        self._entry = entry
        self._engine_factory = engine_factory
        self._engine: CtcEngine | None = None
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load the model once per process; later calls return at once."""
        with self._lock:
            if self._engine is None:
                self._engine = self._engine_factory(self._entry)

    def _run(self, audio: Path, text: str) -> Alignment:
        self.load()
        assert self._engine is not None
        provenance = Provenance(
            provider=PROVIDER, model=self._entry.model, version=self._engine.version
        )
        words = alignable_words(text)
        if not words:
            return Alignment(provenance=provenance, unit_kind="character", words=())
        raw = self._engine.run(audio, [w.tokens for w in words])
        return to_alignment(words, raw, provenance)

    async def align(self, audio: Path, text: str) -> Alignment:
        return await asyncio.to_thread(self._run, audio, text)
