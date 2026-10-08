"""ffmpeg/ffprobe helpers: probing, playback conversion, faststart check, peaks, decoding."""

import json
import struct
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

PLAYBACK_AUDIO_ARGS = ["-c:a", "aac", "-b:a", "64k", "-ac", "1"]


def probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    result: dict[str, Any] = json.loads(out)
    return result


def audio_codec(path: Path) -> str | None:
    for stream in probe(path).get("streams", []):
        if stream.get("codec_type") == "audio":
            codec: str | None = stream.get("codec_name")
            return codec
    return None


def duration_s(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def to_playback(src: Path, dst: Path, mode: str = "auto") -> str:
    """Write the AAC-in-MP4 faststart playback file (System Design 6.1).

    mode "copy" copies an AAC stream as is (no re-encode, keeps channels and bit rate);
    "encode" re-encodes to AAC-LC mono 64 kbit/s; "auto" copies when the source is AAC.
    Returns the mode actually used.
    """
    if mode == "auto":
        mode = "copy" if audio_codec(src) == "aac" else "encode"
    codec_args = ["-c:a", "copy"] if mode == "copy" else PLAYBACK_AUDIO_ARGS
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(src),
            "-vn",
            *codec_args,
            "-movflags",
            "+faststart",
            str(dst),
        ],
        check=True,
    )
    return mode


def is_faststart(path: Path) -> bool:
    """True when the MP4 'moov' atom comes before 'mdat', so playback can start at once."""
    with path.open("rb") as f:
        while True:
            header = f.read(8)
            if len(header) < 8:
                return False
            size, kind = struct.unpack(">I4s", header)
            if kind == b"moov":
                return True
            if kind == b"mdat":
                return False
            if size == 1:
                size = struct.unpack(">Q", f.read(8))[0]
                f.seek(size - 16, 1)
            elif size == 0:
                return False
            else:
                f.seek(size - 8, 1)


def decode(path: Path, sample_rate: int = 16000) -> np.ndarray:
    """Decode any input to mono float32 PCM in memory (the 'analysis audio'), with the
    same ffmpeg output as the product's speech adapters (`listenup.ai.providers.audio`)."""
    raw = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32)


def peaks(path: Path, per_second: int = 20) -> list[int]:
    """Waveform peaks 0-100 for the client to draw without decoding audio (System Design 6.1)."""
    rate = 8000
    audio = decode(path, rate)
    window = rate // per_second
    usable = len(audio) - len(audio) % window
    if usable == 0:
        return []
    blocks = np.abs(audio[:usable]).reshape(-1, window).max(axis=1)
    top = float(blocks.max()) or 1.0
    return [int(round(v / top * 100)) for v in blocks]
