"""Forced alignment for B2 and Shadow (#20), through the product's own aligner.

The model side (the torchaudio bundle, windows, int8, frame handling and the split into
one span per letter) is `listenup.ai.providers.wav2vec2_ctc.TorchaudioCtcEngine`, so the
spikes measure the code that ships and pick up its fixes. Run with
PYTHONPATH=../apps/api/src (the `speech` extra installs pydantic and PyYAML for it).
Two torchaudio bundles are used:
- `MMS_FA`: the multilingual MMS aligner (about 300M parameters, 1.2 GB), lower-case
  letters and apostrophe, no word separator.
- `WAV2VEC2_ASR_BASE_960H`: the English wav2vec2 base model fine-tuned on LibriSpeech
  960 h (95M parameters, 360 MB), upper-case letters, apostrophe and `|` between words.

This module keeps only the spike's text normalisation and the per-word summary that
Shadow's measures read.
"""

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
    def __init__(self, model: str = "MMS_FA", window_s: float = 0.0, int8: bool = False) -> None:
        import torch
        from listenup.ai.config import ProviderEntry
        from listenup.ai.providers import wav2vec2_ctc

        self._torch = torch
        self._frame_s = wav2vec2_ctc.FRAME_SAMPLES / SAMPLE_RATE
        self.model_name = model
        self.window_s = window_s
        entry = ProviderEntry(
            provider=wav2vec2_ctc.PROVIDER,
            model=model,
            # threads: keep what the caller set (OMP_NUM_THREADS, torch.set_num_threads)
            options={"window_seconds": window_s, "int8": int8, "threads": torch.get_num_threads()},
        )
        self.engine = wav2vec2_ctc.TorchaudioCtcEngine(entry)

    def align(self, audio: np.ndarray, text: str) -> list[AlignedWord]:
        """Align `text` to mono float samples at 16 kHz."""
        words = alignable_words(text)
        if not words:
            return []
        samples = self._torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))
        raw = self.engine.run_samples(samples, words)
        out = []
        for word, spans in zip(words, raw.spans, strict=True):
            scores = [span.score for span in spans]
            out.append(
                AlignedWord(
                    word=word,
                    start=spans[0].start * self._frame_s,
                    end=spans[-1].end * self._frame_s,
                    score=sum(scores) / len(scores),
                    last_score=scores[-1],
                )
            )
        return out
