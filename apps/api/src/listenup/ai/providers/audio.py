"""Audio decoding shared by the self-hosted speech adapters.

Both engines get their samples from ffmpeg (installed in the worker-media image) rather
than from a library's own decoder, so transcription and alignment see the same samples.
faster-whisper 1.2.1 decodes through PyAV with an argument PyAV 19 removed (spike #18,
ADR 0033); the `speech` extra keeps PyAV below 19 for anything that still uses that path.
"""

import subprocess
from pathlib import Path


def decode_pcm(audio: Path, sample_rate: int, *, timeout_seconds: float) -> bytes:
    """Mono 32-bit float little-endian PCM at `sample_rate`, through ffmpeg.

    The engines run in a worker thread that the gateway's timeout cannot stop, so the
    decode has its own: ffmpeg is killed and `TimeoutError` raised when it runs over."""
    try:
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
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"decoding {audio.name} took over {timeout_seconds:g} s") from exc
    if result.returncode != 0:
        raise ValueError(
            f"cannot decode {audio.name}: {result.stderr.decode(errors='replace')[:200]}"
        )
    return result.stdout
