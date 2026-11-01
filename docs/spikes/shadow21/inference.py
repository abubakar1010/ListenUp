"""Bound model work to VAD speech windows; retain the original 20 ms clock."""

from types import SimpleNamespace

import torch


class Windowed:
    def __init__(self, model, phone):
        self.model, self.phone = model, phone
        self.spans = []
        self.labels = None

    def __call__(self, waveform=None, **inputs):
        audio = inputs["input_values"] if self.phone else waveform
        frames = (audio.shape[-1] + 319) // 320
        output = None
        for start, end in self.spans:
            clip = audio[:, start:end]
            if self.phone:
                logits = self.model(input_values=clip).logits
            else:
                logits, _ = self.model(clip)
            self.labels = logits.shape[-1]
            if output is None:
                output = self._blank(frames)
            offset = round(start / 320)
            length = min(logits.shape[1], frames - offset)
            output[:, offset : offset + length] = logits[:, :length]
        if output is None:
            output = self._blank(frames)
        return SimpleNamespace(logits=output) if self.phone else (output, None)

    def _blank(self, frames):
        if self.labels is None:
            raise ValueError("Label count required before an all-silence recording")
        output = torch.full((1, frames, self.labels), -10000.0)
        output[:, :, 0] = 0
        return output
