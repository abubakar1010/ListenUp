"""Characterize the speech-library boundary without downloads or model inference.

These fakes validate adapter wiring, not real model accuracy (spikes B1/B2).
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call

import pytest

from listenup.ai.config import ProviderEntry
from listenup.ai.providers.faster_whisper import FasterWhisperEngine
from listenup.ai.providers.wav2vec2_ctc import TorchaudioCtcEngine


@pytest.mark.parametrize("model_name", ["MMS_FA", "WAV2VEC2_ASR_BASE_960H"])
@pytest.mark.parametrize("int8", [False, True])
@pytest.mark.parametrize("window_seconds", [0, 30])
def test_ctc_engine_uses_bundle_targets_and_keeps_only_window_frames(
    monkeypatch: pytest.MonkeyPatch, model_name: str, int8: bool, window_seconds: int
) -> None:
    class FaBundle:
        sample_rate = 16000

    bundle = FaBundle() if model_name == "MMS_FA" else SimpleNamespace(sample_rate=16000)
    model = Mock()
    quantized = Mock()
    get_model = Mock(return_value=model)
    is_mms = model_name == "MMS_FA"
    labels = ("-", "a", "b") if is_mms else ("-", "|", "A", "B")
    monkeypatch.setattr(bundle, "get_model", get_model, raising=False)
    get_labels = Mock(return_value=labels)
    monkeypatch.setattr(bundle, "get_labels", get_labels, raising=False)
    torch = MagicMock()
    waveform = MagicMock()
    waveform.size.return_value = 61 * 16000
    torch.frombuffer.return_value.unsqueeze.return_value = waveform
    emissions = [MagicMock() for _ in range(3 if window_seconds else 1)]
    active_model = quantized if int8 else model
    active_model.side_effect = [(emission, None) for emission in emissions]
    torch.ao.quantization.quantize_dynamic.return_value = quantized
    log_probs = torch.log_softmax.return_value
    log_probs.size.return_value = 3050
    functional = Mock()
    aligned_labels, scores = MagicMock(), MagicMock()
    functional.forced_align.return_value = (aligned_labels, scores)
    # ASR has a separator span between the two one-letter words; MMS does not.
    span_indices = [0, 1] if is_mms else [0, 1, 2]
    functional.merge_tokens.return_value = [
        SimpleNamespace(start=i * 10, end=i * 10 + 5, score=0.8) for i in span_indices
    ]
    pipelines = SimpleNamespace(Wav2Vec2FABundle=FaBundle, **{model_name: bundle})
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(
        sys.modules, "torchaudio", SimpleNamespace(pipelines=pipelines, functional=functional)
    )
    decode = Mock(return_value=b"pcm")
    monkeypatch.setattr("listenup.ai.providers.wav2vec2_ctc.decode_pcm", decode)
    engine = TorchaudioCtcEngine(
        ProviderEntry(
            provider="wav2vec2-ctc",
            model=model_name,
            options={"threads": 3, "int8": int8, "window_seconds": window_seconds},
        )
    )
    result = engine.run(Path("clip.mp4"), ["a", "b"])

    torch.set_num_threads.assert_called_once_with(3)
    get_model.assert_called_once_with(**({"with_star": False} if is_mms else {}))
    get_labels.assert_called_once_with(**({"star": None} if is_mms else {}))
    if int8:
        torch.ao.quantization.quantize_dynamic.assert_called_once_with(
            model, {torch.nn.Linear}, dtype=torch.qint8
        )
        model.assert_not_called()
    else:
        torch.ao.quantization.quantize_dynamic.assert_not_called()
    decode.assert_called_once_with(Path("clip.mp4"), 16000)
    torch.frombuffer.assert_called_once_with(bytearray(b"pcm"), dtype=torch.float32)
    torch.inference_mode.return_value.__enter__.assert_called_once()
    input_ranges = [(0, 496000), (464000, 976000), (944000, 976000)]
    kept_ranges = [(0, 1500), (50, 1550), (50, 100)]
    if window_seconds:
        assert waveform.__getitem__.call_args_list == [
            call((slice(None), slice(start, end))) for start, end in input_ranges
        ]
        parts = []
        for emission, (start, end) in zip(emissions, kept_ranges, strict=True):
            emission.__getitem__.assert_called_once_with((slice(None), slice(start, end)))
            trimmed = emission.__getitem__.return_value
            trimmed.__getitem__.assert_called_once_with(0)
            parts.append(trimmed.__getitem__.return_value)
    else:
        waveform.__getitem__.assert_called_once_with((slice(None), slice(0, 976000)))
        emissions[0].__getitem__.assert_called_once_with(0)
        parts = [emissions[0].__getitem__.return_value]
    assert active_model.call_count == len(emissions)
    torch.cat.assert_called_once_with(parts)
    torch.log_softmax.assert_called_once_with(torch.cat.return_value, dim=-1)
    torch.tensor.assert_called_once_with([[1, 2] if is_mms else [2, 1, 3]], dtype=torch.int32)
    functional.forced_align.assert_called_once_with(
        log_probs.unsqueeze.return_value, torch.tensor.return_value, blank=0
    )
    functional.merge_tokens.assert_called_once_with(
        aligned_labels[0], scores[0].exp.return_value, blank=0
    )
    scores[0].exp.assert_called_once_with()
    assert (result.sample_rate, result.num_samples, result.num_frames) == (16000, 976000, 3050)
    assert [[(s.start, s.end, s.score) for s in spans] for spans in result.spans] == [
        [(0, 5, 0.8)],
        [(10, 15, 0.8)] if is_mms else [(20, 25, 0.8)],
    ]


def test_whisper_decodes_pcm_and_materializes_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    model_factory = Mock()
    model = model_factory.return_value
    word = SimpleNamespace(start=0.1, end=0.4, word=" Hello", probability=0.9)
    segment = SimpleNamespace(start=0.0, end=0.5, text=" Hello", words=[word])
    empty = SimpleNamespace(start=0.5, end=0.6, text="", words=None)
    model.transcribe.return_value = (
        iter([segment, empty]),
        SimpleNamespace(language="en", duration=0.6),
    )
    numpy = Mock()
    monkeypatch.setitem(sys.modules, "numpy", numpy)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=model_factory))
    decode = Mock(return_value=b"pcm")
    monkeypatch.setattr("listenup.ai.providers.faster_whisper.decode_pcm", decode)
    engine = FasterWhisperEngine(
        ProviderEntry(
            provider="faster-whisper",
            model="small.en",
            options={
                "compute_type": "int8",
                "cpu_threads": 3,
                "beam_size": 2,
                "vad_filter": False,
                "download_root": "/models",
            },
        )
    )
    result = engine.run(Path("clip.mp4"), "en")
    model_factory.assert_called_once_with(
        "small.en", device="cpu", compute_type="int8", cpu_threads=3, download_root="/models"
    )
    decode.assert_called_once_with(Path("clip.mp4"), 16000)
    numpy.frombuffer.assert_called_once_with(b"pcm", dtype=numpy.float32)
    model.transcribe.assert_called_once_with(
        numpy.frombuffer.return_value,
        language="en",
        beam_size=2,
        vad_filter=False,
        word_timestamps=True,
    )
    assert result.model_dump() == {
        "language": "en",
        "duration": 0.6,
        "segments": [
            {"start": 0.0, "end": 0.5, "text": " Hello", "words": [vars(word)]},
            {"start": 0.5, "end": 0.6, "text": "", "words": []},
        ],
    }
