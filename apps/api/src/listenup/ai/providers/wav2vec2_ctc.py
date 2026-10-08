"""wav2vec2 CTC forced-alignment AlignmentPort adapter: self-hosted, CPU (Architecture 7.5).

Uses a torchaudio pipeline bundle named by `model` in `ai.yaml`: the multilingual
`MMS_FA` aligner or an English ASR bundle such as `WAV2VEC2_ASR_BASE_960H` (spike #19,
ADR 0033), with `forced_align` over the words' letters. With the `window_seconds` option
the model runs over the audio in windows rather than in one pass, and `int8: true`
quantises its linear layers; both change the posteriors, so both are part of the
provenance version. Units are characters, so results say `unit_kind: character`. torch
and torchaudio are imported only when the model loads, once per process, in the media
worker (install the CPU wheels there).

As in the faster-whisper adapter, `TorchaudioCtcEngine` is the only code touching the
library; it returns `RawAlignment` data (frame spans per word) that `to_alignment` maps
to the port's schema, so contract tests replay recordings without the model.
"""

import asyncio
import re
import threading
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

from listenup.ai.config import ProviderEntry
from listenup.ai.errors import AIConfigError
from listenup.ai.ports import AlignedUnit, AlignedWord, Alignment, Provenance
from listenup.ai.providers.audio import decode_pcm

if TYPE_CHECKING:
    import torch

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
RECEPTIVE_FIELD_SAMPLES = 400  # what the conv front end reads for one frame
WINDOW_CONTEXT_SAMPLES = 16000  # 1 s of audio each side of a window, then dropped
MIN_WINDOW_SECONDS = 1.0


def model_frames(input_samples: int) -> int:
    """Frames the wav2vec2 conv front end gives for this many samples: one per 320, less
    one when fewer than 80 samples are left over for the last frame's 400-sample field."""
    if input_samples < RECEPTIVE_FIELD_SAMPLES:
        return 0
    return (input_samples - RECEPTIVE_FIELD_SAMPLES) // FRAME_SAMPLES + 1


@dataclass(frozen=True)
class Window:
    start: int  # samples whose frames are kept
    end: int
    input_start: int  # samples the model sees
    input_end: int
    pad_end: int = 0  # silent samples appended to the input so its last frame exists

    @property
    def first_frame(self) -> int:
        """Index, in the model's output for this window, of the first kept frame."""
        return (self.start - self.input_start) // FRAME_SAMPLES

    @property
    def frame_count(self) -> int:
        return (self.end - self.start) // FRAME_SAMPLES


def _window(start: int, end: int, input_start: int, input_end: int) -> Window:
    """A window whose input yields every frame it keeps: at the end of the audio there is
    no context after it, so up to 80 silent samples complete the last frame's field."""
    needed = (start - input_start) // FRAME_SAMPLES + (end - start) // FRAME_SAMPLES
    short = model_frames(input_end - input_start) < needed
    pad = RECEPTIVE_FIELD_SAMPLES - FRAME_SAMPLES if short else 0
    return Window(start, end, input_start, input_end, pad)


def emission_windows(num_samples: int, window_seconds: float, sample_rate: int) -> list[Window]:
    """Windows for running the model over the audio, one frame per 20 ms.

    With `window_seconds` > 0 the model runs in pieces: self-attention over a whole
    passage grows with its length squared, so a 3-minute passage in one pass is slow and
    memory-hungry (spike #19). Each window is a whole number of frames; the model also
    sees up to 1 s on each side, and only the window's own frames are kept, so every
    kept frame was computed with context around it. Either way the frames joined up
    number num_samples // 320, frame i starting at sample 320 * i."""
    if num_samples < FRAME_SAMPLES:
        raise ValueError(f"{num_samples} samples is too short to align")
    if window_seconds <= 0:
        return [_window(0, num_samples, 0, num_samples)]
    step = round(window_seconds * sample_rate) // FRAME_SAMPLES * FRAME_SAMPLES
    if step <= 0:
        raise ValueError(f"window_seconds {window_seconds} is shorter than one frame")
    return [
        _window(
            start,
            min(start + step, num_samples),
            max(0, start - WINDOW_CONTEXT_SAMPLES),
            min(num_samples, start + step + WINDOW_CONTEXT_SAMPLES),
        )
        for start in range(0, num_samples, step)
    ]


BLANK = "-"  # the CTC blank in every torchaudio wav2vec2 bundle
SEPARATOR = "|"  # between words, in the bundles that have one
ALPHABET = "abcdefghijklmnopqrstuvwxyz'"  # what alignable_words produces


@dataclass(frozen=True)
class Vocabulary:
    """A bundle's labels: MMS_FA uses lower-case letters and no word separator; the
    English ASR bundles (WAV2VEC2_ASR_*) use upper-case letters and `|` between words.
    Read from the labels themselves, so a bundle that cannot align our words fails when
    the model loads, not inside a job."""

    labels: tuple[str, ...]
    upper_case: bool
    separator: int | None  # label id of the word separator
    blank: int
    index: Mapping[str, int] = field(compare=False, repr=False)

    @classmethod
    def from_labels(cls, labels: Sequence[str]) -> "Vocabulary":
        labels = tuple(labels)
        index = {label: i for i, label in enumerate(labels)}
        upper_case = "A" in index and "a" not in index
        letters = ALPHABET.upper() if upper_case else ALPHABET
        missing = [c for c in BLANK + letters if c not in index]
        if missing:
            raise AIConfigError(
                f"the alignment model's labels lack {''.join(missing)!r}: "
                "it needs a CTC blank '-', the letters a-z in one case and an apostrophe"
            )
        return cls(labels, upper_case, index.get(SEPARATOR), index[BLANK], index)

    def targets(self, words: list[str]) -> list[int]:
        """Label ids of the words' letters, with the separator between words if any."""
        ids: list[int] = []
        for i, word in enumerate(words):
            if i and self.separator is not None:
                ids.append(self.separator)
            ids.extend(self.index[c] for c in (word.upper() if self.upper_case else word))
        return ids


def spans_per_word(
    spans: list[RawSpan], tokens: list[int], words: list[str], vocabulary: Vocabulary
) -> list[list[RawSpan]]:
    """Split the merged token spans (one per target id, in order) into one list per
    word, dropping the separators' spans."""
    if len(spans) != len(tokens):
        raise ValueError(f"aligner returned {len(spans)} spans for {len(tokens)} tokens")
    letters = [
        span for span, token in zip(spans, tokens, strict=True) if token != vocabulary.separator
    ]
    out, cursor = [], 0
    for word in words:
        out.append(letters[cursor : cursor + len(word)])
        cursor += len(word)
    return out


def window_seconds_option(entry: ProviderEntry) -> float:
    """The `window_seconds` option: 0 (one pass) or at least a second, checked at load."""
    value = float(entry.options.get("window_seconds", 0))
    if value < 0 or 0 < value < MIN_WINDOW_SECONDS:
        raise AIConfigError(
            f"window_seconds must be 0 (one pass) or at least {MIN_WINDOW_SECONDS:g}, not {value:g}"
        )
    return value


def settings_label(window_seconds: float, int8: bool) -> str:
    """The settings that change the emissions, for provenance: windows and int8 move the
    posteriors (and so Shadow's scores), so results from each must stay distinguishable."""
    label = f"window {window_seconds:g}s" if window_seconds > 0 else "one pass"
    return f"{label}; {'int8' if int8 else 'float32'}"


class TorchaudioCtcEngine:
    def __init__(self, entry: ProviderEntry) -> None:
        self._window_seconds = window_seconds_option(entry)
        self._int8 = bool(entry.options.get("int8", False))
        self._decode_timeout = entry.timeout_seconds

        import torch  # lazy: only the media worker installs it
        import torchaudio

        torch.set_num_threads(int(entry.options.get("threads", 2)))
        bundle = getattr(torchaudio.pipelines, entry.model)
        if isinstance(bundle, torchaudio.pipelines.Wav2Vec2FABundle):  # MMS_FA
            self._model = bundle.get_model(with_star=False)
            labels = bundle.get_labels(star=None)
        elif isinstance(bundle, torchaudio.pipelines.Wav2Vec2ASRBundle):  # WAV2VEC2_ASR_*
            self._model = bundle.get_model()
            labels = bundle.get_labels()
        else:
            raise AIConfigError(
                f"{entry.model} is not a torchaudio wav2vec2 CTC bundle "
                "(use MMS_FA or a WAV2VEC2_ASR_* bundle)"
            )
        self._vocabulary = Vocabulary.from_labels(labels)
        if self._int8:
            # Dynamic int8 linear layers: 23% less CPU, same boundaries (spike #19).
            self._model = torch.ao.quantization.quantize_dynamic(
                self._model, {torch.nn.Linear}, dtype=torch.qint8
            )
        self._torch = torch
        self._functional = torchaudio.functional
        self._sample_rate = int(bundle.sample_rate)

    @property
    def version(self) -> str:
        return (
            f"torchaudio {metadata.version('torchaudio')}; torch {metadata.version('torch')}"
            f"; {settings_label(self._window_seconds, self._int8)}"
        )

    def run(self, audio: Path, words: list[str]) -> RawAlignment:
        pcm = decode_pcm(audio, self._sample_rate, timeout_seconds=self._decode_timeout)
        samples = self._torch.frombuffer(bytearray(pcm), dtype=self._torch.float32)
        return self.run_samples(samples, words)

    def run_samples(self, samples: "torch.Tensor", words: list[str]) -> RawAlignment:
        """Align `words` to mono float samples at the bundle's rate (1-D tensor)."""
        torch = self._torch
        waveform = samples.unsqueeze(0)
        num_samples = int(waveform.size(1))
        with torch.inference_mode():
            parts = []
            for w in emission_windows(num_samples, self._window_seconds, self._sample_rate):
                piece = waveform[:, w.input_start : w.input_end]
                if w.pad_end:
                    piece = torch.nn.functional.pad(piece, (0, w.pad_end))
                emission, _ = self._model(piece)
                kept = emission[0, w.first_frame : w.first_frame + w.frame_count]
                if kept.size(0) != w.frame_count:
                    raise RuntimeError(
                        f"the model gave {emission.size(1)} frames for {piece.size(1)} "
                        f"samples; expected at least {w.first_frame + w.frame_count}"
                    )
                parts.append(kept)
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
    seconds_per_frame = FRAME_SAMPLES / raw.sample_rate  # frame i starts at sample 320 * i
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
