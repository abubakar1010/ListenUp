"""Spike #22 (B4): filler-word recall of disfluency-keeping transcription settings.

Usage:
    OMP_NUM_THREADS=2 spike-b4 data/fillers --model small.en --out results/
data/fillers: NAME.<audio> plus NAME.fillers (one integer: the teacher-marked filler count).
Settings compared: plain decoding, and decoding with a disfluent initial prompt, which nudges
Whisper-family models to keep "um", "uh" and "like" instead of cleaning them up.
"""

import argparse
from pathlib import Path

from listenup_spikes.b1_transcribe import AUDIO_SUFFIXES
from listenup_spikes.common import Report
from listenup_spikes.media import decode
from listenup_spikes.metrics import count_fillers, filler_recall_precision

SETTINGS = {
    "plain": None,
    "disfluent-prompt": "Umm, let me think like, hmm... Okay, uh, here's what I'm, like, thinking.",
}
TARGET_RECALL = 0.8  # issue #22


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("--model", default="small.en")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--out", type=Path, default=Path("results"))
    args = parser.parse_args()

    from faster_whisper import WhisperModel

    items = []
    for audio in sorted(p for p in args.data.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES):
        marks = audio.with_suffix(".fillers")
        if marks.exists():
            items.append((audio, int(marks.read_text().strip())))
    if not items:
        raise SystemExit(f"no audio + .fillers pairs in {args.data}")

    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=args.threads)
    report = Report("spike-22-b4-fillers", ["setting", "recording", "true", "found"])
    for setting, prompt in SETTINGS.items():
        true_counts, found_counts = [], []
        for path, true_count in items:
            segments, _ = model.transcribe(
                decode(path),
                language="en",
                initial_prompt=prompt,
                vad_filter=False,
                condition_on_previous_text=False,
            )
            found = count_fillers(" ".join(seg.text for seg in segments))
            true_counts.append(true_count)
            found_counts.append(found)
            report.add(setting=setting, recording=path.stem, true=true_count, found=found)
        rp = filler_recall_precision(true_counts, found_counts)
        report.summary[f"{setting} recall"] = round(rp.recall, 3)
        report.summary[f"{setting} precision"] = round(rp.precision, 3)
        report.summary[f"{setting} meets 80% recall"] = rp.recall >= TARGET_RECALL
    print(f"wrote {report.write(args.out)}")


if __name__ == "__main__":
    main()
