"""ffprobe and ffmpeg as subprocesses, so the worker's event loop never blocks (ADR 0015).

`probe` reads what a file really holds. `convert` writes the playback file
(System Design 6.1: AAC-LC, mono, 64 kbit/s, MP4 with the index at the front; H.264
360p only when the learner keeps the video) and, from the same decode, the waveform
peaks.
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from pathlib import Path

from listenup.modules.content.domain.media import (
    PEAKS_SAMPLE_RATE,
    PLAYBACK_AUDIO_BITRATE,
    PLAYBACK_VIDEO_HEIGHT,
    PeakMeter,
    Probe,
    parse_probe,
)

logger = logging.getLogger(__name__)

FFPROBE = "ffprobe"
FFMPEG = "ffmpeg"
READ_CHUNK = 64 * 1024
# What is kept of ffmpeg's error output for the logs.
STDERR_TAIL = 2000


class ToolFailed(Exception):
    """ffprobe or ffmpeg could not read or convert the file."""

    def __init__(self, tool: str, returncode: int | None, stderr: str) -> None:
        super().__init__(f"{tool} exited with {returncode}: {stderr[-STDERR_TAIL:]}")
        self.stderr = stderr


@dataclass(frozen=True)
class Converted:
    peaks: list[int]
    has_video: bool


async def probe(path: Path) -> Probe:
    """What the file holds; raises ToolFailed when ffprobe cannot read it as media."""
    process = await asyncio.create_subprocess_exec(
        FFPROBE,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await process.communicate()
    finally:
        _stop(process)
    if process.returncode != 0:
        raise ToolFailed(FFPROBE, process.returncode, stderr.decode(errors="replace"))
    try:
        return parse_probe(stdout.decode(errors="replace"))
    except ValueError as error:
        raise ToolFailed(FFPROBE, process.returncode, str(error)) from error


def convert_args(source: Path, target: Path, *, video: bool) -> list[str]:
    """ffmpeg's arguments: the playback file to `target`, raw samples for peaks to stdout."""
    args = [FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    # Output 1: the playback file.
    args += ["-map", "0:a:0"]
    if video:
        args += [
            "-map",
            "0:V:0",  # capital V: a real video track, never cover art
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-profile:v",
            "main",
            "-pix_fmt",
            "yuv420p",
            # At most 360 lines, never upscaled; both sides even, as yuv420p needs.
            "-vf",
            f"scale=-2:'trunc(min({PLAYBACK_VIDEO_HEIGHT},ih)/2)*2'",
        ]
    args += [
        "-c:a",
        "aac",
        "-profile:a",
        "aac_low",
        "-b:a",
        PLAYBACK_AUDIO_BITRATE,
        "-ac",
        "1",
        "-map_metadata",
        "-1",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(target),
    ]
    # Output 2: mono 16-bit samples at a low rate, read for the waveform peaks.
    args += [
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(PEAKS_SAMPLE_RATE),
        "-f",
        "s16le",
        "-c:a",
        "pcm_s16le",
        "pipe:1",
    ]
    return args


async def convert(source: Path, target: Path, *, video: bool) -> Converted:
    """Write the playback file and measure its peaks in one decode of the source."""
    process = await asyncio.create_subprocess_exec(
        *convert_args(source, target, video=video),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    meter = PeakMeter()

    async def read_samples() -> None:
        assert process.stdout is not None
        while chunk := await process.stdout.read(READ_CHUNK):
            meter.feed(chunk)

    try:
        # Both pipes are drained together, so neither can fill up and stall ffmpeg.
        _, stderr = await asyncio.gather(read_samples(), process.stderr.read())
        await process.wait()
    finally:
        _stop(process)
    if process.returncode != 0:
        raise ToolFailed(FFMPEG, process.returncode, stderr.decode(errors="replace"))
    return Converted(meter.finish(), video)


def _stop(process: asyncio.subprocess.Process) -> None:
    """Kill the tool if the job ended early (a timeout or a cancelled worker)."""
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
