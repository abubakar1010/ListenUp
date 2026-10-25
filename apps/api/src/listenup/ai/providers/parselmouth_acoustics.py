"""Local pitch/intensity evidence only; no assessment or calibrated scores (ADR 0050)."""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VERSION = "0.4.7"
SETTINGS = {
    "frame_step_ms": 20,
    "pitch_floor_hz": 60,
    "pitch_ceiling_hz": 500,
    "pitch_reference_hz": 1,
    "intensity_scale": 100,
    "subtract_mean": True,
}


@dataclass(frozen=True)
class AcousticTrack:
    pitch_cents: list[int | None]
    intensity_cdb: list[int | None]
    provenance: dict[str, Any]


def extract(audio: Path, duration_ms: int) -> AcousticTrack:
    import parselmouth

    if parselmouth.__version__ != VERSION:
        raise ValueError("Unvalidated Parselmouth version")
    sound = parselmouth.Sound(str(audio))
    # Praat needs a complete analysis window. Tiny cache gaps retain unknown
    # evidence rather than changing the accepted pitch floor to force a result.
    pitch = (
        sound.to_pitch(time_step=0.02, pitch_floor=60, pitch_ceiling=500)
        if sound.duration >= 3 / 60
        else None
    )
    intensity = (
        sound.to_intensity(minimum_pitch=60, time_step=0.02, subtract_mean=True)
        if sound.duration >= 6.4 / 60
        else None
    )
    cents: list[int | None] = []
    cdb: list[int | None] = []
    # Fixed frame centres in media-relative time. Praat's window margins stay unknown;
    # interpolation outside observable data must not fabricate edge evidence.
    for index in range(math.ceil(duration_ms / 20)):
        time = (index * 20 + 10) / 1000
        hz = float(pitch.get_value_at_time(time)) if pitch is not None else math.nan
        db = float(intensity.get_value(time)) if intensity is not None else math.nan
        cents.append(round(1200 * math.log2(hz)) if math.isfinite(hz) and hz > 0 else None)
        cdb.append(round(db * 100) if math.isfinite(db) and -300 < db < 300 else None)
    return AcousticTrack(
        cents,
        cdb,
        {
            "provider": "parselmouth",
            "model": "praat-pitch-intensity",
            "version": VERSION,
            "praat_version": parselmouth.PRAAT_VERSION,
            "settings": dict(SETTINGS),
        },
    )
