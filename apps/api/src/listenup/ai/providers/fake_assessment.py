"""Synthetic second assessment provider for E2/AT-22; no audio is read or graded.

The deliberately imperfect scores and nonempty signals exercise downstream consumers.
`synthetic` labels are placeholders, never phoneme-model output or quality evidence.
"""

import asyncio
from itertools import pairwise
from pathlib import Path

from listenup.ai.config import ProviderEntry
from listenup.ai.ports import (
    Filler,
    PitchPoint,
    Provenance,
    SoundScore,
    Span,
    SpeechAssessment,
    WordScore,
)

PROVIDER = "fake-assessment"
VERSION = "1"


class FakeAssessment:
    """Place each word in 0.4 s with a 0.1 s gap; append one synthetic filler."""

    def __init__(self, entry: ProviderEntry) -> None:
        self._entry = entry

    async def assess(
        self, recording: Path, reference_text: str, reference_audio: Path
    ) -> SpeechAssessment:
        await asyncio.sleep(0)
        words = tuple(
            WordScore(
                index=i,
                text=token,
                start=i * 0.5,
                end=i * 0.5 + 0.4,
                accuracy=0.75,
                sounds=(
                    SoundScore(label="synthetic", start=i * 0.5, end=i * 0.5 + 0.4, score=0.75),
                ),
            )
            for i, token in enumerate(reference_text.split())
        )
        return SpeechAssessment(
            provenance=Provenance(provider=PROVIDER, model=self._entry.model, version=VERSION),
            words=words,
            pauses=tuple(Span(start=a.end, end=b.start) for a, b in pairwise(words)),
            fillers=(Filler(text="um", start=words[-1].end, end=words[-1].end + 0.2),)
            if words
            else (),
            pitch=tuple(
                point
                for word in words
                for point in (
                    PitchPoint(time=word.start, hertz=120),
                    PitchPoint(time=word.end, hertz=None),
                )
            ),
        )
