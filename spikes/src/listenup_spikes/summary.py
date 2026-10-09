"""Markdown tables for the results documents, generated from the spike JSON files.

Usage:
    spike-summary b1 data/results/b1     # one row per model and beam, per-set WER
    spike-summary b2 data/results/b2     # one row per aligner setting
Numbers in docs/spikes/ come from this output, not from hand-typing.
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from listenup_spikes.metrics import percentile

SETS = ["test-clean", "test-other", "vp-en", "vp-accented"]


def _load(folder: Path, prefix: str) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(folder.glob(f"{prefix}*.json"))]


def _pooled(rows: list[dict[str, Any]]) -> tuple[float, float]:
    """Pooled Dictation WER and false marks per 100 reference words."""
    words = sum(r["reference_words"] for r in rows)
    errors = sum(r["subs"] + r["dels"] + r["ins"] for r in rows)
    return errors / words, 100 * sum(r["false_marks"] for r in rows) / words


def b1(folder: Path) -> str:
    runs = _load(folder, "spike-18-b1-")
    runs.sort(key=lambda r: (-r["summary"]["beam_size"], r["summary"]["mean core-s/audio-s"]))
    machine = runs[0]["machine"]
    lines = [
        f"Machine: {machine['cpu']}, {machine['cores']} cores, {machine['memory_gb']} GB, "
        f"OMP_NUM_THREADS={machine['omp_num_threads']}, {machine['date']}.",
        "",
        "| Model | Beam | Core-s per audio-s (mean / p95) | RTF (mean) | Throughput, audio-s per s "
        "| Peak memory per process | Load | Dictation WER, all | False marks per 100 words |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run in runs:
        s, rows = run["summary"], run["rows"]
        wer, marks = _pooled(rows)
        rtf = sum(r["rtf"] for r in rows) / len(rows)
        lines.append(
            f"| {s['model']} | {s['beam_size']} | {s['mean core-s/audio-s']:.3f} / "
            f"{s['p95 core-s/audio-s']:.3f} | {rtf:.3f} | {s['throughput audio-s per wall-s']:.1f} "
            f"| {s['peak_rss_mb per process']} MB | {s['load_s mean']} s | {100 * wer:.1f}% "
            f"| {marks:.1f} |"
        )
    lines += [
        "",
        "Dictation WER per set (pooled over the set's passages; false marks per 100 words "
        "in brackets):",
        "",
        "| Model | Beam | " + " | ".join(SETS) + " |",
        "| --- | --- |" + " --- |" * len(SETS),
    ]
    for run in runs:
        s = run["summary"]
        by_set: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in run["rows"]:
            by_set[r["set"]].append(r)
        cells = []
        for name in SETS:
            wer, marks = _pooled(by_set[name])
            cells.append(f"{100 * wer:.1f}% ({marks:.1f})")
        lines.append(f"| {s['model']} | {s['beam_size']} | " + " | ".join(cells) + " |")
    lines += ["", "Worst passage per model (Dictation WER):", ""]
    for run in runs:
        worst = max(run["rows"], key=lambda r: r["dictation_wer"])
        p95 = percentile([r["dictation_wer"] for r in run["rows"]], 95)
        lines.append(
            f"- {run['summary']['model']} beam {run['summary']['beam_size']}: "
            f"{worst['passage']} {100 * worst['dictation_wer']:.1f}% (p95 {100 * p95:.1f}%)"
        )
    return "\n".join(lines)


def letterless_words(passages: Path, name: str) -> int:
    """Words of a passage's text with no letters (numbers, symbols): the aligner skips them."""
    text = (passages / f"{name}.txt").read_text()
    return sum(1 for w in text.split() if not re.search("[A-Za-z]", w))


def b2(folder: Path, passages: Path) -> str:
    runs = _load(folder, "spike-19-b2-")
    runs = [r for r in runs if "model" in r["summary"]]
    lines = [
        "| Model | Emission | Core-s per audio-s (mean / max) | RTF (mean) | Peak memory "
        "| Load | Passages aligned | Words not aligned (digits, symbols) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run in runs:
        s, rows = run["summary"], [r for r in run["rows"] if "rtf" in r]
        rtf = sum(r["rtf"] for r in rows) / len(rows) if rows else float("nan")
        unaligned = sum(letterless_words(passages, r["passage"]) for r in rows)
        words = sum(len((passages / f"{r['passage']}.txt").read_text().split()) for r in rows)
        mean, top = s["mean core-s/audio-s"], s["max core-s/audio-s"]
        speed = f"{mean:.3f} / {top:.3f}" if rows else "n/a"
        lines.append(
            f"| {s['model']} | {s['emission']} | {speed} | {rtf:.3f} | {s['peak_rss_mb']} MB "
            f"| {s['model load_s']} s | {s['passages aligned']} of {len(run['rows'])} "
            f"| {unaligned} of {words} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spike", choices=["b1", "b2"])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--passages", type=Path, default=Path("data/passages"))
    args = parser.parse_args()
    print(b1(args.folder) if args.spike == "b1" else b2(args.folder, args.passages))


if __name__ == "__main__":
    main()
