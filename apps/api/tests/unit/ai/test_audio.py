"""The speech adapters' shared ffmpeg decoder (ADR 0033). Needs ffmpeg on the PATH."""

import struct
import subprocess
from pathlib import Path

import pytest

from listenup.ai.providers.audio import decode_pcm


def tone(path: Path, seconds: float) -> Path:
    subprocess.run(
        [
            *("ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi"),
            *("-i", f"sine=frequency=440:duration={seconds}", "-ac", "2", "-ar", "44100"),
            str(path),
        ],
        check=True,
    )
    return path


def test_decode_gives_mono_float_samples_at_the_requested_rate(tmp_path: Path) -> None:
    pcm = decode_pcm(tone(tmp_path / "tone.mp3", 0.5), 16000)
    samples = struct.unpack(f"<{len(pcm) // 4}f", pcm)
    assert len(samples) == pytest.approx(8000, abs=1200)  # mp3 adds encoder padding
    assert 0.1 < max(samples) <= 1.0  # a float signal, not integer PCM


def test_decode_refuses_a_file_that_is_not_media(tmp_path: Path) -> None:
    junk = tmp_path / "notes.txt"
    junk.write_text("not audio")
    with pytest.raises(ValueError, match=r"cannot decode notes\.txt"):
        decode_pcm(junk, 16000)
