"""Spike #17: YouTube link to playable file, with rejection rules and timings.

Usage (on the stage 0 server, public test videos only):
    spike-youtube urls.txt --out results/
urls.txt: one URL per line, optionally followed by a label after whitespace.
"""

import argparse
import tempfile
from pathlib import Path
from typing import Any

from listenup_spikes.common import Report, measure
from listenup_spikes.media import duration_s, is_faststart, peaks, to_playback
from listenup_spikes.metrics import percentile

BUDGET_S = 45.0  # System Design 3.2: 10-minute clip playable in under 45 s at p95


def reject_reason(info: dict[str, Any], max_minutes: float) -> str | None:
    """Rejection from metadata alone (FR-CI-3). None means the video is acceptable."""
    availability = info.get("availability")
    if availability in {"private", "premium_only", "subscriber_only", "needs_auth"}:
        return f"not public ({availability})"
    if (info.get("age_limit") or 0) >= 18:
        return "age-restricted"
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
        return "live or upcoming"
    duration = info.get("duration")
    if duration is None:
        return "unknown duration"
    if duration > max_minutes * 60:
        return f"longer than {max_minutes:g} min"
    return None


def caption_kind(info: dict[str, Any]) -> str:
    if any(k.startswith("en") for k in (info.get("subtitles") or {})):
        return "creator"
    if any(k.startswith("en") for k in (info.get("automatic_captions") or {})):
        return "auto-only"
    return "none"


def error_reason(message: str) -> str:
    text = message.lower()
    for needle, reason in (
        ("private", "not public (private)"),
        ("sign in to confirm your age", "age-restricted"),
        ("age", "age-restricted"),
        ("live", "live or upcoming"),
        ("unavailable", "unavailable"),
    ):
        if needle in text:
            return reason
    return "error: " + message.splitlines()[0][:80]


def run_one(url: str, label: str, max_minutes: float, work: Path, report: Report) -> None:
    import yt_dlp  # imported here so the pure helpers can be tested without yt-dlp

    base = {"quiet": True, "no_warnings": True, "noplaylist": True}
    try:
        with measure() as t_meta, yt_dlp.YoutubeDL({**base, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        report.add(label=label, reject=error_reason(str(exc)))
        return
    reason = reject_reason(info, max_minutes)
    row: dict[str, Any] = {
        "label": label,
        "duration_s": info.get("duration"),
        "captions": caption_kind(info),
        "metadata_s": round(t_meta.wall_s, 2),
        "reject": reason,
    }
    if reason:
        report.add(**row)
        return
    target = work / f"{info['id']}.%(ext)s"
    with (
        measure() as t_dl,
        yt_dlp.YoutubeDL(
            {**base, "format": "bestaudio[ext=m4a]/bestaudio", "outtmpl": str(target)}
        ) as ydl,
    ):
        ydl.download([url])
    src = next(work.glob(f"{info['id']}.*"))
    playback = work / f"{info['id']}.playback.m4a"
    with measure() as t_conv:
        mode = to_playback(src, playback, "auto")
    encoded = work / f"{info['id']}.encoded.m4a"
    with measure() as t_enc:
        to_playback(src, encoded, "encode")
    with measure() as t_peaks:
        peaks(playback)
    row |= {
        "download_s": round(t_dl.wall_s, 2),
        "source_codec_copy": mode == "copy",
        "convert_s": round(t_conv.wall_s, 2),
        "encode_s": round(t_enc.wall_s, 2),
        "faststart": is_faststart(playback),
        "peaks_s": round(t_peaks.wall_s, 2),
        "playable_s": round(t_meta.wall_s + t_dl.wall_s + t_conv.wall_s, 2),
        "playback_mb": round(playback.stat().st_size / 1e6, 2),
        "encoded_mb": round(encoded.stat().st_size / 1e6, 2),
        "check_duration_s": round(duration_s(playback), 1),
    }
    report.add(**row)
    for f in work.glob(f"{info['id']}*"):
        f.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", type=Path)
    parser.add_argument("--out", type=Path, default=Path("results"))
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=120.0,
        help="reject longer videos (daily intake cap, D16)",
    )
    args = parser.parse_args()
    report = Report(
        "spike-17-youtube",
        [
            "label",
            "duration_s",
            "reject",
            "captions",
            "metadata_s",
            "download_s",
            "source_codec_copy",
            "convert_s",
            "encode_s",
            "faststart",
            "peaks_s",
            "playable_s",
            "playback_mb",
            "encoded_mb",
        ],
    )
    with tempfile.TemporaryDirectory() as tmp:
        for line in args.urls.read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            url, _, label = line.strip().partition(" ")
            run_one(url, label.strip() or url, args.max_minutes, Path(tmp), report)
    ten_min = [
        r["playable_s"]
        for r in report.rows
        if r.get("playable_s") and 480 <= (r.get("duration_s") or 0) <= 720
    ]
    if ten_min:
        p95 = percentile(ten_min, 95)
        report.summary |= {
            "clips_8_to_12_min": len(ten_min),
            "p50_playable_s": percentile(ten_min, 50),
            "p95_playable_s": p95,
            "budget_s": BUDGET_S,
            "pass": p95 <= BUDGET_S,
        }
    print(f"wrote {report.write(args.out)}")


if __name__ == "__main__":
    main()
