"""Spike #19 (B2): forced-alignment speed and word-boundary accuracy.

Usage:
    OMP_NUM_THREADS=2 spike-b2 data/captioned --out results/
data/captioned: NAME.<audio>, NAME.txt (caption text) and optionally NAME.labels.csv
(hand labels: word,start_s,end_s per line) for the boundary-error check.
"""

import argparse
import csv
from pathlib import Path

from listenup_spikes.align import Aligner
from listenup_spikes.b1_transcribe import passages
from listenup_spikes.common import Report, measure
from listenup_spikes.media import decode
from listenup_spikes.metrics import mean_boundary_error_ms

TARGET_CORE_S_PER_AUDIO_S = 0.2  # System Design 5.1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("--out", type=Path, default=Path("results"))
    args = parser.parse_args()

    with measure() as t_load:
        aligner = Aligner()
    report = Report(
        "spike-19-b2-alignment",
        ["passage", "audio_s", "wall_s", "core_s_per_audio_s", "boundary_error_ms"],
    )
    report.summary["model load_s"] = round(t_load.wall_s, 1)
    rates, errors = [], []
    for path, text in passages(args.data):
        audio = decode(path)
        audio_s = len(audio) / 16000
        with measure() as t:
            words = aligner.align(audio, text)
        rate = t.cpu_s / audio_s
        rates.append(rate)
        error = None
        labels = path.with_suffix(".labels.csv")
        if labels.exists():
            with labels.open() as f:
                labelled = [(w, float(s), float(e)) for w, s, e in csv.reader(f)]
            error = mean_boundary_error_ms([(w.word, w.start, w.end) for w in words], labelled)
            errors.append(error)
        report.add(
            passage=path.stem,
            audio_s=round(audio_s, 1),
            wall_s=round(t.wall_s, 1),
            core_s_per_audio_s=round(rate, 3),
            boundary_error_ms=None if error is None else round(error, 1),
        )
    report.summary["mean core-s/audio-s"] = round(sum(rates) / len(rates), 3)
    report.summary["meets 0.2 target"] = max(rates) <= TARGET_CORE_S_PER_AUDIO_S
    if errors:
        report.summary["mean boundary error ms"] = round(sum(errors) / len(errors), 1)
    print(f"wrote {report.write(args.out)}")


if __name__ == "__main__":
    main()
