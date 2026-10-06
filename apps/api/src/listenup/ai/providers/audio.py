"""Audio decoding shared by the self-hosted speech adapters.

Both engines get their samples from ffmpeg (installed in the worker-media image) rather
than from a library's own decoder: faster-whisper 1.2.1 decodes through PyAV with an
argument PyAV 19 removed, so handing it a file path fails (spike #18, ADR 0033).
"""

import subprocess
from pathlib import Path


def decode_pcm(audio: Path, sample_rate: int) -> bytes:
    """Mono 32-bit float little-endian PCM at `sample_rate`, through ffmpeg."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(audio),
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"cannot decode {audio.name}: {result.stderr.decode(errors='replace')[:200]}"
        )
    return result.stdout
