"""Forced alignment with torchaudio MMS_FA (wav2vec2 CTC), shared by B2 and Shadow."""

import re
from dataclasses import dataclass

import numpy as np

from listenup_spikes.metrics import normalize_words

SAMPLE_RATE = 16000


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


class Aligner:
    def __init__(self) -> None:
        import torch
        import torchaudio

        self._torch = torch
        bundle = torchaudio.pipelines.MMS_FA
        self.model = bundle.get_model(with_star=False)
        self.tokenizer = bundle.get_tokenizer()
        self.aligner = bundle.get_aligner()

    def align(self, audio: np.ndarray, text: str) -> list[AlignedWord]:
        torch = self._torch
        words = alignable_words(text)
        waveform = torch.from_numpy(audio).unsqueeze(0)
        with torch.inference_mode():
            emission, _ = self.model(waveform)
        spans = self.aligner(emission[0], self.tokenizer(words))
        seconds_per_frame = waveform.size(1) / emission.size(1) / SAMPLE_RATE
        out = []
        for word, word_spans in zip(words, spans, strict=True):
            scores = [s.score for s in word_spans]
            out.append(
                AlignedWord(
                    word=word,
                    start=word_spans[0].start * seconds_per_frame,
                    end=word_spans[-1].end * seconds_per_frame,
                    score=float(sum(scores) / len(scores)),
                    last_score=float(scores[-1]),
                )
            )
        return out
