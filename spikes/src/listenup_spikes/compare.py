"""Compare word timings from several sources (B1 timestamps, B2 aligners, hand labels).

Usage:
    spike-compare results/words --labels ../docs/spikes/b2-labels --out results/
results/words/<source>/<passage>.json are written by spike-b1 and spike-b2 (`window`
and `words` in the passage file's time). Hand labels are NAME.labels.csv
(word,start_s,end_s, in the same time), from `spike-labelkit import`.

Two tables:
- against hand labels (only for the labelled windows): the boundary error of each source;
- agreement between sources (every passage): how far two systems' boundaries are apart.
  Agreement is a proxy, not accuracy: two systems can agree and both be wrong.
"""

import argparse
import csv
import json
from itertools import combinations
from pathlib import Path

from listenup_spikes.common import Report
from listenup_spikes.metrics import boundary_errors_ms, spread

Words = list[tuple[str, float, float]]


def load_source(folder: Path) -> dict[str, Words]:
    """Passage name to the words inside its passage window."""
    out = {}
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text())
        start, end = data["window"]
        out[path.stem] = [
            (w["word"], w["start"], w["end"])
            for w in data["words"]
            if start <= (w["start"] + w["end"]) / 2 < end
        ]
    return out


Window = tuple[str, float, float]  # passage, start_s, end_s in the passage file's time

PAUSE = "<pause>"  # a labelled stretch with no speech; covers the window but is not a word
MAX_GAP_S = 3.0  # longest unlabelled stretch a window may keep (edges, cut-off words)


def load_labels(folder: Path) -> dict[str, Words]:
    """Passage name to its labelled intervals, pause markers included."""
    out = {}
    for path in sorted(folder.glob("*.labels.csv")):
        with path.open() as f:
            out[path.name.removesuffix(".labels.csv")] = [
                (w, float(s), float(e)) for w, s, e in csv.reader(f)
            ]
    return out


def load_windows(folder: Path) -> dict[str, Window]:
    """The windows.json beside the labels; a hand-label comparison cannot run without it."""
    spec = folder / "windows.json"
    if not spec.exists():
        raise SystemExit(f"{spec} is missing: hand labels are checked against their windows")
    windows: dict[str, Window] = {}
    for name, w in json.loads(spec.read_text())["windows"].items():
        if any(passage == w["passage"] for passage, _, _ in windows.values()):
            raise SystemExit(f"two windows use passage {w['passage']}; labels are per passage")
        start = float(w["start_s"])
        windows[name] = (w["passage"], start, start + float(w["seconds"]))
    return windows


def incomplete_windows(windows: dict[str, Window], labels: dict[str, Words]) -> list[str]:
    """Windows whose labels leave more than MAX_GAP_S unlabelled anywhere, or have no words.

    A window counts as labelled only when its words (and marked pauses) cover it, so a
    few labelled words cannot stand in for the whole window (ADR 0034, ADR 0055).
    """
    out = []
    for name, (passage, start, end) in windows.items():
        rows = sorted(labels.get(passage, []), key=lambda r: r[1])
        edge, gap = start, 0.0
        for _, s, e in rows:
            gap = max(gap, s - edge)
            edge = max(edge, e)
        gap = max(gap, end - edge)
        if not any(w != PAUSE for w, _, _ in rows) or gap > MAX_GAP_S:
            out.append(name)
    return sorted(out)


def _row(
    name: str,
    errors: list[float],
    words: int,
    *,
    hand_labels: bool = False,
    complete: bool = True,
) -> dict[str, object]:
    s = spread(errors) if errors else None
    matched = len(errors) // 2
    row: dict[str, object] = {
        "comparison": name,
        "words_matched": matched,
        "words_compared": words,
        "words_unmatched": words - matched,
        "coverage": round(matched / words, 3) if words else 0.0,
        "mean_ms": round(s.mean, 1) if s else None,
        "median_ms": round(s.median, 1) if s else None,
        "p90_ms": round(s.p90, 1) if s else None,
        # Shares use ALL compared boundaries, so dropping a word cannot improve them.
        "within_50ms": round(sum(e <= 50 for e in errors) / (2 * words), 3) if words else 0.0,
        "within_100ms": round(sum(e <= 100 for e in errors) / (2 * words), 3) if words else 0.0,
    }
    if hand_labels:
        row["meets_hand_label_gate"] = bool(complete and s and matched == words and s.mean <= 50)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("words", type=Path)
    parser.add_argument("--sources", nargs="+", help="subfolders to compare (default: all)")
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--only", help="compare only passages whose name starts with this")
    parser.add_argument("--name", default="spike-19-b2-boundaries", help="report file name")
    parser.add_argument("--out", type=Path, default=Path("results"))
    args = parser.parse_args()

    names = args.sources or sorted(p.name for p in args.words.iterdir() if p.is_dir())
    sources = {
        name: {
            passage: words
            for passage, words in load_source(args.words / name).items()
            if not args.only or passage.startswith(args.only)
        }
        for name in names
    }
    columns = [
        "comparison",
        "words_matched",
        "words_compared",
        "words_unmatched",
        "coverage",
        "mean_ms",
        "median_ms",
        "p90_ms",
        "within_50ms",
        "within_100ms",
        "meets_hand_label_gate",
    ]
    report = Report(args.name, columns)
    report.summary["passages"] = args.only or "all"

    windows = {
        name: w
        for name, w in (load_windows(args.labels) if args.labels else {}).items()
        if not args.only or w[0].startswith(args.only)
    }
    rows_of = load_labels(args.labels) if args.labels else {}
    passages = {passage for passage, _, _ in windows.values()}
    labels = {
        passage: [r for r in rows_of.get(passage, []) if r[0] != PAUSE] for passage in passages
    }
    # A window left unlabelled or partly labelled cannot be excluded from a pass (ADR 0034).
    missing = incomplete_windows(windows, rows_of)
    report.summary["hand-labelled windows"] = len(windows) - len(missing)
    report.summary["incomplete windows"] = ", ".join(missing) or "none"
    report.summary["boundary_matching"] = "ordered text blocks; no timing cutoff; v2"
    report.summary["hand_label_gate"] = (
        f"every window labelled (no unlabelled gap over {MAX_GAP_S:g} s), all labelled words"
        " matched and mean boundary error <= 50 ms"
    )
    if args.labels and not sources:
        # No model output is a failed gate, never an empty report.
        sources = {"no model output": {}}
    for name, words_of in sources.items():
        errors, compared = [], 0
        for passage, labelled in labels.items():
            errors += boundary_errors_ms(words_of.get(passage, []), labelled)
            compared += len(labelled)
        if args.labels:
            report.add(
                **_row(
                    f"{name} vs hand labels",
                    errors,
                    compared,
                    hand_labels=True,
                    complete=not missing,
                )
            )
    for a, b in combinations([n for n in names if n in sources], 2):
        errors, compared = [], 0
        for passage in sorted(sources[b]):
            errors += boundary_errors_ms(sources[a].get(passage, []), sources[b][passage])
            compared += len(sources[b][passage])
        if compared:
            report.add(**_row(f"{a} vs {b} (agreement)", errors, compared))
    print(f"wrote {report.write(args.out)}")


if __name__ == "__main__":
    main()
