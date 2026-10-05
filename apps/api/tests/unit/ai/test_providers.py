"""Pure parts of the speech adapters and the fakes (ADR 0028)."""

from pathlib import Path

import pytest

from listenup.ai.config import ProviderEntry
from listenup.ai.ports import Provenance
from listenup.ai.providers import fake
from listenup.ai.providers.faster_whisper import RawTranscription, to_transcript
from listenup.ai.providers.wav2vec2_ctc import (
    RawAlignment,
    Wav2Vec2CtcAlignment,
    alignable_words,
    to_alignment,
)

PROVENANCE = Provenance(provider="p", model="m", version="v")


def test_alignable_words_keep_their_place_in_the_reference() -> None:
    curly = "\N{RIGHT SINGLE QUOTATION MARK}"
    words = alignable_words(f"Café isn{curly}t open — 24 HOURS, 'really'!")
    assert [(w.index, w.text, w.tokens) for w in words] == [
        (0, "Café", "cafe"),
        (1, f"isn{curly}t", "isn't"),
        (2, "open", "open"),
        (5, "HOURS,", "hours"),
        (6, "'really'!", "really"),
    ]


def test_whisper_times_are_clamped_and_blank_words_dropped() -> None:
    raw = RawTranscription.model_validate(
        {
            "language": "en",
            "duration": 1.0,
            "segments": [
                {
                    "start": -0.02,
                    "end": 1.0,
                    "text": " Hi there. ",
                    "words": [
                        {"start": -0.02, "end": 0.3, "word": " Hi", "probability": 1.2},
                        {"start": 0.5, "end": 0.4, "word": " there.", "probability": -0.1},
                        {"start": 0.9, "end": 1.0, "word": "  ", "probability": 0.5},
                    ],
                }
            ],
        }
    )
    transcript = to_transcript(raw, PROVENANCE)
    hi, there = transcript.words
    assert (hi.start, hi.confidence) == (0.0, 1.0)
    assert (there.start, there.end, there.confidence) == (0.5, 0.5, 0.0)
    assert transcript.segments[0].text == "Hi there."


def test_alignment_converts_frames_to_seconds() -> None:
    words = alignable_words("go now")
    raw = RawAlignment(
        sample_rate=16000,
        num_samples=16000,
        num_frames=50,  # 20 ms a frame
        spans=[
            [{"start": 5, "end": 6, "score": 0.9}, {"start": 7, "end": 9, "score": 0.7}],
            [{"start": 20, "end": 21, "score": 0.8}] * 3,
        ],
    )
    result = to_alignment(words, raw, PROVENANCE)
    go = result.words[0]
    assert (go.start, go.end) == pytest.approx((0.1, 0.18))
    assert go.confidence == pytest.approx(0.8)
    assert [u.label for u in go.units] == ["g", "o"]


def test_alignment_refuses_a_word_count_mismatch() -> None:
    raw = RawAlignment(sample_rate=16000, num_samples=1, num_frames=1, spans=[])
    with pytest.raises(ValueError, match="0 words for 1"):
        to_alignment(alignable_words("go"), raw, PROVENANCE)


@pytest.mark.anyio
async def test_text_without_alignable_words_skips_the_model() -> None:
    class Loaded:
        version = "v"

        def run(self, audio: Path, words: list[str]) -> RawAlignment:
            raise AssertionError("the model must not run")

    adapter = Wav2Vec2CtcAlignment(
        ProviderEntry(provider="wav2vec2-ctc", model="MMS_FA"), engine_factory=lambda e: Loaded()
    )
    assert (await adapter.align(Path("a.wav"), "42 — 7")).words == ()


@pytest.mark.anyio
async def test_fake_transcription_reads_a_sidecar_text(tmp_path: Path) -> None:
    audio = tmp_path / "clip.mp4"
    audio.with_suffix(".txt").write_text("one two three")
    transcriber = fake.FakeTranscription(ProviderEntry(provider="fake"))
    transcript = await transcriber.transcribe(audio)
    assert [w.text for w in transcript.words] == ["one", "two", "three"]
    assert transcript.duration_seconds == pytest.approx(1.2)


@pytest.mark.anyio
async def test_fake_text_ai_needs_a_valid_registered_response() -> None:
    from pydantic import BaseModel

    from listenup.ai.ports import TextTask

    class Needs(BaseModel):
        value: int

    text_ai = fake.FakeTextAI(ProviderEntry(provider="fake"))
    with pytest.raises(ValueError, match="register one"):
        await text_ai.generate(TextTask("unknown", "v1"), {}, Needs)
