import shutil
import subprocess
from pathlib import Path

import pytest

from listenup_spikes.media import audio_codec, decode, duration_s, is_faststart, peaks, to_playback

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def tone(path: Path, codec: list[str], seconds: int = 3) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-ac",
            "2",
            *codec,
            str(path),
        ],
        check=True,
    )
    return path


def test_aac_source_is_copied_and_faststart(tmp_path: Path) -> None:
    src = tone(tmp_path / "in.m4a", ["-c:a", "aac", "-b:a", "128k"])
    out = tmp_path / "out.m4a"
    assert to_playback(src, out) == "copy"
    assert is_faststart(out)
    assert audio_codec(out) == "aac"


def test_non_aac_source_is_encoded_mono(tmp_path: Path) -> None:
    src = tone(tmp_path / "in.mp3", ["-c:a", "libmp3lame"])
    out = tmp_path / "out.m4a"
    assert to_playback(src, out) == "encode"
    assert is_faststart(out)
    stream = next(s for s in __import__("listenup_spikes.media").media.probe(out)["streams"])
    assert stream["channels"] == 1


def test_mp4_without_faststart_is_detected(tmp_path: Path) -> None:
    src = tone(tmp_path / "slow.m4a", ["-c:a", "aac"])
    assert not is_faststart(src)  # ffmpeg writes moov at the end unless +faststart


def test_decode_and_peaks(tmp_path: Path) -> None:
    src = tone(tmp_path / "in.wav", [], seconds=2)
    audio = decode(src)
    assert len(audio) == 32000
    assert duration_s(src) == pytest.approx(2.0, abs=0.05)
    p = peaks(src, per_second=20)
    assert len(p) == 40 and max(p) == 100
