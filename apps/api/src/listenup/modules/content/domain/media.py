"""What makes an uploaded file usable, and the waveform peaks drawn from it (#36).

Pure rules, no I/O: the conversion job runs ffprobe and ffmpeg and hands their output
here. The file name and the browser's type are never trusted; only what ffprobe finds
in the bytes counts (Architecture 5.1, NFR-SEC-3).
"""

import json
from array import array
from dataclasses import dataclass, field
from typing import Any, Literal

# C2: every passage is 30 s to 15 min. A clip shorter than the shortest passage can
# never be practised; a longer clip is fine, since the learner picks a passage in it.
MIN_CLIP_MS = 30_000

# Containers ffprobe may report for the accepted upload types (files.ACCEPTED_TYPES):
# MP3, M4A, WAV, MP4, MOV and WEBM. ffprobe names formats as comma-separated aliases,
# for example "mov,mp4,m4a,3gp,3g2,mj2" or "matroska,webm".
ACCEPTED_FORMATS = frozenset({"mp3", "wav", "mov", "mp4", "m4a", "matroska", "webm"})

# The playback file (System Design 6.1).
PLAYBACK_AUDIO_BITRATE = "64k"
PLAYBACK_VIDEO_HEIGHT = 360

# Waveform peaks (System Design 6.1: about 2 KB per minute): ten values per second,
# each the loudest sample of its tenth of a second on a 0 to 100 scale.
PEAKS_PER_SECOND = 10
PEAKS_SCALE = 100
# The rate ffmpeg decodes to for peaks; enough to find the loud parts of speech.
PEAKS_SAMPLE_RATE = 8000
SAMPLES_PER_PEAK = PEAKS_SAMPLE_RATE // PEAKS_PER_SECOND
BYTES_PER_PEAK = SAMPLES_PER_PEAK * 2  # signed 16-bit mono
INT16_MAX = 32767

# How far the conversion job has got (#40): reading and probing the original, running
# ffmpeg, storing the outputs. Stored as `media_objects.stage` while it is prepared.
Stage = Literal["checking", "converting", "saving"]

# Why a media object failed, as the learner reads it. The code is stored on the media
# object (`error_code`); the text is chosen when it is shown.
FAILURE_MESSAGES: dict[str, str] = {
    "unsupported_media": (
        "This file isn't audio or video we can play, whatever its name says. "
        "Choose an MP3, M4A, WAV, MP4, MOV or WEBM file."
    ),
    "no_audio_track": "This file has no sound track. Choose a file with speech in it.",
    "clip_too_short": (
        "This clip is shorter than 30 seconds, the shortest passage you can practise. "
        "Choose a longer clip."
    ),
    "upload_missing": "We could not find the uploaded file. Upload it again.",
    "conversion_failed": (
        "We could not convert this file; it may be damaged. Try another copy of it."
    ),
    "processing_failed": (
        "Something went wrong while we prepared this clip. Delete it and upload the file again."
    ),
}


def failure_message(code: str | None) -> str | None:
    if code is None:
        return None
    return FAILURE_MESSAGES.get(code, FAILURE_MESSAGES["processing_failed"])


@dataclass(frozen=True)
class Probe:
    """The facts about a file that intake needs, from `ffprobe -show_format -show_streams`."""

    formats: frozenset[str]
    duration_ms: int | None
    has_audio: bool
    has_video: bool  # a real picture track, not an MP3's embedded cover art


@dataclass(frozen=True)
class MediaProblem:
    code: str
    detail: str


def parse_probe(output: str) -> Probe:
    """Read ffprobe's JSON. Raises ValueError when it is not ffprobe output."""
    data = json.loads(output)
    if not isinstance(data, dict):
        raise ValueError("ffprobe output is not an object")
    fmt: dict[str, Any] = data.get("format") or {}
    streams: list[dict[str, Any]] = data.get("streams") or []
    formats = frozenset(
        name.strip() for name in str(fmt.get("format_name", "")).split(",") if name.strip()
    )
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    video = [
        s
        for s in streams
        if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
    ]
    return Probe(formats, _duration_ms(fmt, audio), bool(audio), bool(video))


def _duration_ms(fmt: dict[str, Any], audio: list[dict[str, Any]]) -> int | None:
    """The sound track's length, or the file's when the stream does not say."""
    for value in [*(s.get("duration") for s in audio), fmt.get("duration")]:
        try:
            seconds = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            return round(seconds * 1000)
    return None


def check_probe(probe: Probe) -> MediaProblem | None:
    """Why this file cannot become a clip, or None when it can."""
    if not probe.formats & ACCEPTED_FORMATS:
        return _problem("unsupported_media")
    if not probe.has_audio:
        return _problem("no_audio_track")
    if probe.duration_ms is None:
        return _problem("unsupported_media")
    if probe.duration_ms < MIN_CLIP_MS:
        return _problem("clip_too_short")
    return None


def _problem(code: str) -> MediaProblem:
    return MediaProblem(code, FAILURE_MESSAGES[code])


@dataclass
class PeakMeter:
    """Turns a stream of signed 16-bit mono samples into waveform peaks.

    Feed it bytes in pieces of any size; each tenth of a second of samples becomes
    one value from 0 (silence) to 100 (full scale).
    """

    peaks: list[int] = field(default_factory=list)
    _pending: bytearray = field(default_factory=bytearray)

    def feed(self, data: bytes) -> None:
        self._pending += data
        whole = len(self._pending) - len(self._pending) % BYTES_PER_PEAK
        if whole == 0:
            return
        samples = array("h")
        samples.frombytes(bytes(self._pending[:whole]))
        del self._pending[:whole]
        for start in range(0, len(samples), SAMPLES_PER_PEAK):
            self.peaks.append(_scaled(samples[start : start + SAMPLES_PER_PEAK]))

    def finish(self) -> list[int]:
        usable = len(self._pending) - len(self._pending) % 2
        if usable:
            samples = array("h")
            samples.frombytes(bytes(self._pending[:usable]))
            self.peaks.append(_scaled(samples))
        self._pending.clear()
        return self.peaks


def _scaled(samples: "array[int]") -> int:
    loudest = max(max(samples), -min(samples))
    return min(PEAKS_SCALE, round(loudest * PEAKS_SCALE / INT16_MAX))


def peaks_json(peaks: list[int]) -> bytes:
    """The stored peaks file: compact JSON the browser draws without decoding audio."""
    return json.dumps(
        {"version": 1, "per_second": PEAKS_PER_SECOND, "scale": PEAKS_SCALE, "peaks": peaks},
        separators=(",", ":"),
    ).encode()


def media_prefix(learner: object, media_id: object) -> str:
    """Where an upload's files live: under the learner's prefix (Architecture 8.1)."""
    return f"users/{learner}/media/{media_id}/"


def playback_key(learner: object, media_id: object) -> str:
    return media_prefix(learner, media_id) + "playback.mp4"


def peaks_key(learner: object, media_id: object) -> str:
    return media_prefix(learner, media_id) + "peaks.json"
