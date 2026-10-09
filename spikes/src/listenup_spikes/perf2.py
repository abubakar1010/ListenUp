"""NFR-PERF-2 (#18): how long a 10-minute upload takes to become playable.

Usage (PYTHONPATH adds the product's conversion command):
    PYTHONPATH=../apps/api/src spike-perf2 data/raw/LibriSpeech/test-clean --out results/
Builds 10-minute test uploads from LibriSpeech audio (an MP3 and an AAC .m4a, as a
learner's file would arrive; not timed), then runs the product's own ffmpeg conversion
(`listenup.modules.content.ffmpeg.convert_args`: playback MP4 plus waveform peaks in one
decode) several times and reports wall and CPU time. Upload transfer time depends on
the learner's network and is not included.
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

from listenup_spikes.common import Report, measure
from listenup_spikes.media import duration_s
from listenup_spikes.metrics import percentile

SOURCES = {
    "mp3 128k stereo 44.1k": ["-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k"],
    "m4a aac 128k stereo 44.1k": ["-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", "128k"],
}


def build_source(flacs: list[Path], target: Path, codec_args: list[str], seconds: float) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as listing:
        listing.writelines(f"file '{f.resolve()}'\n" for f in flacs)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing.name]
        + ["-t", str(seconds), *codec_args, str(target)],
        check=True,
    )
    Path(listing.name).unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("librispeech", type=Path, help="LibriSpeech/test-clean")
    parser.add_argument("--seconds", type=float, default=600.0)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("results"))
    args = parser.parse_args()

    from listenup.modules.content.ffmpeg import convert_args

    flacs = sorted(args.librispeech.rglob("*.flac"))
    report = Report("spike-18-perf2-conversion", ["source", "run", "audio_s", "wall_s", "core_s"])
    with tempfile.TemporaryDirectory() as tmp:
        for label, codec_args in SOURCES.items():
            suffix = ".mp3" if "mp3" in label else ".m4a"
            source = Path(tmp) / f"upload{suffix}"
            build_source(flacs, source, codec_args, args.seconds)
            audio_s = duration_s(source)
            walls = []
            for run in range(1, args.runs + 1):
                target = Path(tmp) / "playback.mp4"
                with measure() as t:
                    subprocess.run(
                        convert_args(source, target, video=False),
                        check=True,
                        stdout=subprocess.DEVNULL,  # the peaks stream; the job reads it
                    )
                walls.append(t.wall_s)
                report.add(
                    source=label,
                    run=run,
                    audio_s=round(audio_s, 1),
                    wall_s=round(t.wall_s, 2),
                    core_s=round(t.cpu_s, 2),
                )
            report.summary[f"{label}: median wall_s"] = round(sorted(walls)[len(walls) // 2], 2)
            report.summary[f"{label}: max wall_s"] = round(percentile(walls, 100), 2)
    print(f"wrote {report.write(args.out)}")


if __name__ == "__main__":
    main()
