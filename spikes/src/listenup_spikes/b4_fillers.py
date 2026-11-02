"""Spike #22 (B4): filler-word recall of disfluency-keeping transcription settings.

Usage:
    OMP_NUM_THREADS=2 spike-b4 data/fillers --model small.en --out results/
data/fillers: NAME.<audio> plus NAME.fillers (one integer: the human-marked filler count)
and, when the marks are timed, NAME.marks.json (spike-ami fetch writes both). With timed
marks each transcribed filler must land on a marked one (metrics.match_fillers); with a
count alone the comparison is count-level.
Settings compared: plain decoding, and decoding with a disfluent initial prompt, which nudges
Whisper-family models to keep "um", "uh" and "like" instead of cleaning them up.
"""

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from listenup_spikes.b1_transcribe import AUDIO_SUFFIXES
from listenup_spikes.common import Report, measure
from listenup_spikes.media import decode
from listenup_spikes.metrics import (
    FillerCounts,
    FillerMark,
    count_fillers,
    filler_recall_precision,
    hypothesis_fillers,
    match_fillers,
    percentile,
)

SETTINGS = {
    "plain": None,
    "disfluent-prompt": "Umm, let me think like, hmm... Okay, uh, here's what I'm, like, thinking.",
}
TARGET_RECALL = 0.8  # issue #22
SAMPLE_RATE = 16000


@dataclass(frozen=True)
class Item:
    audio: Path
    true_count: int
    marks: list[FillerMark] | None  # None when only a count was marked


def load_items(data: Path) -> list[Item]:
    items = []
    for audio in sorted(p for p in data.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES):
        count_file = audio.with_suffix(".fillers")
        if not count_file.exists():
            continue
        marks_file = audio.with_suffix(".marks.json")
        marks = None
        if marks_file.exists():
            marks = [FillerMark(**m) for m in json.loads(marks_file.read_text())]
        items.append(Item(audio, int(count_file.read_text().strip()), marks))
    return items


def matching_mode(items: Sequence[Item]) -> str:
    """ "timed" when every recording has timed marks, "count" when none has; a mix would
    pool two different measures, so it is refused."""
    timed = [item.marks is not None for item in items]
    if all(timed):
        return "timed"
    if not any(timed):
        return "count"
    raise SystemExit("the data folder mixes timed marks and bare counts: use one kind")


def speed_summary(setting: str, speeds: Sequence[float]) -> dict[str, float]:
    return {
        f"{setting} core-s per audio-s p50": round(percentile(speeds, 50), 3),
        f"{setting} core-s per audio-s p95": round(percentile(speeds, 95), 3),
    }


def _rate(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def summarize_setting(
    setting: str, recordings: Sequence[dict[str, FillerCounts]]
) -> dict[str, Any]:
    """Pool the timed matches of all recordings (micro-average), overall and per kind."""
    summary: dict[str, Any] = {}
    for kind in ("all", "hesitation", "discourse"):
        pooled = FillerCounts(
            *(sum(getattr(r[kind], f) for r in recordings) for f in ("hits", "missed", "extra"))
        )
        label = setting if kind == "all" else f"{setting} {kind}"
        summary[f"{label} recall"] = _rate(pooled.recall)
        summary[f"{label} precision"] = _rate(pooled.precision)
        summary[f"{label} marked"] = pooled.hits + pooled.missed
    recall = summary[f"{setting} recall"]
    summary[f"{setting} meets 80% recall"] = recall is not None and recall >= TARGET_RECALL
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("--model", default="small.en")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--out", type=Path, default=Path("results"))
    parser.add_argument(
        "--evidence",
        default="",
        help='label stored with the results, e.g. "CI-runner evidence (E4)"',
    )
    args = parser.parse_args()

    from faster_whisper import WhisperModel

    items = load_items(args.data)
    if not items:
        raise SystemExit(f"no audio + .fillers pairs in {args.data}")
    timed = matching_mode(items) == "timed"

    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=args.threads)
    # One untimed transcription first, so no setting pays for a cold model (E4: warm models).
    warm_up, _ = model.transcribe(decode(items[0].audio), language="en", word_timestamps=timed)
    list(warm_up)  # segments are lazy: consume them so the model really runs
    report = Report(
        "spike-22-b4-fillers",
        ["setting", "recording", "true", "found", "hits", "missed", "extra", "core_s_per_audio_s"],
    )
    report.summary["evidence"] = args.evidence
    report.summary["model"] = args.model
    report.summary["matching"] = "timed, 0.5 s tolerance" if timed else "count-level"
    for setting, prompt in SETTINGS.items():
        true_counts, found_counts, matches, speeds = [], [], [], []
        for item in items:
            audio = decode(item.audio)
            with measure() as timer:
                segments, _ = model.transcribe(
                    audio,
                    language="en",
                    initial_prompt=prompt,
                    vad_filter=False,
                    condition_on_previous_text=False,
                    word_timestamps=timed,
                )
                segments = list(segments)
            speeds.append(timer.cpu_s / (len(audio) / SAMPLE_RATE))
            row: dict[str, Any] = {"setting": setting, "recording": item.audio.stem}
            if timed and item.marks is not None:
                words = [(w.word, w.start, w.end) for seg in segments for w in seg.words or []]
                found = hypothesis_fillers(words)
                result = match_fillers(item.marks, found)
                matches.append(result)
                row |= {
                    "true": len(item.marks),
                    "found": len(found),
                    "hits": result["all"].hits,
                    "missed": result["all"].missed,
                    "extra": result["all"].extra,
                }
            else:
                found_count = count_fillers(" ".join(seg.text for seg in segments))
                true_counts.append(item.true_count)
                found_counts.append(found_count)
                row |= {"true": item.true_count, "found": found_count}
            row["core_s_per_audio_s"] = round(speeds[-1], 3)
            report.add(**row)
        if timed:
            report.summary |= summarize_setting(setting, matches)
        else:
            rp = filler_recall_precision(true_counts, found_counts)
            report.summary[f"{setting} recall"] = round(rp.recall, 3)
            report.summary[f"{setting} precision"] = round(rp.precision, 3)
            report.summary[f"{setting} meets 80% recall"] = rp.recall >= TARGET_RECALL
        report.summary |= speed_summary(setting, speeds)
    print(f"wrote {report.write(args.out)}")


if __name__ == "__main__":
    main()
