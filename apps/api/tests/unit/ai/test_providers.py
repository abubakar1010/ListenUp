"""Pure parts of the speech adapters and the fakes (ADR 0028)."""

from itertools import pairwise
from pathlib import Path

import pytest

from listenup.ai.config import ProviderEntry
from listenup.ai.errors import AIConfigError
from listenup.ai.ports import Provenance
from listenup.ai.providers import fake
from listenup.ai.providers.faster_whisper import RawTranscription, to_transcript
from listenup.ai.providers.wav2vec2_ctc import (
    FRAME_SAMPLES,
    WINDOW_CONTEXT_SAMPLES,
    RawAlignment,
    RawSpan,
    Vocabulary,
    Wav2Vec2CtcAlignment,
    Window,
    alignable_words,
    emission_windows,
    model_frames,
    settings_label,
    spans_per_word,
    to_alignment,
    window_seconds_option,
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


def test_model_frames_match_the_wav2vec2_conv_front_end() -> None:
    layers = [(10, 5), (3, 2), (3, 2), (3, 2), (3, 2), (2, 2), (2, 2)]  # kernel, stride

    def conv_stack(samples: int) -> int:
        for kernel, stride in layers:
            samples = max((samples - kernel) // stride + 1, 0)
        return samples

    assert all(model_frames(n) == conv_stack(n) for n in range(0, 20000, 7))


def kept_frames_after_running_the_model(windows: list[Window]) -> int:
    total = 0
    for w in windows:
        produced = model_frames(w.input_end - w.input_start + w.pad_end)
        assert produced >= w.first_frame + w.frame_count  # never a short slice
        total += w.frame_count
    return total


@pytest.mark.parametrize("window_seconds", [0, 30])
@pytest.mark.parametrize("n", [16000, 112960, 2_880_000, 75 * 16000 + 123, 2_880_000 + 79])
def test_every_frame_of_the_audio_is_kept_once(window_seconds: float, n: int) -> None:
    windows = emission_windows(n, window_seconds, 16000)
    assert kept_frames_after_running_the_model(windows) == n // FRAME_SAMPLES
    assert windows[0].start == 0 and windows[-1].end == n
    assert all(b.start == a.end for a, b in pairwise(windows))


def test_emission_windows_cover_the_audio_in_whole_frames_with_context() -> None:
    n = 75 * 16000 + 123
    whole = emission_windows(n, 0, 16000)
    assert [(w.start, w.end, w.input_start, w.input_end) for w in whole] == [(0, n, 0, n)]
    windows = emission_windows(n, 30, 16000)
    assert [(w.start, w.end) for w in windows] == [(0, 480000), (480000, 960000), (960000, n)]
    for w in windows:
        assert w.input_start == max(0, w.start - WINDOW_CONTEXT_SAMPLES)
        assert w.input_end == min(n, w.end + WINDOW_CONTEXT_SAMPLES)
        assert (w.start - w.input_start) % FRAME_SAMPLES == 0
    assert windows[1].first_frame == 50 and windows[1].frame_count == 1500
    assert [w.pad_end for w in windows] == [0, 0, 0]  # 123 left over: the last frame fits


def test_the_last_window_is_padded_when_its_last_frame_lacks_samples() -> None:
    n = 2_880_000  # 3 minutes: six exact 30 s windows, nothing left over
    windows = emission_windows(n, 30, 16000)
    assert [w.pad_end for w in windows] == [0] * 5 + [80]
    assert emission_windows(n, 0, 16000)[0].pad_end == 80


def test_emission_windows_refuse_audio_or_windows_shorter_than_a_frame() -> None:
    with pytest.raises(ValueError, match="too short"):
        emission_windows(0, 30, 16000)
    with pytest.raises(ValueError, match="shorter than one frame"):
        emission_windows(16000, 0.01, 16000)


@pytest.mark.parametrize("value", [-1, 0.01, 0.5])
def test_window_seconds_must_be_zero_or_a_second_or_more(value: float) -> None:
    entry = ProviderEntry(provider="wav2vec2-ctc", options={"window_seconds": value})
    with pytest.raises(AIConfigError, match="window_seconds"):
        window_seconds_option(entry)
    assert window_seconds_option(ProviderEntry(provider="wav2vec2-ctc")) == 0


def test_provenance_tells_windowed_and_int8_runs_apart() -> None:
    labels = {settings_label(w, q) for w in (0, 15, 30) for q in (False, True)}
    assert len(labels) == 6
    assert settings_label(30, True) == "window 30s; int8"


MMS = Vocabulary.from_labels(("-", "a", "o", "g", "n", "w", "'", *"bcdefhijklmpqrstuvxyz"))
ASR = Vocabulary.from_labels(("-", "|", "A", "O", "G", "N", "W", "'", *"BCDEFHIJKLMPQRSTUVXYZ"))


def test_vocabulary_reads_case_separator_and_blank_from_the_labels() -> None:
    assert (MMS.upper_case, MMS.separator, MMS.blank) == (False, None, 0)
    assert (ASR.upper_case, ASR.separator, ASR.blank) == (True, 1, 0)


def test_vocabulary_refuses_labels_that_cannot_spell_our_words() -> None:
    with pytest.raises(AIConfigError, match="lack '-'"):
        Vocabulary.from_labels(("<s>", *"abcdefghijklmnopqrstuvwxyz'"))
    with pytest.raises(AIConfigError, match='lack "\'"'):
        Vocabulary.from_labels(("-", "|", *"ABCDEFGHIJKLMNOPQRSTUVWXYZ"))


def test_targets_add_the_word_separator_only_where_the_model_has_one() -> None:
    assert MMS.targets(["go", "now"]) == [3, 2, 4, 2, 5]
    assert ASR.targets(["go", "now"]) == [4, 3, 1, 5, 3, 6]


def test_spans_per_word_drop_the_separator_spans() -> None:
    tokens = ASR.targets(["go", "now"])
    spans = [RawSpan(start=i, end=i + 1, score=0.5) for i in range(len(tokens))]
    go, now = spans_per_word(spans, tokens, ["go", "now"], ASR)
    assert [s.start for s in go] == [0, 1]
    assert [s.start for s in now] == [3, 4, 5]  # span 2 was the separator


def test_spans_per_word_refuses_a_span_count_mismatch() -> None:
    with pytest.raises(ValueError, match="1 spans for 2 tokens"):
        spans_per_word([RawSpan(start=0, end=1, score=1.0)], [3, 2], ["go"], MMS)
