"""Forced alignment with wav2vec2 CTC models in torchaudio, shared by B2 and Shadow.

Two torchaudio bundles are supported:
- `MMS_FA`: the multilingual MMS aligner (about 300M parameters, 1.2 GB), lower-case
  letters and apostrophe, no word separator.
- `WAV2VEC2_ASR_BASE_960H`: the English wav2vec2 base model fine-tuned on LibriSpeech
  960 h (95M parameters, 360 MB), upper-case letters, apostrophe and `|` between words.

Both use the same path: emissions (optionally in windows, see `emissions`), then
`torchaudio.functional.forced_align` over the words' letters, then one span per letter.
"""

import re
from dataclasses import dataclass

import numpy as np

from listenup_spikes.metrics import normalize_words

SAMPLE_RATE = 16000
FRAME_SAMPLES = 320  # both models: one emission frame per 20 ms
CONTEXT_S = 1.0  # audio added on each side of a window, then dropped


@dataclass(frozen=True)
class AlignedWord:
    word: str
    start: float  # seconds
    end: float
    score: float  # mean CTC posterior of the word's characters, 0..1
    last_score: float  # posterior of the final character (word endings, articulation proxy)


def alignable_words(text: str) -> list[str]:
    """Words in the aligner's alphabet (a-z and apostrophe). Digits are dropped, so number
    words should be spelled out in references for best results."""
    words = [re.sub(r"[^a-z']", "", w) for w in normalize_words(text)]
    return [w for w in words if w.strip("'")]


def window_bounds(num_samples: int, window_s: float) -> list[tuple[int, int, int, int]]:
    """Windows for chunked emissions: (start, end, input_start, input_end) in samples.

    Each window [start, end) is a whole number of frames; the model sees CONTEXT_S more
    on each side (clamped to the audio), and only the frames of [start, end) are kept,
    so every frame comes from audio with context around it."""
    step = round(window_s * SAMPLE_RATE) // FRAME_SAMPLES * FRAME_SAMPLES
    context = round(CONTEXT_S * SAMPLE_RATE) // FRAME_SAMPLES * FRAME_SAMPLES
    out = []
    for start in range(0, num_samples, step):
        end = min(start + step, num_samples)
        out.append((start, end, max(0, start - context), min(num_samples, end + context)))
    return out


class Aligner:
    def __init__(self, model: str = "MMS_FA", window_s: float = 0.0, int8: bool = False) -> None:
        import torch
        import torchaudio

        self._torch = torch
        self._functional = torchaudio.functional
        bundle = getattr(torchaudio.pipelines, model)
        self.model_name = model
        self.window_s = window_s
        if model == "MMS_FA":
            self.model = bundle.get_model(with_star=False)
            labels = bundle.get_labels(star=None)
            self._upper, self._separator = False, None
        else:
            self.model = bundle.get_model()
            labels = bundle.get_labels()
            self._upper, self._separator = True, labels.index("|")
        if int8:  # dynamic int8 quantisation of the linear layers (weights int8, CPU only)
            self.model = torch.ao.quantization.quantize_dynamic(
                self.model, {torch.nn.Linear}, dtype=torch.qint8
            )
        self._index = {label: i for i, label in enumerate(labels)}
        self._blank = 0  # "-" in both bundles

    def emissions(self, audio: np.ndarray) -> "object":
        """Log-probabilities per frame, (frames, labels). With window_s > 0 the audio is
        run in windows (with context) and the frames are joined, which bounds memory:
        self-attention over a whole 3-minute passage grows with its length squared."""
        torch = self._torch
        waveform = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32)).unsqueeze(0)
        with torch.inference_mode():
            if self.window_s <= 0:
                emission, _ = self.model(waveform)
                return torch.log_softmax(emission[0], dim=-1)
            parts = []
            for start, end, in_start, in_end in window_bounds(len(audio), self.window_s):
                emission, _ = self.model(waveform[:, in_start:in_end])
                first = (start - in_start) // FRAME_SAMPLES
                count = (end - start) // FRAME_SAMPLES
                parts.append(emission[0, first : first + count])
            return torch.log_softmax(torch.cat(parts), dim=-1)

    def _targets(self, words: list[str]) -> tuple[list[int], list[int]]:
        """Label ids for the words' letters (with `|` between words where the model has
        it) and, for each word, how many of the ids are its letters."""
        ids, lengths = [], []
        for i, word in enumerate(words):
            letters = word.upper() if self._upper else word
            if i and self._separator is not None:
                ids.append(self._separator)
            ids.extend(self._index[c] for c in letters)
            lengths.append(len(letters))
        return ids, lengths

    def align(self, audio: np.ndarray, text: str) -> list[AlignedWord]:
        torch = self._torch
        words = alignable_words(text)
        if not words:
            return []
        emission = self.emissions(audio)
        ids, lengths = self._targets(words)
        targets = torch.tensor([ids], dtype=torch.int32)
        with torch.inference_mode():
            labels, scores = self._functional.forced_align(
                emission.unsqueeze(0), targets, blank=self._blank
            )
        spans = self._functional.merge_tokens(labels[0], scores[0].exp(), blank=self._blank)
        if self._separator is not None:
            spans = [s for s in spans if s.token != self._separator]
        seconds_per_frame = len(audio) / emission.size(0) / SAMPLE_RATE
        out, cursor = [], 0
        for word, length in zip(words, lengths, strict=True):
            word_spans = spans[cursor : cursor + length]
            cursor += length
            word_scores = [float(s.score) for s in word_spans]
            out.append(
                AlignedWord(
                    word=word,
                    start=word_spans[0].start * seconds_per_frame,
                    end=word_spans[-1].end * seconds_per_frame,
                    score=sum(word_scores) / len(word_scores),
                    last_score=word_scores[-1],
                )
            )
        return out
