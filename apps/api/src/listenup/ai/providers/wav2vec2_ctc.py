"""wav2vec2 CTC forced-alignment AlignmentPort adapter: self-hosted, CPU (Architecture 7.5).

Uses a torchaudio pipeline bundle named by `model` in `ai.yaml`: the multilingual
`MMS_FA` aligner or an English ASR bundle such as `WAV2VEC2_ASR_BASE_960H` (spike #19,
ADR 0033), with `forced_align` over the words' letters. With the `window_seconds` option
the model runs over the audio in windows rather than in one pass, and `int8: true`
quantises its linear layers. Units are characters,
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


FRAME_SAMPLES = 320  # wav2vec2: one emission frame per 20 ms at 16 kHz
WINDOW_CONTEXT_SAMPLES = 16000  # 1 s of audio each side of a window, then dropped


@dataclass(frozen=True)
class Window:
    start: int  # samples whose frames are kept
    end: int
    input_start: int  # samples the model sees
    input_end: int

    @property
    def first_frame(self) -> int:
        """Index, in the model's output for this window, of the first kept frame."""
        return (self.start - self.input_start) // FRAME_SAMPLES

    @property
    def frame_count(self) -> int:
        return (self.end - self.start) // FRAME_SAMPLES


def emission_windows(num_samples: int, window_seconds: float, sample_rate: int) -> list[Window]:
    """Windows for running the model in pieces (`window_seconds` > 0).

    Self-attention over a whole passage grows with its length squared, so a 3-minute
    passage in one pass is slow and memory-hungry (spike #19). Each window is a whole
    number of frames; the model also sees up to 1 s on each side, and only the window's
    own frames are kept, so every kept frame was computed with context around it."""
    if window_seconds <= 0:
        return [Window(0, num_samples, 0, num_samples)]
    step = round(window_seconds * sample_rate) // FRAME_SAMPLES * FRAME_SAMPLES
    windows = []
    for start in range(0, num_samples, step):
        end = min(start + step, num_samples)
        windows.append(
            Window(
                start,
                end,
                max(0, start - WINDOW_CONTEXT_SAMPLES),
                min(num_samples, end + WINDOW_CONTEXT_SAMPLES),
            )
        )
    return windows


@dataclass(frozen=True)
class Vocabulary:
    """A bundle's labels: MMS_FA uses lower-case letters and no word separator; the
    English ASR bundles (WAV2VEC2_ASR_*) use upper-case letters and `|` between words."""

    labels: tuple[str, ...]
    upper_case: bool
    separator: str | None
    blank: int = 0  # "-" in every torchaudio wav2vec2 bundle

    def targets(self, words: list[str]) -> list[int]:
        """Label ids of the words' letters, with the separator between words if any."""
        index = {label: i for i, label in enumerate(self.labels)}
        ids: list[int] = []
        for i, word in enumerate(words):
            if i and self.separator is not None:
                ids.append(index[self.separator])
            ids.extend(index[c] for c in (word.upper() if self.upper_case else word))
        return ids


def spans_per_word(
    spans: list[RawSpan], tokens: list[int], words: list[str], vocabulary: Vocabulary
) -> list[list[RawSpan]]:
    """Split the merged token spans (one per target id, in order) into one list per
    word, dropping the separators' spans."""
    if len(spans) != len(tokens):
        raise ValueError(f"aligner returned {len(spans)} spans for {len(tokens)} tokens")
    separator = (
        vocabulary.labels.index(vocabulary.separator) if vocabulary.separator is not None else None
    )
    letters = [span for span, token in zip(spans, tokens, strict=True) if token != separator]
    out, cursor = [], 0
    for word in words:
        out.append(letters[cursor : cursor + len(word)])
        cursor += len(word)
    return out


class TorchaudioCtcEngine:
    def __init__(self, entry: ProviderEntry) -> None:
        import torch  # lazy: only the media worker installs it
        import torchaudio

        torch.set_num_threads(int(entry.options.get("threads", 2)))
        bundle = getattr(torchaudio.pipelines, entry.model)
        if isinstance(bundle, torchaudio.pipelines.Wav2Vec2FABundle):  # MMS_FA
            self._model = bundle.get_model(with_star=False)
            labels = bundle.get_labels(star=None)
            self._vocabulary = Vocabulary(tuple(labels), upper_case=False, separator=None)
        else:  # an ASR bundle such as WAV2VEC2_ASR_BASE_960H
            self._model = bundle.get_model()
            labels = bundle.get_labels()
            self._vocabulary = Vocabulary(tuple(labels), upper_case=True, separator="|")
        if entry.options.get("int8", False):
            # Dynamic int8 linear layers: 23% less CPU, same boundaries (spike #19).
            self._model = torch.ao.quantization.quantize_dynamic(
                self._model, {torch.nn.Linear}, dtype=torch.qint8
            )
        self._torch = torch
        self._functional = torchaudio.functional
        self._sample_rate = int(bundle.sample_rate)
        self._window_seconds = float(entry.options.get("window_seconds", 0))

    @property
    def version(self) -> str:
        return f"torchaudio {metadata.version('torchaudio')}; torch {metadata.version('torch')}"

    def run(self, audio: Path, words: list[str]) -> RawAlignment:
        torch = self._torch
        pcm = decode_pcm(audio, self._sample_rate)
        waveform = torch.frombuffer(bytearray(pcm), dtype=torch.float32).unsqueeze(0)
        num_samples = int(waveform.size(1))
        with torch.inference_mode():
            parts = []
            for w in emission_windows(num_samples, self._window_seconds, self._sample_rate):
                emission, _ = self._model(waveform[:, w.input_start : w.input_end])
                if self._window_seconds > 0:
                    emission = emission[:, w.first_frame : w.first_frame + w.frame_count]
                parts.append(emission[0])
            log_probs = torch.log_softmax(torch.cat(parts), dim=-1)
            tokens = self._vocabulary.targets(words)
            labels, scores = self._functional.forced_align(
                log_probs.unsqueeze(0),
                torch.tensor([tokens], dtype=torch.int32),
                blank=self._vocabulary.blank,
            )
            merged = self._functional.merge_tokens(
                labels[0], scores[0].exp(), blank=self._vocabulary.blank
            )
        spans = [RawSpan(start=int(s.start), end=int(s.end), score=float(s.score)) for s in merged]
        return RawAlignment(
            sample_rate=self._sample_rate,
            num_samples=num_samples,
            num_frames=int(log_probs.size(0)),
            spans=spans_per_word(spans, tokens, words, self._vocabulary),
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
